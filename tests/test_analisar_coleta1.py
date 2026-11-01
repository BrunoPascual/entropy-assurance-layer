"""Testes de scripts/analisar_coleta1.py (Dia 6), com lotes sintéticos pequenos."""
from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pytest

from eal.sources.base import RawBatch
from eal.sources.ibm_bits import BIT_ORDER
from eal.storage import save_batch

_SPEC = importlib.util.spec_from_file_location(
    "analisar_coleta1",
    Path(__file__).resolve().parents[1] / "scripts" / "analisar_coleta1.py")
an = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = an
_SPEC.loader.exec_module(an)

QUBITS, SHOTS = 8, 2048  # 16.384 bits por lote


def make_real(raw: Path, job_id: str, seed: int) -> Path:
    bits = np.random.default_rng(seed).integers(0, 2, QUBITS * SHOTS, dtype=np.uint8)
    params = {"backend": "ibm_kingston", "job_id": job_id, "shots": SHOTS, "qubits": QUBITS,
              "n_qubits": QUBITS, "physical_qubits": list(range(QUBITS)), "bit_order": BIT_ORDER,
              "discarded_bits": 0,
              "readout_error_by_position": [0.01 * (i + 1) for i in range(QUBITS)]}
    batch = RawBatch(source_id="ibm_kingston", source_type="qpu_ibm", source_version="teste",
                     is_local=False, is_simulated=False, bits=bits, params=params)
    return save_batch(batch, "coleta1", raw)


def write_inventory(path: Path, npys: list[Path]) -> None:
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(an.INVENTORY_COLUMNS)
        for npy in npys:
            meta = npy.with_suffix(".json")
            p = json.loads(meta.read_text(encoding="utf-8"))
            w.writerow([meta.name, p["params"]["job_id"], QUBITS, SHOTS, QUBITS * SHOTS,
                        hashlib.sha256(npy.read_bytes()).hexdigest(),
                        hashlib.sha256(meta.read_bytes()).hexdigest()])


@pytest.fixture
def lots(tmp_path):
    raw = tmp_path / "raw"
    npys = [make_real(raw, "job1", 1), make_real(raw, "job2", 2)]
    inv = tmp_path / "inv.csv"
    write_inventory(inv, npys)
    return raw, inv, npys


class FakeSim:
    def __init__(self, n_qubits, seed, physical):
        self.rng = np.random.default_rng(seed)

    def read(self, n_bits):
        bits = self.rng.integers(0, 2, n_bits, dtype=np.uint8)
        return RawBatch(source_id="qpu_sim", source_type="qpu_sim", source_version="teste",
                        is_local=True, is_simulated=True, bits=bits, params={})


# ---- carga e conferência

def test_load_real_ok(lots):
    raw, inv, _ = lots
    batches = an.load_real(raw, inv)
    assert [b.params["job_id"] for b in batches] == ["job1", "job2"]
    assert all(b.n_bits == QUBITS * SHOTS for b in batches)


def test_inventory_sha_mismatch_refuses(lots, tmp_path):
    raw, inv, _ = lots
    text = inv.read_text(encoding="utf-8")
    sha = text.splitlines()[1].split(",")[5]
    inv.write_text(text.replace(sha, "0" * 64), encoding="utf-8")
    with pytest.raises(an.AnalysisError, match="sha256"):
        an.load_real(raw, inv)


def test_altered_npy_refuses(lots):
    raw, inv, npys = lots
    np.save(npys[0], np.packbits(np.ones(QUBITS * SHOTS, dtype=np.uint8)))
    with pytest.raises(an.AnalysisError):
        an.load_real(raw, inv)


def test_lot_outside_inventory_refuses(lots):
    raw, inv, _ = lots
    make_real(raw, "job3", 3)
    with pytest.raises(an.AnalysisError, match="diferem do inventário"):
        an.load_real(raw, inv)


def test_repeated_lot_refuses(tmp_path):
    raw = tmp_path / "raw"
    npys = [make_real(raw, "job1", 1), make_real(raw, "job2", 1)]  # mesmos bits
    inv = tmp_path / "inv.csv"
    write_inventory(inv, npys)
    with pytest.raises(an.AnalysisError, match="repetido"):
        an.load_real(raw, inv)


def test_missing_inventory_refuses(tmp_path):
    with pytest.raises(an.AnalysisError, match="não encontrado"):
        an.load_real(tmp_path, tmp_path / "nao_existe.csv")


# ---- métricas por qubit

def test_qubit_metrics_known_matrix():
    # shots x qubits = [[1,1],[0,0],[1,1],[0,0]]: colunas iguais, alternando
    m = an.qubit_metrics(np.array([1, 1, 0, 0, 1, 1, 0, 0], dtype=np.uint8), 2)
    assert m["n_shots"] == 4
    assert np.allclose(m["p1"], [0.5, 0.5])
    assert np.allclose(m["z_p1"], [0.0, 0.0])
    assert m["corr_vizinho"][0] == pytest.approx(1.0)
    assert np.isnan(m["corr_vizinho"][1])
    assert np.allclose(m["corr_prox_shot"], [-1.0, -1.0])


def test_qubit_metrics_column_order_and_constant_columns():
    shots = 16
    bits = np.tile(np.array([0, 1], dtype=np.uint8), shots)  # qubit 0 sempre 0, qubit 1 sempre 1
    m = an.qubit_metrics(bits, 2)
    assert np.allclose(m["p1"], [0.0, 1.0])
    assert np.allclose(m["z_p1"], [-4.0, 4.0])  # -+0,5 / sqrt(0,25 / 16)
    assert np.isnan(m["corr_vizinho"]).all()
    assert np.isnan(m["corr_prox_shot"]).all()


def test_qubit_metrics_bad_shape_refuses():
    with pytest.raises(an.AnalysisError):
        an.qubit_metrics(np.zeros(10, dtype=np.uint8), 3)
    with pytest.raises(an.AnalysisError):
        an.qubit_metrics(np.zeros(4, dtype=np.uint8), 2)  # só 2 shots


# ---- achatamento e gravação

def test_flatten_nested():
    got = an.flatten("x", {"a": 1, "b": {"c": None, "d": [1, 2]}, "e": np.float64(0.5),
                           "f": np.bool_(True)})
    assert got == {"x_a": 1, "x_b_c": "", "x_b_d": "1 | 2", "x_e": 0.5, "x_f": True}


def test_csv_text_different_columns_refuses():
    with pytest.raises(an.AnalysisError):
        an.csv_text([{"a": 1}, {"b": 2}])


def test_write_outputs_all_or_nothing(tmp_path):
    out = tmp_path / "res"
    paths = an.write_outputs(out, "a\n1\n", "b\n2\n")
    assert [p.read_text(encoding="utf-8") for p in paths] == ["a\n1\n", "b\n2\n"]
    assert not list(out.glob("*.tmp"))
    with pytest.raises(an.AnalysisError, match="já existe"):
        an.write_outputs(out, "x\n", "y\n")
    assert paths[0].read_text(encoding="utf-8") == "a\n1\n"


def test_write_outputs_refuses_if_one_exists(tmp_path):
    out = tmp_path / "res"
    out.mkdir()
    (out / an.QUBIT_NAME).write_text("velho\n", encoding="utf-8")
    with pytest.raises(an.AnalysisError):
        an.write_outputs(out, "x\n", "y\n")
    assert not (out / an.LOTS_NAME).exists()
    assert (out / an.QUBIT_NAME).read_text(encoding="utf-8") == "velho\n"


# ---- ponta a ponta (fonte simulada trocada por uma falsa, rápida)

def test_main_end_to_end(lots, tmp_path, monkeypatch):
    raw, inv, _ = lots
    monkeypatch.chdir(tmp_path)
    out = tmp_path / "saida"
    rc = an.main(["--raw-dir", str(raw), "--inventario", str(inv), "--out-dir", str(out)],
                 sim_factory=FakeSim)
    assert rc == 0
    with open(out / an.LOTS_NAME, encoding="utf-8", newline="") as fh:
        lots_rows = list(csv.DictReader(fh))
    with open(out / an.QUBIT_NAME, encoding="utf-8", newline="") as fh:
        qubit_rows = list(csv.DictReader(fh))
    assert [(r["fonte"], r["lote"]) for r in lots_rows] == [
        (f, str(i)) for f in ("qpu_real", "simulador", "os") for i in (1, 2)]
    assert len(qubit_rows) == 6 * QUBITS
    assert all(r["pipe_seed_generated"] == "False" for r in lots_rows if r["fonte"] == "qpu_real")
    assert "ext_n_output_bits" in lots_rows[0] and "pipe_status" in lots_rows[0]
    assert "ext_seed_hash" not in lots_rows[0]
    real_q = [r for r in qubit_rows if r["fonte"] == "qpu_real" and r["lote"] == "1"]
    assert [r["erro_leitura"] for r in real_q] == [f"{0.01 * (i + 1):.12g}" for i in range(QUBITS)]
    assert all(r["erro_leitura"] == "" for r in qubit_rows if r["fonte"] != "qpu_real")
    assert not (tmp_path / "data").exists()  # nada em data/logs, receipts ou keys


def test_main_refuses_on_bad_inventory_and_writes_nothing(lots, tmp_path):
    raw, inv, _ = lots
    text = inv.read_text(encoding="utf-8")
    inv.write_text(text.replace(text.splitlines()[1].split(",")[5], "f" * 64), encoding="utf-8")
    out = tmp_path / "saida"
    rc = an.main(["--raw-dir", str(raw), "--inventario", str(inv), "--out-dir", str(out)],
                 sim_factory=FakeSim)
    assert rc == 1
    assert not out.exists()


def test_main_refuses_if_output_exists_before_simulating(lots, tmp_path):
    raw, inv, _ = lots
    out = tmp_path / "saida"
    out.mkdir()
    (out / an.LOTS_NAME).write_text("velho\n", encoding="utf-8")

    def boom(*a):
        raise AssertionError("não deveria simular")

    rc = an.main(["--raw-dir", str(raw), "--inventario", str(inv), "--out-dir", str(out)],
                 sim_factory=boom)
    assert rc == 1
    assert (out / an.LOTS_NAME).read_text(encoding="utf-8") == "velho\n"
    assert not (out / an.QUBIT_NAME).exists()
