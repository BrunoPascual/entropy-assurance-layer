"""Testes de scripts/inventario_coleta1.py (Dia 6, R6), com lotes e log sintéticos."""
from __future__ import annotations

import csv
import importlib.util
import io
import json
import sys
from pathlib import Path

import numpy as np
import pytest

from eal.sources.qpu_budget import UsageEntry, append_entry

_SPEC = importlib.util.spec_from_file_location(
    "inventario_coleta1",
    Path(__file__).resolve().parents[1] / "scripts" / "inventario_coleta1.py")
inv = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = inv  # o @dataclass do módulo exige o registro
_SPEC.loader.exec_module(inv)

QUBITS, SHOTS = 3, 8  # 24 bits por lote: 3 bytes empacotados


def make_batch(raw: Path, n: int, job_id: str, seed: int, **over) -> Path:
    bits = np.random.default_rng(seed).integers(0, 2, QUBITS * SHOTS, dtype=np.uint8)
    name = f"2026-11-01_ibm_kingston_coleta1_{n:03d}"
    raw.mkdir(parents=True, exist_ok=True)
    np.save(raw / f"{name}.npy", over.pop("packed", np.packbits(bits, bitorder="big")))
    params = {"backend": "ibm_kingston", "job_id": job_id, "shots": SHOTS, "qubits": QUBITS,
              "physical_qubits": list(range(QUBITS)),
              "calibration_date": "2026-11-01 11:57:51-03:00"}
    params.update(over.pop("params", {}))
    meta = {"format": "eal-rawbatch-v1", "packing": "numpy.packbits, bitorder=big",
            "n_bits": QUBITS * SHOTS, "source_id": "ibm_kingston", "source_type": "qpu_ibm",
            "is_local": False, "is_simulated": False, "params": params}
    meta.update(over)
    path = raw / f"{name}.json"
    path.write_text(json.dumps(meta), encoding="utf-8")
    return path


def log_job(log: Path, job_id: str, n: int, *, session="coleta1", uso=5.0, final=True,
            output=None, shots=SHOTS) -> None:
    append_entry(log, UsageEntry(ts="2026-11-01T15:00:00+00:00", event="submitted",
                                 job_id=job_id, backend="ibm_kingston", qubits=QUBITS,
                                 shots=shots, reserve_seconds=20.0,
                                 note=f"session={session}"))
    if final:
        out = output or f"2026-11-01_ibm_kingston_coleta1_{n:03d}.npy"
        append_entry(log, UsageEntry(ts="2026-11-01T15:05:00+00:00", event="final",
                                     job_id=job_id, quantum_seconds=uso, output_file=out,
                                     note="status=DONE"))


@pytest.fixture
def env(tmp_path):
    raw, log = tmp_path / "raw", tmp_path / "logs" / "qpu_usage.csv"
    make_batch(raw, 1, "jobA", 1)
    make_batch(raw, 2, "jobB", 2)
    log_job(log, "cal1", 9, session="cal", output="2026-11-01_ibm_kingston_cal_001.npy")
    log_job(log, "jobA", 1)
    log_job(log, "jobB", 2)
    return raw, log, tmp_path / "results" / "dia6_coleta1_inventario.csv"


def refused(raw, log, match):
    with pytest.raises(inv.InventoryError, match=match):
        inv.build_rows(raw, log)


def test_inventario_de_dois_lotes(env):
    raw, log, _ = env
    rows = inv.build_rows(raw, log)
    assert [r.job_id for r in rows] == ["jobA", "jobB"]
    assert all(r.n_bits == 24 and r.uso_qpu_s == 5.0 and r.reserva_s == 20.0 for r in rows)
    assert rows[0].npy_sha256 != rows[1].npy_sha256 and len(rows[0].json_sha256) == 64


def test_csv_tem_cabecalho_crlf_e_uma_linha_por_lote(env):
    raw, log, _ = env
    data = inv.render(inv.build_rows(raw, log))
    assert data.count(b"\r\n") == 3 and b"\n" not in data.replace(b"\r\n", b"")
    rows = list(csv.reader(io.StringIO(data.decode(), newline="")))
    assert tuple(rows[0]) == inv.COLUMNS
    assert rows[1][:8] == ["2026-11-01_ibm_kingston_coleta1_001.json", "jobA", "ibm_kingston",
                           "3", "8", "24", "5", "20"]


def test_main_grava_e_segunda_vez_nao_grava(env, capsys):
    raw, log, out = env
    assert inv.main(raw, log, out) == 0
    first, mtime = out.read_bytes(), out.stat().st_mtime_ns
    assert "bits: 48" in capsys.readouterr().out
    assert inv.main(raw, log, out) == 0
    assert out.read_bytes() == first and out.stat().st_mtime_ns == mtime
    assert "já existia igual" in capsys.readouterr().out


def test_nao_sobrescreve_csv_diferente(env, capsys):
    raw, log, out = env
    out.parent.mkdir(parents=True)
    out.write_bytes(b"outro")
    assert inv.main(raw, log, out) == 1
    assert out.read_bytes() == b"outro" and "RECUSADO" in capsys.readouterr().out


def test_recusa_nao_grava_nada(env):
    raw, log, out = env
    (raw / "2026-11-01_ibm_kingston_coleta1_002.npy").unlink()
    assert inv.main(raw, log, out) == 1 and not out.exists()


def test_sem_lotes(tmp_path):
    refused(tmp_path / "raw", tmp_path / "log.csv", "nenhum lote")


@pytest.mark.parametrize("over,match", [
    ({"n_bits": 23}, "n_bits"),
    ({"is_simulated": True}, "não é real"),
    ({"is_local": True}, "não é real"),
    ({"source_id": "outro"}, "source_id"),
    ({"format": "v0"}, "formato"),
    ({"packing": "numpy.packbits, bitorder=little"}, "formato"),
    ({"params": {"physical_qubits": [0, 1]}}, "mapa de qubits"),
    ({"params": {"shots": True}}, "inválidos"),
    ({"packed": np.zeros(4, dtype=np.uint8)}, "bytes uint8"),
    ({"packed": np.zeros(3, dtype=np.int16)}, "bytes uint8"),
    ({"packed": np.zeros((1, 3), dtype=np.uint8)}, "bytes uint8"),
])
def test_recusa_lote_invalido(env, over, match):
    raw, log, _ = env
    make_batch(raw, 2, "jobB", 2, **over)
    refused(raw, log, match)


def test_recusa_npy_identicos(env):
    raw, log, _ = env
    make_batch(raw, 2, "jobB", 1)  # mesma semente do jobA: mesmos bits
    refused(raw, log, "idênticos")


def test_recusa_job_id_repetido(env):
    raw, log, _ = env
    make_batch(raw, 2, "jobA", 2)
    refused(raw, log, "submitted|final")


def test_recusa_job_sem_final(tmp_path):
    raw, log = tmp_path / "raw", tmp_path / "log.csv"
    make_batch(raw, 1, "jobA", 1)
    log_job(log, "jobA", 1, final=False)
    refused(raw, log, "final")


def test_recusa_final_apontando_para_outro_arquivo(tmp_path):
    raw, log = tmp_path / "raw", tmp_path / "log.csv"
    make_batch(raw, 1, "jobA", 1)
    log_job(log, "jobA", 1, output="outro.npy")
    refused(raw, log, "final")


def test_recusa_job_de_outra_sessao(tmp_path):
    raw, log = tmp_path / "raw", tmp_path / "log.csv"
    make_batch(raw, 1, "jobA", 1)
    log_job(log, "jobA", 1, session="cal")
    refused(raw, log, "sessão coleta1")


def test_recusa_shots_do_log_diferentes(tmp_path):
    raw, log = tmp_path / "raw", tmp_path / "log.csv"
    make_batch(raw, 1, "jobA", 1)
    log_job(log, "jobA", 1, shots=SHOTS + 1)
    refused(raw, log, "diferem dos params")


def test_recusa_job_da_sessao_sem_lote(env):
    raw, log, _ = env
    log_job(log, "jobC", 3)
    refused(raw, log, "sem lote")


def test_recusa_log_com_problemas(env):
    raw, log, _ = env
    with open(log, "ab") as fh:
        fh.write(b"linha,quebrada\n")
    refused(raw, log, "log de uso com problemas")
