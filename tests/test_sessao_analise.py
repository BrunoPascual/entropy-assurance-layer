"""DEP_SESSAO, passo 2: analisar_coleta1.py e resumo_coleta1.py com --sessao (padrão coleta1)."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"


def _load(name: str, alias: str):
    spec = importlib.util.spec_from_file_location(alias, _SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[alias] = module
    spec.loader.exec_module(module)
    return module


ac = _load("analisar_coleta1", "_sessao_analisar_coleta1")
rc = _load("resumo_coleta1", "_sessao_resumo_coleta1")

ENVIO = [0.01, 0.02]
EXEC = [0.03, 0.04]


# ---------------------------------------------------------------- nomes

def test_padrao_mantem_os_nomes_de_sempre():
    assert ac.SESSION == rc.SESSION == "coleta1"
    assert ac.inventory_for("coleta1") == ac.INVENTORY_PATH
    assert ac._targets(Path("r")) == [Path("r/dia6_qpu_vs_sim_lotes.csv"),
                                      Path("r/dia6_qpu_vs_sim_por_qubit.csv")]
    assert rc.input_for("coleta1") == rc.IN_PATH
    assert rc.session_file(rc.RESUMO_NAME, "coleta1") == "dia6_qpu_vs_sim_resumo.csv"
    assert rc.session_file(rc.EXCESSO_NAME, "coleta1") == "dia6_qpu_excesso_leitura.csv"


def test_outra_sessao_ganha_prefixo():
    assert ac.inventory_for("coleta2") == Path("data/results/dia6_coleta2_inventario.csv")
    assert ac._targets(Path("r"), "coleta2") == [Path("r/dia6_coleta2_qpu_vs_sim_lotes.csv"),
                                                 Path("r/dia6_coleta2_qpu_vs_sim_por_qubit.csv")]
    assert rc.session_file(rc.RESUMO_NAME, "coleta2") == "dia6_coleta2_qpu_vs_sim_resumo.csv"
    assert rc.session_file(rc.EXCESSO_NAME, "coleta2") == "dia6_coleta2_qpu_excesso_leitura.csv"


def test_entrada_do_resumo_e_a_saida_do_analisar():
    for session in ("coleta1", "coleta2"):
        assert rc.input_for(session) == Path("data/results") / ac.session_file(ac.QUBIT_NAME, session)


@pytest.mark.parametrize("session", ["", "coleta_2", "../x", "a*", "col eta", "seção", None])
def test_sessao_invalida_recusa_nos_dois(session):
    with pytest.raises(ac.AnalysisError):
        ac.check_session(session)
    with pytest.raises(rc.SummaryError):
        rc.check_session(session)


# ---------------------------------------------------------------- retrato de leitura

@pytest.mark.parametrize("params, expected", [
    ({"readout_error_by_position": ENVIO, "readout_error_run_by_position": EXEC}, EXEC),
    ({"readout_error_by_position": ENVIO, "readout_error_run_by_position": None}, ENVIO),
    ({"readout_error_by_position": ENVIO}, ENVIO),
    ({}, None),
])
def test_readout_of_prefere_a_execucao(params, expected):
    assert ac.readout_of(params) == expected


def _fake_pipeline(*args, **kwargs):
    ext = SimpleNamespace(to_dict=lambda: {"n_output_bits": 0})
    return SimpleNamespace(inputs=[SimpleNamespace(extraction=ext)],
                           outcomes=[SimpleNamespace(status="ok", reasons=[])],
                           error=None, seed_generated=False)


def _batch(params: dict) -> SimpleNamespace:
    bits = np.array([1, 0, 0, 1, 1, 1, 0, 0], dtype=np.uint8)  # 4 shots x 2 qubits
    return SimpleNamespace(bits=bits, params=params, source_id="ibm_x", is_simulated=False,
                           n_bits=bits.size, batch_hash="h")


@pytest.mark.parametrize("params, expected", [
    ({"readout_error_by_position": ENVIO, "readout_error_run_by_position": EXEC}, EXEC),
    ({"readout_error_by_position": ENVIO}, ENVIO),
])
def test_analyze_source_usa_o_retrato_da_execucao(params, expected):
    _, qrows = ac.analyze_source(
        "qpu_real", [_batch(params)], physical=[5, 7], use_readout=True,
        os_factory=lambda: None,
        health_fn=lambda b, d, h: SimpleNamespace(to_dict=lambda: {}),
        pipeline_fn=_fake_pipeline)
    assert [r["erro_leitura"] for r in qrows] == expected


# ---------------------------------------------------------------- analisar_coleta1: main e run

@pytest.fixture
def run_calls(monkeypatch):
    seen: dict = {}

    def fake_run(raw_dir, inventory, out_dir, sim_seed, **kw):
        seen.update(inventory=inventory, **kw)
        return []

    monkeypatch.setattr(ac, "run", fake_run)
    return seen


def test_main_padrao_usa_coleta1(run_calls):
    assert ac.main([]) == 0
    assert run_calls["inventory"] == ac.INVENTORY_PATH and run_calls["session"] == "coleta1"


def test_main_deriva_o_inventario_da_sessao(run_calls):
    assert ac.main(["--sessao", "coleta2"]) == 0
    assert run_calls["inventory"] == ac.inventory_for("coleta2")
    assert run_calls["session"] == "coleta2"


def test_main_inventario_explicito_prevalece(run_calls, tmp_path):
    inv = tmp_path / "inv.csv"
    assert ac.main(["--sessao", "coleta2", "--inventario", str(inv)]) == 0
    assert run_calls["inventory"] == inv


def test_main_sessao_invalida_recusa_sem_rodar(run_calls, capsys):
    assert ac.main(["--sessao", "../x"]) == 1
    assert run_calls == {}
    assert "RECUSADO" in capsys.readouterr().out


def test_run_sessao_invalida_recusa_antes_de_carregar(tmp_path, monkeypatch):
    loaded = []
    monkeypatch.setattr(ac, "load_real", lambda *a: loaded.append(a))

    def boom(*a, **k):
        raise AssertionError("não devia simular")
    with pytest.raises(ac.AnalysisError, match="sessão inválida"):
        ac.run(tmp_path, tmp_path / "inv.csv", tmp_path, 1, sim_factory=boom, os_factory=boom,
               session="coleta_2")
    assert loaded == []


def test_run_confere_saida_da_sessao_antes_de_carregar(tmp_path, monkeypatch):
    loaded = []
    monkeypatch.setattr(ac, "load_real", lambda *a: loaded.append(a))
    (tmp_path / "dia6_coleta2_qpu_vs_sim_lotes.csv").write_text("x")
    with pytest.raises(ac.AnalysisError):
        ac.run(tmp_path, tmp_path / "inv.csv", tmp_path, 1, session="coleta2")
    assert loaded == []


class _Src:
    def __init__(self, tag: str) -> None:
        self.tag, self.k = tag, 0

    def read(self, n_bits: int):
        self.k += 1
        return SimpleNamespace(n_bits=n_bits, batch_hash=f"{self.tag}{self.k}")


def test_run_ponta_a_ponta_grava_com_o_prefixo_da_sessao(tmp_path, monkeypatch):
    seen = {}
    real = [SimpleNamespace(n_bits=8, batch_hash=f"r{i}",
                            params={"physical_qubits": [5, 7], "qubits": 2}) for i in (1, 2)]

    def fake_load(raw_dir, inventory, session=ac.SESSION):
        seen["session"] = session
        return real

    monkeypatch.setattr(ac, "load_real", fake_load)
    monkeypatch.setattr(ac, "analyze_source",
                        lambda label, batches, **kw: ([{"fonte": label}], [{"fonte": label}]))
    ac.run(tmp_path, tmp_path / "inv.csv", tmp_path, 1, session="coleta2",
           sim_factory=lambda n, s, p: _Src("s"), os_factory=lambda: _Src("o"))
    assert seen["session"] == "coleta2"
    assert sorted(p.name for p in tmp_path.iterdir()) == [
        "dia6_coleta2_qpu_vs_sim_lotes.csv", "dia6_coleta2_qpu_vs_sim_por_qubit.csv"]


# ---------------------------------------------------------------- resumo_coleta1: main

@pytest.fixture
def build_calls(monkeypatch):
    seen: dict = {}

    def fake_build(path):
        seen["entrada"] = path
        return "a\n1\n", "b\n2\n", []

    monkeypatch.setattr(rc, "build", fake_build)
    return seen


def test_resumo_padrao(build_calls, tmp_path):
    assert rc.main(["--out-dir", str(tmp_path)]) == 0
    assert build_calls["entrada"] == rc.IN_PATH
    assert sorted(p.name for p in tmp_path.iterdir()) == [
        "dia6_qpu_excesso_leitura.csv", "dia6_qpu_vs_sim_resumo.csv"]


def test_resumo_coleta2(build_calls, tmp_path):
    assert rc.main(["--sessao", "coleta2", "--out-dir", str(tmp_path)]) == 0
    assert build_calls["entrada"] == rc.input_for("coleta2")
    assert sorted(p.name for p in tmp_path.iterdir()) == [
        "dia6_coleta2_qpu_excesso_leitura.csv", "dia6_coleta2_qpu_vs_sim_resumo.csv"]


def test_resumo_entrada_explicita_prevalece(build_calls, tmp_path):
    entrada = tmp_path / "e.csv"
    assert rc.main(["--sessao", "coleta2", "--entrada", str(entrada),
                    "--out-dir", str(tmp_path / "o")]) == 0
    assert build_calls["entrada"] == entrada


def test_resumo_sessao_invalida_recusa_sem_ler(build_calls, tmp_path, capsys):
    assert rc.main(["--sessao", "a_b", "--out-dir", str(tmp_path)]) == 1
    assert build_calls == {} and list(tmp_path.iterdir()) == []
    assert "RECUSADO" in capsys.readouterr().out
