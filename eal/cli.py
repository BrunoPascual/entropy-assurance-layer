"""Linha de comando da EAL (Dia 5, etapa 4): init-issuer, run e verify.

  py -3.12 -m eal init-issuer          cria o par ML-DSA-65 do emissor (uma vez)
  py -3.12 -m eal run                  pipeline keygen, chaves, recibo assinado no log encadeado
  py -3.12 -m eal verify <arquivo>     confere recibo, cadeia e (opcional) a cabeça esperada

Códigos de saída: 0 ok; 1 falha esperada (fail-closed, recusa, recibo reprovado);
2 erro de uso. Nada secreto vai ao stdout, ao stderr nem ao log: as mensagens trazem
nomes de fonte, estados, contagens e nomes de classe de exceção, nunca o texto delas.
Protótipo de pesquisa; ver THREAT_MODEL.md para o que isto não garante.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from eal.config import DEFAULT_N_BITS, GENESIS_PREV_HASH, ISSUER_PK_NAME, ISSUER_SK_NAME, RECEIPT_CHAIN_NAME
from eal.pipeline import run_pipeline
from eal.pqc.keygen import derive_keys_from_mix
from eal.receipt.builder import build_receipt_body, issuer_seed_from_mix
from eal.receipt.chain import ChainError, append_receipt, chain_head, verify_chain
from eal.receipt.schema import canonical_bytes, receipt_hash
from eal.receipt.sign import (
    issuer_key_from_seed,
    load_issuer_key,
    load_issuer_public_key,
    save_issuer_key,
    sign_receipt,
)
from eal.receipt.verify import parse_receipt_json, verify_receipt_text
from eal.sources.os_source import OsSource

KEYS_DIR = Path("keys")
RECEIPTS_DIR = Path("data/receipts")
PUBLIC_KEYS_DIR = Path("data/public_keys")
LOGS_DIR = Path("data/logs")
RUN_LOG_NAME = "eal_runs.jsonl"
PUBLIC_KEM_NAME = "ml_kem_768.ek.hex"
PUBLIC_DSA_NAME = "ml_dsa_65.pk.hex"
_LOGGED_COMMANDS = ("init-issuer", "run")


class _Fail(Exception):
    """Falha esperada de um comando: mensagem fixa (sem conteúdo de recibo ou de exceção)."""

    def __init__(self, stage: str, message: str, pipeline: dict | None = None) -> None:
        super().__init__(message)
        self.stage, self.message, self.pipeline = stage, message, pipeline


# ---------------------------------------------------------------- saída e log

def _out(text: str) -> None:
    sys.stdout.write(text + "\n")


def _err(text: str) -> None:
    sys.stderr.write(text + "\n")


def _configure_streams() -> None:
    """Console do Windows (ibm850) não escreve tudo: troca o que não couber em vez de quebrar."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(errors="replace")
            except (OSError, ValueError):
                pass


def _log_failure(logs_dir: Path, command: str, fail: _Fail) -> None:
    """Uma linha por falha em <logs_dir>/eal_runs.jsonl (T14). Falha ao logar só avisa."""
    record = {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"), "command": command,
              "stage": fail.stage, "ok": False, "reason": fail.message, "pipeline": fail.pipeline}
    try:
        try:
            line = json.dumps(record, ensure_ascii=False, sort_keys=True, allow_nan=False)
        except (TypeError, ValueError):
            line = json.dumps({**record, "pipeline": None}, ensure_ascii=False, sort_keys=True)
        logs_dir.mkdir(parents=True, exist_ok=True)
        with open(logs_dir / RUN_LOG_NAME, "ab") as fh:
            fh.write(line.encode("utf-8") + b"\n")
    except OSError:
        _err("aviso: não foi possível gravar o log de falhas")


# ---------------------------------------------------------------- argumentos

def _bits_arg(value: str) -> int:
    try:
        bits = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError("--bits deve ser um inteiro positivo") from None
    if bits <= 0:
        raise argparse.ArgumentTypeError("--bits deve ser um inteiro positivo")
    return bits


def _sources_arg(value: str) -> str:
    names = [n.strip() for n in value.split(",") if n.strip()]
    if names == ["os"]:
        return "os"
    if any(n.startswith(("qpu_sim", "faulty")) for n in names):
        raise argparse.ArgumentTypeError(
            "fonte simulada ou defeituosa não gera chaves (modo keygen); use --sources os")
    if any(n.startswith(("ibm", "qpu_ibm")) for n in names):
        raise argparse.ArgumentTypeError("a fonte da IBM ainda não existe nesta versão (Dia 6); use --sources os")
    raise argparse.ArgumentTypeError("fonte desconhecida; use --sources os")


def _add_dir(parser: argparse.ArgumentParser, flag: str, default: Path, what: str) -> None:
    parser.add_argument(flag, type=Path, default=default, help=f"{what} (padrão: {default})")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="eal", description="Entropy Assurance Layer: protótipo de pesquisa.")
    sub = parser.add_subparsers(dest="command", required=True, metavar="comando")
    init = sub.add_parser("init-issuer", help="cria o par ML-DSA-65 do emissor de recibos (uma vez)")
    init.add_argument("--bits", type=_bits_arg, default=DEFAULT_N_BITS, help="bits lidos da fonte")
    _add_dir(init, "--keys-dir", KEYS_DIR, "pasta da chave do emissor")
    _add_dir(init, "--logs-dir", LOGS_DIR, "pasta do log de falhas")
    run = sub.add_parser("run", help="pipeline keygen: chaves derivadas e recibo assinado")
    run.add_argument("--sources", type=_sources_arg, default="os", help="só 'os' nesta versão")
    run.add_argument("--bits", type=_bits_arg, default=DEFAULT_N_BITS, help="bits lidos da fonte")
    _add_dir(run, "--keys-dir", KEYS_DIR, "pasta da chave do emissor")
    _add_dir(run, "--receipts-dir", RECEIPTS_DIR, "pasta do log encadeado")
    _add_dir(run, "--public-keys-dir", PUBLIC_KEYS_DIR, "pasta das chaves públicas derivadas")
    _add_dir(run, "--logs-dir", LOGS_DIR, "pasta do log de falhas")
    ver = sub.add_parser("verify", help="verifica um recibo e a cadeia")
    ver.add_argument("file", type=Path, help="arquivo do recibo (<receipt_id>.json)")
    _add_dir(ver, "--keys-dir", KEYS_DIR, "pasta da chave pública do emissor")
    ver.add_argument("--chain-dir", type=Path, default=None, help="pasta do chain.jsonl (padrão: a do arquivo)")
    ver.add_argument("--sem-cadeia", action="store_true", help="não confere a cadeia (avisa na saída)")
    ver.add_argument("--expected-head", default=None, help="hash da cabeça da cadeia guardado fora do log")
    return parser


# ---------------------------------------------------------------- pipeline keygen

def _outcome_lines(result: Any) -> list[str]:
    return [f"  fonte {getattr(o, 'source_id', '?')}: {getattr(o, 'status', '?')}" for o in result.outcomes]


def _run_keygen(sources: Sequence[Any] | None, seed_source: Any, n_bits: int) -> tuple[Any, list[Any]]:
    """Roda o pipeline em modo keygen UMA vez. Sem semente: fail-closed (nunca repete sozinho)."""
    srcs = list(sources) if sources is not None else [OsSource()]
    seed = seed_source if seed_source is not None else OsSource()
    result = run_pipeline(srcs, seed, mode="keygen", n_bits=n_bits)
    if result.mix is None:
        ids = ", ".join(str(getattr(s, "source_id", "?")) for s in srcs)
        lines = ["nenhuma semente foi gerada (fail-closed)", f"  fontes consultadas: {ids}",
                 *_outcome_lines(result), f"  política: {result.error}",
                 "  rodar de novo é legítimo; o comando não repete sozinho."]
        raise _Fail("pipeline", "\n".join(lines), pipeline=result.to_dict())
    return result, srcs


# ---------------------------------------------------------------- init-issuer

def _cmd_init_issuer(args: argparse.Namespace, sources: Any, seed_source: Any) -> int:
    sk, pk = args.keys_dir / ISSUER_SK_NAME, args.keys_dir / ISSUER_PK_NAME
    if sk.exists() or pk.exists():
        raise _Fail("issuer_key", "a chave do emissor já existe; não vou sobrescrever")
    result, _ = _run_keygen(sources, seed_source, args.bits)
    key = issuer_key_from_seed(issuer_seed_from_mix(result.mix))
    args.keys_dir.mkdir(parents=True, exist_ok=True)
    save_issuer_key(key, args.keys_dir)
    _out("chave do emissor criada")
    _out(f"pk_hash: {key.pk_hash}")
    _out(f"chave pública: {pk}")
    _out(f"chave privada: {sk} (não vai para o Git)")
    return 0


# ---------------------------------------------------------------- run

def _load_issuer(keys_dir: Path) -> Any:
    sk, pk = keys_dir / ISSUER_SK_NAME, keys_dir / ISSUER_PK_NAME
    if not (sk.exists() and pk.exists()):
        raise _Fail("issuer_key", "chave do emissor não encontrada; rode 'py -3.12 -m eal init-issuer'")
    try:
        return load_issuer_key(sk, pk)
    except (OSError, ValueError):
        raise _Fail("issuer_key", "chave do emissor ilegível ou inconsistente") from None


def _write_public_keys(directory: Path, receipt_id: str, keys: Any) -> Path:
    """Grava SÓ as chaves públicas derivadas, em hex, em <directory>/<receipt_id>/ (nunca sobrescreve)."""
    folder = directory / receipt_id
    folder.mkdir(parents=True, exist_ok=False)
    for name, raw in ((PUBLIC_KEM_NAME, keys.kem_ek), (PUBLIC_DSA_NAME, keys.dsa_pk)):
        with open(folder / name, "xb") as fh:  # binário: o Windows não troca \n por \r\n
            fh.write(raw.hex().encode("ascii") + b"\n")
    return folder


def _current_head(receipts_dir: Path, issuer_pk: bytes) -> str:
    if not receipts_dir.exists():
        return GENESIS_PREV_HASH
    try:
        return chain_head(receipts_dir, issuer_pk)
    except ChainError as exc:
        raise _Fail("chain", str(exc)) from None


def _cmd_run(args: argparse.Namespace, sources: Any, seed_source: Any) -> int:
    issuer = _load_issuer(args.keys_dir)
    head = _current_head(args.receipts_dir, issuer.pk)  # antes do pipeline: log ruim não gasta entropia
    result, srcs = _run_keygen(sources, seed_source, args.bits)
    keys = derive_keys_from_mix(result.mix)
    body = build_receipt_body(result, keys, srcs, prev_receipt_hash=head)
    receipt = sign_receipt(body, issuer)
    try:
        path = append_receipt(receipt, issuer.pk, args.receipts_dir)
    except ChainError as exc:
        raise _Fail("chain", f"recibo recusado: {exc}") from None
    try:
        _write_public_keys(args.public_keys_dir, receipt["receipt_id"], keys)
    except OSError:
        raise _Fail("public_keys", f"recibo gravado em {path}, mas as chaves públicas não puderam ser gravadas") from None
    _out(f"recibo gravado: {path}")
    _out(f"receipt_id: {receipt['receipt_id']}")
    _out(f"semente (hash): {receipt['seed_hash']}")
    _out(f"chaves públicas (hash): ML-KEM-768 {receipt['keys']['ml_kem_768_pk_hash']}; "
         f"ML-DSA-65 {receipt['keys']['ml_dsa_65_pk_hash']}")
    _out("fontes:" + "".join(f" {getattr(o, 'source_id', '?')}={getattr(o, 'status', '?')}" for o in result.outcomes))
    _out(f"cabeça da cadeia: {receipt_hash(receipt)}")
    return 0


# ---------------------------------------------------------------- verify

def _position_in_chain(chain_dir: Path, receipt: dict) -> int | None:
    """Posição (1, 2, ...) do recibo no log, pelo CONTEÚDO canônico; None se não estiver."""
    try:
        data = (chain_dir / RECEIPT_CHAIN_NAME).read_bytes()
    except OSError:
        return None
    target = canonical_bytes(receipt)
    for n, line in enumerate(data.split(b"\n"), start=1):
        if line == target:
            return n
    return None


def _bullets(reasons: Sequence[str]) -> str:
    return "\n".join(f"  - {r}" for r in reasons)


def _load_public(keys_dir: Path) -> bytes:
    try:
        return load_issuer_public_key(keys_dir / ISSUER_PK_NAME)
    except (OSError, ValueError):
        raise _Fail("verify", f"chave pública do emissor não encontrada ou inválida em {keys_dir}") from None


def _cmd_verify(args: argparse.Namespace) -> int:
    pk = _load_public(args.keys_dir)
    try:
        text = args.file.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise _Fail("verify", f"arquivo não encontrado: {args.file}") from None
    except (OSError, UnicodeDecodeError):
        raise _Fail("verify", "arquivo ilegível") from None
    verdict = verify_receipt_text(text, pk)
    if not verdict.ok:
        raise _Fail("verify", f"recibo reprovado ({len(verdict.reasons)} problema(s)):\n{_bullets(verdict.reasons)}")
    receipt = parse_receipt_json(text)
    lines = [f"recibo válido: {receipt['receipt_id']}"]
    if args.sem_cadeia:
        lines.append("AVISO: cadeia não conferida (--sem-cadeia); só a assinatura e o formato foram verificados")
    else:
        chain_dir = args.chain_dir or args.file.parent
        if not (chain_dir / RECEIPT_CHAIN_NAME).exists():
            raise _Fail("verify", f"não há {RECEIPT_CHAIN_NAME} em {chain_dir}; use --chain-dir ou --sem-cadeia")
        res = verify_chain(chain_dir, pk, expected_head=args.expected_head)
        if not res.ok:
            raise _Fail("verify", f"cadeia reprovada ({len(res.reasons)} problema(s)):\n{_bullets(res.reasons)}")
        position = _position_in_chain(chain_dir, receipt)
        if position is None:
            raise _Fail("verify", "recibo não está na cadeia")
        lines.append(f"cadeia: posição {position} de {res.length}")
        if args.expected_head is not None:
            lines.append("cabeça conferida")
    for line in lines:
        _out(line)
    return 0


# ---------------------------------------------------------------- main

def main(
    argv: Sequence[str] | None = None,
    *,
    _sources: Sequence[Any] | None = None,
    _seed_source: Any = None,
) -> int:
    """Ponto de entrada. `_sources` e `_seed_source` existem só para os testes."""
    _configure_streams()
    try:
        args = _build_parser().parse_args(argv)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else (0 if exc.code is None else 2)
    logs_dir = getattr(args, "logs_dir", LOGS_DIR)
    try:
        if args.command == "init-issuer":
            return _cmd_init_issuer(args, _sources, _seed_source)
        if args.command == "run":
            return _cmd_run(args, _sources, _seed_source)
        return _cmd_verify(args)
    except _Fail as fail:
        _err(fail.message)
        if args.command in _LOGGED_COMMANDS:
            _log_failure(logs_dir, args.command, fail)
        return 1
    except Exception as exc:  # noqa: BLE001  (só o nome da classe: a mensagem pode ter segredo)
        message = f"erro inesperado ({type(exc).__name__})"
        _err(message)
        if args.command in _LOGGED_COMMANDS:
            _log_failure(logs_dir, args.command, _Fail("unexpected", message))
        return 1
