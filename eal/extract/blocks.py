"""Divisão em blocos, dimensionamento e resultado comum dos extratores (PROJECT.md 6.8).

Parte compartilhada pelo extrator Toeplitz e pela alternativa SHA3. Nada aqui
gera aleatoriedade: só organiza bits que já vieram de uma fonte aprovada.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, field
from fractions import Fraction
from typing import Any

import numpy as np

from eal.config import EXTRACTOR_EPSILON_LOG2, EXTRACTOR_INPUT_BITS


def validate_bits(bits: Any) -> np.ndarray:
    """Confere que `bits` é um vetor 1-D `uint8` só com 0 e 1 e o devolve."""
    if not isinstance(bits, np.ndarray) or bits.ndim != 1 or bits.dtype != np.uint8:
        raise ValueError("bits deve ser numpy.ndarray 1-D de dtype uint8")
    if bits.size and int(bits.max()) > 1:
        raise ValueError("bits deve conter apenas 0 e 1")
    return bits


def hash_bits(bits: np.ndarray) -> str:
    """SHA3-256 de n_bits (8 bytes, big-endian) + bits empacotados (convenção do batch_hash)."""
    b = validate_bits(bits)
    h = hashlib.sha3_256()
    h.update(int(b.size).to_bytes(8, "big"))
    h.update(np.packbits(b).tobytes())
    return h.hexdigest()


def _check_dimensions(n: int, epsilon_log2: int) -> None:
    if isinstance(n, bool) or not isinstance(n, int) or n <= 0:
        raise ValueError("n deve ser inteiro positivo")
    if isinstance(epsilon_log2, bool) or not isinstance(epsilon_log2, int) or epsilon_log2 >= 0:
        raise ValueError("epsilon_log2 deve ser inteiro negativo")


def _check_entropy(h_used: Any) -> float:
    ok_type = isinstance(h_used, (int, float, np.integer, np.floating))
    if isinstance(h_used, bool) or not ok_type:
        raise ValueError("H deve ser um número")
    h = float(h_used)
    if not math.isfinite(h) or h <= 0.0 or h > 1.0:
        raise ValueError("H deve estar em (0, 1]")
    return h


def block_min_entropy_bits(
    h_used: float, n: int = EXTRACTOR_INPUT_BITS, epsilon_log2: int = EXTRACTOR_EPSILON_LOG2
) -> int:
    """k = floor(n * H): min-entropia do bloco em bits. Usa aritmética exata (Fraction)."""
    _check_dimensions(n, epsilon_log2)
    h = _check_entropy(h_used)
    return math.floor(Fraction(h) * n)


def block_output_bits(
    h_used: float, n: int = EXTRACTOR_INPUT_BITS, epsilon_log2: int = EXTRACTOR_EPSILON_LOG2
) -> int:
    """m = floor(n*H) - 2*log2(1/eps), limitado a 0 (lema do hash residual)."""
    k = block_min_entropy_bits(h_used, n, epsilon_log2)
    margin = -2 * epsilon_log2
    return max(k - margin, 0)


def split_blocks(bits: np.ndarray, n: int = EXTRACTOR_INPUT_BITS) -> tuple[np.ndarray, int]:
    """Divide em blocos de n bits, sem sobreposição. Devolve (blocos, bits descartados)."""
    b = validate_bits(bits)
    _check_dimensions(n, EXTRACTOR_EPSILON_LOG2)
    n_blocks = b.size // n
    blocks = b[: n_blocks * n].reshape(n_blocks, n)
    return blocks, int(b.size - n_blocks * n)


@dataclass(frozen=True)
class ExtractionPlan:
    """Resultado do dimensionamento: blocos a processar e quanto sai de cada um."""

    blocks: np.ndarray = field(repr=False, compare=False)
    n: int
    m: int
    h_used: float
    epsilon_log2: int
    n_input_bits: int
    discarded_bits: int
    notes: tuple[str, ...]


def plan_extraction(
    bits: np.ndarray,
    h_used: float,
    n: int = EXTRACTOR_INPUT_BITS,
    epsilon_log2: int = EXTRACTOR_EPSILON_LOG2,
) -> ExtractionPlan:
    """Valida a entrada, calcula m e divide em blocos. Se m = 0, nenhum bloco é usado."""
    b = validate_bits(bits)
    h = _check_entropy(h_used)
    m = block_output_bits(h, n, epsilon_log2)
    if m == 0:
        empty = np.zeros((0, n), dtype=np.uint8)
        note = "entropia insuficiente: m = 0, todos os blocos descartados"
        return ExtractionPlan(empty, n, 0, h, epsilon_log2, int(b.size), int(b.size), (note,))
    blocks, discarded = split_blocks(b, n)
    notes = (f"{discarded} bits finais descartados (bloco incompleto)",) if discarded else ()
    return ExtractionPlan(blocks, n, m, h, epsilon_log2, int(b.size), discarded, notes)


@dataclass(frozen=True)
class ExtractionResult:
    """Saída de um extrator. Os bits ficam só em memória e nunca vão para `to_dict()`."""

    extractor_type: str
    guarantee: str
    n: int
    m: int
    h_used: float
    epsilon_log2: int
    n_input_bits: int
    n_blocks: int
    discarded_bits: int
    bits: np.ndarray = field(repr=False, compare=False)
    seed_hash: str | None = None
    notes: tuple[str, ...] = ()
    input_hash: str | None = None  # hash_bits dos bits de entrada: amarra a saída ao lote

    @property
    def n_output_bits(self) -> int:
        """Quantidade de bits de saída."""
        return int(self.bits.size)

    @property
    def epsilon_total_log2(self) -> float | None:
        """log2 do limite sobre todos os blocos (n_blocks * eps), sob independência entre blocos."""
        if self.n_blocks == 0:
            return None
        return self.epsilon_log2 + math.log2(self.n_blocks)

    def to_dict(self) -> dict[str, Any]:
        """Metadados para o recibo: nenhum bit de saída, nenhum bit de semente."""
        return {
            "extractor_type": self.extractor_type,
            "guarantee": self.guarantee,
            "n": self.n,
            "m": self.m,
            "h_used": self.h_used,
            "epsilon_log2": self.epsilon_log2,
            "epsilon_total_log2": self.epsilon_total_log2,
            "n_input_bits": self.n_input_bits,
            "n_blocks": self.n_blocks,
            "n_output_bits": self.n_output_bits,
            "discarded_bits": self.discarded_bits,
            "seed_hash": self.seed_hash,
            "input_hash": self.input_hash,
            "notes": list(self.notes),
        }
