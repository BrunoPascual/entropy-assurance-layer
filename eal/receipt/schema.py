"""Formato do recibo da EAL (PROJECT.md 6.11): campos, validação e JSON canônico.

O recibo tem um corpo (todos os campos exceto "signature") e a assinatura.
A assinatura cobre o JSON canônico do corpo: chaves ordenadas, sem espaços,
UTF-8, sem NaN nem infinito. As mensagens de validação citam nomes de campos,
nunca valores.
"""
from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import datetime, timedelta
from typing import Any

from eal.config import (
    RECEIPT_BATCH_PARAM_INT_KEYS,
    RECEIPT_BATCH_PARAM_INT_MAX,
    RECEIPT_BATCH_PARAM_TEXT_KEYS,
    RECEIPT_BATCH_PARAM_TEXT_PATTERN,
    RECEIPT_JOB_ID_REQUIRED_TYPES,
    RECEIPT_REQUIRED_LIMITATIONS,
)

KEYGEN_MODE = "keygen"
MIXED_STATUS = "mixed"
BODY_FIELDS = frozenset({
    "eal_version", "receipt_id", "created_at", "mode", "prev_receipt_hash",
    "software", "sources", "extractor", "mixer", "seed_hash", "keys", "limitations",
})
SIGNATURE_FIELD = "signature"
SIGNATURE_FIELDS = frozenset({"alg", "issuer_pk_hash", "value"})
KEY_FIELDS = frozenset({"ml_kem_768_pk_hash", "ml_dsa_65_pk_hash"})
SOURCE_REQUIRED = frozenset({"source_id", "status", "is_local", "is_simulated", "approved"})
_HEX64 = re.compile(r"[0-9a-f]{64}")
_PARAM_TEXT = re.compile(RECEIPT_BATCH_PARAM_TEXT_PATTERN)
BATCH_PARAM_KEYS = frozenset((*RECEIPT_BATCH_PARAM_TEXT_KEYS, *RECEIPT_BATCH_PARAM_INT_KEYS))


def canonical_bytes(obj: Any) -> bytes:
    """JSON canônico em UTF-8. Recusa NaN, infinito e tipos fora do JSON (numpy etc.)."""
    text = json.dumps(
        obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )
    return text.encode("utf-8")


def is_hex64(value: object) -> bool:
    """True para 64 caracteres hexadecimais minúsculos (SHA3-256 em hex)."""
    return isinstance(value, str) and _HEX64.fullmatch(value) is not None


def receipt_body(receipt: dict) -> dict:
    """Corpo do recibo: todos os campos exceto a assinatura."""
    return {k: v for k, v in receipt.items() if k != SIGNATURE_FIELD}


def receipt_hash(receipt: dict) -> str:
    """SHA3-256 do recibo completo (com assinatura), usado no encadeamento."""
    return hashlib.sha3_256(canonical_bytes(receipt)).hexdigest()


def validate_body(body: object) -> list[str]:
    """Lista de problemas do corpo do recibo; lista vazia = válido."""
    if not isinstance(body, dict):
        return ["corpo do recibo não é objeto"]
    missing = BODY_FIELDS - body.keys()
    extra = body.keys() - BODY_FIELDS
    problems: list[str] = []
    if missing:
        problems.append(f"campos ausentes: {sorted(missing)}")
    if extra:
        problems.append(f"campos desconhecidos: {sorted(map(str, extra))}")
    if problems:
        return problems
    problems += _check_header(body)
    problems += _check_keys(body["keys"])
    problems += _check_limitations(body["limitations"])
    problems += _check_sources(body["sources"])
    for name in ("software", "extractor", "mixer"):
        if not isinstance(body[name], dict):
            problems.append(f"{name} não é objeto")
    return problems


def _check_header(body: dict) -> list[str]:
    problems: list[str] = []
    version = body["eal_version"]
    if not (isinstance(version, str) and version):
        problems.append("eal_version vazio ou não é texto")
    if not _is_canonical_uuid(body["receipt_id"]):
        problems.append("receipt_id não é UUID canônico")
    if not _is_utc_timestamp(body["created_at"]):
        problems.append("created_at não é ISO 8601 em UTC")
    if not (isinstance(body["mode"], str) and body["mode"] == KEYGEN_MODE):
        problems.append("mode diferente de keygen")
    for name in ("prev_receipt_hash", "seed_hash"):
        if not is_hex64(body[name]):
            problems.append(f"{name} não é SHA3-256 em hex minúsculo")
    return problems


def _is_canonical_uuid(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        return str(uuid.UUID(value)) == value
    except ValueError:
        return False


def _is_utc_timestamp(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return False
    return parsed.utcoffset() == timedelta(0)


def _check_keys(keys: object) -> list[str]:
    if not (isinstance(keys, dict) and keys.keys() == KEY_FIELDS):
        return [f"keys deve ter exatamente {sorted(KEY_FIELDS)}"]
    return [f"keys.{k} não é SHA3-256 em hex" for k in sorted(keys) if not is_hex64(keys[k])]


def _check_limitations(limitations: object) -> list[str]:
    if not (isinstance(limitations, list) and all(isinstance(x, str) for x in limitations)):
        return ["limitations não é lista de textos"]
    absent = [x for x in RECEIPT_REQUIRED_LIMITATIONS if x not in limitations]
    return [f"limitations sem itens obrigatórios: {absent}"] if absent else []


def _check_sources(sources: object) -> list[str]:
    if not (isinstance(sources, list) and sources):
        return ["sources vazio ou não é lista"]
    problems: list[str] = []
    seen: set[str] = set()
    for i, src in enumerate(sources):
        if not (isinstance(src, dict) and SOURCE_REQUIRED <= src.keys()):
            problems.append(f"sources[{i}] sem campos {sorted(SOURCE_REQUIRED)}")
            continue
        problems += _check_one_source(i, src, seen)
    if not problems:
        problems += _check_policy(sources)
    return problems


def _check_one_source(i: int, src: dict, seen: set[str]) -> list[str]:
    problems: list[str] = []
    sid = src["source_id"]
    if not (isinstance(sid, str) and sid):
        problems.append(f"sources[{i}].source_id vazio ou não é texto")
    elif sid in seen:
        problems.append(f"sources[{i}].source_id repetido")
    else:
        seen.add(sid)
    if not isinstance(src["status"], str):
        problems.append(f"sources[{i}].status não é texto")
    for flag in ("is_local", "is_simulated", "approved"):
        if type(src[flag]) is not bool:
            problems.append(f"sources[{i}].{flag} não é booleano")
    problems += _check_batch_params(i, src)
    return problems


def batch_param_problems(params: object, where: str) -> list[str]:
    """Problemas dos params do lote no recibo (G6). Cita só nomes de campos, nunca valores."""
    if not isinstance(params, dict):
        return [f"{where} não é objeto"]
    problems: list[str] = []
    extra = params.keys() - BATCH_PARAM_KEYS
    if extra:
        problems.append(f"{where} com campos não previstos: {sorted(map(str, extra))}")
    for key in RECEIPT_BATCH_PARAM_TEXT_KEYS:
        if key in params:
            value = params[key]
            if not (type(value) is str and _PARAM_TEXT.fullmatch(value)):
                problems.append(f"{where}.{key} inválido")
    for key in RECEIPT_BATCH_PARAM_INT_KEYS:
        if key in params:
            value = params[key]
            if not (type(value) is int and 1 <= value <= RECEIPT_BATCH_PARAM_INT_MAX):
                problems.append(f"{where}.{key} inválido")
    return problems


def _check_batch_params(i: int, src: dict) -> list[str]:
    """batch_params é opcional (recibos antigos não têm), mas fonte que exige job_id o traz."""
    where = f"sources[{i}].batch_params"
    params = src.get("batch_params")
    problems = batch_param_problems(params, where) if "batch_params" in src else []
    needs_job = src.get("source_type") in RECEIPT_JOB_ID_REQUIRED_TYPES and src.get("batch_hash") is not None
    if needs_job and not (isinstance(params, dict) and "job_id" in params):
        problems.append(f"{where}.job_id ausente em fonte que exige job_id")
    return problems


def _check_policy(sources: list[dict]) -> list[str]:
    """Repete no recibo a política keygen do mixer (6.9): G2 verificável depois."""
    problems: list[str] = []
    if any(s["is_simulated"] for s in sources):
        problems.append("fonte simulada em recibo keygen")
    mixed = [s for s in sources if s["status"] == MIXED_STATUS]
    if any(not s["approved"] for s in mixed):
        problems.append("fonte misturada sem aprovação")
    if not any(s["approved"] and s["is_local"] and not s["is_simulated"] for s in mixed):
        problems.append("nenhuma fonte local, não simulada e aprovada na mistura")
    return problems
