"""Testes de eal/health/min_entropy.py com respostas calculadas à mão.

Fórmula (SP 800-90B 6.3.1): p_u = min(1, p̂ + 2,576·sqrt(p̂(1-p̂)/(n-1))),
H = -log2(p_u) / bits_do_símbolo. Sequências determinísticas, sem aleatoriedade.
"""
import dataclasses

import numpy as np
import pytest

from eal.health.min_entropy import (
    MIN_BITS,
    estimate_min_entropy,
    mcv_bits,
    mcv_symbols,
    mcv_upper_bound,
)


def alternating(n: int) -> np.ndarray:
    return (np.arange(n) % 2).astype(np.uint8)


def all_bytes(repeats: int) -> np.ndarray:
    """Cada um dos 256 valores de byte aparece `repeats` vezes; bits equilibrados."""
    return np.unpackbits(np.tile(np.arange(256, dtype=np.uint8), repeats))


# ---------- limite superior ----------

def test_upper_bound_600_of_1000():
    # p̂=0,6; sqrt(0,24/999)=0,015500; 2,576·0,015500=0,039927 → 0,639927
    assert mcv_upper_bound(600, 1000) == pytest.approx(0.639927, abs=1e-6)


def test_upper_bound_500_of_1000():
    # p̂=0,5; sqrt(0,25/999)=0,015819; ·2,576=0,040751 → 0,540751
    assert mcv_upper_bound(500, 1000) == pytest.approx(0.540751, abs=1e-6)


def test_upper_bound_all_equal_is_one():
    assert mcv_upper_bound(1000, 1000) == 1.0


def test_upper_bound_is_clamped_at_one():
    # p̂=0,9 com n=10: 0,9 + 2,576·sqrt(0,09/9) = 0,9 + 0,2576 > 1
    assert mcv_upper_bound(9, 10) == 1.0


@pytest.mark.parametrize("max_count, n", [(0, 10), (11, 10), (1, 1), (-1, 10)])
def test_upper_bound_rejects_bad_input(max_count, n):
    with pytest.raises(ValueError):
        mcv_upper_bound(max_count, n)


# ---------- estimador por bit ----------

def test_mcv_bits_600_ones_of_1000():
    bits = np.zeros(1000, dtype=np.uint8)
    bits[:600] = 1
    r = mcv_bits(bits)
    # H = -log2(0,639927) = 0,6440
    assert r.h == pytest.approx(0.64402, abs=1e-5)
    assert r.max_count == 600 and r.n_samples == 1000 and r.p_hat == 0.6


def test_mcv_bits_majority_zero_is_symmetric():
    bits = np.ones(1000, dtype=np.uint8)
    bits[:600] = 0
    assert mcv_bits(bits).h == pytest.approx(0.64402, abs=1e-5)


def test_mcv_bits_balanced_1000():
    # -log2(0,540751) = 0,88696
    assert mcv_bits(alternating(1000)).h == pytest.approx(0.88696, abs=1e-5)


def test_mcv_bits_balanced_million():
    # p_u = 0,5 + 2,576·0,5/sqrt(999999) = 0,501288 → H = 0,99629
    assert mcv_bits(alternating(1_000_000)).h == pytest.approx(0.99629, abs=1e-5)


def test_mcv_bits_all_zero_is_zero():
    r = mcv_bits(np.zeros(1000, dtype=np.uint8))
    assert r.h == 0.0 and r.p_upper == 1.0


# ---------- estimador por byte ----------

def test_mcv_symbols_all_byte_values_equal():
    # n=256000, p̂=1/256; p_u = 0,00390625 + 2,576·sqrt(p̂(1-p̂)/255999)
    #   = 0,00390625 + 0,00031759 = 0,00422384 → -log2 = 7,8872 → /8 = 0,98590
    r = mcv_symbols(all_bytes(1000))
    assert r.h == pytest.approx(0.98590, abs=1e-5)
    assert r.n_samples == 256_000 and r.max_count == 1000 and r.symbol_bits == 8


def test_mcv_symbols_alternating_is_zero():
    # 0101... vira sempre o byte 0x55: o estimador por byte vê que é previsível
    r = mcv_symbols(alternating(10_000))
    assert r.h == 0.0 and r.max_count == 1250


def test_mcv_symbols_discards_remainder():
    r = mcv_symbols(np.concatenate([all_bytes(10), np.ones(3, dtype=np.uint8)]))
    assert r.n_samples == 2560 and r.discarded_bits == 3


def test_mcv_symbols_only_8_bits():
    with pytest.raises(ValueError):
        mcv_symbols(alternating(1000), symbol_bits=4)


# ---------- estimativa combinada ----------

def test_estimate_correlation_caught_only_by_byte():
    e = estimate_min_entropy(alternating(1_000_000))
    assert e.h_bit == pytest.approx(0.99629, abs=1e-5)
    assert e.h_byte == 0.0
    assert e.h_estimated == 0.0 and e.limited_by == "byte"


def test_estimate_all_bytes_limited_by_byte():
    # bits: n=2.048.000 equilibrados → p_u = 0,5 + 2,576·0,5/sqrt(2047999) → H=0,99741
    e = estimate_min_entropy(all_bytes(1000))
    assert e.h_bit == pytest.approx(0.99741, abs=1e-5)
    assert e.h_byte == pytest.approx(0.98590, abs=1e-5)
    assert e.h_estimated == e.h_byte and e.limited_by == "byte"


def test_estimate_bias_limited_by_bit():
    # 600 uns em 1000 bits, todos no começo: bytes 0xFF (75) e 0x00 (50)
    bits = np.zeros(1000, dtype=np.uint8)
    bits[:600] = 1
    e = estimate_min_entropy(bits)
    assert e.h_estimated == min(e.h_bit, e.h_byte)


def test_estimate_all_zero():
    e = estimate_min_entropy(np.zeros(4096, dtype=np.uint8))
    assert e.h_estimated == 0.0


@pytest.mark.parametrize(
    "bits", [alternating(1000), all_bytes(3), np.zeros(64, dtype=np.uint8)]
)
def test_estimate_is_between_0_and_1(bits):
    e = estimate_min_entropy(bits)
    assert 0.0 <= e.h_estimated <= e.h_bit <= 1.0
    assert 0.0 <= e.h_byte <= 1.0


# ---------- validação ----------

def test_min_bits_is_16():
    assert MIN_BITS == 16


def test_rejects_too_short():
    with pytest.raises(ValueError):
        estimate_min_entropy(alternating(15))


def test_accepts_exactly_min_bits():
    assert estimate_min_entropy(alternating(16)).byte.n_samples == 2


@pytest.mark.parametrize("fn", [mcv_bits, mcv_symbols, estimate_min_entropy])
def test_rejects_list(fn):
    with pytest.raises(TypeError):
        fn([0, 1] * 20)


@pytest.mark.parametrize("fn", [mcv_bits, mcv_symbols, estimate_min_entropy])
def test_rejects_wrong_dtype(fn):
    with pytest.raises(TypeError):
        fn(np.zeros(100, dtype=np.int64))


def test_rejects_values_above_one():
    bits = alternating(100)
    bits[5] = 2
    with pytest.raises(ValueError):
        estimate_min_entropy(bits)


def test_rejects_2d():
    with pytest.raises(ValueError):
        estimate_min_entropy(np.zeros((10, 10), dtype=np.uint8))


def test_results_are_frozen():
    e = estimate_min_entropy(alternating(100))
    with pytest.raises(dataclasses.FrozenInstanceError):
        e.h_estimated = 1.0
