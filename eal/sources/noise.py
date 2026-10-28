"""Modelo de ruído a partir da calibração de um chip IBM (backend simulado).

O NoiseModel.from_backend do Aer monta o erro de leitura SIMÉTRICO, o que
cancela o viés num qubit em superposição 50/50. Aqui o erro de leitura é
remontado ASSIMÉTRICO, com os dois valores da calibração:
  prob_meas1_prep0 = P(ler 1 | preparado 0)
  prob_meas0_prep1 = P(ler 0 | preparado 1)
"""
from __future__ import annotations

from qiskit_aer.noise import NoiseModel, ReadoutError
from qiskit_ibm_runtime import fake_provider


def load_fake_backend(name: str = "FakeKingston"):
    """Carrega um backend simulado do qiskit-ibm-runtime pelo nome da classe."""
    cls = getattr(fake_provider, name, None)
    if cls is None:
        raise ValueError(f"backend simulado inexistente: {name}")
    return cls()


def readout_probs(backend, qubit: int) -> tuple[float, float]:
    """Retorna (P(1|0), P(0|1)) do qubit, pela calibração do backend."""
    props = backend.properties()
    p1_0 = float(props.qubit_property(qubit, "prob_meas1_prep0")[0])
    p0_1 = float(props.qubit_property(qubit, "prob_meas0_prep1")[0])
    return p1_0, p0_1


def expected_p1_readout_only(backend, qubit: int) -> float:
    """P(ler 1) para estado 50/50 considerando só o erro de leitura."""
    p1_0, p0_1 = readout_probs(backend, qubit)
    return 0.5 * (1 - p0_1) + 0.5 * p1_0


def build_noise_model(backend, qubits: list[int]) -> NoiseModel:
    """Ruído de portas e relaxação do backend + leitura assimétrica nos qubits dados."""
    model = NoiseModel.from_backend(backend, readout_error=False)
    for q in qubits:
        p1_0, p0_1 = readout_probs(backend, q)
        model.add_readout_error(ReadoutError([[1 - p1_0, p1_0], [p0_1, 1 - p0_1]]), [q])
    return model


def calibration_date(backend) -> str:
    """Data (ISO) da calibração guardada no backend simulado."""
    return backend.properties().last_update_date.isoformat()
