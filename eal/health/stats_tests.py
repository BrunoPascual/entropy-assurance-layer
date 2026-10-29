"""Três testes estatísticos do NIST SP 800-22 Rev. 1a (PROJECT.md 6.6).

Implementação própria das fórmulas; o scipy fornece só erfc e igamc
(gammaincc, gama incompleta superior regularizada).

  - frequência (monobit), seção 2.1;
  - frequência por bloco, seção 2.2 (M = 128, padrão do NIST STS);
  - sequências (runs), seção 2.3, com o pré-teste de frequência.

Estes testes NÃO provam aleatoriedade: um bom gerador pseudoaleatório passa
em todos (limitação T4 / N2 do THREAT_MODEL.md).

Simplificação declarada: com n = 1.000.000 e M = 128 há 7812 blocos, acima da
recomendação N < 100 da seção 2.2.7; M = 128 é o padrão da ferramenta do NIST.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from scipy.special import erfc, gammaincc

from eal.config import STATS_BLOCK_M, STATS_MIN_BITS, STATS_P_MIN


@dataclass(frozen=True)
class StatTestResult:
    """Resultado de um teste estatístico sobre um lote."""

    name: str
    p_value: float
    statistic: float
    passed: bool
    inconclusive: bool
    n_bits: int
    note: str = ""


@dataclass(frozen=True)
class StatsReport:
    """Os três testes juntos; aprovado só se os três passarem."""

    monobit: StatTestResult
    block_frequency: StatTestResult
    runs: StatTestResult

    @property
    def results(self) -> tuple[StatTestResult, ...]:
        return (self.monobit, self.block_frequency, self.runs)

    @property
    def passed(self) -> bool:
        return all(r.passed for r in self.results)

    @property
    def inconclusive(self) -> bool:
        return any(r.inconclusive for r in self.results)

    def p_values(self) -> dict[str, float]:
        """p-valores por nome, no formato do recibo."""
        return {"monobit": self.monobit.p_value, "block": self.block_frequency.p_value,
                "runs": self.runs.p_value}


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


def monobit_p(bits: np.ndarray) -> tuple[float, float]:
    """SP 800-22 2.1: s_obs = |S_n|/sqrt(n); p = erfc(s_obs/sqrt(2)). Devolve (p, s_obs)."""
    _validate_bits(bits)
    n = int(bits.size)
    s_n = 2 * int(bits.sum(dtype=np.int64)) - n
    s_obs = abs(s_n) / math.sqrt(n)
    return float(erfc(s_obs / math.sqrt(2))), s_obs


def block_frequency_p(bits: np.ndarray, m: int = STATS_BLOCK_M) -> tuple[float, float]:
    """SP 800-22 2.2: χ² = 4M·Σ(π_i - 1/2)²; p = igamc(N/2, χ²/2). Devolve (p, χ²).

    Bits que sobram depois do último bloco completo são descartados.
    """
    _validate_bits(bits)
    if m < 1:
        raise ValueError("M deve ser pelo menos 1")
    n_blocks = bits.size // m
    if n_blocks == 0:
        raise ValueError(f"são necessários pelo menos M = {m} bits")
    blocks = bits[: n_blocks * m].reshape(n_blocks, m)
    pi = blocks.sum(axis=1, dtype=np.int64) / m
    chi2 = float(4.0 * m * np.sum((pi - 0.5) ** 2))
    return float(gammaincc(n_blocks / 2.0, chi2 / 2.0)), chi2


def runs_p(bits: np.ndarray) -> tuple[float, float, bool]:
    """SP 800-22 2.3. Devolve (p, V_obs, pré-teste ok).

    Pré-teste: |π - 1/2| < τ = 2/sqrt(n). Se falhar, o teste não se aplica e,
    como manda a seção 2.3.4, p = 0.
    """
    _validate_bits(bits)
    n = int(bits.size)
    ones = int(bits.sum(dtype=np.int64))
    pi = ones / n
    v_obs = float(1 + np.count_nonzero(bits[1:] != bits[:-1]))
    # |π - 1/2| >= 2/sqrt(n)  <=>  (2·ones - n)² >= 16·n, em inteiros (sem erro
    # de ponto flutuante: em float, 0,7 - 0,5 = 0,19999999999999996 < 0,2).
    if (2 * ones - n) ** 2 >= 16 * n or ones in (0, n):
        return 0.0, v_obs, False
    num = abs(v_obs - 2.0 * n * pi * (1.0 - pi))
    den = 2.0 * math.sqrt(2.0 * n) * pi * (1.0 - pi)
    return float(erfc(num / den)), v_obs, True


def _result(name: str, p: float, stat: float, n: int, enough: bool, note: str = "") -> StatTestResult:
    """Monta o resultado; lote pequeno é inconclusivo e não aprovado (fail-closed)."""
    if not enough:
        note = (note + "; " if note else "") + f"lote < {STATS_MIN_BITS} bits: inconclusivo"
    return StatTestResult(name, p, stat, enough and p >= STATS_P_MIN, not enough, n, note)


def run_stats_tests(bits: np.ndarray, min_bits: int = STATS_MIN_BITS) -> StatsReport:
    """Roda os três testes. Abaixo de `min_bits`, os três ficam inconclusivos."""
    _validate_bits(bits)
    n = int(bits.size)
    enough = n >= min_bits
    p_mono, s_obs = monobit_p(bits)
    if n >= STATS_BLOCK_M:
        p_block, chi2 = block_frequency_p(bits)
        block = _result("block", p_block, chi2, n, enough)
    else:
        block = StatTestResult("block", 0.0, 0.0, False, True, n, "menos de M bits")
    p_runs, v_obs, pre_ok = runs_p(bits)
    note = "" if pre_ok else "pré-teste de frequência falhou; p = 0 (SP 800-22 2.3.4)"
    return StatsReport(
        monobit=_result("monobit", p_mono, s_obs, n, enough),
        block_frequency=block,
        runs=_result("runs", p_runs, v_obs, n, enough, note),
    )
