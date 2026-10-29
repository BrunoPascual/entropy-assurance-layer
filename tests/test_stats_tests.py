"""Testes de eal/health/stats_tests.py.

Valores de referência: exemplos publicados no NIST SP 800-22 Rev. 1a,
seções 2.1.4, 2.1.8, 2.2.4, 2.2.8, 2.3.4 e 2.3.8 (conferir no documento).
Vetor grande "aleatório": saída fixa do SHAKE-256 (determinística, não é fonte).
"""
import dataclasses
import hashlib

import numpy as np
import pytest

from eal.config import STATS_BLOCK_M, STATS_MIN_BITS, STATS_P_MIN
from eal.health.stats_tests import (
    block_frequency_p,
    monobit_p,
    run_stats_tests,
    runs_p,
)

# 100 bits do exemplo do SP 800-22 (seções 2.1.8, 2.2.8 e 2.3.8)
E100 = (
    "11001001000011111101101010100010001000010110100011"
    "00001000110100110001001100011001100010100010111000"
)


def b(s: str) -> np.ndarray:
    return np.array([int(c) for c in s], dtype=np.uint8)


def alternating(n: int) -> np.ndarray:
    return (np.arange(n) % 2).astype(np.uint8)


def shake_bits(n_bits: int, label: bytes = b"EAL-test-vector") -> np.ndarray:
    """Vetor de teste fixo: n_bits da saída do SHAKE-256 de um rótulo."""
    data = hashlib.shake_256(label).digest(n_bits // 8)
    return np.unpackbits(np.frombuffer(data, dtype=np.uint8))


def ones_then_zeros(n: int, ones: int) -> np.ndarray:
    bits = np.zeros(n, dtype=np.uint8)
    bits[:ones] = 1
    return bits


# ---------- monobit (SP 800-22 2.1) ----------

def test_monobit_spec_example_10_bits():
    p, s_obs = monobit_p(b("1011010101"))
    assert s_obs == pytest.approx(0.632455532, abs=1e-9)
    assert p == pytest.approx(0.527089, abs=1e-6)


def test_monobit_spec_example_100_bits():
    p, s_obs = monobit_p(b(E100))
    assert s_obs == pytest.approx(1.6)
    assert p == pytest.approx(0.109599, abs=1e-6)


def test_monobit_balanced_is_one():
    p, s_obs = monobit_p(alternating(1000))
    assert s_obs == 0.0 and p == 1.0


def test_monobit_all_ones_is_zero():
    p, _ = monobit_p(np.ones(10_000, dtype=np.uint8))
    assert p < 1e-100


# ---------- frequência por bloco (SP 800-22 2.2) ----------

def test_block_spec_example_10_bits_m3():
    # blocos 011, 001, 101 (sobra 1 bit): χ² = 1; p = igamc(1,5; 0,5)
    p, chi2 = block_frequency_p(b("0110011010"), m=3)
    assert chi2 == pytest.approx(1.0)
    assert p == pytest.approx(0.801252, abs=1e-6)


def test_block_spec_example_100_bits_m10():
    p, chi2 = block_frequency_p(b(E100), m=10)
    assert chi2 == pytest.approx(7.2)
    assert p == pytest.approx(0.706438, abs=1e-6)


def test_block_balanced_blocks_is_one():
    p, chi2 = block_frequency_p(alternating(128 * 100), m=128)
    assert chi2 == 0.0 and p == 1.0


def test_block_catches_bias_that_cancels_globally():
    # metade 70% uns, metade 30%: monobit perfeito, bloco reprova
    half = 128 * 400
    a = np.tile(ones_then_zeros(10, 7), half // 10 + 1)[:half]
    c = np.tile(ones_then_zeros(10, 3), half // 10 + 1)[:half]
    bits = np.concatenate([a, c])
    assert monobit_p(bits)[0] > STATS_P_MIN
    assert block_frequency_p(bits, m=128)[0] < STATS_P_MIN


def test_block_default_m_is_128():
    assert STATS_BLOCK_M == 128


def test_block_rejects_too_short():
    with pytest.raises(ValueError):
        block_frequency_p(alternating(100), m=128)


# ---------- runs (SP 800-22 2.3) ----------

def test_runs_spec_example_10_bits():
    p, v_obs, pre_ok = runs_p(b("1001101011"))
    assert pre_ok and v_obs == 7
    assert p == pytest.approx(0.147232, abs=1e-6)


def test_runs_spec_example_100_bits():
    p, v_obs, pre_ok = runs_p(b(E100))
    assert pre_ok and v_obs == 52
    assert p == pytest.approx(0.500798, abs=1e-6)


def test_runs_alternating_fails():
    # V = n, muito acima de n/2: alternância anormal
    p, v_obs, pre_ok = runs_p(alternating(10_000))
    assert pre_ok and v_obs == 10_000 and p < 1e-100


def test_runs_prerequisite_boundary_exact():
    # n = 100, τ = 0,2. 69 uns: |0,19| < 0,2 → aplica. 70 uns: |0,2| >= 0,2 → p = 0.
    # Em ponto flutuante, 0,7 - 0,5 < 0,2; a conta inteira evita esse erro.
    assert runs_p(ones_then_zeros(100, 69))[2] is True
    p, _, pre_ok = runs_p(ones_then_zeros(100, 70))
    assert pre_ok is False and p == 0.0
    assert runs_p(ones_then_zeros(100, 30))[2] is False


def test_runs_all_equal_prerequisite_fails():
    p, v_obs, pre_ok = runs_p(np.ones(10, dtype=np.uint8))
    assert not pre_ok and p == 0.0 and v_obs == 1


# ---------- relatório dos três testes ----------

def test_report_shake_vector_passes_all():
    r = run_stats_tests(shake_bits(STATS_MIN_BITS))
    assert r.passed and not r.inconclusive
    assert all(t.p_value >= STATS_P_MIN for t in r.results)


def test_report_alternating_fails_only_runs():
    r = run_stats_tests(alternating(STATS_MIN_BITS))
    assert r.monobit.passed and r.block_frequency.passed
    assert not r.runs.passed and not r.passed


def test_report_short_batch_is_inconclusive_and_not_passed():
    r = run_stats_tests(shake_bits(STATS_MIN_BITS - 8))
    assert r.inconclusive and not r.passed
    assert all(t.inconclusive and not t.passed for t in r.results)
    assert "inconclusivo" in r.monobit.note


def test_report_exactly_min_bits_is_conclusive():
    assert not run_stats_tests(shake_bits(STATS_MIN_BITS)).inconclusive


def test_report_custom_min_bits():
    r = run_stats_tests(b(E100), min_bits=100)
    assert not r.monobit.inconclusive and not r.runs.inconclusive
    assert r.block_frequency.inconclusive  # 100 bits < M = 128
    assert r.monobit.p_value == pytest.approx(0.109599, abs=1e-6)


def test_report_runs_note_when_prerequisite_fails():
    r = run_stats_tests(ones_then_zeros(STATS_MIN_BITS, 600_000))
    assert not r.runs.passed and "pré-teste" in r.runs.note


def test_report_fewer_than_m_bits():
    r = run_stats_tests(alternating(100))
    assert r.block_frequency.inconclusive and not r.passed


def test_report_p_values_keys():
    r = run_stats_tests(b(E100), min_bits=100)
    assert set(r.p_values()) == {"monobit", "block", "runs"}


def test_p_min_is_0_01():
    assert STATS_P_MIN == 0.01


def test_min_bits_is_one_million():
    assert STATS_MIN_BITS == 1_000_000


# ---------- validação ----------

@pytest.mark.parametrize("fn", [monobit_p, block_frequency_p, runs_p, run_stats_tests])
def test_rejects_list(fn):
    with pytest.raises(TypeError):
        fn([0, 1] * 100)


@pytest.mark.parametrize("fn", [monobit_p, runs_p, run_stats_tests])
def test_rejects_wrong_dtype(fn):
    with pytest.raises(TypeError):
        fn(np.zeros(200, dtype=np.int64))


@pytest.mark.parametrize(
    "bits",
    [np.array([], dtype=np.uint8), np.zeros((2, 200), dtype=np.uint8),
     np.array([0, 1, 2] * 100, dtype=np.uint8)],
)
def test_rejects_bad_shape_or_values(bits):
    with pytest.raises(ValueError):
        run_stats_tests(bits)


def test_results_are_frozen():
    r = run_stats_tests(b(E100), min_bits=100)
    with pytest.raises(dataclasses.FrozenInstanceError):
        r.monobit.passed = False
