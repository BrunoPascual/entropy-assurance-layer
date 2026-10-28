import hashlib
import time

import numpy as np
import pytest

from eal.sources.os_source import OsSource
from eal.sources.qpu_sim import QpuSim, memory_to_bits


@pytest.mark.parametrize("src", [OsSource(), QpuSim(n_qubits=8)])
@pytest.mark.parametrize("n", [1, 7, 8, 1000, 4097])
def test_exact_size_and_values(src, n):
    b = src.read(n)
    assert b.n_bits == n == b.bits.size
    assert b.bits.dtype == np.uint8 and set(np.unique(b.bits)) <= {0, 1}
    expected = hashlib.sha3_256(n.to_bytes(8, "big") + np.packbits(b.bits).tobytes()).hexdigest()
    assert b.batch_hash == expected
    assert b.source_id == src.source_id and b.created_at.endswith("Z")
    assert b.n_bits == n


def test_qpu_sim_version_has_sdk_versions():
    v = QpuSim().read(8).source_version
    assert "qiskit-" in v and "aer-" in v


def test_flags():
    o, q = OsSource().read(64), QpuSim().read(64)
    assert (o.is_local, o.is_simulated) == (True, False)
    assert (q.is_local, q.is_simulated) == (True, True)
    assert q.source_type == "qpu_sim" and o.source_type == "os"


@pytest.mark.parametrize("bad", [0, -5])
def test_invalid_n_bits(bad):
    with pytest.raises(ValueError):
        OsSource().read(bad)
    with pytest.raises(ValueError):
        QpuSim().read(bad)


def test_os_reads_differ():
    assert OsSource().read(4096).batch_hash != OsSource().read(4096).batch_hash


def test_os_monobit_sane():
    ones = OsSource().read(200_000).bits.mean()
    assert abs(ones - 0.5) < 5 * 0.5 / np.sqrt(200_000)


def test_qpu_sim_reproducible_with_seed():
    a = QpuSim(n_qubits=10, seed=7).read(5000)
    b = QpuSim(n_qubits=10, seed=7).read(5000)
    c = QpuSim(n_qubits=10, seed=8).read(5000)
    assert a.batch_hash == b.batch_hash != c.batch_hash


def test_qpu_sim_monobit_sane_and_params():
    b = QpuSim(n_qubits=10, seed=1).read(100_000)
    assert abs(b.bits.mean() - 0.5) < 5 * 0.5 / np.sqrt(100_000)
    assert b.params["shots"] == 10_000 and b.params["discarded_bits"] == 0
    assert b.params["seed"] == 1


def test_memory_to_bits_qubit_order():
    # "0001": qubit 0 = 1 -> posicao 0 do shot; segundo shot "1000": qubit 3 = 1
    out = memory_to_bits(["0001", "1000"], 4)
    assert out.tolist() == [1, 0, 0, 0, 0, 0, 0, 1]


def test_one_million_bits_fast():
    for src in (OsSource(), QpuSim()):
        t = time.time()
        assert src.read(1_000_000).n_bits == 1_000_000
        assert time.time() - t < 60
