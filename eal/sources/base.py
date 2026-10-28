"""Contrato das fontes de bits e o lote cru (RawBatch).

O resto do sistema (testes de saúde, extrator, mixer, recibo) só conhece
este contrato. Assim, a fonte do sistema operacional, o simulador, a QPU real
e, no futuro, um chip QRNG entram todos pelo mesmo caminho.
"""

from __future__ import annotations

import hashlib
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import cached_property
from typing import Any

import numpy as np

SOURCE_TYPES: tuple[str, ...] = ("os", "qpu_sim", "qpu_ibm", "faulty")


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass(frozen=True)
class RawBatch:
    """Um lote de bits crus (0 ou 1, um por posição) com seus metadados.

    O lote é imutável: os bits são copiados e marcados como somente leitura.
    """

    source_id: str
    source_type: str
    source_version: str
    is_local: bool
    is_simulated: bool
    bits: np.ndarray
    params: dict[str, Any] = field(default_factory=dict)
    batch_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    created_at: str = field(default_factory=_utc_now_iso)

    def __post_init__(self) -> None:
        if not self.source_id:
            raise ValueError("source_id não pode ser vazio")
        if self.source_type not in SOURCE_TYPES:
            raise ValueError(
                f"source_type inválido: {self.source_type!r}. Use um de {SOURCE_TYPES}"
            )
        if not isinstance(self.bits, np.ndarray):
            raise ValueError("bits deve ser um numpy.ndarray")
        if self.bits.ndim != 1:
            raise ValueError("bits deve ter uma dimensão só")
        if self.bits.dtype != np.uint8:
            raise ValueError(f"bits deve ser uint8, recebeu {self.bits.dtype}")
        if self.bits.size == 0:
            raise ValueError("bits não pode ser vazio")
        if int(self.bits.max()) > 1:
            raise ValueError("bits só pode conter 0 e 1")
        frozen_bits = self.bits.copy()
        frozen_bits.setflags(write=False)
        object.__setattr__(self, "bits", frozen_bits)

    @property
    def n_bits(self) -> int:
        return int(self.bits.size)

    @cached_property
    def batch_hash(self) -> str:
        """SHA3-256 dos bits empacotados, incluindo a quantidade de bits.

        Serve para detectar replay (o mesmo lote reaparecendo).
        """
        packed = np.packbits(self.bits).tobytes()
        return hashlib.sha3_256(self.n_bits.to_bytes(8, "big") + packed).hexdigest()


class Source(ABC):
    """Contrato de toda fonte de bits.

    Cada subclasse define os quatro atributos e implementa read().
    """

    source_id: str       # ex.: "os", "qpu_sim", "ibm_kingston", "faulty_biased"
    source_type: str     # um de SOURCE_TYPES
    is_local: bool       # True se os bits nunca saíram desta máquina
    is_simulated: bool   # True para simulador e fontes defeituosas
    source_version: str = "0.1.0"

    @abstractmethod
    def read(self, n_bits: int) -> RawBatch:
        """Retorna exatamente n_bits bits crus, com metadados."""

    @staticmethod
    def validate_n_bits(n_bits: int) -> int:
        """Garante que n_bits é um inteiro positivo. Use no começo de read()."""
        if isinstance(n_bits, bool) or not isinstance(n_bits, (int, np.integer)):
            raise ValueError(f"n_bits deve ser inteiro, recebeu {type(n_bits).__name__}")
        if n_bits <= 0:
            raise ValueError(f"n_bits deve ser positivo, recebeu {n_bits}")
        return int(n_bits)

    def _build_batch(
        self, bits: np.ndarray, params: dict[str, Any] | None = None
    ) -> RawBatch:
        """Monta o RawBatch copiando os metadados da fonte. Use no fim de read()."""
        return RawBatch(
            source_id=self.source_id,
            source_type=self.source_type,
            source_version=self.source_version,
            is_local=self.is_local,
            is_simulated=self.is_simulated,
            bits=bits,
            params=dict(params or {}),
        )
