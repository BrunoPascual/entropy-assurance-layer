"""Extrator Toeplitz sobre GF(2) (PROJECT.md 6.8).

Convenção de índice, fixada e testada contra um oráculo em laço puro:

    T[i, j] = seed[j - i + m - 1]      (i = 0..m-1, j = 0..n-1)

A semente tem n + m - 1 bits. A saída de cada bloco x é (T · x) mod 2.
Garantia: lema do hash residual, SE a semente for uniforme e independente da
fonte (premissa P4) e SE cada bloco tiver min-entropia >= n * H (condicionada
aos blocos anteriores). Nada disso é provado pelo código: vem das premissas.
"""

from __future__ import annotations

from typing import Any, Protocol

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view

from eal.config import EXTRACTOR_EPSILON_LOG2, EXTRACTOR_INPUT_BITS
from eal.extract.blocks import (
    ExtractionResult,
    hash_bits,
    plan_extraction,
    validate_bits,
)

_FLOAT32_EXACT_LIMIT = 2**24  # somas de 0/1 até este valor são exatas em float32


class SeedSource(Protocol):
    """O que o extrator precisa saber da leitura que fornece a semente (um RawBatch serve)."""

    bits: np.ndarray
    is_local: bool
    is_simulated: bool
    batch_id: str


def _validate_seed(seed: Any, n: int, m: int) -> np.ndarray:
    s = validate_bits(seed)
    if s.size != n + m - 1:
        raise ValueError(f"semente deve ter n + m - 1 = {n + m - 1} bits, veio {s.size}")
    return s


def toeplitz_matrix(seed: np.ndarray, n: int, m: int) -> np.ndarray:
    """Matriz m x n (uint8) com T[i, j] = seed[j - i + m - 1]."""
    s = _validate_seed(seed, n, m)
    windows = sliding_window_view(s, n)  # windows[t, j] = s[t + j], t = 0..m-1
    return windows[::-1].copy()  # T[i] = windows[m - 1 - i]


def toeplitz_apply(blocks: np.ndarray, seed: np.ndarray, m: int) -> np.ndarray:
    """Aplica T a cada linha de `blocks` (n_blocks x n) e devolve (n_blocks x m) uint8.

    A multiplicação usa float32, que é exata aqui: cada produto é 0 ou 1 e as
    somas ficam em no máximo n (< 2**24). O mod 2 vem depois, em inteiros.
    """
    if blocks.ndim != 2:
        raise ValueError("blocks deve ser 2-D")
    n = blocks.shape[1]
    if n >= _FLOAT32_EXACT_LIMIT:
        raise ValueError("n grande demais para a multiplicação exata em float32")
    validate_bits(blocks.reshape(-1))
    t = toeplitz_matrix(seed, n, m)
    product = blocks.astype(np.float32) @ t.T.astype(np.float32)
    return (product.astype(np.int32) & 1).astype(np.uint8)


def _is_true(value: Any) -> bool:
    return isinstance(value, (bool, np.bool_)) and bool(value)


def _is_false(value: Any) -> bool:
    return isinstance(value, (bool, np.bool_)) and not bool(value)


def _check_seed_source(
    seed_source: SeedSource, bits: np.ndarray, seed: np.ndarray, input_hash: str
) -> None:
    """Recusa semente simulada, não local ou reaproveitada dos próprios bits extraídos."""
    # Booleano estrito, como no mixer e no construtor do recibo (achado F11): qualquer
    # outro valor conta como o pior caso.
    if not _is_true(seed_source.is_local) or not _is_false(seed_source.is_simulated):
        raise ValueError("semente deve vir de fonte local e não simulada")
    if hash_bits(validate_bits(seed_source.bits)) == input_hash:
        raise ValueError("semente idêntica ao lote de entrada")
    if seed.size <= bits.size and np.array_equal(seed, bits[: seed.size]):
        raise ValueError("semente coincide com o início do lote de entrada")


def extract_toeplitz(
    bits: np.ndarray,
    h_used: float,
    seed_source: SeedSource,
    *,
    input_batch_id: str | None = None,
    n: int = EXTRACTOR_INPUT_BITS,
    epsilon_log2: int = EXTRACTOR_EPSILON_LOG2,
) -> ExtractionResult:
    """Extrai bits quase uniformes de `bits` com uma matriz Toeplitz por execução.

    `h_used` já vem de `extractor_entropy` (min entre H declarada e estimada).
    A semente vem de uma leitura separada e local; seu SHA3-256 vai no resultado.
    """
    plan = plan_extraction(bits, h_used, n, epsilon_log2)
    input_hash = hash_bits(bits)
    if plan.m == 0:
        empty = np.zeros(0, dtype=np.uint8)
        return _result(plan, 0, empty, None, input_hash)
    if input_batch_id is not None and input_batch_id == seed_source.batch_id:
        raise ValueError("semente e lote de entrada têm o mesmo batch_id")
    need = n + plan.m - 1
    seed_all = validate_bits(seed_source.bits)
    if seed_all.size < need:
        raise ValueError(f"semente curta: precisa de {need} bits, veio {seed_all.size}")
    seed = seed_all[:need]
    _check_seed_source(seed_source, bits, seed, input_hash)
    out = toeplitz_apply(plan.blocks, seed, plan.m).reshape(-1)
    return _result(plan, plan.blocks.shape[0], out, hash_bits(seed), input_hash)


def _result(
    plan: Any, n_blocks: int, out: np.ndarray, seed_hash: str | None, input_hash: str
) -> ExtractionResult:
    return ExtractionResult(
        extractor_type="toeplitz",
        guarantee="leftover_hash_lemma",
        n=plan.n,
        m=plan.m,
        h_used=plan.h_used,
        epsilon_log2=plan.epsilon_log2,
        n_input_bits=plan.n_input_bits,
        n_blocks=n_blocks,
        discarded_bits=plan.discarded_bits,
        bits=out,
        seed_hash=seed_hash,
        notes=plan.notes,
        input_hash=input_hash,
    )
