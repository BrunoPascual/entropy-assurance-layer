"""Testes de scripts/resumo_coleta1.py (Dia 6), com tabela por qubit sintética."""
from __future__ import annotations

import csv
import importlib.util
import math
import sys
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "resumo_coleta1", Path(__file__).resolve().parents[1] / "scripts" / "resumo_coleta1.py")
rs = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = rs
_SPEC.loader.exec_module(rs)

SHOTS = 100
COLS = list(rs.COLUMNS_IN)


def row(fonte, lote, pos, p1, viz="", shot="", erro=""):
    return {"fonte": fonte, "lote": lote, "posicao": pos, "qubit_fisico": pos, "n_shots": SHOTS,
            "p1": p1, "corr_vizinho": viz, "corr_prox_shot": shot, "erro_leitura": erro}


def base_rows():
    rows = []
    # qpu_real: q0 0,4 -> 0,6 (zdiff conhecido); q1 0,7 (|z| = 4); q2 0,3 com erro 0,02 (acima)
    real1 = [(0.4, 0.4, "", "0.01"), (0.7, 0.0, 0.0, "0.01"), (0.3, "", "", "0.02")]
    real2 = [(0.6, 0.0, 0.0, "0.01"), (0.7, 0.0, 0.0, "0.01"), (0.3, "", "", "0.06")]
    for lote, spec in (("1", real1), ("2", real2)):
        for pos, (p1, viz, shot, erro) in enumerate(spec):
            rows.append(row("qpu_real", lote, pos, p1, viz, shot, erro))
    for fonte in ("simulador", "os"):
        for lote in ("1", "2"):
            for pos in range(3):
                rows.append(row(fonte, lote, pos, 0.5, 0.0 if pos < 2 else "", 0.0))
    return rows


def write_table(path: Path, rows) -> Path:
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=COLS, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    return path


@pytest.fixture
def table(tmp_path):
    return write_table(tmp_path / "por_qubit.csv", base_rows())


# ---- contas

def test_summary_known_values(table):
    t = rs.read_table(table)
    r = rs.summary_row("qpu_real", t["qpu_real"])
    assert r["n_qubits"] == 3 and r["n_shots"] == SHOTS
    assert r["frac1_lote1"] == pytest.approx((0.4 + 0.7 + 0.3) / 3)
    assert r["frac1_lote2"] == pytest.approx((0.6 + 0.7 + 0.3) / 3)
    # |z| de p1: 0,2/0,05 = 4 (q1, q2); 0,1/0,05 = 2 (q0)
    assert r["zp1_max_abs_lote1"] == pytest.approx(4.0)
    assert r["zp1_n_acima3_lote1"] == 2
    # corr_viz lote 1: r = 0,4 -> z = 0,4 * 10 = 4 (acima); r = 0 (não)
    assert r["corr_viz_n_validos_lote1"] == 2
    assert r["corr_viz_max_abs_lote1"] == pytest.approx(0.4)
    assert r["corr_viz_n_acima3_lote1"] == 1
    assert r["corr_shot_n_acima3_lote1"] == 0
    # zdiff q0: (0,4 - 0,6) / sqrt(2 * 0,25 / 100) = -2,8284; q1 e q2: 0
    expected = -0.2 / math.sqrt(0.5 / SHOTS)
    assert r["zdiff_n"] == 3
    assert r["zdiff_max_abs"] == pytest.approx(abs(expected))
    assert r["zdiff_max_pos"] == 0
    assert r["zdiff_n_acima3"] == 0
    assert r["zdiff_dp"] == pytest.approx(rs.sample_sd([expected, 0.0, 0.0]))


def test_zdiff_skips_constant_qubits():
    a = [{"pos": 0, "p1": 0.0}, {"pos": 1, "p1": 1.0}, {"pos": 2, "p1": 0.5}]
    b = [{"pos": 0, "p1": 0.0}, {"pos": 1, "p1": 1.0}, {"pos": 2, "p1": 0.5}]
    assert rs.zdiff(a, b, SHOTS) == [(2, 0.0)]


def test_sample_sd():
    assert rs.sample_sd([1.0]) is None
    assert rs.sample_sd([1.0, 3.0]) == pytest.approx(math.sqrt(2.0))


def test_excess_rows(table):
    t = rs.read_table(table)
    ex = {(e["lote"], e["posicao"]): e for e in rs.excess_rows(t["qpu_real"])}
    q2 = ex[("1", 2)]  # desvio 0,2, erro 0,02 -> excesso 0,18 > limite 0,15
    assert q2["desvio"] == pytest.approx(0.2)
    assert q2["excesso"] == pytest.approx(0.18)
    assert q2["limite_3ep"] == pytest.approx(0.15)
    assert q2["acima_do_limite"] is True
    assert ex[("2", 2)]["acima_do_limite"] is False  # erro 0,06 -> excesso 0,14 < 0,15
    assert len(ex) == 6


# ---- recusas na leitura

@pytest.mark.parametrize("mutate, match", [
    (lambda rows: [r for r in rows if not (r["fonte"] == "os" and r["lote"] == "2")], "lotes"),
    (lambda rows: rows + [row("os", "1", 1, 0.5)], "posições"),
    (lambda rows: [dict(r, erro_leitura="") if r["fonte"] == "qpu_real" else r for r in rows],
     "erro_leitura vazio"),
    (lambda rows: [dict(r, n_shots=99) if (r["fonte"], r["lote"], r["posicao"]) == ("os", "2", 0)
                   else r for r in rows], "n_shots"),
    (lambda rows: [dict(r, p1=1.5) if r["posicao"] == 0 else r for r in rows], "p1 fora"),
    (lambda rows: [r for r in rows if r["fonte"] != "qpu_real"], "sem a fonte"),
    (lambda rows: [dict(r, qubit_fisico=9) if (r["fonte"], r["lote"], r["posicao"]) == ("os", "2", 1)
                   else r for r in rows], "mapa"),
])
def test_read_refuses(tmp_path, mutate, match):
    path = write_table(tmp_path / "t.csv", mutate(base_rows()))
    with pytest.raises(rs.SummaryError, match=match):
        rs.read_table(path)


# ---- gravação determinística

def test_main_writes_then_equal(table, tmp_path):
    out = tmp_path / "res"
    assert rs.main(["--entrada", str(table), "--out-dir", str(out)]) == 0
    first = [(out / n).read_bytes() for n in (rs.RESUMO_NAME, rs.EXCESSO_NAME)]
    assert rs.main(["--entrada", str(table), "--out-dir", str(out)]) == 0
    assert [(out / n).read_bytes() for n in (rs.RESUMO_NAME, rs.EXCESSO_NAME)] == first
    with open(out / rs.RESUMO_NAME, encoding="utf-8", newline="") as fh:
        assert [r["fonte"] for r in csv.DictReader(fh)] == ["qpu_real", "simulador", "os"]


def test_crlf_copy_counts_as_equal(table, tmp_path):
    out = tmp_path / "res"
    assert rs.main(["--entrada", str(table), "--out-dir", str(out)]) == 0
    p = out / rs.RESUMO_NAME
    p.write_bytes(p.read_bytes().replace(b"\n", b"\r\n"))
    assert rs.main(["--entrada", str(table), "--out-dir", str(out)]) == 0


def test_different_existing_refuses_and_writes_nothing(table, tmp_path):
    out = tmp_path / "res"
    out.mkdir()
    (out / rs.RESUMO_NAME).write_text("velho\n", encoding="utf-8")
    assert rs.main(["--entrada", str(table), "--out-dir", str(out)]) == 1
    assert (out / rs.RESUMO_NAME).read_text(encoding="utf-8") == "velho\n"
    assert not (out / rs.EXCESSO_NAME).exists()
    assert not list(out.glob("*.tmp"))


def test_missing_input_refuses(tmp_path):
    assert rs.main(["--entrada", str(tmp_path / "nada.csv"), "--out-dir", str(tmp_path)]) == 1
