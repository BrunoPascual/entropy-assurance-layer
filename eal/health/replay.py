"""Detecção de replay de lote e de blocos (PROJECT.md 6.4; ameaça T3).

Complementar ao SP 800-90B (não faz parte dele). O detector guarda o hash de cada lote e o hash de cada bloco
completo de 4096 bits (só hashes e ids, nunca bits). O estado pode ser salvo e
restaurado (to_state, from_state; ver replay_store.py). Um lote falha se:
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
  - o estado só persiste entre execuções se o chamador o salvar (replay_store.py);
    apagar ou trocar o arquivo salvo zera a proteção sem alarme.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any

import numpy as np

from eal.config import REPLAY_BLOCK_BITS

_STATE_FIELDS = frozenset({"block_bits", "batch_ids", "batch_hashes", "blocks"})
_HEX64 = re.compile(r"[0-9a-f]{64}")
_MAX_ID_CHARS = 128


def _valid_id(value: object) -> bool:
    return isinstance(value, str) and 0 < len(value) <= _MAX_ID_CHARS


def _valid_ref(value: object, ids: set[str]) -> bool:
    """Referência de bloco no formato "<batch_id>#<índice>", com batch_id conhecido."""
    if not isinstance(value, str):
        return False
    batch_id, sep, index = value.rpartition("#")
    return bool(sep) and batch_id in ids and index.isascii() and index.isdigit()


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
    """Guarda hashes e checa cada lote novo. O estado pode ser salvo e restaurado."""

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
    def block_bits(self) -> int:
        """Tamanho do bloco, em bits, usado nas comparações."""
        return self._block_bits

    @property
    def history_batches(self) -> int:
        """Quantos lotes já passaram por este detector."""
        return len(self._batch_ids)

    def to_state(self) -> dict[str, Any]:
        """Estado serializável: só hashes e ids de lote, nenhum bit."""
        return {
            "block_bits": self._block_bits,
            "batch_ids": sorted(self._batch_ids),
            "batch_hashes": dict(self._batch_hashes),
            "blocks": {digest.hex(): ref for digest, ref in self._blocks.items()},
        }

    @classmethod
    def from_state(cls, state: object) -> ReplayDetector:
        """Restaura o estado salvo. Estado malformado levanta ValueError; a mensagem cita só o campo."""
        if not isinstance(state, dict) or state.keys() != _STATE_FIELDS:
            raise ValueError("estado do detector: campos inesperados")
        block_bits = state["block_bits"]
        if isinstance(block_bits, bool) or not isinstance(block_bits, int):
            raise ValueError("estado do detector: block_bits inválido")
        detector = cls(block_bits)  # recusa tamanho não positivo ou que não seja múltiplo de 8
        ids = state["batch_ids"]
        if not (isinstance(ids, list) and all(_valid_id(x) for x in ids)) or len(set(ids)) != len(ids):
            raise ValueError("estado do detector: batch_ids inválido")
        known = set(ids)
        hashes = state["batch_hashes"]
        if not (isinstance(hashes, dict)
                and all(_valid_id(k) and isinstance(v, str) and v in known for k, v in hashes.items())):
            raise ValueError("estado do detector: batch_hashes inválido")
        raw_blocks = state["blocks"]
        if not isinstance(raw_blocks, dict):
            raise ValueError("estado do detector: blocks inválido")
        blocks: dict[bytes, str] = {}
        for hex_digest, ref in raw_blocks.items():
            if not (isinstance(hex_digest, str) and _HEX64.fullmatch(hex_digest) and _valid_ref(ref, known)):
                raise ValueError("estado do detector: blocks inválido")
            blocks[bytes.fromhex(hex_digest)] = ref
        detector._batch_ids = known
        detector._batch_hashes = dict(hashes)
        detector._blocks = blocks
        return detector

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
