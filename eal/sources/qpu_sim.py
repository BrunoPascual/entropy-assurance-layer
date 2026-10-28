"""Simulador de QPU: Hadamard em N qubits + medição, no Qiskit Aer.

Sem ruído, simula qubits ideais num circuito só. Com noise_backend
(ex.: "FakeKingston"), aplica o ruído da calibração daquele chip, com erro de
leitura assimétrico (ver noise.py), simulando CADA QUBIT SEPARADAMENTE em
matriz densidade. Isso é exato aqui porque o circuito não tem portas entre
qubits e o modelo só tem erros de um qubit; mas significa que o simulador
não reproduz correlação entre qubits (crosstalk) que um chip real pode ter.
É sempre um gerador CLÁSSICO: nunca conta como entropia real.
"""
from __future__ import annotations

import numpy as np
import qiskit
import qiskit_aer
from qiskit import QuantumCircuit, transpile
from qiskit_aer import AerSimulator

from eal.sources.base import RawBatch, Source
from eal.sources import noise


def memory_to_bits(memory: list[str], n_qubits: int) -> np.ndarray:
    """Converte a memória do Aer em bits; posição i de cada shot = qubit lógico i.

    O Qiskit escreve cada string com o bit clássico 0 mais à direita,
    então cada linha é invertida.
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
    """Simulador de QPU, com ou sem ruído de um backend simulado."""

    source_id = "qpu_sim"
    source_type = "qpu_sim"
    is_local = True
    is_simulated = True

    def __init__(self, n_qubits: int = 20, seed: int = 12345,
                 noise_backend: str | None = None,
                 physical_qubits: list[int] | None = None) -> None:
        if n_qubits <= 0:
            raise ValueError("n_qubits deve ser positivo")
        self.n_qubits = n_qubits
        self.seed = seed
        self.noise_backend = noise_backend
        self.physical_qubits = list(physical_qubits or range(n_qubits))
        if len(self.physical_qubits) != n_qubits:
            raise ValueError("physical_qubits deve ter n_qubits elementos")
        self.source_version = (
            f"qpu_sim-0.2.0/qiskit-{qiskit.__version__}/aer-{qiskit_aer.__version__}"
        )
        self._setup()

    def _setup(self) -> None:
        if self.noise_backend is None:
            self._sim = AerSimulator(seed_simulator=self.seed)
            self._circuits = [hadamard_circuit(self.n_qubits)]
            self._calibration = None
            return
        backend = noise.load_fake_backend(self.noise_backend)
        model = noise.build_noise_model(backend, self.physical_qubits)
        self._sim = AerSimulator(noise_model=model, method="density_matrix",
                                 seed_simulator=self.seed)
        one = hadamard_circuit(1)
        self._circuits = [
            transpile(one, backend, initial_layout=[q], optimization_level=0,
                      seed_transpiler=self.seed)
            for q in self.physical_qubits
        ]
        self._calibration = noise.calibration_date(backend)

    def _run(self, shots: int) -> np.ndarray:
        """Executa e devolve matriz shots x n_qubits (coluna i = physical_qubits[i])."""
        result = self._sim.run(self._circuits, shots=shots, memory=True).result()
        if self.noise_backend is None:
            return memory_to_bits(result.get_memory(0), self.n_qubits).reshape(shots, -1)
        cols = [memory_to_bits(result.get_memory(i), 1) for i in range(self.n_qubits)]
        return np.stack(cols, axis=1)

    def read(self, n_bits: int) -> RawBatch:
        """Retorna n_bits bits; descarta o excesso do último shot."""
        n_bits = self.validate_n_bits(n_bits)
        shots = -(-n_bits // self.n_qubits)  # teto
        bits = self._run(shots).reshape(-1)[:n_bits].copy()
        params = {
            "backend": "AerSimulator", "n_qubits": self.n_qubits, "shots": shots,
            "seed": self.seed, "noise_model": self.noise_backend or "none",
            "calibration_date": self._calibration,
            "physical_qubits": self.physical_qubits,
            "readout_error": "asymmetric" if self.noise_backend else "none",
            "simulation": "per_qubit_density_matrix" if self.noise_backend else "ideal",
            "bit_order": "shot-major; posicao i do shot = physical_qubits[i]",
            "discarded_bits": shots * self.n_qubits - n_bits,
        }
        return self._build_batch(bits, params)
