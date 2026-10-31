"""Histórico do detector de replay entre execuções (Dia 6, achado F12; ameaça T3).

O ReplayDetector guarda só hashes de lote e de bloco (nunca bits). Este módulo grava esse
estado num arquivo JSON e o restaura na execução seguinte, para que um lote antigo devolvido
depois seja visto como replay.

Formato: {"schema", "state", "state_hash"}. O state_hash é o SHA3-256 do JSON canônico do
estado e detecta corrupção acidental, não adulteração: quem tem acesso ao disco pode refazer
o arquivo ou apagá-lo (limitação declarada, ver THREAT_MODEL N14).

Fail-closed: arquivo ausente vale como histórico vazio (primeira execução). Qualquer outro
problema (ilegível, corrompido, de outro tamanho de bloco, grande demais) levanta
ReplayHistoryError, e quem chama não deve seguir. Nada é apagado nem reparado sozinho.
A gravação é atômica: arquivo temporário, fsync e os.replace.

Limites declarados: sem trava para duas execuções ao mesmo tempo (a última gravação vence);
o arquivo cresce a cada lote até REPLAY_HISTORY_MAX_BYTES; apagar o arquivo zera a proteção.
As mensagens de erro não citam o conteúdo do arquivo nem o caminho.
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import os
from pathlib import Path
from typing import Any

from eal.config import REPLAY_BLOCK_BITS, REPLAY_HISTORY_MAX_BYTES, REPLAY_HISTORY_SCHEMA
from eal.health.replay import ReplayDetector

_DOC_FIELDS = frozenset({"schema", "state", "state_hash"})


class ReplayHistoryError(Exception):
    """O histórico de replay não pôde ser lido ou gravado com segurança."""


def _canonical(obj: Any) -> bytes:
    """JSON canônico em UTF-8: chaves ordenadas, sem espaços, sem NaN."""
    text = json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return text.encode("utf-8")


def _no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    keys = [k for k, _ in pairs]
    if len(set(keys)) != len(keys):
        raise ValueError("chave repetida")
    return dict(pairs)


def _no_constant(name: str) -> Any:
    raise ValueError("constante não permitida")


def _parse(raw: bytes) -> Any:
    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=_no_duplicates, parse_constant=_no_constant)
    except (UnicodeDecodeError, ValueError, RecursionError):
        raise ReplayHistoryError("histórico de replay corrompido") from None


def load_detector(path: Path, block_bits: int = REPLAY_BLOCK_BITS) -> ReplayDetector:
    """Detector restaurado de `path`; vazio se o arquivo não existe; ReplayHistoryError se ruim."""
    try:
        if not path.exists():
            return ReplayDetector(block_bits)
        if not path.is_file():
            raise ReplayHistoryError("histórico de replay não é um arquivo")
        if path.stat().st_size > REPLAY_HISTORY_MAX_BYTES:
            raise ReplayHistoryError("histórico de replay maior que o limite de tamanho")
        raw = path.read_bytes()
    except OSError:
        raise ReplayHistoryError("histórico de replay ilegível") from None
    doc = _parse(raw)
    if not (isinstance(doc, dict) and doc.keys() == _DOC_FIELDS
            and doc["schema"] == REPLAY_HISTORY_SCHEMA and isinstance(doc["state_hash"], str)):
        raise ReplayHistoryError("histórico de replay com formato desconhecido")
    try:
        expected = hashlib.sha3_256(_canonical(doc["state"])).hexdigest()
    except (TypeError, ValueError):
        raise ReplayHistoryError("histórico de replay corrompido") from None
    if doc["state_hash"] != expected:
        raise ReplayHistoryError("histórico de replay corrompido (a conferência do hash falhou)")
    try:
        detector = ReplayDetector.from_state(doc["state"])
    except (TypeError, ValueError):
        raise ReplayHistoryError("histórico de replay com estado inválido") from None
    if detector.block_bits != block_bits:
        raise ReplayHistoryError("histórico de replay feito com outro tamanho de bloco")
    return detector


def save_detector(detector: ReplayDetector, path: Path) -> None:
    """Grava o estado de forma atômica. ReplayHistoryError se não couber ou não gravar."""
    state = detector.to_state()
    doc = {"schema": REPLAY_HISTORY_SCHEMA, "state": state,
           "state_hash": hashlib.sha3_256(_canonical(state)).hexdigest()}
    data = _canonical(doc) + b"\n"
    if len(data) > REPLAY_HISTORY_MAX_BYTES:
        raise ReplayHistoryError("histórico de replay passou do limite de tamanho; arquive-o à mão")
    tmp = path.with_name(path.name + ".tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(tmp, "wb") as fh:  # binário: o Windows não troca \n por \r\n
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except OSError:
        with contextlib.suppress(OSError):
            tmp.unlink()
        raise ReplayHistoryError("histórico de replay não pôde ser gravado") from None
