"""Testes de eal/health/continuous.py com respostas conhecidas.

Valores do RCT conferidos à mão: C = 1 + ceil(X / H), com α = 2^-X.
Os testes da fórmula passam α explicitamente; os testes de "padrão do projeto"
conferem o que está em eal/config.py (RCT 2^-40, APT 2^-20).
Valores do APT conferidos com scipy.stats.binom e pela propriedade que define
CRITBINOM (P(X <= C-2) < 1 - α <= P(X <= C-1)); conferir também na tabela
do SP 800-90B (seção 4.4.2).

Sequências de teste são padrões determinísticos (sem aleatoriedade).
"""
import dataclasses
import math

import numpy as np
import pytest
from scipy.stats import binom

from eal.health.continuous import (
    apt_cutoff,
    longest_run,
    rct_cutoff,
    run_apt,
    run_rct,
    window_counts,
)

A20 = 20  # α = 2^-20, exemplo do SP 800-90B
A40 = 40  # α = 2^-40, outro extremo da faixa


def alternating(n: int, first: int = 0) -> np.ndarray:
    """0101... (ou 1010...) de tamanho n: maior sequência = 1."""
    return ((np.arange(n) + first) % 2).astype(np.uint8)


def with_run(n: int, start: int, length: int, value: int) -> np.ndarray:
    """Base alternada com uma sequência de `length` bits `value` em `start`.

    Os vizinhos da sequência recebem o valor oposto, para ela não crescer.
    """
    bits = alternating(n)
    bits[start : start + length] = value
    if start > 0:
        bits[start - 1] = 1 - value
    if start + length < n:
        bits[start + length] = 1 - value
    return bits


def window_with_ref_count(ref: int, count: int, w: int = 1024) -> np.ndarray:
    """Janela que começa com `ref` e onde `ref` aparece exatamente `count` vezes."""
    win = np.full(w, 1 - ref, dtype=np.uint8)
    win[:count] = ref
    return win


# ---------- RCT: limite ----------

@pytest.mark.parametrize(
    "h, expected",
    [(1.0, 21), (1, 21), (0.9, 24), (0.8, 26), (0.7, 30), (0.5, 41), (0.25, 81)],
)
def test_rct_cutoff_alpha20_known_values(h, expected):
    # 20/1=20→21; 20/0,9=22,2→23→24; 20/0,8=25→26; 20/0,7=28,6→29→30;
    # 20/0,5=40→41; 20/0,25=80→81
    assert rct_cutoff(h, A20) == expected


@pytest.mark.parametrize("h, expected", [(1.0, 41), (0.9, 46), (0.8, 51), (0.5, 81)])
def test_rct_cutoff_alpha40_known_values(h, expected):
    # 40/1=40→41; 40/0,9=44,4→45→46; 40/0,8=50→51; 40/0,5=80→81
    assert rct_cutoff(h, A40) == expected


def test_rct_cutoff_project_default_is_alpha40():
    assert rct_cutoff(1.0) == 41


def test_rct_default_false_alarm_per_megabit_is_tiny():
    # ~500 mil sequências por lote de 1M bits; cada uma tem P(>= C) = 2^-(C-1)
    expected_false_alarms = 500_000 * 2.0 ** -(rct_cutoff(1.0) - 1)
    assert expected_false_alarms < 1e-5


@pytest.mark.parametrize("a", [19, 41, 0])
def test_cutoffs_reject_alpha_out_of_range(a):
    with pytest.raises(ValueError):
        rct_cutoff(1.0, a)
    with pytest.raises(ValueError):
        apt_cutoff(1.0, alpha_neg_log2=a)


@pytest.mark.parametrize("a", [20.0, True, "20"])
def test_cutoffs_reject_alpha_wrong_type(a):
    with pytest.raises(TypeError):
        rct_cutoff(1.0, a)


@pytest.mark.parametrize("h", [0, 0.0, -0.1, 1.0001, 2, math.nan, math.inf])
def test_rct_cutoff_rejects_invalid_h_values(h):
    with pytest.raises(ValueError):
        rct_cutoff(h)


@pytest.mark.parametrize("h", [True, "1", None])
def test_rct_cutoff_rejects_invalid_h_types(h):
    with pytest.raises(TypeError):
        rct_cutoff(h)


# ---------- RCT: maior sequência ----------

def test_longest_run_known():
    assert longest_run(np.array([0, 0, 1, 1, 1, 0], dtype=np.uint8)) == (3, 2)


def test_longest_run_alternating_is_one():
    assert longest_run(alternating(1000)) == (1, 0)


def test_longest_run_single_bit():
    assert longest_run(np.array([1], dtype=np.uint8)) == (1, 0)


def test_longest_run_all_equal():
    assert longest_run(np.zeros(500, dtype=np.uint8)) == (500, 0)


def test_longest_run_tie_returns_first():
    bits = np.array([1, 1, 0, 0, 1], dtype=np.uint8)
    assert longest_run(bits) == (2, 0)


def test_longest_run_at_end():
    bits = with_run(100, 70, 30, 1)
    assert longest_run(bits) == (30, 70)


# ---------- RCT: decisão ----------

@pytest.mark.parametrize("value", [0, 1])
def test_rct_alpha20_run_20_passes(value):
    r = run_rct(with_run(10_000, 5_000, 20, value), h=1.0, alpha_neg_log2=A20)
    assert r.passed and r.max_run == 20 and r.cutoff == 21


@pytest.mark.parametrize("value", [0, 1])
def test_rct_alpha20_run_21_fails(value):
    r = run_rct(with_run(10_000, 5_000, 21, value), h=1.0, alpha_neg_log2=A20)
    assert not r.passed and r.max_run == 21 and r.max_run_start == 5_000


def test_rct_alpha20_h09_boundary():
    assert run_rct(with_run(10_000, 100, 23, 1), h=0.9, alpha_neg_log2=A20).passed
    assert not run_rct(with_run(10_000, 100, 24, 1), h=0.9, alpha_neg_log2=A20).passed


def test_rct_default_boundary_40_41():
    r40 = run_rct(with_run(10_000, 100, 40, 0), h=1.0)
    r41 = run_rct(with_run(10_000, 100, 41, 0), h=1.0)
    assert r40.passed and r40.cutoff == 41 and r40.alpha_neg_log2 == 40
    assert not r41.passed


def test_rct_stuck_64_fails():
    # mesmo trecho que a faulty_stuck injeta; reprova com o padrão (C = 41)
    assert not run_rct(with_run(1_000_000, 123_456, 64, 0), h=1.0).passed


def test_rct_run_at_start_fails():
    r = run_rct(with_run(10_000, 0, 41, 1), h=1.0)
    assert not r.passed and r.max_run_start == 0


def test_rct_alternating_large_passes():
    r = run_rct(alternating(1_000_000), h=1.0)
    assert r.passed and r.max_run == 1


def test_rct_records_h_used():
    assert run_rct(alternating(100), h=0.9).h_used == 0.9


# ---------- APT: limite ----------

@pytest.mark.parametrize("h, expected", [(1.0, 589), (0.9, 625), (0.8, 664)])
def test_apt_cutoff_alpha20_known_values(h, expected):
    assert apt_cutoff(h, alpha_neg_log2=A20) == expected


def test_apt_cutoff_project_default_is_alpha20():
    assert apt_cutoff(1.0) == 589


@pytest.mark.parametrize("a", [A20, A40])
@pytest.mark.parametrize("h", [1.0, 0.9, 0.8, 0.5])
def test_apt_cutoff_matches_critbinom_definition(h, a):
    # CRITBINOM: menor k com P(X <= k) >= 1 - α; C = 1 + k
    k = apt_cutoff(h, alpha_neg_log2=a) - 1
    p = 2.0 ** -h
    assert binom.cdf(k, 1024, p) >= 1 - 2.0 ** -a
    assert binom.cdf(k - 1, 1024, p) < 1 - 2.0 ** -a


def test_apt_cutoff_h1_normal_sanity():
    # conta à mão: média 512, desvio 16, z(1-2^-20) ≈ 4,76 → 512 + 76 ≈ 588
    assert 585 <= apt_cutoff(1.0, alpha_neg_log2=A20) <= 592


def test_apt_cutoff_grows_as_h_falls():
    assert apt_cutoff(1.0) < apt_cutoff(0.9) < apt_cutoff(0.8) < apt_cutoff(0.5)


def test_apt_cutoff_rejects_bad_window():
    with pytest.raises(ValueError):
        apt_cutoff(1.0, window=1)


# ---------- APT: contagem por janela ----------

def test_window_counts_alternating_is_half():
    counts = window_counts(alternating(1024 * 5))
    assert counts.tolist() == [512] * 5


def test_window_counts_all_ones():
    assert window_counts(np.ones(2048, dtype=np.uint8)).tolist() == [1024, 1024]


def test_window_counts_reference_zero_alone():
    # começa com 0, resto todo 1: o valor de referência (0) aparece 1 vez
    win = np.ones(1024, dtype=np.uint8)
    win[0] = 0
    assert window_counts(win).tolist() == [1]


def test_window_counts_includes_reference():
    assert window_counts(window_with_ref_count(1, 600)).tolist() == [600]


def test_window_counts_short_input_is_empty():
    assert window_counts(alternating(1023)).size == 0


# ---------- APT: decisão ----------

def test_apt_balanced_passes():
    r = run_apt(alternating(1024 * 10), h=1.0)
    assert r.passed and not r.inconclusive and r.max_count == 512


@pytest.mark.parametrize("ref", [0, 1])
def test_apt_h1_boundary_588_passes(ref):
    r = run_apt(window_with_ref_count(ref, 588), h=1.0)
    assert r.passed and r.max_count == 588


@pytest.mark.parametrize("ref", [0, 1])
def test_apt_h1_boundary_589_fails(ref):
    r = run_apt(window_with_ref_count(ref, 589), h=1.0)
    assert not r.passed and r.max_count == 589


def test_apt_all_equal_window_fails():
    assert not run_apt(np.ones(1024, dtype=np.uint8), h=1.0).passed


def test_apt_reports_failed_windows():
    good = alternating(1024)
    bad = window_with_ref_count(1, 700)
    bits = np.concatenate([good, good, bad, good, bad])
    r = run_apt(bits, h=1.0)
    assert not r.passed
    assert r.n_windows == 5
    assert r.n_failed_windows == 2
    assert r.first_failed_window == 2


def test_apt_discards_remainder():
    bits = np.concatenate([alternating(1024 * 3), np.ones(100, dtype=np.uint8)])
    r = run_apt(bits, h=1.0)
    # os 100 uns no fim não são testados: só as 3 janelas completas contam
    assert r.passed and r.n_windows == 3 and r.discarded_bits == 100


def test_apt_short_batch_is_inconclusive_and_not_passed():
    r = run_apt(alternating(1000), h=1.0)
    assert r.inconclusive and not r.passed
    assert r.n_windows == 0 and r.discarded_bits == 1000


def test_apt_custom_window():
    r = run_apt(np.ones(64, dtype=np.uint8), h=1.0, window=64)
    assert not r.passed and r.window == 64


# ---------- validação de entrada ----------

@pytest.mark.parametrize("fn", [longest_run, window_counts])
def test_rejects_list(fn):
    with pytest.raises(TypeError):
        fn([0, 1, 0])


@pytest.mark.parametrize("fn", [longest_run, window_counts])
def test_rejects_wrong_dtype(fn):
    with pytest.raises(TypeError):
        fn(np.array([0, 1, 0], dtype=np.int64))


@pytest.mark.parametrize(
    "bits",
    [
        np.zeros((2, 2), dtype=np.uint8),
        np.array([], dtype=np.uint8),
        np.array([0, 2, 1], dtype=np.uint8),
    ],
)
def test_rejects_bad_shape_or_values(bits):
    with pytest.raises(ValueError):
        run_rct(bits, h=1.0)


def test_results_are_frozen():
    r = run_rct(alternating(100), h=1.0)
    with pytest.raises(dataclasses.FrozenInstanceError):
        r.passed = False
