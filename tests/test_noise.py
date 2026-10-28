import time

import numpy as np
import pytest

from eal.sources import noise
from eal.sources.qpu_sim import QpuSim

N = 20


@pytest.fixture(scope="module")
def backend():
    return noise.load_fake_backend("FakeKingston")


@pytest.fixture(scope="module")
def noisy():
    return QpuSim(n_qubits=N, seed=1, noise_backend="FakeKingston")


def test_unknown_backend():
    with pytest.raises(ValueError):
        noise.load_fake_backend("FakeNaoExiste")


def test_expected_p1_formula(backend):
    p1_0, p0_1 = noise.readout_probs(backend, 0)
    assert noise.expected_p1_readout_only(backend, 0) == pytest.approx(
        0.5 * (1 - p0_1) + 0.5 * p1_0)


def test_readout_is_asymmetric(backend):
    model = noise.build_noise_model(backend, [1])
    err = [e for e in model.to_dict()["errors"]
           if e["operations"] == ["measure"] and e["gate_qubits"] == [(1,)]]
    assert len(err) == 1
    probs = np.array(err[0]["probabilities"])
    assert probs[0, 1] != pytest.approx(probs[1, 0])  # P(1|0) != P(0|1)


def test_bias_matches_calibration(noisy, backend):
    b = noisy.read(1_000_000)
    per = b.bits.reshape(-1, N).mean(axis=0)
    expected = np.array([noise.expected_p1_readout_only(backend, q) for q in range(N)])
    sd = np.sqrt(0.25 / (1_000_000 // N))
    # 5 desvios-padrão + 0,005 de folga para erro de porta e relaxação
    assert np.all(np.abs(per - expected) < 5 * sd + 0.005)
    assert per[1] > 0.54  # qubit 1 tem leitura muito assimétrica


def test_noisy_reproducible_and_params(backend):
    a = QpuSim(n_qubits=4, seed=3, noise_backend="FakeKingston").read(4000)
    c = QpuSim(n_qubits=4, seed=3, noise_backend="FakeKingston").read(4000)
    assert a.batch_hash == c.batch_hash
    assert a.params["noise_model"] == "FakeKingston"
    assert a.params["physical_qubits"] == [0, 1, 2, 3]
    assert a.params["readout_error"] == "asymmetric"
    assert a.params["calibration_date"]
    assert a.is_simulated is True


def test_physical_qubits_mapping(backend):
    b = QpuSim(n_qubits=2, seed=5, noise_backend="FakeKingston",
               physical_qubits=[16, 1]).read(200_000)
    per = b.bits.reshape(-1, 2).mean(axis=0)
    assert per[0] < 0.485 and per[1] > 0.54  # 16 tende a 0, 1 tende a 1


def test_physical_qubits_length_checked():
    with pytest.raises(ValueError):
        QpuSim(n_qubits=3, physical_qubits=[0, 1])


def test_noisy_million_bits_fast(noisy):
    t = time.time()
    assert noisy.read(1_000_000).n_bits == 1_000_000
    assert time.time() - t < 60
