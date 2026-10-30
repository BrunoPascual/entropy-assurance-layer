"""Verificação de recibos (PROJECT.md 6.11, regra 4; garantia G4).

verify_receipt nunca levanta exceção por causa do recibo: devolve VerifyResult
com a lista de motivos. Recibo adulterado é dado, não erro de programa.
O encadeamento (prev_receipt_hash) é conferido na etapa 3 (chain.py).
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
from dataclasses import dataclass

from dilithium_py.ml_dsa import ML_DSA_65

from eal.config import DSA_PK_BYTES, DSA_SIG_BYTES, RECEIPT_CTX, RECEIPT_SIG_ALG
from eal.receipt.schema import (
    SIGNATURE_FIELD,
    SIGNATURE_FIELDS,
    canonical_bytes,
    is_hex64,
    receipt_body,
    validate_body,
)


@dataclass(frozen=True)
class VerifyResult:
    """Resultado da verificação: ok só se não houver nenhum motivo."""

    ok: bool
    reasons: tuple[str, ...]


def _fail(*reasons: str) -> VerifyResult:
    return VerifyResult(ok=False, reasons=tuple(reasons))


def verify_receipt(receipt: object, issuer_pk: bytes) -> VerifyResult:
    """Confere formato, emissor e assinatura de um recibo já carregado."""
    if not (isinstance(issuer_pk, bytes) and len(issuer_pk) == DSA_PK_BYTES):
        return _fail("chave pública do emissor inválida")
    if not isinstance(receipt, dict):
        return _fail("recibo não é objeto JSON")
    sig, reasons = _parse_signature(receipt.get(SIGNATURE_FIELD), issuer_pk)
    body = receipt_body(receipt)
    reasons += validate_body(body)
    if sig is not None:
        try:
            message = canonical_bytes(body)
        except (TypeError, ValueError):
            reasons.append("recibo não serializa em JSON canônico")
        else:
            if not _signature_ok(issuer_pk, message, sig):
                reasons.append("assinatura não confere")
    return VerifyResult(ok=not reasons, reasons=tuple(reasons))


def _parse_signature(block: object, issuer_pk: bytes) -> tuple[bytes | None, list[str]]:
    if not (isinstance(block, dict) and block.keys() == SIGNATURE_FIELDS):
        return None, [f"signature ausente ou sem exatamente {sorted(SIGNATURE_FIELDS)}"]
    reasons: list[str] = []
    if block["alg"] != RECEIPT_SIG_ALG:
        reasons.append("algoritmo de assinatura não suportado")
    expected = hashlib.sha3_256(issuer_pk).hexdigest()
    pk_hash = block["issuer_pk_hash"]
    if not (is_hex64(pk_hash) and hmac.compare_digest(pk_hash, expected)):
        reasons.append("recibo assinado por outro emissor (issuer_pk_hash não confere)")
    sig = _decode_signature(block["value"])
    if sig is None:
        reasons.append("valor da assinatura não é base64 de 3309 bytes")
    return (sig if not reasons else None), reasons


def _decode_signature(value: object) -> bytes | None:
    if not isinstance(value, str):
        return None
    try:
        sig = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError):
        return None
    return sig if len(sig) == DSA_SIG_BYTES else None


def _signature_ok(pk: bytes, message: bytes, sig: bytes) -> bool:
    # A biblioteca pode levantar exceção com entrada malformada; isso é reprovação.
    try:
        return bool(ML_DSA_65.verify(pk, message, sig, ctx=RECEIPT_CTX))
    except Exception:  # noqa: BLE001
        return False


def parse_receipt_json(text: str) -> dict:
    """Lê o JSON de um recibo; recusa chave repetida, NaN e infinito."""

    def no_duplicates(pairs: list[tuple[str, object]]) -> dict:
        keys = [k for k, _ in pairs]
        if len(keys) != len(set(keys)):
            raise ValueError("JSON com chave repetida")
        return dict(pairs)

    def no_constants(name: str) -> object:
        raise ValueError(f"JSON com constante não permitida: {name}")

    data = json.loads(text, object_pairs_hook=no_duplicates, parse_constant=no_constants)
    if not isinstance(data, dict):
        raise ValueError("JSON do recibo não é objeto")
    return data


def verify_receipt_text(text: str, issuer_pk: bytes) -> VerifyResult:
    """Lê e verifica um recibo em texto JSON."""
    try:
        receipt = parse_receipt_json(text)
    except (ValueError, TypeError) as exc:  # inclui json.JSONDecodeError
        return _fail(f"JSON inválido: {exc}")
    return verify_receipt(receipt, issuer_pk)
