"""Ferramentas de teste reutilizáveis.

Todo teste de fonte nova (os, qpu_sim, qpu_ibm, faulty_*) deve chamar
assert_source_contract(), para provar que a fonte cumpre o contrato.
"""

from __future__ import annotations

import numpy as np

from eal.sources.base import SOURCE_TYPES, RawBatch, Source


def assert_source_contract(source: Source, n_bits: int = 1024) -> RawBatch:
    """Verifica que a fonte cumpre o contrato e devolve o lote lido."""
    assert isinstance(source.source_id, str) and source.source_id, "source_id ausente"
    assert source.source_type in SOURCE_TYPES, f"source_type inválido: {source.source_type!r}"
    assert isinstance(source.is_local, bool), "is_local deve ser bool"
    assert isinstance(source.is_simulated, bool), "is_simulated deve ser bool"
    assert isinstance(source.source_version, str) and source.source_version

    batch = source.read(n_bits)

    assert isinstance(batch, RawBatch), "read() deve devolver um RawBatch"
    assert batch.n_bits == n_bits, f"pediu {n_bits} bits, veio {batch.n_bits}"
    assert batch.bits.dtype == np.uint8
    assert set(np.unique(batch.bits).tolist()) <= {0, 1}, "bits fora de {0, 1}"
    assert batch.source_id == source.source_id
    assert batch.source_type == source.source_type
    assert batch.source_version == source.source_version
    assert batch.is_local == source.is_local
    assert batch.is_simulated == source.is_simulated
    assert len(batch.batch_hash) == 64
    return batch
