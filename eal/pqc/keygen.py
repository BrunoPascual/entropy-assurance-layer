"""Derivação de chaves PQC a partir da semente (PROJECT.md 6.10).

ML-KEM-768 (FIPS 203): d || z = SHAKE256(KEM_DOMAIN || semente, 64 bytes)
ML-DSA-65  (FIPS 204): xi     = SHAKE256(DSA_DOMAIN || semente, 32 bytes)

Usa só a API pública key_derive das bibliotecas, nunca keygen() (que gera a
própria semente) nem métodos privados. Nenhuma mensagem de erro inclui o
conteúdo da semente.
"""
from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass, field

import numpy as np
from dilithium_py.ml_dsa import ML_DSA_65
from kyber_py.ml_kem import ML_KEM_768

from eal.config import (
    DSA_DOMAIN,
    DSA_SEED_BYTES,
    KEM_DOMAIN,
    KEM_SEED_BYTES,
    SEED_BYTES,
)

KEYGEN_MODE = "keygen"


@dataclass(frozen=True, eq=False)
class DerivedKeys:
    """Chaves derivadas da semente. Os campos secretos não aparecem em repr.

    eq=False: não há motivo para comparar chaves privadas com ==.
    """

    kem_ek: bytes
    kem_dk: bytes = field(repr=False)
    dsa_pk: bytes
    dsa_sk: bytes = field(repr=False)

    def public_summary(self) -> dict[str, str]:
        """Hashes SHA3-256 das chaves públicas, para o recibo."""
        return {
            "ml_kem_768_pk_hash": hashlib.sha3_256(self.kem_ek).hexdigest(),
            "ml_dsa_65_pk_hash": hashlib.sha3_256(self.dsa_pk).hexdigest(),
        }


def _check_seed(seed: object) -> bytes:
    """Recusa semente que não seja bytes de SEED_BYTES. Não ecoa o valor."""
    if not isinstance(seed, bytes):
        raise TypeError(f"semente deve ser bytes, recebido {type(seed).__name__}")
    if len(seed) != SEED_BYTES:
        raise ValueError(
            f"semente deve ter {SEED_BYTES} bytes, recebido {len(seed)}"
        )
    return seed


def derive_keys(seed: bytes) -> DerivedKeys:
    """Deriva ML-KEM-768 e ML-DSA-65 de uma semente de 64 bytes."""
    seed = _check_seed(seed)
    kem_material = hashlib.shake_256(KEM_DOMAIN + seed).digest(KEM_SEED_BYTES)
    dsa_material = hashlib.shake_256(DSA_DOMAIN + seed).digest(DSA_SEED_BYTES)
    kem_ek, kem_dk = ML_KEM_768.key_derive(kem_material)
    dsa_pk, dsa_sk = ML_DSA_65.key_derive(dsa_material)
    return DerivedKeys(kem_ek=kem_ek, kem_dk=kem_dk, dsa_pk=dsa_pk, dsa_sk=dsa_sk)


def _is_true_flag(value: object) -> bool:
    """Só True ou numpy.bool_ verdadeiro contam (mesma regra do mixer, 6.9.1)."""
    if isinstance(value, bool):
        return value
    if isinstance(value, np.bool_):
        return bool(value)
    return False


def derive_keys_from_mix(mix: object) -> DerivedKeys:
    """Deriva as chaves de um MixResult de modo keygen, utilizável para chave."""
    if mix is None:
        raise ValueError("sem MixResult: a política do mixer não gerou semente")
    mode = getattr(mix, "mode", None)
    if not (isinstance(mode, str) and mode == KEYGEN_MODE):
        raise ValueError("MixResult fora do modo keygen não gera chaves")
    if not _is_true_flag(getattr(mix, "usable_for_key", None)):
        raise ValueError("MixResult com usable_for_key falso não gera chaves")
    seed = _check_seed(getattr(mix, "seed", None))
    seed_hash = getattr(mix, "seed_hash", None)
    if not isinstance(seed_hash, str):
        raise ValueError("MixResult sem seed_hash em texto")
    expected = hashlib.sha3_256(seed).hexdigest()
    if not hmac.compare_digest(expected, seed_hash):
        raise ValueError("seed_hash não confere com a semente do MixResult")
    return derive_keys(seed)
