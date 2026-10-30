"""Log encadeado dos recibos (Dia 5, etapa 3).

O log é ``<pasta>/chain.jsonl``: uma linha por recibo, cada linha é o JSON
canônico do recibo COMPLETO (com assinatura) seguido de ``\\n``. Cada recibo
também é gravado em ``<pasta>/<receipt_id>.json`` (mesmos bytes da linha).
O encadeamento usa ``receipt_hash`` (com assinatura): o ``prev_receipt_hash`` do
primeiro recibo é GENESIS_PREV_HASH e o dos seguintes é o hash do anterior.
Uma chave de emissor por cadeia. Fail-closed: log corrompido recusa gravações.

Limitações (ver PROJECT.md, seção 17): sem trava contra duas gravações
simultâneas; apagar o ÚLTIMO recibo só é detectável com ``expected_head``
guardado fora do log; quem tem acesso ao disco e à chave do emissor pode
refazer a cadeia inteira (N11). As mensagens de erro trazem só contagens e
números de linha, nunca o conteúdo do recibo.
"""
from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from pathlib import Path

from eal.config import DSA_PK_BYTES, GENESIS_PREV_HASH, RECEIPT_CHAIN_NAME
from eal.receipt.builder import receipt_id_for
from eal.receipt.schema import canonical_bytes, is_hex64, receipt_hash
from eal.receipt.verify import parse_receipt_json, verify_receipt


class ChainError(Exception):
    """Recusa de gravação ou leitura da cadeia. A mensagem não ecoa dados do recibo."""


@dataclass(frozen=True)
class ChainResult:
    """Resultado de verify_chain: ok só se não houver nenhum motivo."""

    ok: bool
    reasons: tuple[str, ...]
    length: int
    head: str


def _is_uuid(value: object) -> bool:
    try:
        return isinstance(value, str) and str(uuid.UUID(value)) == value
    except ValueError:
        return False


def _pk_ok(issuer_pk: object) -> bool:
    return isinstance(issuer_pk, bytes) and len(issuer_pk) == DSA_PK_BYTES


def _read_log(directory: Path) -> bytes | None:
    """Bytes do log (log ausente = vazio). None se não for possível ler."""
    log = directory / RECEIPT_CHAIN_NAME
    try:
        return log.read_bytes() if log.exists() else b""
    except OSError:
        return None


def _split_lines(data: bytes) -> list[bytes]:
    """Linhas do log. Uma última linha sem \\n também entra (será acusada à parte)."""
    if not data:
        return []
    parts = data.split(b"\n")
    return parts[:-1] if data.endswith(b"\n") else parts


def _parse_line(raw: bytes) -> dict | None:
    try:
        return parse_receipt_json(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None


def _check_line(n: int, raw: bytes, issuer_pk: bytes) -> tuple[dict | None, list[str]]:
    """Conferências de UMA linha, sem olhar as vizinhas. Devolve (recibo ou None, motivos)."""
    if raw == b"":
        return None, [f"linha {n}: vazia"]
    receipt = _parse_line(raw)
    if receipt is None:
        return None, [f"linha {n}: JSON inválido"]
    reasons: list[str] = []
    try:
        if canonical_bytes(receipt) != raw:
            reasons.append(f"linha {n}: não canônico")
    except (TypeError, ValueError):
        reasons.append(f"linha {n}: não canônico")
    verdict = verify_receipt(receipt, issuer_pk)
    if not verdict.ok:
        reasons.append(f"linha {n}: recibo inválido ({len(verdict.reasons)} problema(s))")
    return receipt, reasons


def _check_identity(n: int, receipt: dict, seen: set[str]) -> list[str]:
    """receipt_id único no log e igual ao uuid5 do seed_hash."""
    reasons: list[str] = []
    rid = receipt.get("receipt_id")
    if isinstance(rid, str):
        if rid in seen:
            reasons.append(f"linha {n}: receipt_id repetido")
        seen.add(rid)
    seed_hash = receipt.get("seed_hash")
    if not (is_hex64(seed_hash) and rid == receipt_id_for(seed_hash)):
        reasons.append(f"linha {n}: receipt_id não corresponde ao seed_hash")
    return reasons


def _scan(lines: list[bytes], issuer_pk: bytes) -> tuple[list[str], str, list[tuple[int, bytes, object]]]:
    """Percorre as linhas. Devolve (motivos, cabeça, [(nº da linha, bytes, receipt_id)])."""
    reasons: list[str] = []
    entries: list[tuple[int, bytes, object]] = []
    seen: set[str] = set()
    expected_prev: str | None = GENESIS_PREV_HASH
    head = GENESIS_PREV_HASH
    for n, raw in enumerate(lines, start=1):
        receipt, found = _check_line(n, raw, issuer_pk)
        reasons += found
        if receipt is None:
            expected_prev = None  # o elo seguinte não é verificável; a linha ruim já foi acusada
            continue
        reasons += _check_identity(n, receipt, seen)
        if expected_prev is not None and receipt.get("prev_receipt_hash") != expected_prev:
            reasons.append(f"linha {n}: elo quebrado (prev_receipt_hash não é o hash da linha anterior)")
        entries.append((n, raw, receipt.get("receipt_id")))
        try:
            head = expected_prev = receipt_hash(receipt)
        except (TypeError, ValueError):
            expected_prev = None
    return reasons, head, entries


def _check_files(directory: Path, entries: list[tuple[int, bytes, object]]) -> list[str]:
    """Confere o <id>.json de cada linha e procura arquivos .json sem linha."""
    reasons: list[str] = []
    ids: set[str] = set()
    for n, raw, rid in entries:
        if not _is_uuid(rid):
            continue
        ids.add(rid)
        path = directory / f"{rid}.json"
        try:
            if not path.is_file():
                reasons.append(f"linha {n}: arquivo individual ausente")
            elif path.read_bytes() != raw + b"\n":
                reasons.append(f"linha {n}: arquivo individual diferente da linha")
        except OSError:
            reasons.append(f"linha {n}: arquivo individual ilegível")
    try:
        strays = [p for p in directory.glob("*.json") if p.stem not in ids]
    except OSError:
        return reasons + ["não foi possível listar a pasta"]
    if strays:
        reasons.append(f"{len(strays)} arquivo(s) .json sem linha no log")
    return reasons


def verify_chain(
    directory: Path, issuer_pk: bytes, *, expected_head: str | None = None
) -> ChainResult:
    """Percorre o log e confere linhas, assinaturas, elos, ids e arquivos individuais."""
    directory = Path(directory)
    if not _pk_ok(issuer_pk):
        return ChainResult(False, ("chave pública do emissor inválida",), 0, GENESIS_PREV_HASH)
    if not directory.is_dir():
        return ChainResult(False, ("pasta do log não existe",), 0, GENESIS_PREV_HASH)
    data = _read_log(directory)
    if data is None:
        return ChainResult(False, ("não foi possível ler o log",), 0, GENESIS_PREV_HASH)
    lines = _split_lines(data)
    reasons, head, entries = _scan(lines, issuer_pk)
    if data and not data.endswith(b"\n"):
        reasons.append("última linha sem quebra de linha")
    reasons += _check_files(directory, entries)
    if expected_head is not None and not (is_hex64(expected_head) and expected_head == head):
        reasons.append("cabeça da cadeia diferente da esperada")
    return ChainResult(not reasons, tuple(reasons), len(lines), head)


def chain_head(directory: Path, issuer_pk: bytes) -> str:
    """Hash da última linha (ou GENESIS_PREV_HASH com o log vazio). Recusa log inválido."""
    res = verify_chain(directory, issuer_pk)
    if not res.ok:
        raise ChainError(f"cadeia existente inválida ({len(res.reasons)} problema(s))")
    return res.head


def _logged_ids(directory: Path) -> set[str]:
    data = _read_log(directory) or b""
    found = (_parse_line(raw) for raw in _split_lines(data))
    return {r["receipt_id"] for r in found if r and isinstance(r.get("receipt_id"), str)}


def _fsynced_write(path: Path, mode: str, data: bytes) -> None:
    with open(path, mode) as fh:
        fh.write(data)
        fh.flush()
        os.fsync(fh.fileno())


def _write_individual(path: Path, data: bytes) -> None:
    """Grava <receipt_id>.json em modo exclusivo ('x'), com fsync."""
    _fsynced_write(path, "xb", data)


def append_receipt(receipt: dict, issuer_pk: bytes, directory: Path) -> Path:
    """Acrescenta um recibo assinado ao log. Devolve o caminho de <receipt_id>.json.

    Recusa (ChainError) sem gravar nada se: a chave for inválida, o log existente
    estiver corrompido, o recibo for inválido, o prev não for a cabeça, o
    receipt_id não vier do seed_hash, estiver repetido, ou o arquivo já existir.
    """
    directory = Path(directory)
    if not _pk_ok(issuer_pk):
        raise ChainError("chave pública do emissor inválida")
    head, seen = GENESIS_PREV_HASH, set()
    if directory.exists():
        res = verify_chain(directory, issuer_pk)
        if not res.ok:
            raise ChainError(f"cadeia existente inválida ({len(res.reasons)} problema(s))")
        head, seen = res.head, _logged_ids(directory)
    verdict = verify_receipt(receipt, issuer_pk)
    if not verdict.ok:
        raise ChainError(f"recibo inválido ({len(verdict.reasons)} problema(s))")
    if receipt["prev_receipt_hash"] != head:
        raise ChainError("prev_receipt_hash não é o hash da cabeça da cadeia")
    rid = receipt["receipt_id"]
    if rid != receipt_id_for(receipt["seed_hash"]):
        raise ChainError("receipt_id não corresponde ao seed_hash")
    if rid in seen:
        raise ChainError("receipt_id repetido")
    path = directory / f"{rid}.json"
    if path.exists():
        raise ChainError("arquivo individual já existe")
    line = canonical_bytes(receipt) + b"\n"
    directory.mkdir(parents=True, exist_ok=True)
    _fsynced_write(directory / RECEIPT_CHAIN_NAME, "ab", line)
    try:
        _write_individual(path, line)
    except OSError:
        raise ChainError("linha gravada no log, mas o arquivo individual falhou") from None
    return path
