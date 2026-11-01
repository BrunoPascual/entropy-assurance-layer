"""Testes de scripts/analisar_cal.py (Dia 6), com lotes sintéticos e métricas montadas à mão."""
from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import math
import sys
from pathlib import Path

import numpy as np
import pytest

from eal.sources.base import RawBatch
from eal.sources.ibm_bits import BIT_ORDER
from eal.storage import save_batch

_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(_SCRIPTS))
_SPEC = importlib.util.spec_from_file_location("analisar_cal", _SCRIPTS / "analisar_cal.py")
cal = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = cal
_SPEC.loader.exec_module(cal)

QUBITS = 4
PROBS = [0.5, 0.4, 0.55, 0.5]
SMALL_GROUPS = (("vies", (1,)), ("controle", (2,)))
SMALL_PAIRS = ((0, 1),)
READOUT = [0.01 * (i + 1) for i in range(QUBITS)]


# ---- contas, com métricas montadas à mão

def metrics(p1, viz=None):
    return {"p1": np.array(p1, dtype=float),
            "corr_vizinho": np.array(viz if viz is not None else [0.0] * len(p1), dtype=float)}


def test_fixed_qubit_known_values():
    labels = ["cal_002", "coleta1_001", "coleta1_002"]
    shots = {"cal_002": 4000, "coleta1_001": 10000, "coleta1_002": 10000}
    m = {"cal_002": metrics([0.5, 0.41]), "coleta1_001": metrics([0.5, 0.40]),
         "coleta1_002": metrics([0.5, 0.40])}
    rows = cal.fixed_rows(labels, shots, m, [0.01, 0.02], groups=(("g", (1,)),), pairs=())
    r = {x["lote"]: x for x in rows}["cal_002"]
    se = 0.5 / math.sqrt(4000)
    assert r["se"] == pytest.approx(se)
    assert r["z"] == pytest.approx(-0.09 / se)
    assert r["referencia_coleta1"] == pytest.approx(0.40)
    assert r["z_esperado"] == pytest.approx(0.10 / se)
    assert r["testavel"] is True and r["sinal_igual"] is True and r["replica"] is True
    # zdiff = 0,01 / sqrt(0,41*0,59/4000 + 0,40*0,60/20000)
    assert r["zdiff_vs_coleta1"] == pytest.approx(1.1747, rel=1e-3)
    assert r["magnitude_compativel"] is True
    assert r["excesso"] == pytest.approx(0.09 - 0.02)
    ref_row = {x["lote"]: x for x in rows}["coleta1_001"]
    assert ref_row["testavel"] is None and ref_row["replica"] is None


def test_low_power_is_not_testable():
    shots = {"cal_001": 100, "coleta1_001": 10000, "coleta1_002": 10000}
    m = {"cal_001": metrics([0.5, 0.38]), "coleta1_001": metrics([0.5, 0.40]),
         "coleta1_002": metrics([0.5, 0.40])}
    rows = cal.fixed_rows(list(shots), shots, m, [0.0, 0.0], groups=(("g", (1,)),), pairs=())
    r = {x["lote"]: x for x in rows}["cal_001"]
    assert r["z_esperado"] == pytest.approx(2.0)  # 0,10 / 0,05
    assert r["testavel"] is False
    assert r["replica"] is None and r["magnitude_compativel"] is None


def test_opposite_sign_is_not_replica():
    shots = {"cal_002": 4000, "coleta1_001": 10000, "coleta1_002": 10000}
    m = {"cal_002": metrics([0.5, 0.6]), "coleta1_001": metrics([0.5, 0.4]),
         "coleta1_002": metrics([0.5, 0.4])}
    rows = cal.fixed_rows(list(shots), shots, m, [0.0, 0.0], groups=(("g", (1,)),), pairs=())
    r = {x["lote"]: x for x in rows}["cal_002"]
    assert r["testavel"] is True and r["sinal_igual"] is False
    assert r["replica"] is False and r["magnitude_compativel"] is False


def test_pair_known_values_and_power():
    shots = {"cal_001": 1000, "cal_002": 4000, "coleta1_001": 10000, "coleta1_002": 10000}
    m = {"cal_001": metrics([0.5, 0.5], [-0.05, 0.0]), "cal_002": metrics([0.5, 0.5], [-0.05, 0.0]),
         "coleta1_001": metrics([0.5, 0.5], [-0.06, 0.0]), "coleta1_002": metrics([0.5, 0.5], [-0.06, 0.0])}
    rows = cal.fixed_rows(list(shots), shots, m, [0.0, 0.0], groups=(), pairs=((0, 1),))
    by = {x["lote"]: x for x in rows}
    r2 = by["cal_002"]
    assert r2["z"] == pytest.approx(-0.05 * math.sqrt(4000))
    assert r2["z_esperado"] == pytest.approx(0.06 * math.sqrt(4000))  # 3,795
    assert r2["testavel"] is True and r2["replica"] is True
    # |r - ref| / sqrt(1/4000 + 1/20000) = 0,01 / 0,017321
    assert r2["zdiff_vs_coleta1"] == pytest.approx(0.01 / math.sqrt(1 / 4000 + 1 / 20000))
    assert r2["magnitude_compativel"] is True
    r1 = by["cal_001"]
    assert r1["z_esperado"] == pytest.approx(0.06 * math.sqrt(1000))  # 1,897
    assert r1["testavel"] is False and r1["replica"] is None


def test_fixed_rows_refuse_bad_positions():
    shots = {"cal_001": 100, "coleta1_001": 100}
    m = {k: metrics([0.5, 0.5]) for k in shots}
    with pytest.raises(cal.CalError):
        cal.fixed_rows(list(shots), shots, m, [0.0, 0.0], groups=(("g", (5,)),), pairs=())
    with pytest.raises(cal.CalError):
        cal.fixed_rows(list(shots), shots, m, [0.0, 0.0], groups=(), pairs=((0, 2),))


def test_stability_known_values():
    shots = {"a": 10000, "b": 10000}
    m = {"a": metrics([0.5, 0.0, 0.3]), "b": metrics([0.52, 0.0, 0.3])}
    (row,) = cal.stability_rows(["a", "b"], shots, m)
    assert row["n_qubits"] == 2  # a posição 1 (constante em 0) fica de fora
    z0 = (0.5 - 0.52) / math.sqrt(0.51 * 0.49 * 2 / 10000)
    assert row["zdiff_max_abs"] == pytest.approx(abs(z0))
    assert row["zdiff_max_pos"] == 0
    assert row["zdiff_media"] == pytest.approx(z0 / 2)
    assert row["zdiff_n_acima3"] == 0


# ---- carga e ponta a ponta com lotes sintéticos

def make_lot(raw: Path, session: str, job_id: str, shots: int, seed: int, **over) -> Path:
    rng = np.random.default_rng(seed)
    bits = (rng.random((shots, QUBITS)) < np.array(PROBS)).astype(np.uint8).reshape(-1)
    params = {"backend": "ibm_kingston", "job_id": job_id, "shots": shots, "qubits": QUBITS,
              "n_qubits": QUBITS, "physical_qubits": list(range(QUBITS)), "bit_order": BIT_ORDER,
              "discarded_bits": 0, "readout_error_by_position": list(READOUT),
              "calibration_date": "2026-11-01 11:57:51-03:00"}
    params.update(over)
    batch = RawBatch(source_id="ibm_kingston", source_type="qpu_ibm", source_version="teste",
                     is_local=False, is_simulated=False, bits=bits, params=params)
    return save_batch(batch, session, raw)


def write_inventory(path: Path, npys) -> None:
    import analisar_coleta1 as ac
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(ac.INVENTORY_COLUMNS)
        for npy in npys:
            meta = npy.with_suffix(".json")
            p = json.loads(meta.read_text(encoding="utf-8"))["params"]
            w.writerow([meta.name, p["job_id"], p["qubits"], p["shots"], p["qubits"] * p["shots"],
                        hashlib.sha256(npy.read_bytes()).hexdigest(),
                        hashlib.sha256(meta.read_bytes()).hexdigest()])


@pytest.fixture
def world(tmp_path):
    raw = tmp_path / "raw"
    refs = [make_lot(raw, "coleta1", "r1", 3000, 1), make_lot(raw, "coleta1", "r2", 3000, 2)]
    cals = [make_lot(raw, "cal", "c1", 1000, 3), make_lot(raw, "cal", "c2", 2000, 4)]
    inv = tmp_path / "inv.csv"
    write_inventory(inv, refs)
    return raw, inv, refs, cals


def test_run_end_to_end_and_deterministic(world, tmp_path, monkeypatch):
    raw, inv, _, _ = world
    monkeypatch.chdir(tmp_path)
    out = tmp_path / "res"
    states, paths, frows, srows = cal.run(raw, inv, out, groups=SMALL_GROUPS, pairs=SMALL_PAIRS)
    assert states == ["novo"] * 4
    n_fixed = 4 * (1 + 1 + 1)  # 4 lotes x (2 qubits + 1 par)
    def rows(name):
        with open(out / name, encoding="utf-8", newline="") as fh:
            return list(csv.DictReader(fh))
    assert len(rows(cal.LOTES_NAME)) == 4
    assert len(rows(cal.QUBIT_NAME)) == 4 * QUBITS
    assert len(rows(cal.FIXO_NAME)) == n_fixed == len(frows)
    assert len(rows(cal.EST_NAME)) == 6 == len(srows)
    lotes = {r["lote"]: r for r in rows(cal.LOTES_NAME)}
    assert set(lotes) == {"cal_001", "cal_002", "coleta1_001", "coleta1_002"}
    assert lotes["cal_001"]["conferencia"] == "batch_hash"
    assert lotes["coleta1_001"]["conferencia"] == "inventario+batch_hash"
    assert lotes["cal_002"]["n_shots"] == "2000"
    # o qubit 1 tem p = 0,40: a coleta 1 enxerga o viés e cal_002 (2000 shots) o replica
    fix = {(r["id"], r["lote"]): r for r in rows(cal.FIXO_NAME)}
    assert fix[("1", "cal_002")]["testavel"] == "True" and fix[("1", "cal_002")]["replica"] == "True"
    assert fix[("1", "coleta1_001")]["replica"] == ""
    states2, *_ = cal.run(raw, inv, out, groups=SMALL_GROUPS, pairs=SMALL_PAIRS)
    assert states2 == ["igual"] * 4
    assert not (tmp_path / "data").exists()


@pytest.mark.parametrize("over, match", [
    ({"readout_error_by_position": [0.5] * QUBITS}, "erro de leitura"),
    ({"physical_qubits": [4, 5, 6, 7]}, "mapa de qubits"),
    ({"bit_order": "outra"}, "bit_order"),
    ({"backend": "ibm_outro"}, "backend"),
])
def test_load_cal_refuses_inconsistent(tmp_path, over, match):
    raw = tmp_path / "raw"
    ref = make_lot(raw / "ref", "coleta1", "r1", 500, 1)
    make_lot(raw, "cal", "c1", 500, 3, **over)
    make_lot(raw, "cal", "c2", 500, 4)
    import analisar_coleta1 as ac
    refbatch = ac.load_batch(ref)
    with pytest.raises(cal.CalError, match=match):
        cal.load_cal(raw, refbatch)


def test_load_cal_refuses_wrong_count(tmp_path):
    raw = tmp_path / "raw"
    ref = make_lot(raw / "ref", "coleta1", "r1", 500, 1)
    make_lot(raw, "cal", "c1", 500, 3)
    import analisar_coleta1 as ac
    with pytest.raises(cal.CalError, match="esperava 2"):
        cal.load_cal(raw, ac.load_batch(ref))


def test_altered_cal_npy_refuses(world):
    raw, inv, _, cals = world
    np.save(cals[0], np.packbits(np.ones(QUBITS * 1000, dtype=np.uint8)))
    with pytest.raises(cal.CalError):
        cal.run(raw, inv, raw.parent / "res", groups=SMALL_GROUPS, pairs=SMALL_PAIRS)


def test_different_existing_output_refuses_and_writes_nothing(world, tmp_path):
    raw, inv, _, _ = world
    out = tmp_path / "res"
    out.mkdir()
    (out / cal.FIXO_NAME).write_text("velho\n", encoding="utf-8")
    with pytest.raises(Exception):
        cal.run(raw, inv, out, groups=SMALL_GROUPS, pairs=SMALL_PAIRS)
    assert (out / cal.FIXO_NAME).read_text(encoding="utf-8") == "velho\n"
    assert not (out / cal.LOTES_NAME).exists()


def test_main_refuses_without_inventory(tmp_path):
    assert cal.main(["--raw-dir", str(tmp_path), "--inventario", str(tmp_path / "x.csv"),
                     "--out-dir", str(tmp_path / "o")]) == 1
