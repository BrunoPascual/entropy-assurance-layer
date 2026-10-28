"""Gravação e leitura de lotes crus (RawBatch) em disco.

Formato (seção 11 do PROJECT.md):
  data/raw/AAAA-MM-DD_<source_id>_<sessao>_<n>.npy   bits com numpy.packbits
  data/raw/AAAA-MM-DD_<source_id>_<sessao>_<n>.json  metadados, sem os bits

Regras:
  - nunca sobrescreve um lote já salvo;
  - grava primeiro em arquivos temporários e só depois dá o nome final;
    o .json é o último a aparecer, então lote sem .json = lote incompleto;
  - ao carregar, recalcula o batch_hash e recusa o lote se não bater.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

import numpy as np

from eal.sources.base import RawBatch

RAW_DIR = Path("data/raw")
FORMAT = "eal-rawbatch-v1"
_SESSION_RE = re.compile(r"^[A-Za-z0-9-]+$")


def _json_default(obj: Any) -> Any:
    """Converte tipos do numpy para tipos nativos do JSON."""
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, np.floating):
        return float(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    raise TypeError(f"valor não serializável em params: {type(obj).__name__}")


def batch_metadata(batch: RawBatch) -> dict[str, Any]:
    """Metadados do lote (todos os campos, menos os bits)."""
    return {
        "format": FORMAT,
        "batch_id": batch.batch_id,
        "source_id": batch.source_id,
        "source_type": batch.source_type,
        "source_version": batch.source_version,
        "is_local": batch.is_local,
        "is_simulated": batch.is_simulated,
        "n_bits": batch.n_bits,
        "created_at": batch.created_at,
        "params": batch.params,
        "batch_hash": batch.batch_hash,
        "packing": "numpy.packbits, bitorder=big",
    }


def next_path(raw_dir: Path, day: str, source_id: str, session: str) -> Path:
    """Próximo caminho livre AAAA-MM-DD_<fonte>_<sessao>_<n>.npy (n com 3 dígitos)."""
    prefix = f"{day}_{source_id}_{session}_"
    used = [int(p.stem[len(prefix):]) for p in raw_dir.glob(f"{prefix}*.npy")
            if p.stem[len(prefix):].isdigit()]
    return raw_dir / f"{prefix}{max(used, default=0) + 1:03d}.npy"


def save_batch(batch: RawBatch, session: str, raw_dir: Path = RAW_DIR) -> Path:
    """Salva o lote como .npy + .json e retorna o caminho do .npy."""
    if not _SESSION_RE.match(session):
        raise ValueError("session só pode ter letras, números e hífen (ex.: s1)")
    raw_dir.mkdir(parents=True, exist_ok=True)
    npy = next_path(raw_dir, batch.created_at[:10], batch.source_id, session)
    meta = npy.with_suffix(".json")
    if npy.exists() or meta.exists():
        raise FileExistsError(f"lote já existe: {npy}")
    meta_text = json.dumps(batch_metadata(batch), indent=2, ensure_ascii=False,
                           default=_json_default)
    tmp_npy, tmp_meta = npy.with_suffix(".npy.tmp"), npy.with_suffix(".json.tmp")
    with open(tmp_npy, "xb") as fh:
        np.save(fh, np.packbits(batch.bits), allow_pickle=False)
    with open(tmp_meta, "x", encoding="utf-8") as fh:
        fh.write(meta_text)
    os.rename(tmp_npy, npy)
    os.rename(tmp_meta, meta)  # por último: marca o lote como completo
    return npy


def load_batch(npy_path: Path | str) -> RawBatch:
    """Carrega o lote e confere a integridade pelo batch_hash."""
    npy = Path(npy_path)
    meta_path = npy.with_suffix(".json")
    if not meta_path.exists():
        raise FileNotFoundError(f"lote incompleto, falta o .json: {meta_path}")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    if meta.get("format") != FORMAT:
        raise ValueError(f"formato desconhecido: {meta.get('format')!r}")
    packed = np.load(npy, allow_pickle=False)
    n_bits = int(meta["n_bits"])
    if packed.dtype != np.uint8 or packed.size != (n_bits + 7) // 8:
        raise ValueError("tamanho do .npy não confere com n_bits do .json")
    batch = RawBatch(
        source_id=meta["source_id"], source_type=meta["source_type"],
        source_version=meta["source_version"], is_local=meta["is_local"],
        is_simulated=meta["is_simulated"],
        bits=np.unpackbits(packed)[:n_bits].copy(), params=meta["params"],
        batch_id=meta["batch_id"], created_at=meta["created_at"],
    )
    if batch.batch_hash != meta["batch_hash"]:
        raise ValueError(f"batch_hash não confere: lote alterado ou corrompido ({npy.name})")
    return batch
