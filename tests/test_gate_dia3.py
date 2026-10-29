"""Testes das partes puras de scripts/gate_dia3.py (linhas, CSV e regras do gate).

A execução com as fontes reais não é testada aqui: ela é o próprio gate.
"""
import hashlib
from dataclasses import dataclass

import numpy as np
import pytest

from eal.health.replay import ReplayDetector
from eal.health.report import build_health_report
from scripts.gate_dia3 import (
    COLUMNS,
    N,
    REPORT_COLS,
    evaluate_gate,
    other_row,
    read_csv,
    report_row,
    write_csv,
)


@dataclass(frozen=True)
class FakeBatch:
    batch_id: str
    source_id: str
    bits: np.ndarray

    @property
    def batch_hash(self) -> str:
        payload = len(self.bits).to_bytes(8, "big") + np.packbits(self.bits).tobytes()
        return hashlib.sha3_256(payload).hexdigest()


def small_report():
    data = hashlib.shake_256(b"gate").digest(1024)
    bits = np.unpackbits(np.frombuffer(data, dtype=np.uint8))
    return build_health_report(FakeBatch("b1", "os", bits), ReplayDetector()).to_dict()


# ---------- linhas ----------

def test_report_row_has_every_column_and_flattens_stats():
    row = report_row({"run_index": 1, "read_index": 1, "n_bits_requested": 8192}, small_report())
    assert list(row) == COLUMNS
    assert row["status"] == "avaliado" and row["source_id"] == "os"
    assert row["stats_monobit"] != "" and row["stats_block"] != "" and row["stats_runs"] != ""
    assert row["approved"] == "False"  # 8192 bits: estatísticos inconclusivos
    assert "inconclusivo" in row["reasons"]


def test_report_row_keeps_full_float_precision():
    rep = small_report()
    row = report_row({}, rep)
    assert float(row["h_estimated"]) == rep["h_estimated"]


def test_report_row_joins_reasons_and_notes():
    rep = small_report()
    row = report_row({}, rep)
    assert row["reasons"] == " | ".join(rep["reasons"])
    assert row["notes"] == " | ".join(rep["notes"])


def test_report_row_none_becomes_empty():
    rep = small_report()
    rep["h_bit"] = None
    assert report_row({}, rep)["h_bit"] == ""


def test_report_row_rejects_unknown_field():
    rep = small_report()
    rep["campo_novo"] = 1
    with pytest.raises(ValueError):
        report_row({}, rep)


def test_report_columns_cover_the_health_report():
    keys = set(small_report()) - {"stats", "source_id"}
    keys |= {"stats_monobit", "stats_block", "stats_runs"}
    assert keys == set(REPORT_COLS)


def test_other_row_pending_and_error():
    p = other_row({"source_id": "ibm_<backend>"}, "pendente", "Dia 6")
    e = other_row({"source_id": "os"}, "erro", "boom")
    assert p["status"] == "pendente" and p["approved"] == "" and list(p) == COLUMNS
    assert e["status"] == "erro" and e["error"] == "boom"
    with pytest.raises(ValueError):
        other_row({}, "ok")


# ---------- CSV ----------

def test_csv_roundtrip(tmp_path):
    rows = [report_row({"run_index": 1}, small_report()), other_row({"run_index": 2}, "pendente")]
    path = tmp_path / "t.csv"
    write_csv(path, rows)
    assert read_csv(path) == rows


def test_csv_never_overwrites(tmp_path):
    path = tmp_path / "t.csv"
    write_csv(path, [])
    with pytest.raises(FileExistsError):
        write_csv(path, [])


def test_csv_keeps_accents(tmp_path):
    path = tmp_path / "t.csv"
    write_csv(path, [other_row({"variant": "ruído"}, "erro", "não")])
    assert read_csv(path)[0]["variant"] == "ruído"


# ---------- gate ----------

def r(source, read, approved, n=N, **flags):
    row = {c: "" for c in COLUMNS}
    base = {"rct_pass": True, "apt_pass": True, "replay_pass": True,
            "h_health_pass": True, "stats_pass": True}
    base.update(flags)
    row.update({k: str(v) for k, v in base.items()})
    row.update(status="avaliado", source_id=source, read_index=str(read),
               n_bits_requested=str(n), approved=str(approved))
    return row


def passing_rows():
    return [
        r("os", 1, True), r("os", 2, True),
        r("faulty_biased", 1, False, apt_pass=False, h_health_pass=False),
        r("faulty_biased", 2, False, apt_pass=False, h_health_pass=False),
        r("faulty_stuck", 1, False, rct_pass=False), r("faulty_stuck", 2, False, rct_pass=False),
        r("faulty_correlated", 1, False, h_health_pass=False),
        r("faulty_correlated", 2, False, h_health_pass=False),
        r("faulty_replay", 1, True), r("faulty_replay", 2, False, replay_pass=False),
        r("faulty_replay", 3, False, n=409_600, replay_pass=False, stats_pass=False),
        r("faulty_prng", 1, True), r("faulty_prng", 2, True),
    ]


def test_gate_passes_with_expected_rows():
    checks = evaluate_gate(passing_rows())
    assert len(checks) == 6 and all(c.ok for c in checks), checks


def _replace(rows, source, read, row):
    return [row if (x["source_id"], x["read_index"]) == (source, str(read)) else x for x in rows]


@pytest.mark.parametrize("source, read, bad, rule", [
    ("os", 2, r("os", 2, False, stats_pass=False), "os aprovada"),
    ("faulty_biased", 1, r("faulty_biased", 1, False, apt_pass=True, h_health_pass=False),
     "faulty_biased reprovada"),
    ("faulty_stuck", 1, r("faulty_stuck", 1, False, rct_pass=True), "faulty_stuck reprovada"),
    ("faulty_correlated", 2, r("faulty_correlated", 2, True), "faulty_correlated reprovada"),
    ("faulty_replay", 1, r("faulty_replay", 1, False, replay_pass=False),
     "faulty_replay pega por replay"),
    ("faulty_replay", 2, r("faulty_replay", 2, False, replay_pass=False, stats_pass=False),
     "faulty_replay pega por replay"),
    ("faulty_prng", 1, r("faulty_prng", 1, False), "faulty_prng passa (limitação T4)"),
])
def test_gate_fails_on_each_unexpected_result(source, read, bad, rule):
    checks = {c.rule: c for c in evaluate_gate(_replace(passing_rows(), source, read, bad))}
    assert not checks[rule].ok
    assert sum(not c.ok for c in checks.values()) == 1


def test_gate_fails_when_source_is_missing():
    rows = [x for x in passing_rows() if x["source_id"] != "faulty_stuck"]
    checks = {c.rule: c for c in evaluate_gate(rows)}
    assert not checks["faulty_stuck reprovada"].ok
    assert "esperadas ao menos" in checks["faulty_stuck reprovada"].detail


def test_gate_fails_on_error_row():
    rows = passing_rows() + [other_row({"source_id": "os", "variant": ""}, "erro", "boom")]
    checks = {c.rule: c for c in evaluate_gate(rows)}
    assert not checks["os aprovada"].ok


def test_gate_ignores_control_and_pending_rows():
    extra_ctrl = r("qpu_sim", 1, False)
    extra_ctrl["variant"] = "ideal (controle)"
    pending = other_row({"source_id": "ibm_<backend>", "variant": "QPU real"}, "pendente")
    assert all(c.ok for c in evaluate_gate(passing_rows() + [extra_ctrl, pending]))
