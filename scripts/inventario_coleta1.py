"""Dia 6, R6: inventário dos lotes crus da coleta 1 (só leitura dos dados) em data/results.

Lê os lotes ``*_coleta1_*.json``/``.npy`` de ``data/raw`` e o log de uso, confere tudo e grava
``data/results/dia6_coleta1_inventario.csv``, uma linha por lote. Nenhum número é digitado à
mão: o registro do gate no PROJECT.md sai deste CSV.

Conferências (qualquer falha recusa e não grava nada):

- formato ``eal-rawbatch-v1``, packbits big, lote real (``is_local`` e ``is_simulated`` falsos)
  e ``source_id`` igual ao backend dos params;
- ``n_bits == shots * qubits``, mapa de qubits com ``qubits`` posições e ``.npy`` uint8 1-D com
  ``ceil(n_bits / 8)`` bytes;
- job_ids distintos e ``.npy`` com SHA-256 distintos (sem lote repetido);
- log de uso sem problemas; cada job tem um ``submitted`` da sessão, com shots e qubits iguais
  aos params, e um ``final`` que aponta para o próprio ``.npy`` com uso maior que zero;
- todo job da sessão no log tem lote em ``data/raw`` (nenhum lote faltando).

O CSV é determinístico (sem data de execução). Se já existir igual, nada é gravado; se existir
diferente, recusa.

Uso (na raiz do projeto):
    py -3.12 scripts\\inventario_coleta1.py
    py -3.12 scripts\\inventario_coleta1.py --sessao coleta2
A sessão (só letras e dígitos) escolhe os lotes e o nome da saída,
``data/results/dia6_<sessao>_inventario.csv``; o padrão é ``coleta1``.
Código de saída: 0 gravado ou já igual; 1 recusado (nada foi gravado); 2 erro de uso.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from eal.sources.qpu_budget import read_log  # noqa: E402

SESSION = "coleta1"
RAW_DIR = Path("data/raw")
LOG_PATH = Path("data/logs/qpu_usage.csv")
SESSION_RE = re.compile(r"[A-Za-z0-9]+")
OUT_PATH = Path("data/results/dia6_coleta1_inventario.csv")
FORMAT = "eal-rawbatch-v1"
PACKING = "numpy.packbits, bitorder=big"
COLUMNS = ("arquivo", "job_id", "backend", "qubits", "shots", "n_bits", "uso_qpu_s",
           "reserva_s", "calibracao", "npy_sha256", "json_sha256")


class InventoryError(Exception):
    """Recusa: nada foi gravado."""


@dataclass(frozen=True)
class Row:
    arquivo: str
    job_id: str
    backend: str
    qubits: int
    shots: int
    n_bits: int
    uso_qpu_s: float
    reserva_s: float
    calibracao: str
    npy_sha256: str
    json_sha256: str


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _check_batch(meta_path: Path) -> tuple[dict, str, str]:
    """Confere um lote; devolve (params, sha do .npy, sha do .json)."""
    name = meta_path.name
    json_bytes = meta_path.read_bytes()
    meta = json.loads(json_bytes.decode("utf-8"))
    params = meta.get("params") or {}
    if meta.get("format") != FORMAT or meta.get("packing") != PACKING:
        raise InventoryError(f"{name}: formato ou packing inesperado")
    if meta.get("is_local") is not False or meta.get("is_simulated") is not False:
        raise InventoryError(f"{name}: lote não é real (is_local/is_simulated)")
    if meta.get("source_id") != params.get("backend"):
        raise InventoryError(f"{name}: source_id difere do backend dos params")
    shots, qubits, n_bits = params.get("shots"), params.get("qubits"), meta.get("n_bits")
    if not all(isinstance(v, int) and not isinstance(v, bool) and v > 0
               for v in (shots, qubits, n_bits)):
        raise InventoryError(f"{name}: shots, qubits ou n_bits inválidos")
    if n_bits != shots * qubits:
        raise InventoryError(f"{name}: n_bits {n_bits} != shots x qubits {shots * qubits}")
    if len(params.get("physical_qubits") or []) != qubits:
        raise InventoryError(f"{name}: mapa de qubits com tamanho diferente de qubits")
    npy = meta_path.with_suffix(".npy")
    if not npy.exists():
        raise InventoryError(f"{name}: falta o .npy")
    packed = np.load(npy, allow_pickle=False)
    if packed.dtype != np.uint8 or packed.ndim != 1 or packed.size != math.ceil(n_bits / 8):
        raise InventoryError(f"{npy.name}: .npy não tem {math.ceil(n_bits / 8)} bytes uint8 1-D")
    return params, _sha256(npy.read_bytes()), _sha256(json_bytes)


def build_rows(raw_dir: Path, log_path: Path, session: str = SESSION) -> list[Row]:
    """Monta e confere as linhas do inventário; levanta InventoryError."""
    metas = sorted(raw_dir.glob(f"*_{session}_*.json"))
    if not metas:
        raise InventoryError(f"nenhum lote da sessão {session} em {raw_dir}")
    entries, problems = read_log(log_path)
    if problems:
        raise InventoryError("log de uso com problemas: " + "; ".join(problems))
    tag = f"session={session}"
    session_jobs = {e.job_id for e in entries
                    if e.event == "submitted" and tag in e.note.split("; ")}
    rows: list[Row] = []
    for meta_path in metas:
        params, npy_sha, json_sha = _check_batch(meta_path)
        job_id = params.get("job_id")
        npy_name = meta_path.with_suffix(".npy").name
        sub = [e for e in entries if e.event == "submitted" and e.job_id == job_id]
        fin = [e for e in entries if e.event == "final" and e.job_id == job_id]
        if len(sub) != 1 or job_id not in session_jobs:
            raise InventoryError(f"{job_id}: sem um único submitted da sessão {session} no log")
        if (sub[0].shots, sub[0].qubits) != (params["shots"], params["qubits"]):
            raise InventoryError(f"{job_id}: shots ou qubits do log diferem dos params")
        if len(fin) != 1 or fin[0].output_file != npy_name:
            raise InventoryError(f"{job_id}: sem um único final apontando para {npy_name}")
        if fin[0].quantum_seconds is None or not fin[0].quantum_seconds > 0:
            raise InventoryError(f"{job_id}: final sem uso de QPU")
        rows.append(Row(meta_path.name, job_id, params["backend"], params["qubits"],
                        params["shots"], params["shots"] * params["qubits"],
                        fin[0].quantum_seconds, sub[0].reserve_seconds,
                        str(params.get("calibration_date", "")), npy_sha, json_sha))
    if len({r.job_id for r in rows}) != len(rows):
        raise InventoryError("job_id repetido entre lotes")
    if len({r.npy_sha256 for r in rows}) != len(rows):
        raise InventoryError(".npy idênticos entre lotes (possível replay)")
    missing = session_jobs - {r.job_id for r in rows}
    if missing:
        raise InventoryError("jobs da sessão no log sem lote em data/raw: "
                             + ", ".join(sorted(missing)))
    return rows


def render(rows: list[Row]) -> bytes:
    """CSV com cabeçalho, CRLF (igual ao que o Git devolve no Windows), UTF-8."""
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\r\n")
    writer.writerow(COLUMNS)
    for r in rows:
        writer.writerow([getattr(r, c) if c not in ("uso_qpu_s", "reserva_s")
                         else f"{getattr(r, c):g}" for c in COLUMNS])
    return out.getvalue().encode("utf-8")


def write(out_path: Path, data: bytes) -> str:
    """Grava sem sobrescrever; devolve 'gravado' ou 'ja igual'. Levanta InventoryError."""
    if out_path.exists():
        if out_path.read_bytes() == data:
            return "ja igual"
        raise InventoryError(f"{out_path} já existe com outro conteúdo")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "xb") as fh:
        fh.write(data)
        fh.flush()
        os.fsync(fh.fileno())
    return "gravado"


def out_path_for(session: str) -> Path:
    """CSV do inventário de uma sessão; ``coleta1`` dá o nome de sempre (OUT_PATH)."""
    return Path(f"data/results/dia6_{session}_inventario.csv")


def check_session(session: str) -> str:
    """Só letras e dígitos: o nome entra num glob e no nome do arquivo, e ``_`` separa o rótulo."""
    if not isinstance(session, str) or not SESSION_RE.fullmatch(session):
        raise InventoryError(f"sessão inválida: {session!r}")
    return session


def main(raw_dir: Path = RAW_DIR, log_path: Path = LOG_PATH, out_path: Path | None = None,
         session: str = SESSION) -> int:
    try:
        session = check_session(session)
        if out_path is None:
            out_path = out_path_for(session)
        rows = build_rows(raw_dir, log_path, session)
        data = render(rows)
        state = write(out_path, data)
    except (InventoryError, OSError, ValueError) as exc:
        print(f"RECUSADO (nada foi gravado): {exc}")
        return 1
    for r in rows:
        print(f"{r.arquivo} | job {r.job_id} | {r.n_bits} bits | uso {r.uso_qpu_s:g} s")
    total = sum(r.n_bits for r in rows)
    print(f"lotes: {len(rows)} | bits: {total} | uso de QPU: {sum(r.uso_qpu_s for r in rows):g} s")
    label = "gravado" if state == "gravado" else "já existia igual (nada gravado)"
    print(f"{out_path}: {label}; SHA-256 {_sha256(data).upper()}")
    return 0


def cli(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Dia 6: inventário dos lotes de uma sessão")
    ap.add_argument("--sessao", default=SESSION)
    args = ap.parse_args(argv)
    return main(session=args.sessao)


if __name__ == "__main__":
    sys.exit(cli())
