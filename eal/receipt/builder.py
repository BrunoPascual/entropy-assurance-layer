"""Monta o corpo do recibo a partir de uma execução keygen (PROJECT.md 6.11, Dia 5 etapa 2B).

Entradas: o PipelineResult, as DerivedKeys e os objetos Source usados na execução.
O PipelineResult não guarda os lotes; por isso source_type e source_version vêm
do objeto Source, e o hash do lote é o input_hash do MixInput (mesma convenção
do batch_hash). Os params do lote (ex.: job_id da IBM) ainda não chegam aqui.

Regras:
  - só modo keygen, com semente; qualquer inconsistência levanta ValueError
    (nunca um recibo parcial);
  - as chaves são re-derivadas da semente e conferidas com as recebidas;
  - tudo que vai para o recibo é convertido para tipos nativos do JSON;
    bytes e tipos desconhecidos são recusados;
  - nenhum bit, nenhum byte de semente, nenhuma mensagem de exceção.
"""
from __future__ import annotations

import hashlib
import math
import platform
import uuid
from collections.abc import Sequence
from datetime import datetime, timezone
from importlib import metadata
from typing import Any

import numpy as np

from eal.config import (
    DSA_SEED_BYTES,
    EAL_VERSION,
    EXTRACTOR_EPSILON_LOG2,
    EXTRACTOR_INPUT_BITS,
    GENESIS_PREV_HASH,
    ISSUER_DOMAIN,
    RECEIPT_EXTRACTOR_TYPE,
    RECEIPT_ID_NAMESPACE,
    RECEIPT_REQUIRED_LIMITATIONS,
)
from eal.pqc.keygen import DerivedKeys, derive_keys_from_mix
from eal.receipt.schema import KEYGEN_MODE, MIXED_STATUS, validate_body

SOFTWARE_PACKAGES = ("kyber-py", "dilithium-py", "numpy", "scipy")


def to_native(value: Any) -> Any:
    """Converte para tipos nativos do JSON. Recusa bytes, NaN e tipos desconhecidos."""
    if value is None or isinstance(value, str):
        return value
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if isinstance(value, (int, np.integer)):
        return int(value)
    if isinstance(value, (float, np.floating)):
        f = float(value)
        if not math.isfinite(f):
            raise ValueError("valor não finito no recibo")
        return f
    if isinstance(value, dict):
        if not all(isinstance(k, str) for k in value):
            raise TypeError("chave de dicionário que não é texto no recibo")
        return {k: to_native(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_native(v) for v in value]
    raise TypeError(f"tipo não permitido no recibo: {type(value).__name__}")


def software_versions() -> dict[str, str]:
    """Versões do Python e dos pacotes que afetam as chaves e os testes."""
    versions = {"python": platform.python_version()}
    for name in SOFTWARE_PACKAGES:
        try:
            versions[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            versions[name] = "ausente"
    return versions


def receipt_id_for(seed_hash: str) -> str:
    """UUID5 determinístico do seed_hash (sem aleatoriedade fora das fontes)."""
    return str(uuid.uuid5(uuid.UUID(RECEIPT_ID_NAMESPACE), seed_hash))


def issuer_seed_from_mix(mix: Any) -> bytes:
    """xi da chave do emissor a partir de uma semente keygen válida (32 bytes)."""
    derive_keys_from_mix(mix)  # mesma validação: keygen, usable_for_key, seed_hash
    return hashlib.shake_256(ISSUER_DOMAIN + mix.seed).digest(DSA_SEED_BYTES)


def _strict_bool(value: Any, what: str) -> bool:
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    raise ValueError(f"{what} não é booleano")


def _check_result(result: Any) -> None:
    if getattr(result, "mode", None) != KEYGEN_MODE:
        raise ValueError("recibo só existe para execução keygen")
    if getattr(result, "mix", None) is None or getattr(result, "error", None) is not None:
        raise ValueError("execução sem semente: não há recibo (fail-closed)")


def _check_keys(result: Any, keys: Any) -> dict[str, str]:
    if not isinstance(keys, DerivedKeys):
        raise TypeError("keys deve ser DerivedKeys")
    expected = derive_keys_from_mix(result.mix).public_summary()
    given = keys.public_summary()
    if given != expected:
        raise ValueError("as chaves não foram derivadas da semente desta execução")
    return given


def _by_id(items: Sequence[Any], what: str) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for item in items:
        sid = getattr(item, "source_id", None)
        if not isinstance(sid, str) or not sid:
            raise ValueError(f"{what} sem source_id")
        if sid in out:
            raise ValueError(f"{what} com source_id repetido")
        out[sid] = item
    return out


def _source_entry(outcome: Any, src: Any, mi: Any) -> dict[str, Any]:
    is_local = _strict_bool(getattr(src, "is_local", None), "is_local da fonte")
    is_simulated = _strict_bool(getattr(src, "is_simulated", None), "is_simulated da fonte")
    entry: dict[str, Any] = {
        "source_id": outcome.source_id,
        "source_type": str(src.source_type),
        "source_version": str(src.source_version),
        "status": str(outcome.status),
        "batch_id": outcome.batch_id,
        "batch_hash": None,
        "is_local": is_local,
        "is_simulated": is_simulated,
        "approved": False,
        "reasons": [str(r) for r in outcome.reasons],
        "health": None,
        "extraction": None,
    }
    if mi is None:
        return entry
    if (_strict_bool(mi.is_local, "is_local do lote") != is_local
            or _strict_bool(mi.is_simulated, "is_simulated do lote") != is_simulated):
        raise ValueError("flags do lote diferentes das flags da fonte")
    if mi.batch_id != outcome.batch_id:
        raise ValueError("batch_id do lote diferente do registrado na execução")
    entry["batch_hash"] = mi.input_hash
    entry["approved"] = _strict_bool(mi.report.approved, "approved do relatório")
    entry["health"] = to_native(mi.report.to_dict())
    entry["extraction"] = to_native(mi.extraction.to_dict())
    if outcome.status == MIXED_STATUS and mi.extraction.extractor_type != RECEIPT_EXTRACTOR_TYPE:
        raise ValueError("fonte misturada sem extração Toeplitz")
    return entry


def build_receipt_body(
    result: Any,
    keys: DerivedKeys,
    sources: Sequence[Any],
    *,
    prev_receipt_hash: str = GENESIS_PREV_HASH,
    created_at: str | None = None,
    software: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Corpo do recibo (sem assinatura) de uma execução keygen com semente."""
    _check_result(result)
    key_hashes = _check_keys(result, keys)
    src_by_id = _by_id(sources, "fonte")
    inputs_by_id = _by_id(result.inputs, "entrada do mixer")
    _by_id(result.outcomes, "resultado de fonte")  # recusa source_id repetido
    entries = []
    for outcome in result.outcomes:
        src = src_by_id.get(outcome.source_id)
        if src is None:
            raise ValueError("resultado de fonte sem objeto Source correspondente")
        entries.append(_source_entry(outcome, src, inputs_by_id.get(outcome.source_id)))
    mix_meta = to_native(result.mix.to_dict())
    if mix_meta.get("seed_hash") != result.mix.seed_hash:
        raise ValueError("seed_hash do mixer inconsistente")
    body = {
        "eal_version": EAL_VERSION,
        "receipt_id": receipt_id_for(result.mix.seed_hash),
        "created_at": created_at or datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "mode": KEYGEN_MODE,
        "prev_receipt_hash": prev_receipt_hash,
        "software": to_native(software if software is not None else software_versions()),
        "sources": entries,
        "extractor": {"type": RECEIPT_EXTRACTOR_TYPE, "n": EXTRACTOR_INPUT_BITS,
                      "epsilon_log2": EXTRACTOR_EPSILON_LOG2},
        "mixer": mix_meta,
        "seed_hash": result.mix.seed_hash,
        "keys": key_hashes,
        "limitations": list(RECEIPT_REQUIRED_LIMITATIONS),
    }
    problems = validate_body(body)
    if problems:
        raise ValueError("recibo inválido: " + "; ".join(problems))
    return body
