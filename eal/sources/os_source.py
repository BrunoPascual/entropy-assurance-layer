"""Fonte de referência: aleatoriedade do sistema operacional."""
from __future__ import annotations

import secrets

import numpy as np

from eal.sources.base import RawBatch, Source


class OsSource(Source):
    """Bits de os.urandom (via secrets). Local e não simulada."""

    source_id = "os"
    source_type = "os"
    is_local = True
    is_simulated = False

    def read(self, n_bits: int) -> RawBatch:
        """Retorna n_bits bits do sistema operacional."""
        n_bits = self.validate_n_bits(n_bits)
        raw = np.frombuffer(secrets.token_bytes((n_bits + 7) // 8), dtype=np.uint8)
        bits = np.unpackbits(raw)[:n_bits].copy()
        return self._build_batch(bits, {"generator": "secrets.token_bytes"})
