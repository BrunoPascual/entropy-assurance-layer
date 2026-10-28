"""Simulador de QPU: Hadamard em N qubits + medição, no Qiskit Aer."""
from __future__ import annotations

import numpy as np
import qiskit
import qiskit_aer
from qiskit import QuantumCircuit
from qiskit_aer import AerSimulator

from eal.sources.base import RawBatch, Source


def memory_to_bits(memory: list[str], n_qubits: int) -> np.ndarray:
    """Converte a memória do Aer em bits; bit i de cada shot = qubit i.

    O Qiskit escreve cada string com o qubit 0 mais à direita, então
    invertemos cada linha. Saída: shot a shot, qubits 0..N-1.
    """
    flat = np.frombuffer("".join(memory).encode("ascii"), dtype=np.uint8) - ord("0")
    return flat.reshape(len(memory), n_qubits)[:, ::-1].reshape(-1).astype(np.uint8)


def hadamard_circuit(n_qubits: int) -> QuantumCircuit:
    """Hadamard em todos os qubits, seguido de medição."""
    qc = QuantumCircuit(n_qubits, n_qubits)
    qc.h(range(n_qubits))
    qc.measure(range(n_qubits), range(n_qubits))
    return qc


class QpuSim(Source):
    """Simulador (gerador pseudoaleatório clássico). Nunca conta como entropia real."""

    source_id = "qpu_sim"
    source_type = "qpu_sim"
    is_local = True
    is_simulated = True

    def __init__(self, n_qubits: int = 20, seed: int = 12345,
                 noise_model=None, noise_name: str = "none") -> None:
        if n_qubits <= 0:
            raise ValueError("n_qubits deve ser positivo")
        self.n_qubits = n_qubits
        self.seed = seed
        self.noise_model = noise_model  # modelo de ruído entra no próximo item do Dia 2
        self.noise_name = noise_name
        self.source_version = (
            f"qpu_sim-0.1.0/qiskit-{qiskit.__version__}/aer-{qiskit_aer.__version__}"
        )

    def read(self, n_bits: int) -> RawBatch:
        """Retorna n_bits bits; descarta o excesso do último shot."""
        n_bits = self.validate_n_bits(n_bits)
        shots = -(-n_bits // self.n_qubits)  # teto
        sim = AerSimulator(noise_model=self.noise_model, seed_simulator=self.seed)
        job = sim.run(hadamard_circuit(self.n_qubits), shots=shots, memory=True)
        bits = memory_to_bits(job.result().get_memory(), self.n_qubits)[:n_bits].copy()
        params = {
            "backend": "AerSimulator", "n_qubits": self.n_qubits, "shots": shots,
            "seed": self.seed, "noise_model": self.noise_name,
            "bit_order": "shot-major; posicao i do shot = qubit i",
            "discarded_bits": shots * self.n_qubits - n_bits,
        }
        return self._build_batch(bits, params)
