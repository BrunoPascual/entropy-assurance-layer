"""Fontes defeituosas de propósito, para provar que os testes de saúde funcionam.

Cada uma simula uma falha conhecida, com intensidade controlada. Todas são
locais e simuladas (is_simulated=True): nunca entram numa chave real.
É o ÚNICO módulo do projeto onde o `random` do Python é permitido
(regra 5 da seção 12 do PROJECT.md). Toda semente fica registrada em params.
"""
from __future__ import annotations

import random

import numpy as np

from eal.sources.base import RawBatch, Source


class _FaultySource(Source):
    """Base comum: local, simulada, com gerador de semente fixa."""

    source_type = "faulty"
    is_local = True
    is_simulated = True

    def __init__(self, seed: int = 2026) -> None:
        self.seed = seed
        self._rng = np.random.default_rng(seed)

    def _random_bits(self, n_bits: int) -> np.ndarray:
        return self._rng.integers(0, 2, size=n_bits, dtype=np.uint8)


class BiasedSource(_FaultySource):
    """Cada bit vale 1 com probabilidade p (em vez de 0,5)."""

    source_id = "faulty_biased"

    def __init__(self, p: float = 0.55, seed: int = 2026) -> None:
        if not 0.0 < p < 1.0:
            raise ValueError("p deve estar entre 0 e 1")
        super().__init__(seed)
        self.p = p

    def read(self, n_bits: int) -> RawBatch:
        """Bits independentes com P(1) = p."""
        n_bits = self.validate_n_bits(n_bits)
        bits = (self._rng.random(n_bits) < self.p).astype(np.uint8)
        return self._build_batch(bits, {"fault": "biased", "p": self.p, "seed": self.seed})


class StuckSource(_FaultySource):
    """Bits bons, mas em cada janela de `every` bits um trecho fica travado."""

    source_id = "faulty_stuck"

    def __init__(self, run_length: int = 64, every: int = 1024, seed: int = 2026) -> None:
        if run_length <= 0 or every < run_length:
            raise ValueError("exige 0 < run_length <= every")
        super().__init__(seed)
        self.run_length = run_length
        self.every = every

    def read(self, n_bits: int) -> RawBatch:
        """Insere um trecho de run_length bits iguais em cada janela."""
        n_bits = self.validate_n_bits(n_bits)
        bits = self._random_bits(n_bits)
        for start in range(0, n_bits - self.run_length + 1, self.every):
            span = min(self.every, n_bits - start) - self.run_length
            offset = start + int(self._rng.integers(0, span + 1))
            bits[offset:offset + self.run_length] = self._rng.integers(0, 2)
        params = {"fault": "stuck", "run_length": self.run_length,
                  "every": self.every, "seed": self.seed}
        return self._build_batch(bits, params)


class ReplaySource(_FaultySource):
    """Devolve de novo um lote já entregue (replay exato)."""

    source_id = "faulty_replay"

    def __init__(self, seed: int = 2026) -> None:
        super().__init__(seed)
        self._stored: np.ndarray | None = None

    def read(self, n_bits: int) -> RawBatch:
        """1ª leitura (ou pedido maior que o guardado): bits novos, que ficam
        guardados. Depois: repete os primeiros n_bits do lote guardado."""
        n_bits = self.validate_n_bits(n_bits)
        replayed = self._stored is not None and self._stored.size >= n_bits
        if not replayed:
            self._stored = self._random_bits(n_bits)
        bits = self._stored[:n_bits].copy()
        return self._build_batch(bits, {"fault": "replay", "replayed": replayed,
                                        "seed": self.seed})


class PrngSource(_FaultySource):
    """Mersenne Twister (random do Python) com semente fixa, disfarçado de QPU.

    Os testes de saída NÃO devem reprová-lo: é a limitação T4 do modelo de ameaça.
    """

    source_id = "faulty_prng"

    def __init__(self, seed: int = 2026) -> None:
        super().__init__(seed)
        self._mt = random.Random(seed)

    def read(self, n_bits: int) -> RawBatch:
        """Bits do Mersenne Twister, na ordem em que getrandbits os produz."""
        n_bits = self.validate_n_bits(n_bits)
        n_bytes = (n_bits + 7) // 8
        raw = self._mt.getrandbits(n_bytes * 8).to_bytes(n_bytes, "big")
        bits = np.unpackbits(np.frombuffer(raw, dtype=np.uint8))[:n_bits].copy()
        params = {"fault": "prng", "generator": "MT19937 (random.Random)",
                  "disguised_as": "qpu", "seed": self.seed}
        return self._build_batch(bits, params)


class CorrelatedSource(_FaultySource):
    """Cada bit repete o anterior com probabilidade rho (e troca com 1 - rho)."""

    source_id = "faulty_correlated"

    def __init__(self, rho: float = 0.6, seed: int = 2026) -> None:
        if not 0.0 <= rho < 1.0:
            raise ValueError("rho deve estar em [0, 1)")
        super().__init__(seed)
        self.rho = rho

    def read(self, n_bits: int) -> RawBatch:
        """Cadeia de Markov binária: bit[i] = bit[i-1] XOR troca[i]."""
        n_bits = self.validate_n_bits(n_bits)
        flips = (self._rng.random(n_bits) >= self.rho).astype(np.int64)
        flips[0] = int(self._rng.integers(0, 2))  # primeiro bit: aleatório
        bits = (np.cumsum(flips) % 2).astype(np.uint8)
        return self._build_batch(bits, {"fault": "correlated", "rho": self.rho,
                                        "seed": self.seed})


FAULTY_SOURCES: dict[str, type[_FaultySource]] = {
    cls.source_id: cls
    for cls in (BiasedSource, StuckSource, ReplaySource, PrngSource, CorrelatedSource)
}
