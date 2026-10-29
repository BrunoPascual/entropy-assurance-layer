"""Detecção de replay de lote e de blocos (PROJECT.md 6.4; ameaça T3).

Complementar ao SP 800-90B (não faz parte dele). O detector guarda, só em
memória e só durante a execução, o hash de cada lote e o hash de cada bloco
completo de 4096 bits. Um lote falha se:
  - o hash do lote já foi visto; ou
  - algum bloco de 4096 bits já apareceu em outro lote (qualquer fonte); ou
  - algum bloco se repete dentro do próprio lote.

Os hashes dos blocos são calculados a partir dos BITS, nunca do batch_hash
informado: um replay não escapa informando um hash diferente. Um replay que
devolve só o começo de um lote antigo (prefixo) muda o hash do lote, mas os
blocos coincidem, por isso a comparação por bloco existe.

Limitações declaradas (testadas, não escondidas):
  - replay transformado (um bit alterado em cada bloco) não é detectado;
  - replay deslocado para um ponto que não é múltiplo de 4096 bits não é detectado;
  - replay menor que um bloco só é detectado se o lote inteiro for idêntico;
  - o estado não persiste entre execuções.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass

import numpy as np

from eal.config import REPLAY_BLOCK_BITS


@dataclass(frozen=True)
class ReplayResult:
    """Resultado da checagem de replay de um lote."""

    passed: bool
    history_batches: int          # lotes já vistos antes deste (0 = primeiro lote)
    batch_repeated: bool
    repeated_batch_of: str | None  # batch_id do lote idêntico visto antes
    n_blocks: int                  # blocos completos comparados
    n_repeated_blocks: int         # blocos já vistos em lotes anteriores
    n_duplicate_blocks_within: int  # blocos repetidos dentro do próprio lote
    first_match: str | None        # descrição do primeiro bloco repetido
    discarded_bits: int            # bits finais fora de bloco completo
    block_bits: int


def _validate_bits(bits: np.ndarray) -> None:
    """Exige array 1-D uint8, não vazio, só com 0 e 1."""
    if not isinstance(bits, np.ndarray):
        raise TypeError("bits deve ser numpy.ndarray")
    if bits.dtype != np.uint8:
        raise TypeError(f"bits deve ser uint8, recebido {bits.dtype}")
    if bits.ndim != 1 or bits.size == 0:
        raise ValueError("bits deve ser 1-D e não vazio")
    if np.any(bits > 1):
        raise ValueError("bits deve conter só 0 e 1")


def block_digests(bits: np.ndarray, block_bits: int = REPLAY_BLOCK_BITS) -> list[bytes]:
    """SHA3-256 de cada bloco completo de `block_bits` bits, na ordem."""
    _validate_bits(bits)
    n_blocks = bits.size // block_bits
    if n_blocks == 0:
        return []
    blocks = bits[: n_blocks * block_bits].reshape(n_blocks, block_bits)
    packed = np.packbits(blocks, axis=1)
    return [hashlib.sha3_256(row.tobytes()).digest() for row in packed]


class ReplayDetector:
    """Guarda hashes em memória e checa cada lote novo. Uma instância por execução."""

    def __init__(self, block_bits: int = REPLAY_BLOCK_BITS) -> None:
        if isinstance(block_bits, bool) or not isinstance(block_bits, int):
            raise TypeError("block_bits deve ser int")
        if block_bits <= 0 or block_bits % 8 != 0:
            raise ValueError("block_bits deve ser positivo e múltiplo de 8")
        self._block_bits = block_bits
        self._batch_hashes: dict[str, str] = {}   # batch_hash -> batch_id
        self._blocks: dict[bytes, str] = {}       # digest -> "batch_id#índice"
        self._batch_ids: set[str] = set()

    @property
    def history_batches(self) -> int:
        """Quantos lotes já passaram por este detector."""
        return len(self._batch_ids)

    def check(self, bits: np.ndarray, *, batch_hash: str, batch_id: str) -> ReplayResult:
        """Checa o lote contra o histórico e depois o registra (mesmo se falhar).

        Cada lote deve ser checado uma vez: o mesmo batch_id duas vezes é erro,
        para que uma checagem repetida não vire um falso alarme de replay.
        """
        for name, value in (("batch_hash", batch_hash), ("batch_id", batch_id)):
            if not isinstance(value, str) or not value:
                raise TypeError(f"{name} deve ser str não vazia")
        if batch_id in self._batch_ids:
            raise ValueError(f"lote {batch_id} já foi checado por este detector")

        digests = block_digests(bits, self._block_bits)
        history = self.history_batches
        repeated_of = self._batch_hashes.get(batch_hash)

        n_prior = 0
        n_within = 0
        first_match: str | None = None
        seen_here: dict[bytes, int] = {}
        for i, d in enumerate(digests):
            if d in self._blocks:
                n_prior += 1
                if first_match is None:
                    first_match = f"bloco {i} igual a {self._blocks[d]}"
            elif d in seen_here:
                n_within += 1
                if first_match is None:
                    first_match = f"bloco {i} igual ao bloco {seen_here[d]} do próprio lote"
            seen_here.setdefault(d, i)

        # registra depois de checar; setdefault mantém a referência ao 1º lote
        for i, d in enumerate(digests):
            self._blocks.setdefault(d, f"{batch_id}#{i}")
        self._batch_hashes.setdefault(batch_hash, batch_id)
        self._batch_ids.add(batch_id)

        batch_repeated = repeated_of is not None
        return ReplayResult(
            passed=not batch_repeated and n_prior == 0 and n_within == 0,
            history_batches=history,
            batch_repeated=batch_repeated,
            repeated_batch_of=repeated_of,
            n_blocks=len(digests),
            n_repeated_blocks=n_prior,
            n_duplicate_blocks_within=n_within,
            first_match=first_match,
            discarded_bits=int(bits.size - len(digests) * self._block_bits),
            block_bits=self._block_bits,
        )
