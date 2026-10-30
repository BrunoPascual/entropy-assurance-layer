"""Chave do emissor e assinatura de recibos com ML-DSA-65 (PROJECT.md 6.11).

A assinatura é determinística (sem o gerador interno da biblioteca, regra 5
da seção 12) e usa o contexto RECEIPT_CTX (FIPS 204, ctx), que separa as
assinaturas de recibo de qualquer outro uso da mesma chave.
"""
from __future__ import annotations

import base64
import copy
import hashlib
from dataclasses import dataclass, field
from pathlib import Path

from dilithium_py.ml_dsa import ML_DSA_65

from eal.config import (
    DSA_PK_BYTES,
    DSA_SEED_BYTES,
    ISSUER_PK_NAME,
    ISSUER_SK_NAME,
    RECEIPT_CTX,
    RECEIPT_SIG_ALG,
)
from eal.receipt.schema import SIGNATURE_FIELD, canonical_bytes, validate_body

DSA_SK_BYTES = 4032
_PAIR_PROBE = b"EAL-v1|issuer-pair-check"


@dataclass(frozen=True, eq=False)
class IssuerKey:
    """Par ML-DSA-65 do emissor. A chave privada não aparece em repr."""

    pk: bytes
    sk: bytes = field(repr=False)

    @property
    def pk_hash(self) -> str:
        """SHA3-256 da chave pública, em hex."""
        return hashlib.sha3_256(self.pk).hexdigest()


def issuer_key_from_seed(xi: bytes) -> IssuerKey:
    """Deriva o par do emissor de 32 bytes (vindos da fonte os)."""
    if not isinstance(xi, bytes):
        raise TypeError(f"semente do emissor deve ser bytes, recebido {type(xi).__name__}")
    if len(xi) != DSA_SEED_BYTES:
        raise ValueError(f"semente do emissor deve ter {DSA_SEED_BYTES} bytes, recebido {len(xi)}")
    pk, sk = ML_DSA_65.key_derive(xi)
    return IssuerKey(pk=pk, sk=sk)


def save_issuer_key(key: IssuerKey, directory: Path) -> tuple[Path, Path]:
    """Grava .sk e .pk em hex. Nunca sobrescreve uma chave existente."""
    directory.mkdir(parents=True, exist_ok=True)
    sk_path, pk_path = directory / ISSUER_SK_NAME, directory / ISSUER_PK_NAME
    if sk_path.exists() or pk_path.exists():
        raise FileExistsError("já existe chave do emissor nesse diretório")
    _write_new(pk_path, key.pk.hex())
    _write_new(sk_path, key.sk.hex())
    return sk_path, pk_path


def _write_new(path: Path, text: str) -> None:
    # Modo "x": falha se o arquivo já existir (segunda defesa contra sobrescrever).
    with open(path, "x", encoding="ascii") as f:
        f.write(text + "\n")


def _read_hex(path: Path, size: int, what: str) -> bytes:
    try:
        data = bytes.fromhex(path.read_text(encoding="ascii").strip())
    except (UnicodeDecodeError, ValueError):
        raise ValueError(f"{what}: arquivo não é hexadecimal") from None
    if len(data) != size:
        raise ValueError(f"{what}: esperado {size} bytes, recebido {len(data)}")
    return data


def load_issuer_public_key(pk_path: Path) -> bytes:
    """Lê a chave pública do emissor (hex)."""
    return _read_hex(pk_path, DSA_PK_BYTES, "chave pública do emissor")


def load_issuer_key(sk_path: Path, pk_path: Path) -> IssuerKey:
    """Lê o par do emissor e confere que as duas metades combinam."""
    sk = _read_hex(sk_path, DSA_SK_BYTES, "chave privada do emissor")
    pk = load_issuer_public_key(pk_path)
    probe = ML_DSA_65.sign(sk, _PAIR_PROBE, ctx=RECEIPT_CTX, deterministic=True)
    if not ML_DSA_65.verify(pk, _PAIR_PROBE, probe, ctx=RECEIPT_CTX):
        raise ValueError("chave privada e chave pública do emissor não formam um par")
    return IssuerKey(pk=pk, sk=sk)


def sign_receipt(body: dict, key: IssuerKey) -> dict:
    """Devolve uma cópia do corpo com o bloco signature. Recusa corpo inválido."""
    if not isinstance(key, IssuerKey):
        raise TypeError("key deve ser IssuerKey")
    problems = validate_body(body)
    if problems:
        raise ValueError("recibo inválido: " + "; ".join(problems))
    message = canonical_bytes(body)
    sig = ML_DSA_65.sign(key.sk, message, ctx=RECEIPT_CTX, deterministic=True)
    signed = copy.deepcopy(body)
    signed[SIGNATURE_FIELD] = {
        "alg": RECEIPT_SIG_ALG,
        "issuer_pk_hash": key.pk_hash,
        "value": base64.b64encode(sig).decode("ascii"),
    }
    return signed
