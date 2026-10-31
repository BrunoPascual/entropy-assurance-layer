"""Registro automático do gate manual do Dia 5 (etapa 5).

Dois comandos. Cada um confere antes de gravar qualquer coisa.

``extrair --handoff ARQUIVO``
    Lê o bloco ``gate_manual_dia5_resultado`` do handoff, valida o formato e
    grava ``data/results/dia5_gate_manual_2026-10-31.json``. Não sobrescreve.

``doc [--out ARQUIVO]``
    Lê esse JSON e confere cada execução contra o log e os recibos em
    ``data/receipts/`` (cabeça, receipt_id, seed_hash e chaves públicas).
    Confere no Git que as chaves e o log estão fora do controle de versão e
    grava a seção 16.3 no ``PROJECT.md``, entre âncoras. Com ``--out`` só grava
    o bloco gerado nesse arquivo, para inspeção, e não toca no ``PROJECT.md``.

Nenhum número é digitado à mão: tudo sai do handoff, passando pelo JSON.
Se algo não bater, o script para com código 1 e não grava nada.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import uuid
from collections.abc import Callable, Sequence
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
GATE_REL = Path("data") / "results" / "dia5_gate_manual_2026-10-31.json"
RECEIPTS_REL = Path("data") / "receipts"
CHAIN_NAME = "chain.jsonl"
PROJECT_REL = Path("PROJECT.md")
HANDOFF_BLOCK = "gate_manual_dia5_resultado"
START = "<!-- dia5-gate:start -->"
END = "<!-- dia5-gate:end -->"
NEXT_HEADING = "## 17. Limitações conhecidas"
BASE_KEYS = ("data", "init_issuer", "runs", "checagens_todas_ok", "outros")
DROPPED_KEYS = ("observacao",)
FILE_KEYS = BASE_KEYS + ("origem",)
ORIGIN_KEYS = ("bloco", "handoff_sha3_256")
RUN_KEYS = (
    "tentativa",
    "codigo",
    "receipt_id",
    "seed_hash",
    "ml_kem_768_pk_hash",
    "ml_dsa_65_pk_hash",
    "fontes",
    "cabeca",
)
HASH_KEYS = ("seed_hash", "ml_kem_768_pk_hash", "ml_dsa_65_pk_hash", "cabeca")
GIT_IGNORED = (
    "keys/issuer_ml_dsa_65.sk",
    "keys/issuer_ml_dsa_65.pk",
    "data/receipts/chain.jsonl",
)
HEX64 = re.compile(r"[0-9a-f]{64}")
EXIT_OK = 0
EXIT_CHECK = 1
EXIT_USAGE = 2

GitRunner = Callable[[str, Path], int]


class GateError(Exception):
    """Falha de formato ou de conferência. As mensagens nunca trazem conteúdo do gate."""


# ------------------------------------------------------------ leitura JSON

def sha3_hex(data: bytes) -> str:
    """SHA3-256 em hex minúsculo."""
    return hashlib.sha3_256(data).hexdigest()


def _pairs_no_dupes(pairs: list[tuple[str, object]]) -> dict:
    out: dict = {}
    for key, value in pairs:
        if key in out:
            raise GateError("JSON com chave repetida")
        out[key] = value
    return out


def _reject_constant(_name: str) -> None:
    raise GateError("JSON com NaN ou Infinity")


def parse_json(data: bytes) -> object:
    """JSON estrito: UTF-8 (com ou sem BOM), sem chave repetida e sem NaN."""
    try:
        text = data.decode("utf-8-sig")
        return json.loads(text, object_pairs_hook=_pairs_no_dupes,
                          parse_constant=_reject_constant)
    except (UnicodeDecodeError, ValueError) as exc:
        raise GateError("conteúdo não é JSON UTF-8 válido") from exc


# -------------------------------------------------------------- validação

def _check_keys(obj: dict, expected: tuple[str, ...], where: str) -> None:
    missing = [key for key in expected if key not in obj]
    extra = len([key for key in obj if key not in expected])
    if missing or extra:
        names = ", ".join(missing) if missing else "nenhum"
        raise GateError(f"{where}: campos faltando: {names}; campos não previstos: {extra}")


def _is_hex64(value: object) -> bool:
    return isinstance(value, str) and HEX64.fullmatch(value) is not None


def _is_uuid(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        return str(uuid.UUID(value)) == value
    except ValueError:
        return False


def _non_empty_text(value: object) -> bool:
    return isinstance(value, str) and value.strip() != ""


def _validate_run(run: object, index: int) -> None:
    where = f"execução {index}"
    if not isinstance(run, dict):
        raise GateError(f"{where}: formato inválido")
    _check_keys(run, RUN_KEYS, where)
    if type(run["tentativa"]) is not int or run["tentativa"] != index:
        raise GateError(f"{where}: número de tentativa fora de ordem")
    if type(run["codigo"]) is not int:
        raise GateError(f"{where}: código de saída não é inteiro")
    if not _is_uuid(run["receipt_id"]):
        raise GateError(f"{where}: receipt_id não é UUID canônico em minúsculas")
    for key in HASH_KEYS:
        if not _is_hex64(run[key]):
            raise GateError(f"{where}: '{key}' não é SHA3-256 em hex minúsculo")
    if not _non_empty_text(run["fontes"]):
        raise GateError(f"{where}: 'fontes' vazio")


def _validate_origin(origin: object) -> None:
    if not isinstance(origin, dict):
        raise GateError("origem: formato inválido")
    _check_keys(origin, ORIGIN_KEYS, "origem")
    if origin["bloco"] != HANDOFF_BLOCK:
        raise GateError("origem: bloco inesperado")
    if not _is_hex64(origin["handoff_sha3_256"]):
        raise GateError("origem: hash do handoff inválido")


def validate_gate(obj: object, expected_keys: tuple[str, ...] = FILE_KEYS) -> dict:
    """Confere o formato do gate. Devolve o próprio objeto se estiver certo."""
    if not isinstance(obj, dict):
        raise GateError("o gate não é um objeto JSON")
    _check_keys(obj, expected_keys, "gate")
    for key in ("data", "init_issuer", "outros"):
        if not _non_empty_text(obj[key]):
            raise GateError(f"gate: '{key}' vazio ou não é texto")
    checks = obj["checagens_todas_ok"]
    if not isinstance(checks, list) or not checks or not all(_non_empty_text(c) for c in checks):
        raise GateError("gate: 'checagens_todas_ok' vazio ou inválido")
    runs = obj["runs"]
    if not isinstance(runs, list) or not runs:
        raise GateError("gate: nenhuma execução registrada")
    for index, run in enumerate(runs, start=1):
        _validate_run(run, index)
    if "origem" in obj:
        _validate_origin(obj["origem"])
    return obj


def build_gate(handoff_bytes: bytes) -> tuple[bytes, list[str]]:
    """Extrai o bloco do gate do handoff. Devolve (bytes do JSON, campos descartados)."""
    handoff = parse_json(handoff_bytes)
    if not isinstance(handoff, dict) or HANDOFF_BLOCK not in handoff:
        raise GateError(f"o handoff não tem o bloco '{HANDOFF_BLOCK}'")
    block = handoff[HANDOFF_BLOCK]
    if not isinstance(block, dict):
        raise GateError("o bloco do gate não é um objeto")
    unknown = [key for key in block if key not in BASE_KEYS and key not in DROPPED_KEYS]
    if unknown:
        raise GateError(f"o bloco do handoff tem {len(unknown)} campo(s) não previstos")
    base = {key: block[key] for key in BASE_KEYS if key in block}
    validate_gate(base, BASE_KEYS)
    gate = {**base, "origem": {"bloco": HANDOFF_BLOCK,
                               "handoff_sha3_256": sha3_hex(handoff_bytes)}}
    validate_gate(gate, FILE_KEYS)
    data = (json.dumps(gate, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    dropped = [key for key in DROPPED_KEYS if key in block]
    return data, dropped


def write_new(path: Path, data: bytes) -> None:
    """Grava um arquivo novo. Recusa se ele já existir (nunca sobrescreve)."""
    path = Path(path)
    if path.exists():
        raise GateError("o arquivo já existe; nada foi gravado")
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(path, "xb") as fh:
            fh.write(data)
    except FileExistsError as exc:
        raise GateError("o arquivo já existe; nada foi gravado") from exc


def load_gate(path: Path) -> tuple[dict, str]:
    """Lê e valida o JSON do gate. Devolve (gate, SHA3-256 do arquivo)."""
    try:
        data = Path(path).read_bytes()
    except OSError as exc:
        raise GateError("gate não encontrado; rode 'extrair' antes") from exc
    return validate_gate(parse_json(data)), sha3_hex(data)


# ---------------------------------------------------- conferência com o disco

def _line_receipt_id(line: bytes) -> str:
    obj = parse_json(line)
    rid = obj.get("receipt_id") if isinstance(obj, dict) else None
    if not _is_uuid(rid):
        raise GateError("linha do log sem receipt_id válido")
    assert isinstance(rid, str)
    return rid


def read_disk(root: Path) -> tuple[list[bytes], dict[str, bytes]]:
    """Lê o log (uma linha por recibo, sem a quebra final) e os arquivos dos recibos."""
    base = Path(root) / RECEIPTS_REL
    try:
        data = (base / CHAIN_NAME).read_bytes()
    except OSError as exc:
        raise GateError("log da cadeia não encontrado em data/receipts/") from exc
    if not data.endswith(b"\n"):
        raise GateError("o log não termina em quebra de linha")
    lines = data.split(b"\n")[:-1]
    if not lines or any(not line for line in lines):
        raise GateError("o log está vazio ou tem linha vazia")
    receipts: dict[str, bytes] = {}
    for line in lines:
        rid = _line_receipt_id(line)
        path = base / f"{rid}.json"
        if path.is_file():
            receipts[rid] = path.read_bytes()
    return lines, receipts


def _check_run(index: int, run: dict, line: bytes, receipts: dict[str, bytes]) -> list[str]:
    where = f"execução {index}"
    found: list[str] = []
    if _line_receipt_id(line) != run["receipt_id"]:
        found.append(f"{where}: receipt_id diferente do log")
    if sha3_hex(line) != run["cabeca"]:
        found.append(f"{where}: cabeça diferente da cabeça do log")
    recibo = receipts.get(run["receipt_id"])
    if recibo is None:
        found.append(f"{where}: arquivo do recibo ausente")
        return found
    # O .json pode ou não ter a quebra final; o conteúdo JSON precisa ser igual.
    if recibo not in (line, line + b"\n"):
        found.append(f"{where}: arquivo do recibo diferente da linha do log")
        return found
    body = parse_json(recibo)
    keys = body.get("keys") if isinstance(body, dict) else None
    if not isinstance(body, dict) or body.get("seed_hash") != run["seed_hash"]:
        found.append(f"{where}: seed_hash do recibo diferente do gate")
    if not isinstance(keys, dict) or keys.get("ml_kem_768_pk_hash") != run["ml_kem_768_pk_hash"]:
        found.append(f"{where}: chave ML-KEM-768 do recibo diferente do gate")
    if not isinstance(keys, dict) or keys.get("ml_dsa_65_pk_hash") != run["ml_dsa_65_pk_hash"]:
        found.append(f"{where}: chave ML-DSA-65 do recibo diferente do gate")
    return found


def cross_check(gate: dict, lines: list[bytes], receipts: dict[str, bytes]) -> list[str]:
    """Confere cada execução do gate contra o log e os recibos. Lista vazia = tudo bate."""
    problems: list[str] = []
    runs = gate["runs"]
    if len(lines) != len(runs):
        problems.append(f"o log tem {len(lines)} linha(s) e o gate registra {len(runs)} execução(ões)")
    for index, run in enumerate(runs, start=1):
        if index > len(lines):
            break
        problems.extend(_check_run(index, run, lines[index - 1], receipts))
    return problems


def default_git_runner(rel: str, root: Path) -> int:
    """Código de ``git check-ignore``: 0 = ignorado, 1 = não ignorado, outro = erro."""
    try:
        proc = subprocess.run(
            ["git", "check-ignore", "-q", "--", rel],
            cwd=str(root), capture_output=True, timeout=60, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return -1
    return proc.returncode


def git_problems(root: Path, runner: GitRunner) -> list[str]:
    """Confere que as chaves e o log estão ignorados pelo Git."""
    problems: list[str] = []
    for rel in GIT_IGNORED:
        code = runner(rel, Path(root))
        if code != 0:
            problems.append(f"o Git não ignora '{rel}' (código {code})")
    return problems


# ------------------------------------------------------------- documento

def _limits(count: int) -> tuple[str, ...]:
    return (
        f"{count} execução(ões) com a fonte `os`. São dados de um dia, não uma taxa: "
        "com elas não dá para estimar a frequência de falhas por acaso.",
        "A fonte é a `os`, cuja imprevisibilidade é premissa (P3). A QPU da IBM não "
        "entrou nesta execução, e a CLI ainda não tem coleta de QPU.",
        "O gate confere fluxo, cadeia e chaves no disco. Não mede a qualidade "
        "estatística da semente nem a taxa de detecção de fontes defeituosas "
        "(isso é o E2).",
    )


def _cell(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def render_section(gate: dict, gate_sha3: str) -> str:
    """Texto da seção 16.3, com as âncoras. Todo número vem do gate."""
    origem = gate["origem"]
    rows = ["| " + " | ".join(_cell(run[key]) for key in RUN_KEYS) + " |"
            for run in gate["runs"]]
    lines = [
        START,
        "### 16.3 Gate manual do Dia 5 (execução real na máquina do autor)",
        "",
        f"Gerado por `scripts/registrar_gate_dia5.py` a partir de `{GATE_REL.as_posix()}` "
        f"(SHA3-256 `{gate_sha3}`). Nenhum número foi digitado à mão. Antes de gravar, o "
        "script conferiu cada recibo, cabeça e chave pública contra o log e os arquivos em "
        "`data/receipts/`, e confirmou no Git que as chaves e o log ficam fora do controle "
        f"de versão. O JSON veio do bloco `{origem['bloco']}` do handoff "
        f"(SHA3-256 `{origem['handoff_sha3_256']}`).",
        "",
        f"**Origem.** {gate['data']}.",
        "",
        "**Execuções.**",
        "",
        "| Tentativa | Código | receipt_id | seed_hash | ML-KEM-768 (pk_hash) | "
        "ML-DSA-65 (pk_hash) | Fontes | Cabeça após a execução |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
        *rows,
        "",
        f"**Chave do emissor.** {gate['init_issuer']}",
        "",
        "**Checagens.**",
        "",
        *[f"- {check}" for check in gate["checagens_todas_ok"]],
        "",
        f"**Outras conferências na data do gate.** {gate['outros']}",
        "",
        "**O que este gate mostra e o que não mostra.**",
        "",
        *[f"- {text}" for text in _limits(len(gate["runs"]))],
        END,
    ]
    return "\n".join(lines)


def apply_section(text: str, block: str) -> str:
    """Põe o bloco no lugar das âncoras; se não houver âncoras, insere antes da seção 17."""
    starts, ends = text.count(START), text.count(END)
    if starts != ends or starts > 1:
        raise GateError("âncoras da seção 16.3 inconsistentes (devem aparecer em par, uma vez)")
    if starts == 0:
        if text.count(NEXT_HEADING) != 1:
            raise GateError("o cabeçalho da seção 17 não aparece exatamente uma vez")
        idx = text.index(NEXT_HEADING)
        return text[:idx] + block + "\n\n" + text[idx:]
    begin, finish = text.index(START), text.index(END)
    if finish < begin:
        raise GateError("âncora de fim antes da de início")
    return text[:begin] + block + text[finish + len(END):]


def write_project(path: Path, block: str) -> bool:
    """Atualiza o PROJECT.md mantendo as quebras de linha. True se mudou."""
    raw = Path(path).read_bytes()
    crlf = raw.count(b"\r\n")
    lf = raw.count(b"\n")
    if crlf not in (0, lf):
        raise GateError("o PROJECT.md mistura CRLF e LF; nada foi gravado")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise GateError("o PROJECT.md não é UTF-8; nada foi gravado") from exc
    norm = text.replace("\r\n", "\n")
    new_norm = apply_section(norm, block)
    if new_norm == norm:
        return False
    new_text = new_norm.replace("\n", "\r\n") if crlf else new_norm
    Path(path).write_bytes(new_text.encode("utf-8"))
    return True


# --------------------------------------------------------------- comandos

def cmd_extrair(args: argparse.Namespace, root: Path) -> int:
    """Subcomando ``extrair``: handoff -> JSON do gate."""
    try:
        data = Path(args.handoff).read_bytes()
    except OSError:
        print("erro: não consegui ler o handoff", file=sys.stderr)
        return EXIT_USAGE
    try:
        gate_bytes, dropped = build_gate(data)
        target = Path(root) / GATE_REL
        write_new(target, gate_bytes)
    except GateError as exc:
        print(f"erro: {exc}", file=sys.stderr)
        return EXIT_CHECK
    print(f"gate gravado: {target}")
    print(f"SHA3-256 do gate: {sha3_hex(gate_bytes)}")
    print(f"SHA3-256 do handoff: {sha3_hex(data)}")
    for key in dropped:
        print(f"campo do handoff não copiado: {key} (nota de trabalho)")
    return EXIT_OK


def cmd_doc(args: argparse.Namespace, root: Path, git_runner: GitRunner) -> int:
    """Subcomando ``doc``: confere tudo e grava a seção 16.3."""
    root = Path(root)
    try:
        gate, gate_sha3 = load_gate(root / GATE_REL)
        lines, receipts = read_disk(root)
        problems = cross_check(gate, lines, receipts) + git_problems(root, git_runner)
        if problems:
            for problem in problems:
                print(f"falhou: {problem}", file=sys.stderr)
            print("nada foi gravado", file=sys.stderr)
            return EXIT_CHECK
        block = render_section(gate, gate_sha3)
        if args.out is not None:
            write_new(Path(args.out), block.encode("utf-8"))
            print(f"bloco da seção 16.3 gerado em: {args.out}")
            print("PROJECT.md não foi tocado")
        else:
            changed = write_project(root / PROJECT_REL, block)
            print("PROJECT.md: seção 16.3 " + ("gravada" if changed else "já estava igual; nada mudou"))
    except GateError as exc:
        print(f"erro: {exc}", file=sys.stderr)
        print("nada foi gravado", file=sys.stderr)
        return EXIT_CHECK
    print(f"conferido: {len(gate['runs'])} execução(ões) contra o log e os recibos; "
          f"{len(GIT_IGNORED)} caminhos ignorados pelo Git")
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    """Subcomandos e opções."""
    parser = argparse.ArgumentParser(
        prog="py -3.12 -m scripts.registrar_gate_dia5",
        description="Registra o gate manual do Dia 5 a partir do handoff.")
    sub = parser.add_subparsers(dest="comando", required=True)
    extract = sub.add_parser("extrair", help="lê o handoff e grava o JSON do gate (não sobrescreve)")
    extract.add_argument("--handoff", required=True, type=Path,
                         help="arquivo JSON do handoff do Dia 5")
    doc = sub.add_parser("doc", help="confere o gate contra o disco e grava a seção 16.3")
    doc.add_argument("--out", type=Path, default=None,
                     help="só grava o bloco gerado neste arquivo; não mexe no PROJECT.md")
    return parser


def main(argv: Sequence[str] | None = None, *, _root: Path | None = None,
         _git_runner: GitRunner | None = None) -> int:
    """Ponto de entrada. ``_root`` e ``_git_runner`` existem só para testes."""
    args = build_parser().parse_args(argv)
    root = Path(_root) if _root is not None else PROJECT_ROOT
    if args.comando == "extrair":
        return cmd_extrair(args, root)
    runner = _git_runner if _git_runner is not None else default_git_runner
    return cmd_doc(args, root, runner)


if __name__ == "__main__":
    sys.exit(main())
