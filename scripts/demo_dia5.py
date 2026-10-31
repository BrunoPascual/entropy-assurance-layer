"""Demo ponta a ponta da EAL (Dia 5, etapa 5).

Roda a CLI de verdade (``py -3.12 -m eal``) numa pasta NOVA e descartável e
confere, passo a passo, o código de saída e o texto esperados. Nunca toca em
``keys/`` nem em ``data/`` do projeto: todos os comandos rodam com a pasta da
demo como diretório atual, e a pasta é recusada se existir ou se ficar dentro
do projeto.

Uso (a partir da raiz do projeto)::

    py -3.12 -m scripts.demo_dia5 [--pasta CAMINHO]

Códigos de saída: 0 demo ok; 1 algum passo falhou ou a demo foi abortada;
2 erro de uso (pasta recusada, opção inválida).

É um protótipo de pesquisa. A demo mostra que o fluxo funciona e que a
verificação reprova adulteração; não prova que a fonte de entropia é boa.
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from collections.abc import Callable, Sequence
from datetime import datetime, timezone
from pathlib import Path

MAX_RUN_ATTEMPTS = 3
STEP_COUNT = 9
CLI_TIMEOUT_SECONDS = 600
EXIT_OK = 0
EXIT_DEMO_FAILED = 1
EXIT_USAGE = 2

KEYS_REL = Path("keys")
RECEIPTS_REL = Path("data") / "receipts"
LOGS_REL = Path("data") / "logs"
RUN_LOG_NAME = "eal_runs.jsonl"
CHAIN_NAME = "chain.jsonl"
RETRY_STAGE = "pipeline"
TAMPER_OLD = b'"mode":"keygen"'
TAMPER_NEW = b'"mode":"keygex"'
WRONG_HEAD = "a" * 64
TAMPER_DIR = "tamper"
TRUNCATED_DIR = "truncated"
MAX_OUTPUT_LINES = 12
MAX_LINE_CHARS = 200
PROJECT_ROOT = Path(__file__).resolve().parents[1]


class DemoError(Exception):
    """Erro da demo (pasta recusada, arquivo inesperado, comando sem resposta)."""


@dataclasses.dataclass(frozen=True)
class CliResult:
    """Resultado de uma chamada da CLI."""

    code: int
    stdout: str
    stderr: str

    @property
    def text(self) -> str:
        """Saída padrão e de erro juntas."""
        return self.stdout + "\n" + self.stderr


@dataclasses.dataclass(frozen=True)
class StepResult:
    """Um passo da demo: o esperado, o obtido e o texto de apoio."""

    number: int
    title: str
    expected_code: int
    got_code: int
    ok: bool
    detail: str = ""
    output: tuple[str, ...] = ()


@dataclasses.dataclass(frozen=True)
class DemoReport:
    """Relatório da demo inteira."""

    steps: tuple[StepResult, ...]
    aborted: str | None = None

    @property
    def ok(self) -> bool:
        """True só se não abortou e os 9 passos bateram."""
        return (
            self.aborted is None
            and len(self.steps) == STEP_COUNT
            and all(step.ok for step in self.steps)
        )


Runner = Callable[[Sequence[str], Path], CliResult]


# ---------------------------------------------------------------- pasta

def _norm(path: Path) -> Path:
    return Path(os.path.normcase(str(Path(path).resolve())))


def _is_inside(child: Path, parent: Path) -> bool:
    c, p = _norm(child), _norm(parent)
    return c == p or p in c.parents


def check_demo_dir(demo_dir: Path, project_root: Path) -> Path:
    """Recusa pasta existente ou dentro do projeto; devolve o caminho resolvido."""
    demo_dir = Path(demo_dir)
    if demo_dir.exists():
        raise DemoError("a pasta da demo já existe; escolha um nome novo")
    if _is_inside(demo_dir, project_root):
        raise DemoError("a pasta da demo não pode ficar dentro do projeto")
    return demo_dir.resolve()


def default_demo_dir(now: datetime | None = None) -> Path:
    """Pasta padrão: uma subpasta nova do diretório temporário do sistema."""
    moment = now if now is not None else datetime.now(timezone.utc)
    return Path(tempfile.gettempdir()) / f"eal_demo_{moment.strftime('%Y%m%d_%H%M%S')}"


# ------------------------------------------------------------------ log

def read_log_lines(log_path: Path) -> list[bytes]:
    """Linhas não vazias do log de falhas (lista vazia se o arquivo não existe)."""
    try:
        data = Path(log_path).read_bytes()
    except FileNotFoundError:
        return []
    return [line for line in data.split(b"\n") if line]


def new_log_entries(lines_before: int, lines: list[bytes]) -> list[dict]:
    """Entradas do log acrescentadas depois de ``lines_before`` linhas."""
    entries: list[dict] = []
    for raw in lines[lines_before:]:
        try:
            obj = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            obj = {}
        entries.append(obj if isinstance(obj, dict) else {})
    return entries


def should_retry(
    code: int,
    entries: list[dict],
    command: str,
    attempt: int,
    max_attempts: int = MAX_RUN_ATTEMPTS,
) -> bool:
    """Repete só se: código 1, ainda há tentativas e UMA falha nova de pipeline."""
    if code != 1 or attempt >= max_attempts or len(entries) != 1:
        return False
    entry = entries[0]
    return (
        entry.get("command") == command
        and entry.get("stage") == RETRY_STAGE
        and entry.get("ok") is False
    )


# --------------------------------------------------------------- cadeia

def _chain_lines(chain_path: Path) -> list[bytes]:
    try:
        data = Path(chain_path).read_bytes()
    except OSError as exc:
        raise DemoError("não consegui ler o log da cadeia") from exc
    if not data:
        raise DemoError("o log da cadeia está vazio")
    if not data.endswith(b"\n"):
        raise DemoError("a última linha do log da cadeia não termina em quebra de linha")
    lines = data.split(b"\n")[:-1]
    if any(not line for line in lines):
        raise DemoError("o log da cadeia tem linha vazia")
    return lines


def chain_head_from_file(chain_path: Path) -> str:
    """Cabeça da cadeia: SHA3-256 da última linha (sem a quebra de linha)."""
    return hashlib.sha3_256(_chain_lines(chain_path)[-1]).hexdigest()


def receipt_ids(chain_path: Path) -> list[str]:
    """``receipt_id`` de cada linha do log, na ordem."""
    ids: list[str] = []
    for line in _chain_lines(chain_path):
        try:
            obj = json.loads(line.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            raise DemoError("linha do log da cadeia ilegível") from exc
        rid = obj.get("receipt_id") if isinstance(obj, dict) else None
        if not isinstance(rid, str):
            raise DemoError("linha do log da cadeia sem receipt_id")
        ids.append(rid)
    return ids


def tamper_copy(src: Path, dst: Path) -> None:
    """Grava em ``dst`` uma cópia de ``src`` com UM byte trocado (nunca sobrescreve)."""
    data = Path(src).read_bytes()
    if TAMPER_OLD not in data:
        raise DemoError("o recibo não tem o trecho esperado para adulterar")
    dst = Path(dst)
    if dst.exists():
        raise DemoError("a cópia adulterada já existe")
    dst.parent.mkdir(parents=True, exist_ok=True)
    with open(dst, "xb") as fh:
        fh.write(data.replace(TAMPER_OLD, TAMPER_NEW, 1))


def truncate_chain_copy(src_dir: Path, dst_dir: Path) -> tuple[str, str]:
    """Copia a cadeia SEM o último recibo; devolve (último mantido, removido)."""
    src, dst = Path(src_dir), Path(dst_dir)
    lines = _chain_lines(src / CHAIN_NAME)
    if len(lines) < 2:
        raise DemoError("a cadeia precisa de pelo menos 2 recibos")
    ids = receipt_ids(src / CHAIN_NAME)
    kept, removed = ids[:-1], ids[-1]
    for rid in kept:
        if not (src / f"{rid}.json").is_file():
            raise DemoError("arquivo individual de recibo ausente")
    if dst.exists():
        raise DemoError("a pasta da cadeia truncada já existe")
    dst.mkdir(parents=True)
    (dst / CHAIN_NAME).write_bytes(b"\n".join(lines[:-1]) + b"\n")
    for rid in kept:
        (dst / f"{rid}.json").write_bytes((src / f"{rid}.json").read_bytes())
    return kept[-1], removed


# ------------------------------------------------------------------ CLI

def cli_command(args: Sequence[str]) -> list[str]:
    """Linha de comando: o mesmo Python que roda a demo, módulo ``eal``."""
    return [sys.executable, "-m", "eal", *args]


def build_cli_env(project_root: Path, base_env: dict | None = None) -> dict:
    """Ambiente do subprocesso: UTF-8 na saída e a raiz do projeto no PYTHONPATH."""
    env = dict(os.environ if base_env is None else base_env)
    env["PYTHONIOENCODING"] = "utf-8"
    old = env.get("PYTHONPATH")
    root = str(project_root)
    env["PYTHONPATH"] = root if not old else root + os.pathsep + old
    return env


def run_cli(args: Sequence[str], cwd: Path, project_root: Path = PROJECT_ROOT) -> CliResult:
    """Roda a CLI real num subprocesso, com ``cwd`` como diretório atual."""
    try:
        proc = subprocess.run(
            cli_command(args),
            cwd=str(cwd),
            env=build_cli_env(project_root),
            capture_output=True,
            timeout=CLI_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise DemoError("o comando passou do tempo limite") from exc
    return CliResult(
        proc.returncode,
        proc.stdout.decode("utf-8", "replace"),
        proc.stderr.decode("utf-8", "replace"),
    )


# ----------------------------------------------------------------- demo

def _output_lines(result: CliResult) -> tuple[str, ...]:
    lines = [ln.strip() for ln in result.text.splitlines() if ln.strip()]
    return tuple(ln[:MAX_LINE_CHARS] for ln in lines[:MAX_OUTPUT_LINES])


def _run_with_retry(
    runner: Runner, args: Sequence[str], demo: Path, command: str
) -> tuple[CliResult, int, list[str]]:
    log = demo / LOGS_REL / RUN_LOG_NAME
    attempt = 0
    reasons: list[str] = []
    while True:
        attempt += 1
        before = len(read_log_lines(log))
        result = runner(args, demo)
        entries = new_log_entries(before, read_log_lines(log))
        if not should_retry(result.code, entries, command, attempt):
            return result, attempt, reasons
        reasons.append(str(entries[0].get("reason", ""))[:MAX_LINE_CHARS])


def _detail(attempts: int, reasons: list[str], missing: list[str], extra: str = "") -> str:
    parts: list[str] = []
    if attempts > 1:
        parts.append(f"tentativas: {attempts}")
        for number, reason in enumerate(reasons, start=1):
            parts.append(f"tentativa {number} reprovada: {reason}")
    if missing:
        parts.append("texto esperado ausente: " + "; ".join(missing))
    if extra:
        parts.append(extra)
    return " | ".join(parts)


def _step(
    number: int,
    title: str,
    expected: int,
    result: CliResult,
    patterns: Sequence[str] = (),
    *,
    attempts: int = 1,
    reasons: list[str] | None = None,
    extra: str = "",
    extra_ok: bool = True,
) -> StepResult:
    missing = [p for p in patterns if not re.search(p, result.text)]
    ok = result.code == expected and not missing and extra_ok
    return StepResult(
        number, title, expected, result.code, ok,
        _detail(attempts, reasons or [], missing, extra), _output_lines(result),
    )


def _failed_step(number: int, title: str, expected: int, message: str) -> StepResult:
    return StepResult(number, title, expected, -1, False, message)


def _chain_ids(demo: Path) -> list[str] | None:
    try:
        return receipt_ids(demo / RECEIPTS_REL / CHAIN_NAME)
    except DemoError:
        return None


def _issue_step(runner: Runner, demo: Path, number: int, title: str,
                command: str, expected_receipts: int | None) -> StepResult:
    result, attempts, reasons = _run_with_retry(runner, [command], demo, command)
    extra, extra_ok = "", True
    if expected_receipts is not None:
        ids = _chain_ids(demo)
        extra_ok = ids is not None and len(ids) == expected_receipts
        if not extra_ok:
            extra = f"a cadeia deveria ter {expected_receipts} recibo(s)"
    return _step(number, title, 0, result, attempts=attempts, reasons=reasons,
                 extra=extra, extra_ok=extra_ok)


def _rel(*parts: str) -> str:
    return str(Path(*parts))


def _verify_steps(runner: Runner, demo: Path, ids: list[str], head: str) -> list[StepResult]:
    rec = RECEIPTS_REL
    first, last = ids[0], ids[-1]
    steps: list[StepResult] = []
    steps.append(_step(
        4, "verify do último recibo com a cabeça anotada", 0,
        runner(["verify", str(rec / f"{last}.json"), "--expected-head", head], demo),
        [rf"v.lido: {re.escape(last)}", r"cadeia: posi..o 2 de 2", r"cabe.a conferida"],
    ))
    steps.append(_step(
        5, "verify do primeiro recibo", 0,
        runner(["verify", str(rec / f"{first}.json")], demo),
        [rf"v.lido: {re.escape(first)}", r"cadeia: posi..o 1 de 2"],
    ))
    steps.append(_tamper_step(runner, demo, last))
    steps.append(_step(
        7, "verify com cabeça errada", 1,
        runner(["verify", str(rec / f"{last}.json"), "--expected-head", WRONG_HEAD], demo),
        [r"cadeia reprovada"],
    ))
    steps.extend(_truncate_steps(runner, demo, head))
    return steps


def _tamper_step(runner: Runner, demo: Path, last: str) -> StepResult:
    title = "verify de cópia adulterada"
    copy = Path(TAMPER_DIR) / f"{last}.json"
    try:
        tamper_copy(demo / RECEIPTS_REL / f"{last}.json", demo / copy)
    except DemoError as exc:
        return _failed_step(6, title, 1, str(exc))
    return _step(6, title, 1,
                 runner(["verify", str(copy), "--chain-dir", str(RECEIPTS_REL)], demo),
                 [r"recibo reprovado"])


def _truncate_steps(runner: Runner, demo: Path, head: str) -> list[StepResult]:
    t8 = "limitação: último recibo apagado, sem cabeça anotada"
    t9 = "último recibo apagado, com a cabeça anotada"
    try:
        kept, _removed = truncate_chain_copy(demo / RECEIPTS_REL, demo / TRUNCATED_DIR)
    except DemoError as exc:
        return [_failed_step(8, t8, 0, str(exc)), _failed_step(9, t9, 1, str(exc))]
    target = str(Path(TRUNCATED_DIR) / f"{kept}.json")
    return [
        _step(8, t8, 0, runner(["verify", target], demo),
              [rf"v.lido: {re.escape(kept)}", r"cadeia: posi..o 1 de 1"]),
        _step(9, t9, 1, runner(["verify", target, "--expected-head", head], demo),
              [r"cadeia reprovada"]),
    ]


def run_demo(demo_dir: Path, runner: Runner | None = None,
             project_root: Path = PROJECT_ROOT) -> DemoReport:
    """Executa os 9 passos na pasta ``demo_dir`` (que não pode existir)."""
    demo = Path(demo_dir)
    call: Runner = runner if runner is not None else (
        lambda args, cwd: run_cli(args, cwd, project_root))
    try:
        demo.mkdir(parents=True, exist_ok=False)
    except FileExistsError as exc:
        raise DemoError("a pasta da demo já existe") from exc
    steps: list[StepResult] = []
    plan = [
        (1, "init-issuer", "init-issuer", None),
        (2, "run (1º recibo)", "run", 1),
        (3, "run (2º recibo)", "run", 2),
    ]
    for number, title, command, count in plan:
        step = _issue_step(call, demo, number, title, command, count)
        steps.append(step)
        if not step.ok:
            return DemoReport(tuple(steps), f"passo {number} falhou; os seguintes não rodaram")
    chain = demo / RECEIPTS_REL / CHAIN_NAME
    ids = receipt_ids(chain)
    steps.extend(_verify_steps(call, demo, ids, chain_head_from_file(chain)))
    return DemoReport(tuple(steps), None)


def format_report(report: DemoReport) -> str:
    """Texto da demo: uma linha por passo, detalhes e o resultado final."""
    lines: list[str] = []
    for s in report.steps:
        verdict = "OK" if s.ok else "FALHOU"
        lines.append(
            f"passo {s.number}: {s.title} | esperado {s.expected_code} "
            f"| obtido {s.got_code} | {verdict}")
        if s.detail:
            lines.append(f"    {s.detail}")
        lines.extend(f"    > {out}" for out in s.output)
    if report.aborted is not None:
        lines.append(f"ABORTADO: {report.aborted}")
    good = sum(1 for s in report.steps if s.ok)
    if report.ok:
        lines.append(f"RESULTADO: OK ({good} de {STEP_COUNT} passos)")
    else:
        lines.append(f"RESULTADO: FALHOU ({good} de {STEP_COUNT} passos ok)")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    """Opções da linha de comando da demo."""
    parser = argparse.ArgumentParser(
        prog="py -3.12 -m scripts.demo_dia5",
        description="Demo ponta a ponta da EAL numa pasta nova e descartável.")
    parser.add_argument("--pasta", type=Path, default=None,
                        help="pasta nova da demo (padrão: subpasta do diretório temporário)")
    return parser


def main(argv: Sequence[str] | None = None, *, _runner: Runner | None = None,
         _project_root: Path | None = None) -> int:
    """Ponto de entrada. ``_runner`` e ``_project_root`` são só para testes."""
    args = build_parser().parse_args(argv)
    root = Path(_project_root) if _project_root is not None else PROJECT_ROOT
    chosen = args.pasta if args.pasta is not None else default_demo_dir()
    try:
        demo = check_demo_dir(chosen, root)
    except DemoError as exc:
        print(f"erro: {exc}", file=sys.stderr)
        return EXIT_USAGE
    print(f"pasta da demo: {demo}")
    try:
        report = run_demo(demo, _runner, root)
    except DemoError as exc:
        print(f"erro: {exc}", file=sys.stderr)
        return EXIT_DEMO_FAILED
    except Exception as exc:  # noqa: BLE001 - só o nome da classe, nunca a mensagem
        print(f"erro inesperado: {type(exc).__name__}", file=sys.stderr)
        return EXIT_DEMO_FAILED
    print(format_report(report))
    print(f"A pasta da demo não é apagada. Apague quando quiser: {demo}")
    return EXIT_OK if report.ok else EXIT_DEMO_FAILED


if __name__ == "__main__":
    sys.exit(main())
