"""Alternativa de comparação: condicionamento com SHAKE256 (PROJECT.md 6.8).

Mesmo dimensionamento e mesma interface do Toeplitz (mesmo m, mesmos blocos),
para comparar saída e tempo. A garantia aqui é HEURÍSTICA (modelo de oráculo
aleatório): não existe prova do lema do hash residual para esta função. Por
isso o Toeplitz continua sendo o extrator do pipeline.

Saída por bloco: SHAKE256(DOMINIO || bloco empacotado), ceil(m/8) bytes,
cortados em m bits. Sem índice do bloco: a função depende só do bloco.
"""

from __future__ import annotations

import hashlib

import numpy as np

from eal.config import EXTRACTOR_EPSILON_LOG2, EXTRACTOR_INPUT_BITS
from eal.extract.blocks import ExtractionResult, hash_bits, plan_extraction

SHA3_EXTRACT_DOMAIN = b"EAL-v1|sha3-extract|"


def sha3_extract_block(block: np.ndarray, m: int, domain: bytes = SHA3_EXTRACT_DOMAIN) -> np.ndarray:
    """Condiciona um bloco (n bits, n múltiplo de 8) em m bits com SHAKE256."""
    if block.ndim != 1 or block.size % 8 != 0:
        raise ValueError("bloco deve ser 1-D com tamanho múltiplo de 8")
    if m <= 0:
        raise ValueError("m deve ser positivo")
    digest = hashlib.shake_256(domain + np.packbits(block).tobytes()).digest((m + 7) // 8)
    return np.unpackbits(np.frombuffer(digest, dtype=np.uint8))[:m]


def extract_sha3(
    bits: np.ndarray,
    h_used: float,
    *,
    n: int = EXTRACTOR_INPUT_BITS,
    epsilon_log2: int = EXTRACTOR_EPSILON_LOG2,
    domain: bytes = SHA3_EXTRACT_DOMAIN,
) -> ExtractionResult:
    """Extrai com SHAKE256, usando o mesmo m e os mesmos blocos do Toeplitz."""
    if n % 8 != 0:
        raise ValueError("n deve ser múltiplo de 8 no extrator SHA3")
    plan = plan_extraction(bits, h_used, n, epsilon_log2)
    n_blocks = plan.blocks.shape[0]
    if n_blocks == 0:
        out = np.zeros(0, dtype=np.uint8)
    else:
        out = np.concatenate([sha3_extract_block(blk, plan.m, domain) for blk in plan.blocks])
    notes = plan.notes + ("garantia heurística (oráculo aleatório); epsilon é só o alvo de dimensionamento",)
    return ExtractionResult(
        extractor_type="sha3",
        guarantee="heuristic_random_oracle",
        n=plan.n,
        m=plan.m,
        h_used=plan.h_used,
        epsilon_log2=plan.epsilon_log2,
        n_input_bits=plan.n_input_bits,
        n_blocks=n_blocks,
        discarded_bits=plan.discarded_bits,
        bits=out,
        seed_hash=None,
        notes=notes,
        input_hash=hash_bits(bits),
    )
