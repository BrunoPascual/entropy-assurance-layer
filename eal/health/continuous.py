"""Testes de saúde contínuos do NIST SP 800-90B (seção 4.4), adaptados para lotes.

Adaptação declarada: no SP 800-90B os testes rodam sobre a fonte viva, amostra
a amostra; aqui rodam sobre um lote já coletado. O resultado relata o pior caso
do lote e quantas janelas falharam, em vez de parar na primeira falha.

α é a taxa de falso alarme por amostra (RCT) ou por janela (APT), não por
lote; os valores padrão estão em eal/config.py com a justificativa.

Este módulo não decide qual H usar: quem chama passa H (no projeto, o mínimo
entre a H declarada e a estimada; ver report.py).
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from fractions import Fraction

import numpy as np
from scipy.stats import binom

from eal.config import APT_ALPHA_NEG_LOG2, APT_WINDOW_BITS as APT_WINDOW, RCT_ALPHA_NEG_LOG2

@dataclass(frozen=True)
class RctResult:
    """Resultado do Repetition Count Test sobre um lote."""

    passed: bool
    cutoff: int
    max_run: int
    max_run_start: int
    h_used: float
    alpha_neg_log2: int


@dataclass(frozen=True)
class AptResult:
    """Resultado do Adaptive Proportion Test sobre um lote."""

    passed: bool
    inconclusive: bool
    cutoff: int
    max_count: int
    window: int
    n_windows: int
    n_failed_windows: int
    first_failed_window: int | None
    discarded_bits: int
    h_used: float
    alpha_neg_log2: int


def _validate_h(h: float) -> None:
    """Exige 0 < H <= 1 (min-entropia por bit)."""
    if isinstance(h, bool) or not isinstance(h, (int, float)):
        raise TypeError(f"H deve ser número, recebido {type(h).__name__}")
    if not math.isfinite(h) or not 0 < h <= 1:
        raise ValueError(f"H deve estar em (0, 1], recebido {h}")


def _validate_alpha(alpha_neg_log2: int) -> None:
    """Exige α = 2^-X com X inteiro em [20, 40] (faixa do SP 800-90B)."""
    if isinstance(alpha_neg_log2, bool) or not isinstance(alpha_neg_log2, int):
        raise TypeError("alpha_neg_log2 deve ser int")
    if not 20 <= alpha_neg_log2 <= 40:
        raise ValueError(f"alpha_neg_log2 deve estar em [20, 40], recebido {alpha_neg_log2}")


def _validate_bits(bits: np.ndarray) -> None:
    """Exige array 1-D uint8, não vazio, só com 0 e 1."""
    if not isinstance(bits, np.ndarray):
        raise TypeError("bits deve ser numpy.ndarray")
    if bits.dtype != np.uint8:
        raise TypeError(f"bits deve ser uint8, recebido {bits.dtype}")
    if bits.ndim != 1 or bits.size == 0:
        raise ValueError("bits deve ser 1-D e não vazio")
    if np.any(bits > 1):
        raise ValueError("bits deve conter só 0 e 1")


def rct_cutoff(h: float, alpha_neg_log2: int = RCT_ALPHA_NEG_LOG2) -> int:
    """Limite do RCT: C = 1 + ceil(-log2(α) / H) (SP 800-90B 4.4.1).

    A divisão é feita com Fraction sobre a representação decimal de H, para que
    o ceil nunca dependa de arredondamento de ponto flutuante.
    """
    _validate_h(h)
    _validate_alpha(alpha_neg_log2)
    return 1 + math.ceil(Fraction(alpha_neg_log2) / Fraction(str(h)))


def apt_cutoff(
    h: float, window: int = APT_WINDOW, alpha_neg_log2: int = APT_ALPHA_NEG_LOG2
) -> int:
    """Limite do APT: C = 1 + CRITBINOM(W, 2^-H, 1 - α) (SP 800-90B 4.4.2).

    CRITBINOM devolve o menor k com P(X <= k) >= 1 - α, que é binom.ppf.
    """
    _validate_h(h)
    _validate_alpha(alpha_neg_log2)
    if window < 2:
        raise ValueError("a janela do APT deve ter ao menos 2 bits")
    k = binom.ppf(1 - 2.0 ** -alpha_neg_log2, window, 2.0 ** -h)
    return 1 + int(k)


def longest_run(bits: np.ndarray) -> tuple[int, int]:
    """Devolve (tamanho, posição inicial) da maior sequência de bits iguais."""
    _validate_bits(bits)
    changes = np.flatnonzero(np.diff(bits)) + 1
    starts = np.concatenate(([0], changes))
    ends = np.concatenate((changes, [bits.size]))
    lengths = ends - starts
    i = int(np.argmax(lengths))
    return int(lengths[i]), int(starts[i])


def run_rct(
    bits: np.ndarray, h: float, alpha_neg_log2: int = RCT_ALPHA_NEG_LOG2
) -> RctResult:
    """Reprova se algum valor se repetir C ou mais vezes seguidas."""
    cutoff = rct_cutoff(h, alpha_neg_log2)
    max_run, start = longest_run(bits)
    return RctResult(
        passed=max_run < cutoff,
        cutoff=cutoff,
        max_run=max_run,
        max_run_start=start,
        h_used=float(h),
        alpha_neg_log2=alpha_neg_log2,
    )


def window_counts(bits: np.ndarray, window: int = APT_WINDOW) -> np.ndarray:
    """Para cada janela completa, conta quantas vezes o 1º bit aparece nela.

    A contagem inclui o próprio 1º bit, como no SP 800-90B. Bits que sobram
    depois da última janela completa são ignorados aqui.
    """
    _validate_bits(bits)
    n_windows = bits.size // window
    if n_windows == 0:
        return np.empty(0, dtype=np.int64)
    w = bits[: n_windows * window].reshape(n_windows, window)
    ones = w.sum(axis=1, dtype=np.int64)
    return np.where(w[:, 0] == 1, ones, window - ones)


def run_apt(
    bits: np.ndarray,
    h: float,
    window: int = APT_WINDOW,
    alpha_neg_log2: int = APT_ALPHA_NEG_LOG2,
) -> AptResult:
    """Reprova se, em alguma janela, o 1º bit aparecer C ou mais vezes.

    Lote menor que uma janela: inconclusivo e não aprovado (fail-closed).
    """
    cutoff = apt_cutoff(h, window, alpha_neg_log2)
    counts = window_counts(bits, window)
    n_windows = int(counts.size)
    discarded = int(bits.size - n_windows * window)
    if n_windows == 0:
        return AptResult(
            passed=False,
            inconclusive=True,
            cutoff=cutoff,
            max_count=0,
            window=window,
            n_windows=0,
            n_failed_windows=0,
            first_failed_window=None,
            discarded_bits=discarded,
            h_used=float(h),
            alpha_neg_log2=alpha_neg_log2,
        )
    failed = np.flatnonzero(counts >= cutoff)
    return AptResult(
        passed=failed.size == 0,
        inconclusive=False,
        cutoff=cutoff,
        max_count=int(counts.max()),
        window=window,
        n_windows=n_windows,
        n_failed_windows=int(failed.size),
        first_failed_window=int(failed[0]) if failed.size else None,
        discarded_bits=discarded,
        h_used=float(h),
        alpha_neg_log2=alpha_neg_log2,
    )
