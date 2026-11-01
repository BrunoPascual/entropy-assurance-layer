"""Testes de scripts/analisar_deriva.py (deriva da coleta 2 contra a coleta 1, Dia 6)."""
from __future__ import annotations

import csv
import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

_PATH = Path(__file__).resolve().parent.parent / "scripts" / "analisar_deriva.py"
_spec = importlib.util.spec_from_file_location("_analisar_deriva", _PATH)
mod = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = mod
_spec.loader.exec_module(mod)
cal, ac = mod.cal, mod.ac

N_Q, SHOTS = 156, 2000
CAL1, CAL2 = "2026-11-01 11:57:51-03:00", "2026-11-01 16:56:51-03:00"
ENVIO = [0.01 + 0.0001 * q for q in range(N_Q)]
EXEC2 = [0.02 + 0.0001 * q for q in range(N_Q)]


def _bits(seed: int, bias: dict[int, float]) -> np.ndarray:
    rng = np.random.default_rng(seed)
    p = np.full(N_Q, 0.5)
    for q, v in bias.items():
        p[q] = v
    x = (rng.random((SHOTS, N_Q)) < p).astype(np.uint8)
    x[:, 113] = x[:, 112] ^ (rng.random(SHOTS) < 0.3)  # par 112-113 correlacionado
    x[:, 131] = x[:, 130] ^ (rng.random(SHOTS) < 0.3)  # par 130-131 correlacionado
    return x.reshape(-1)


def _batch(job: str, seed: int, bias: dict[int, float], **params) -> SimpleNamespace:
    bits = _bits(seed, bias)
    base = {"backend": "ibm_kingston", "job_id": job, "shots": SHOTS, "qubits": N_Q,
            "physical_qubits": list(range(N_Q)), "calibration_date": CAL1,
            "readout_error_by_position": ENVIO}
    base.update(params)
    return SimpleNamespace(bits=bits, params=base, n_bits=bits.size, batch_hash=f"h-{job}",
                           created_at=f"2026-11-01T00:00:{seed:02d}Z")


BIAS = {14: 0.45, 21: 0.46, 138: 0.45, 121: 0.47, 131: 0.47}


def _sessions() -> dict[str, list[SimpleNamespace]]:
    return {
        "coleta1": [_batch("j1", 1, BIAS), _batch("j2", 2, BIAS)],
        "coleta2": [_batch("j3", 3, BIAS, calibration_date=CAL2, calibration_date_run=CAL2,
                           readout_error_run_by_position=EXEC2),
                    _batch("j4", 4, {14: 0.5, 21: 0.5, 138: 0.5}, calibration_date=CAL2,
                           calibration_date_run=CAL2, readout_error_run_by_position=EXEC2)],
    }


@pytest.fixture
def world(tmp_path, monkeypatch):
    raw, out = tmp_path / "raw", tmp_path / "out"
    raw.mkdir()
    sessions = _sessions()
    for session, batches in sessions.items():
        for i in range(len(batches)):
            (raw / f"2026-11-01_ibm_kingston_{session}_{i + 1:03d}.json").write_text("{}")
    seen = []

    def fake_load(raw_dir, inventory, session):
        seen.append((inventory, session))
        return sessions[session]

    monkeypatch.setattr(ac, "load_real", fake_load)
    return SimpleNamespace(raw=raw, out=out, sessions=sessions, seen=seen)


def _read(path: Path) -> list[dict[str, str]]:
    with open(path, encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def test_grava_os_quatro_csvs_com_a_sessao_no_nome(world):
    states, paths, *_ = mod.run(world.raw, world.out)
    assert states == ["novo"] * 4
    assert [p.name for p in paths] == ["dia6_deriva_coleta2_lotes.csv",
                                       "dia6_deriva_coleta2_por_qubit.csv",
                                       "dia6_deriva_coleta2_conjunto_fixo.csv",
                                       "dia6_deriva_coleta2_estabilidade.csv"]
    assert world.seen == [(ac.inventory_for("coleta1"), "coleta1"),
                          (ac.inventory_for("coleta2"), "coleta2")]


def test_lotes_registram_calibracao_e_retrato(world):
    mod.run(world.raw, world.out)
    rows = {r["lote"]: r for r in _read(world.out / "dia6_deriva_coleta2_lotes.csv")}
    assert list(rows) == ["coleta1_001", "coleta1_002", "coleta2_001", "coleta2_002"]
    for lab in ("coleta1_001", "coleta1_002"):
        assert rows[lab]["sessao"] == "coleta1" and rows[lab]["retrato_leitura"] == "envio"
        assert rows[lab]["calibracao_igual_coleta1"] == "True"
    for lab in ("coleta2_001", "coleta2_002"):
        assert rows[lab]["sessao"] == "coleta2" and rows[lab]["retrato_leitura"] == "execucao"
        assert rows[lab]["calibracao_execucao"] == CAL2
        assert rows[lab]["calibracao_igual_coleta1"] == "False"


def test_cada_lote_usa_o_proprio_retrato_de_leitura(world):
    mod.run(world.raw, world.out)
    rows = _read(world.out / "dia6_deriva_coleta2_por_qubit.csv")
    got = {(r["lote"], int(r["posicao"])): float(r["erro_leitura"]) for r in rows}
    assert got[("coleta1_001", 14)] == pytest.approx(ENVIO[14])
    assert got[("coleta2_001", 14)] == pytest.approx(EXEC2[14])
    fixo = [r for r in _read(world.out / "dia6_deriva_coleta2_conjunto_fixo.csv")
            if r["tipo"] == "qubit" and r["id"] == "14"]
    by_lot = {r["lote"]: float(r["erro_leitura"]) for r in fixo}
    assert by_lot["coleta1_001"] == pytest.approx(ENVIO[14])
    assert by_lot["coleta2_002"] == pytest.approx(EXEC2[14])


def test_veredito_e_o_mesmo_do_analisar_cal(world):
    *_, frows, _ = mod.run(world.raw, world.out)
    s = world.sessions
    labels = ["coleta1_001", "coleta1_002", "coleta2_001", "coleta2_002"]
    batches = s["coleta1"] + s["coleta2"]
    shots = {lab: SHOTS for lab in labels}
    m = {lab: ac.qubit_metrics(b.bits, N_Q) for lab, b in zip(labels, batches)}
    direct = cal.fixed_rows(labels, shots, m, EXEC2)
    keys = ("estimativa", "z", "referencia_coleta1", "z_esperado", "testavel", "sinal_igual",
            "replica", "zdiff_vs_coleta1", "magnitude_compativel")
    for r in direct:
        key = (r["tipo"], r["id"], r["lote"])
        mine = [x for x in frows if (x["tipo"], x["id"], x["lote"]) == key]
        assert len(mine) == 1
        assert {k: mine[0][k] for k in keys} == {k: r[k] for k in keys}
    assert len(frows) == len(direct)


def test_conjunto_fixo_ordenado_por_item_e_lote(world):
    *_, frows, _ = mod.run(world.raw, world.out)
    ids = [(r["tipo"], r["id"]) for r in frows]
    assert ids[:4] == [("qubit", "14")] * 4
    assert ids[-4:] == [("par", "130-131")] * 4
    assert [r["lote"] for r in frows[:4]] == ["coleta1_001", "coleta1_002",
                                              "coleta2_001", "coleta2_002"]
    assert all(r["calibracao_igual_coleta1"] == r["lote"].startswith("coleta1_") for r in frows)


def test_replica_e_nao_replica_aparecem(world):
    *_, frows, _ = mod.run(world.raw, world.out)
    q14 = {r["lote"]: r for r in frows if (r["tipo"], r["id"]) == ("qubit", "14")}
    assert q14["coleta2_001"]["replica"] is True
    assert q14["coleta2_002"]["replica"] is False
    assert q14["coleta1_001"]["replica"] is None


def test_calibracao_trocada_entre_envio_e_execucao_conta_a_da_execucao(world):
    """O caso do cal_001: o envio registrou uma calibração e o job rodou sob outra."""
    world.sessions["coleta2"][0].params.update(calibration_date=CAL1, calibration_date_run=CAL2)
    lotes = {r["lote"]: r for r in mod.run(world.raw, world.out)[2]}
    assert lotes["coleta2_001"]["calibracao_no_envio"] == CAL1
    assert lotes["coleta2_001"]["calibracao_igual_coleta1"] is False


def test_estabilidade_cobre_os_seis_pares(world):
    *_, srows = mod.run(world.raw, world.out)
    assert len(srows) == 6


def test_segunda_execucao_nao_grava_nada(world):
    mod.run(world.raw, world.out)
    before = {p.name: p.read_bytes() for p in world.out.iterdir()}
    states, *_ = mod.run(world.raw, world.out)
    assert states == ["igual"] * 4
    assert {p.name: p.read_bytes() for p in world.out.iterdir()} == before


def test_saida_existente_diferente_recusa_sem_gravar(world):
    world.out.mkdir()
    (world.out / "dia6_deriva_coleta2_estabilidade.csv").write_text("outro\n")
    with pytest.raises(mod.rc.SummaryError):
        mod.run(world.raw, world.out)
    assert [p.name for p in world.out.iterdir()] == ["dia6_deriva_coleta2_estabilidade.csv"]


@pytest.mark.parametrize("session, err", [("coleta_2", "AnalysisError"),
                                          ("coleta1", "DerivaError")])
def test_sessao_invalida_ou_a_propria_referencia_recusa(world, session, err):
    exc = ac.AnalysisError if err == "AnalysisError" else mod.DerivaError
    with pytest.raises(exc):
        mod.run(world.raw, world.out, session)
    assert world.seen == [] and not world.out.exists()


@pytest.mark.parametrize("change, msg", [
    ({"backend": "ibm_outro"}, "backend"),
    ({"physical_qubits": list(range(1, N_Q + 1))}, "mapa de qubits"),
    ({"readout_error_run_by_position": EXEC2[:-1]}, "erro de leitura"),
    ({"job_id": "j1"}, "job_id repetido"),
])
def test_incoerencia_na_coleta2_recusa(world, change, msg):
    world.sessions["coleta2"][1].params.update(change)
    with pytest.raises(mod.DerivaError, match=msg):
        mod.run(world.raw, world.out)
    assert not world.out.exists()


def test_lote_repetido_recusa(world):
    world.sessions["coleta2"][1].batch_hash = world.sessions["coleta1"][0].batch_hash
    with pytest.raises(ac.AnalysisError):
        mod.run(world.raw, world.out)


def test_coleta1_com_duas_calibracoes_recusa(world):
    world.sessions["coleta1"][1].params["calibration_date"] = CAL2
    with pytest.raises(mod.DerivaError, match="calibração única"):
        mod.run(world.raw, world.out)


def test_arquivos_em_disco_diferentes_do_inventario_recusa(world):
    (world.raw / "2026-11-01_ibm_kingston_coleta2_003.json").write_text("{}")
    with pytest.raises(mod.DerivaError, match="em disco"):
        mod.run(world.raw, world.out)


def test_main_imprime_e_devolve_zero(world, capsys):
    assert mod.main(["--raw-dir", str(world.raw), "--out-dir", str(world.out)]) == 0
    out = capsys.readouterr().out
    assert "novo:" in out and "lote coleta2_001" in out and "igual_coleta1=False" in out


def test_main_recusa_com_codigo_1(world, capsys):
    assert mod.main(["--sessao", "coleta1", "--raw-dir", str(world.raw),
                     "--out-dir", str(world.out)]) == 1
    assert "RECUSADO" in capsys.readouterr().out
