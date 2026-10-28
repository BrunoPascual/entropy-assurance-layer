import random
import time

import numpy as np
import pytest

from eal.sources.faulty import (FAULTY_SOURCES, BiasedSource, CorrelatedSource,
                                PrngSource, ReplaySource, StuckSource)

M = 200_000


def max_run(bits: np.ndarray) -> int:
    change = np.flatnonzero(np.diff(bits) != 0)
    edges = np.concatenate(([-1], change, [bits.size - 1]))
    return int(np.diff(edges).max())


def test_registry_has_five():
    assert set(FAULTY_SOURCES) == {"faulty_biased", "faulty_stuck", "faulty_replay",
                                   "faulty_prng", "faulty_correlated"}


@pytest.mark.parametrize("cls", list(FAULTY_SOURCES.values()))
@pytest.mark.parametrize("n", [1, 7, 1000, 4097])
def test_contract(cls, n):
    b = cls().read(n)
    assert b.n_bits == n and b.bits.dtype == np.uint8
    assert set(np.unique(b.bits)) <= {0, 1}
    assert b.source_type == "faulty" and b.source_id == cls.source_id
    assert b.is_local is True and b.is_simulated is True
    assert b.params["seed"] == 2026


@pytest.mark.parametrize("cls", list(FAULTY_SOURCES.values()))
def test_same_seed_reproducible(cls):
    assert cls(seed=9).read(5000).batch_hash == cls(seed=9).read(5000).batch_hash


@pytest.mark.parametrize("cls", [BiasedSource, StuckSource, PrngSource, CorrelatedSource])
def test_successive_reads_differ(cls):
    s = cls()
    assert s.read(4096).batch_hash != s.read(4096).batch_hash


def test_biased_frequency():
    for p in (0.55, 0.7):
        m = BiasedSource(p=p).read(M).bits.mean()
        assert abs(m - p) < 5 * np.sqrt(p * (1 - p) / M)


def test_stuck_has_long_runs():
    b = StuckSource(run_length=64).read(M).bits
    assert max_run(b) >= 64
    assert max_run(PrngSource().read(M).bits) < 40  # referência: fonte boa


def test_replay_repeats_exactly():
    s = ReplaySource()
    a, b = s.read(4096), s.read(4096)
    assert a.batch_hash == b.batch_hash
    assert a.params["replayed"] is False and b.params["replayed"] is True
    assert np.array_equal(s.read(1000).bits, a.bits[:1000])


def test_prng_known_answer():
    n = 4096
    raw = random.Random(123).getrandbits(n).to_bytes(n // 8, "big")
    expected = np.unpackbits(np.frombuffer(raw, dtype=np.uint8))
    assert np.array_equal(PrngSource(seed=123).read(n).bits, expected)


def test_prng_looks_fine():
    m = PrngSource().read(M).bits.mean()
    assert abs(m - 0.5) < 5 * 0.5 / np.sqrt(M)


def test_correlated_repeat_rate():
    for rho in (0.6, 0.8):
        b = CorrelatedSource(rho=rho).read(M).bits
        same = np.mean(b[1:] == b[:-1])
        assert abs(same - rho) < 5 * np.sqrt(rho * (1 - rho) / M)
        assert abs(b.mean() - 0.5) < 0.02  # frequência quase normal


@pytest.mark.parametrize("kwargs, cls", [
    ({"p": 0.0}, BiasedSource), ({"p": 1.0}, BiasedSource),
    ({"run_length": 0}, StuckSource), ({"run_length": 100, "every": 50}, StuckSource),
    ({"rho": 1.0}, CorrelatedSource), ({"rho": -0.1}, CorrelatedSource),
])
def test_invalid_params(kwargs, cls):
    with pytest.raises(ValueError):
        cls(**kwargs)


def test_gate_one_million_bits_each():
    t = time.time()
    for cls in FAULTY_SOURCES.values():
        assert cls().read(1_000_000).n_bits == 1_000_000
    assert time.time() - t < 300  # gate do Dia 2: menos de 5 minutos
