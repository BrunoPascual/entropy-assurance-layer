"""Estimativa conservadora de min-entropia por bit (PROJECT.md 6.5).

Dois estimadores do tipo "valor mais comum" (MCV, SP 800-90B 6.3.1):
  1. sobre bits isolados;
  2. sobre símbolos de 8 bits, dividido por 8, para captar correlação entre
     bits vizinhos que o estimador por bit não enxerga.
H_estimada = min(H_bit, H_byte).

Simplificação declarada: o SP 800-90B usa vários estimadores e regras de
tamanho de amostra; este módulo não alega conformidade com ele.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from eal.config import H_MIN_HEALTH, MCV_SYMBOL_BITS, MCV_Z

MIN_BITS = 2 * MCV_SYMBOL_BITS  # pelo menos 2 símbolos para o estimador por byte


@dataclass(frozen=True)
class McvResult:
    """Resultado de um estimador MCV; h é sempre por bit."""

    h: float
    p_hat: float
    p_upper: float
    max_count: int
    n_samples: int
    symbol_bits: int
    discarded_bits: int


@dataclass(frozen=True)
class MinEntropyEstimate:
    """As duas estimativas e o mínimo entre elas."""

    bit: McvResult
    byte: McvResult
    h_estimated: float
    limited_by: str  # "bit" ou "byte"

    @property
    def h_bit(self) -> float:
        return self.bit.h

    @property
    def h_byte(self) -> float:
        return self.byte.h


def _validate_bits(bits: np.ndarray) -> None:
    """Exige array 1-D uint8 só com 0 e 1, com pelo menos MIN_BITS bits."""
    if not isinstance(bits, np.ndarray):
        raise TypeError("bits deve ser numpy.ndarray")
    if bits.dtype != np.uint8:
        raise TypeError(f"bits deve ser uint8, recebido {bits.dtype}")
    if bits.ndim != 1:
        raise ValueError("bits deve ser 1-D")
    if bits.size < MIN_BITS:
        raise ValueError(f"são necessários pelo menos {MIN_BITS} bits, recebidos {bits.size}")
    if np.any(bits > 1):
        raise ValueError("bits deve conter só 0 e 1")


def mcv_upper_bound(max_count: int, n: int, z: float = MCV_Z) -> float:
    """p_u = min(1, p̂ + z·sqrt(p̂(1 - p̂) / (n - 1))), com p̂ = max_count / n."""
    if n < 2:
        raise ValueError("n deve ser pelo menos 2")
    if not 0 < max_count <= n:
        raise ValueError("max_count deve estar em (0, n]")
    p_hat = max_count / n
    return min(1.0, p_hat + z * math.sqrt(p_hat * (1.0 - p_hat) / (n - 1)))


def _h_from_p(p_upper: float, symbol_bits: int) -> float:
    """Min-entropia por bit: -log2(p_u) / bits do símbolo; 0 se p_u = 1."""
    return 0.0 if p_upper >= 1.0 else -math.log2(p_upper) / symbol_bits


def mcv_bits(bits: np.ndarray) -> McvResult:
    """MCV sobre bits isolados."""
    _validate_bits(bits)
    n = int(bits.size)
    ones = int(bits.sum(dtype=np.int64))
    max_count = max(ones, n - ones)
    p_u = mcv_upper_bound(max_count, n)
    return McvResult(_h_from_p(p_u, 1), max_count / n, p_u, max_count, n, 1, 0)


def mcv_symbols(bits: np.ndarray, symbol_bits: int = MCV_SYMBOL_BITS) -> McvResult:
    """MCV sobre símbolos de `symbol_bits` bits (só 8 é suportado), por bit."""
    _validate_bits(bits)
    if symbol_bits != 8:
        raise ValueError("só símbolos de 8 bits são suportados")
    n = int(bits.size // symbol_bits)
    used = n * symbol_bits
    symbols = np.packbits(bits[:used])
    max_count = int(np.bincount(symbols, minlength=256).max())
    p_u = mcv_upper_bound(max_count, n)
    return McvResult(
        _h_from_p(p_u, symbol_bits), max_count / n, p_u, max_count, n,
        symbol_bits, int(bits.size - used),
    )


def estimate_min_entropy(bits: np.ndarray) -> MinEntropyEstimate:
    """H_estimada = min(H_bit, H_byte); em empate, registra "bit"."""
    bit = mcv_bits(bits)
    byte = mcv_symbols(bits)
    if byte.h < bit.h:
        return MinEntropyEstimate(bit, byte, byte.h, "byte")
    return MinEntropyEstimate(bit, byte, bit.h, "bit")


def entropy_health_ok(h_estimated: float, threshold: float = H_MIN_HEALTH) -> bool:
    """True se H estimada >= limiar. Limiar fixo em config.py (escolha de projeto)."""
    if isinstance(h_estimated, bool) or not isinstance(h_estimated, (int, float)):
        raise TypeError("h_estimated deve ser número")
    if not math.isfinite(h_estimated):
        raise ValueError("h_estimated deve ser finito")
    return h_estimated >= threshold


def extractor_entropy(h_declared: float, h_estimated: float) -> float:
    """H usada pelo extrator: min(H declarada, H estimada). Nunca maior que a declarada."""
    for name, h in (("h_declared", h_declared), ("h_estimated", h_estimated)):
        if isinstance(h, bool) or not isinstance(h, (int, float)):
            raise TypeError(f"{name} deve ser número")
        if not math.isfinite(h) or not 0.0 <= h <= 1.0:
            raise ValueError(f"{name} deve estar em [0, 1], recebido {h}")
    return min(h_declared, h_estimated)