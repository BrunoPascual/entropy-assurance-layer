"""Monta o corpo do recibo a partir de uma execução keygen (PROJECT.md 6.11, Dia 5 etapa 2B).

Entradas: o PipelineResult, as DerivedKeys e os objetos Source usados na execução.
O PipelineResult não guarda os lotes; por isso source_type e source_version vêm
do objeto Source, e o hash do lote é o input_hash do MixInput (mesma convenção
do batch_hash). Os params do lote (G6) vêm do SourceOutcome; só as chaves da lista
fechada de config.py entram, no bloco batch_params de cada fonte.

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
import re
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
    RECEIPT_BATCH_PARAM_INT_KEYS,
    RECEIPT_BATCH_PARAM_TEXT_KEYS,
    RECEIPT_EXTRACTOR_TYPE,
    RECEIPT_JOB_ID_REQUIRED_TYPES,
    RECEIPT_ID_NAMESPACE,
    RECEIPT_REQUIRED_LIMITATIONS,
)
from eal.pqc.keygen import DerivedKeys, derive_keys_from_mix
from eal.receipt.schema import KEYGEN_MODE, MIXED_STATUS, batch_param_problems, validate_body

SOFTWARE_PACKAGES = ("kyber-py", "dilithium-py", "numpy", "scipy")

# --- Achado F9 (revisão adversarial do Dia 5, parte 2) -------------------------------
# Campos permitidos nos objetos ANINHADOS que este construtor emite. O validador do
# esquema só olha o topo do recibo; sem esta lista, um campo novo em HealthReport (que usa
# dataclasses.asdict e serializa todos os campos) iria para o recibo assinado sem alarme.
# Vale só para recibos NOVOS: a verificação (schema.py, verify.py) não muda. Um campo novo
# numa dessas classes precisa entrar aqui de propósito; os testes travam as listas.
SOURCE_ENTRY_KEYS = frozenset({
    "source_id", "source_type", "source_version", "status", "batch_id", "batch_hash",
    "is_local", "is_simulated", "approved", "reasons", "health", "extraction",
    "batch_params"
})
HEALTH_KEYS = frozenset({  # os 35 campos de eal.health.report.HealthReport
    "schema", "batch_id", "source_id", "n_bits", "h_declared", "rct_pass", "rct_cutoff",
    "rct_max_run", "rct_max_run_start", "rct_alpha_neg_log2", "apt_pass", "apt_inconclusive",
    "apt_cutoff", "apt_max_count", "apt_n_windows", "apt_n_failed_windows",
    "apt_discarded_bits", "apt_alpha_neg_log2", "replay_pass", "replay_history_batches",
    "replay_n_blocks", "replay_repeated_blocks", "replay_batch_repeated", "h_bit", "h_byte",
    "h_estimated", "h_limited_by", "h_threshold", "h_health_pass", "stats", "stats_pass",
    "stats_inconclusive", "approved", "reasons", "notes"
})
EXTRACTION_KEYS = frozenset({  # ExtractionResult.to_dict()
    "extractor_type", "guarantee", "n", "m", "h_used", "epsilon_log2", "epsilon_total_log2",
    "n_input_bits", "n_blocks", "n_output_bits", "discarded_bits", "seed_hash", "input_hash",
    "notes"
})
MIXER_KEYS = frozenset({  # MixResult.to_dict()
    "mode", "usable_for_key", "mixer_type", "domain", "policy", "seed_hash", "included",
    "excluded"
})
MIXER_INCLUDED_KEYS = frozenset({"source_id", "batch_id", "input_hash", "is_local", "is_simulated", "n_bits_mixed"})
MIXER_EXCLUDED_KEYS = frozenset({"source_id", "batch_id", "reasons"})
EXTRACTOR_KEYS = frozenset({"type", "n", "epsilon_log2"})
_HEX_ONLY = re.compile(r"[0-9a-fA-F]+")
_MAX_HEX_CHARS = 127  # hash SHA3-256 tem 64 caracteres; 128 ou mais é tamanho de semente de 64 bytes
_MAX_BIT_LIST = 63    # o recibo não tem listas de números; 64 ou mais zeros e uns parecem bits


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


def clean_batch_params(params: Any) -> dict[str, Any]:
    """G6: só as chaves da lista fechada (config.py) vão para o recibo; o resto é descartado.

    Token, semente e qualquer outro campo do lote ficam de fora por construção. Valor inválido
    numa chave permitida recusa o recibo; a mensagem cita o nome do campo, nunca o valor.
    """
    if params is None:
        return {}
    if not isinstance(params, dict):
        raise ValueError("params do lote não é objeto")
    clean: dict[str, Any] = {}
    for key in (*RECEIPT_BATCH_PARAM_TEXT_KEYS, *RECEIPT_BATCH_PARAM_INT_KEYS):
        if key in params:
            value = params[key]
            clean[key] = int(value) if isinstance(value, np.integer) else value
    problems = batch_param_problems(clean, "batch_params")
    if problems:
        raise ValueError("params do lote inválidos: " + "; ".join(problems))
    return clean


def _require_job_id(outcome: Any, src: Any, entry: dict[str, Any]) -> None:
    """Fonte de tipo que exige job_id (qpu_ibm) com lote lido sem job_id: recusa o recibo."""
    if (outcome.batch_id is not None
            and str(src.source_type) in RECEIPT_JOB_ID_REQUIRED_TYPES
            and "job_id" not in entry["batch_params"]):
        raise ValueError(f"fonte do tipo {src.source_type} sem job_id nos params do lote")


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
        "batch_params": clean_batch_params(getattr(outcome, "params", None)),
    }
    _require_job_id(outcome, src, entry)
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


def _extra_keys(obj: Any, allowed: frozenset[str], where: str) -> None:
    """Recusa campo fora da lista. A mensagem cita só o NOME do campo, nunca o valor."""
    if isinstance(obj, dict):
        extra = obj.keys() - allowed
        if extra:
            raise ValueError(f"campos não previstos em {where}: {sorted(map(str, extra))}")


def _scan_material(value: Any, where: str) -> None:
    """Recusa bytes, texto hexadecimal longo e lista longa de bits em qualquer campo permitido."""
    if isinstance(value, (bytes, bytearray)):
        raise TypeError(f"bytes no recibo em {where}")
    if isinstance(value, str):
        if len(value) > _MAX_HEX_CHARS and _HEX_ONLY.fullmatch(value):
            raise ValueError(f"texto hexadecimal longo no recibo em {where}")
    elif isinstance(value, dict):
        for key, item in value.items():
            _scan_material(item, f"{where}.{key}")
    elif isinstance(value, (list, tuple)):
        if len(value) > _MAX_BIT_LIST and all(type(x) is int and x in (0, 1) for x in value):
            raise ValueError(f"lista longa de bits no recibo em {where}")
        for i, item in enumerate(value):
            _scan_material(item, f"{where}[{i}]")


def check_nested_fields(body: dict[str, Any]) -> None:
    """Achado F9: o construtor só emite os campos previstos nos objetos aninhados."""
    _extra_keys(body.get("extractor"), EXTRACTOR_KEYS, "extractor")
    mixer = body.get("mixer")
    _extra_keys(mixer, MIXER_KEYS, "mixer")
    if isinstance(mixer, dict):
        for name, allowed in (("included", MIXER_INCLUDED_KEYS), ("excluded", MIXER_EXCLUDED_KEYS)):
            items = mixer.get(name)
            if isinstance(items, list):
                for i, item in enumerate(items):
                    _extra_keys(item, allowed, f"mixer.{name}[{i}]")
    sources = body.get("sources")
    if isinstance(sources, list):
        for i, entry in enumerate(sources):
            _extra_keys(entry, SOURCE_ENTRY_KEYS, f"sources[{i}]")
            if isinstance(entry, dict):
                _extra_keys(entry.get("health"), HEALTH_KEYS, f"sources[{i}].health")
                _extra_keys(entry.get("extraction"), EXTRACTION_KEYS, f"sources[{i}].extraction")
    _scan_material(body, "recibo")


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
    check_nested_fields(body)
    problems = validate_body(body)
    if problems:
        raise ValueError("recibo inválido: " + "; ".join(problems))
    return body
