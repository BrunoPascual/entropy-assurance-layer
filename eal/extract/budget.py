"""Contabilidade de perdas do extrator (Dia 4, etapa 3).

Responde: de cada bit cru de entrada, quanto sai e para onde vai o resto.
Funções puras, sem I/O e sem aleatoriedade. O tamanho da saída vem de
`block_output_bits` (Etapa 1), nunca de uma segunda cópia da fórmula; aqui só
se decompõe a diferença entre entrada e saída.

Por bloco de n bits, com k_exato = n * H (H exato como número de ponto flutuante):

    n = (n - k_exato)            déficit de entropia
      + (k_exato - floor(k))     arredondamento
      + 2 * log2(1/eps)          margem de segurança (128 bits com eps = 2^-64)
      + m                        saída, m = floor(k) - margem

Se m = 0, o lote inteiro é descartado por entropia insuficiente e não há
decomposição por bloco. Os bits que não completam um bloco (resto) ficam fora.
As parcelas são Fraction: a soma fecha exatamente em n_input_bits.

Estas são contas do modelo, não medidas. A H usada continua sendo uma
estimativa (T8): o modelo diz o que o extrator faz com ela, não se ela está certa.
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from typing import Any

from eal.config import EXTRACTOR_EPSILON_LOG2, EXTRACTOR_INPUT_BITS
from eal.extract.blocks import block_min_entropy_bits, block_output_bits


def _check_input_bits(n_input_bits: Any) -> int:
    if isinstance(n_input_bits, bool) or not isinstance(n_input_bits, int) or n_input_bits < 0:
        raise ValueError("n_input_bits deve ser inteiro não negativo")
    return n_input_bits


def yield_ratio(
    h_used: float, n: int = EXTRACTOR_INPUT_BITS, epsilon_log2: int = EXTRACTOR_EPSILON_LOG2
) -> float:
    """Rendimento por bloco: m / n (bits de saída por bit de entrada)."""
    return block_output_bits(h_used, n, epsilon_log2) / n


@dataclass(frozen=True)
class LossBreakdown:
    """Para onde foi cada bit de entrada de um lote. A soma das parcelas é n_input_bits."""

    n_input_bits: int
    n: int
    epsilon_log2: int
    h_used: float
    m: int
    n_blocks: int
    deficit_bits: Fraction
    rounding_bits: Fraction
    margin_bits: int
    output_bits: int
    tail_bits: int
    low_entropy_discard_bits: int

    @property
    def accounted_bits(self) -> Fraction:
        """Soma de todas as parcelas; deve ser exatamente n_input_bits."""
        return (
            self.deficit_bits
            + self.rounding_bits
            + self.margin_bits
            + self.output_bits
            + self.tail_bits
            + self.low_entropy_discard_bits
        )

    @property
    def total_yield(self) -> float | None:
        """Saída sobre entrada do lote inteiro, contando o resto; None se não há entrada."""
        if self.n_input_bits == 0:
            return None
        return self.output_bits / self.n_input_bits

    def to_dict(self) -> dict[str, Any]:
        """Para CSV e recibo: números simples, sem Fraction."""
        return {
            "n_input_bits": self.n_input_bits,
            "n": self.n,
            "epsilon_log2": self.epsilon_log2,
            "h_used": self.h_used,
            "m": self.m,
            "n_blocks": self.n_blocks,
            "deficit_bits": float(self.deficit_bits),
            "rounding_bits": float(self.rounding_bits),
            "margin_bits": self.margin_bits,
            "output_bits": self.output_bits,
            "tail_bits": self.tail_bits,
            "low_entropy_discard_bits": self.low_entropy_discard_bits,
            "total_yield": self.total_yield,
        }


def loss_breakdown(
    n_input_bits: int,
    h_used: float,
    n: int = EXTRACTOR_INPUT_BITS,
    epsilon_log2: int = EXTRACTOR_EPSILON_LOG2,
) -> LossBreakdown:
    """Decompõe a entrada de um lote em déficit, arredondamento, margem, saída e resto."""
    total = _check_input_bits(n_input_bits)
    m = block_output_bits(h_used, n, epsilon_log2)  # valida h, n e epsilon
    h = float(h_used)
    if m == 0:
        return LossBreakdown(total, n, epsilon_log2, h, 0, 0, Fraction(0), Fraction(0), 0, 0, 0, total)
    n_blocks, tail = divmod(total, n)
    k_exact = Fraction(h) * n
    k_floor = block_min_entropy_bits(h_used, n, epsilon_log2)
    return LossBreakdown(
        n_input_bits=total,
        n=n,
        epsilon_log2=epsilon_log2,
        h_used=h,
        m=m,
        n_blocks=n_blocks,
        deficit_bits=n_blocks * (n - k_exact),
        rounding_bits=n_blocks * (k_exact - k_floor),
        margin_bits=n_blocks * (-2 * epsilon_log2),
        output_bits=n_blocks * m,
        tail_bits=tail,
        low_entropy_discard_bits=0,
    )
