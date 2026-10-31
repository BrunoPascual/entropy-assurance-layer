"""G6, passo 2: params do lote no recibo (eal/config.py, eal/receipt/schema.py, eal/receipt/builder.py).

Uso (na raiz do projeto):  py -3.12 scripts\\aplicar_g6_passo2.py [raiz do projeto]

Tudo ou nada: confere os três arquivos antes de gravar qualquer um. Idempotente, preserva
LF ou CRLF de cada arquivo e recusa sem gravar se qualquer conferência falhar.
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

CONFIG_BLOCK = '''
# --- G6: params do lote no recibo (Dia 6) ---
# Lista fechada: só estas chaves de RawBatch.params vão para o recibo (bloco "batch_params" da
# fonte). Token, semente e qualquer outro campo ficam de fora por construção. O adaptador da
# QPU precisa usar exatamente estes nomes.
RECEIPT_BATCH_PARAM_TEXT_KEYS: tuple[str, ...] = ("backend", "job_id")
RECEIPT_BATCH_PARAM_INT_KEYS: tuple[str, ...] = ("shots", "qubits")
RECEIPT_BATCH_PARAM_TEXT_PATTERN: str = r"[A-Za-z0-9._-]{1,64}"  # texto curto, sem espaço nem barra
RECEIPT_BATCH_PARAM_INT_MAX: int = 10**9
RECEIPT_JOB_ID_REQUIRED_TYPES: tuple[str, ...] = ("qpu_ibm",)  # lote desses tipos exige job_id
'''

SCHEMA_FUNCS = '''def batch_param_problems(params: object, where: str) -> list[str]:
    """Problemas dos params do lote no recibo (G6). Cita só nomes de campos, nunca valores."""
    if not isinstance(params, dict):
        return [f"{where} não é objeto"]
    problems: list[str] = []
    extra = params.keys() - BATCH_PARAM_KEYS
    if extra:
        problems.append(f"{where} com campos não previstos: {sorted(map(str, extra))}")
    for key in RECEIPT_BATCH_PARAM_TEXT_KEYS:
        if key in params:
            value = params[key]
            if not (type(value) is str and _PARAM_TEXT.fullmatch(value)):
                problems.append(f"{where}.{key} inválido")
    for key in RECEIPT_BATCH_PARAM_INT_KEYS:
        if key in params:
            value = params[key]
            if not (type(value) is int and 1 <= value <= RECEIPT_BATCH_PARAM_INT_MAX):
                problems.append(f"{where}.{key} inválido")
    return problems


def _check_batch_params(i: int, src: dict) -> list[str]:
    """batch_params é opcional (recibos antigos não têm), mas fonte que exige job_id o traz."""
    where = f"sources[{i}].batch_params"
    params = src.get("batch_params")
    problems = batch_param_problems(params, where) if "batch_params" in src else []
    needs_job = src.get("source_type") in RECEIPT_JOB_ID_REQUIRED_TYPES and src.get("batch_hash") is not None
    if needs_job and not (isinstance(params, dict) and "job_id" in params):
        problems.append(f"{where}.job_id ausente em fonte que exige job_id")
    return problems


'''

BUILDER_FUNCS = '''def clean_batch_params(params: Any) -> dict[str, Any]:
    """G6: só as chaves da lista fechada (config.py) vão para o recibo; o resto é descartado.

    Token, semente e qualquer outro campo do lote ficam de fora por construção. Valor inválido
    numa chave permitida recusa o recibo; a mensagem cita o nome do campo, nunca o valor.
    """
    if params is None:
        return {}
    if not isinstance(params, dict):
        raise ValueError("params do lote não é objeto")
    clean: dict[str, Any] = {}
    for key in (*RECEIPT_BATCH_PARAM_TEXT_KEYS, *RECEIPT_BATCH_PARAM_INT_KEYS):
        if key in params:
            value = params[key]
            clean[key] = int(value) if isinstance(value, np.integer) else value
    problems = batch_param_problems(clean, "batch_params")
    if problems:
        raise ValueError("params do lote inválidos: " + "; ".join(problems))
    return clean


def _require_job_id(outcome: Any, src: Any, entry: dict[str, Any]) -> None:
    """Fonte de tipo que exige job_id (qpu_ibm) com lote lido sem job_id: recusa o recibo."""
    if (outcome.batch_id is not None
            and str(src.source_type) in RECEIPT_JOB_ID_REQUIRED_TYPES
            and "job_id" not in entry["batch_params"]):
        raise ValueError(f"fonte do tipo {src.source_type} sem job_id nos params do lote")


'''

# (arquivo relativo, marcador de "já aplicado", lista de (antigo, novo) ou ("APPEND", texto))
PLAN: list[tuple[str, str, list[tuple[str, str]]]] = [
    ("eal/config.py", "RECEIPT_BATCH_PARAM_TEXT_KEYS", [("APPEND", CONFIG_BLOCK)]),
    ("eal/receipt/schema.py", "def batch_param_problems(", [
        ("from eal.config import RECEIPT_REQUIRED_LIMITATIONS\n",
         "from eal.config import (\n"
         "    RECEIPT_BATCH_PARAM_INT_KEYS,\n"
         "    RECEIPT_BATCH_PARAM_INT_MAX,\n"
         "    RECEIPT_BATCH_PARAM_TEXT_KEYS,\n"
         "    RECEIPT_BATCH_PARAM_TEXT_PATTERN,\n"
         "    RECEIPT_JOB_ID_REQUIRED_TYPES,\n"
         "    RECEIPT_REQUIRED_LIMITATIONS,\n"
         ")\n"),
        ('_HEX64 = re.compile(r"[0-9a-f]{64}")\n',
         '_HEX64 = re.compile(r"[0-9a-f]{64}")\n'
         "_PARAM_TEXT = re.compile(RECEIPT_BATCH_PARAM_TEXT_PATTERN)\n"
         "BATCH_PARAM_KEYS = frozenset((*RECEIPT_BATCH_PARAM_TEXT_KEYS, *RECEIPT_BATCH_PARAM_INT_KEYS))\n"),
        ('            problems.append(f"sources[{i}].{flag} não é booleano")\n    return problems\n',
         '            problems.append(f"sources[{i}].{flag} não é booleano")\n'
         "    problems += _check_batch_params(i, src)\n"
         "    return problems\n"),
        ("def _check_policy(sources: list[dict]) -> list[str]:\n",
         SCHEMA_FUNCS + "def _check_policy(sources: list[dict]) -> list[str]:\n"),
    ]),
    ("eal/receipt/builder.py", "def clean_batch_params(", [
        ("do batch_hash). Os params do lote (ex.: job_id da IBM) ainda não chegam aqui.",
         "do batch_hash). Os params do lote (G6) vêm do SourceOutcome; só as chaves da lista\n"
         "fechada de config.py entram, no bloco batch_params de cada fonte."),
        ("    RECEIPT_EXTRACTOR_TYPE,\n",
         "    RECEIPT_BATCH_PARAM_INT_KEYS,\n"
         "    RECEIPT_BATCH_PARAM_TEXT_KEYS,\n"
         "    RECEIPT_EXTRACTOR_TYPE,\n"
         "    RECEIPT_JOB_ID_REQUIRED_TYPES,\n"),
        ("from eal.receipt.schema import KEYGEN_MODE, MIXED_STATUS, validate_body\n",
         "from eal.receipt.schema import KEYGEN_MODE, MIXED_STATUS, batch_param_problems, validate_body\n"),
        ('"reasons", "health", "extraction"\n})\n',
         '"reasons", "health", "extraction",\n    "batch_params"\n})\n'),
        ("def _source_entry(outcome: Any, src: Any, mi: Any) -> dict[str, Any]:\n",
         BUILDER_FUNCS + "def _source_entry(outcome: Any, src: Any, mi: Any) -> dict[str, Any]:\n"),
        ('        "extraction": None,\n    }\n    if mi is None:\n        return entry\n',
         '        "extraction": None,\n'
         '        "batch_params": clean_batch_params(getattr(outcome, "params", None)),\n'
         "    }\n"
         "    _require_job_id(outcome, src, entry)\n"
         "    if mi is None:\n        return entry\n"),
    ]),
]


def _load(path: Path) -> tuple[str, bool] | str:
    try:
        text = path.read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return f"não consegui ler {path} ({type(exc).__name__})"
    crlf = "\r\n" in text
    if crlf and text.count("\n") != text.count("\r\n"):
        return f"{path} mistura LF e CRLF"
    return text.replace("\r\n", "\n"), crlf


def _apply(norm: str, edits: list[tuple[str, str]]) -> str | None:
    for old, _ in edits:
        if old != "APPEND" and norm.count(old) != 1:
            return None
    for old, new in edits:
        if old == "APPEND":
            norm = (norm if norm.endswith("\n") else norm + "\n") + new
        else:
            norm = norm.replace(old, new, 1)
    return norm


def main() -> int:
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[1]
    staged: list[tuple[Path, bytes]] = []
    already = 0
    for rel, marker, edits in PLAN:
        path = root / rel
        loaded = _load(path)
        if isinstance(loaded, str):
            print(f"RECUSADO: {loaded}; nada foi gravado")
            return 1
        norm, crlf = loaded
        if marker in norm:
            if all(new in norm for old, new in edits if old != "APPEND") and (
                    edits[0][0] != "APPEND" or edits[0][1].strip() in norm):
                already += 1
                continue
            print(f"RECUSADO: {rel} com aplicação parcial anterior; nada foi gravado")
            return 1
        result = _apply(norm, edits)
        if result is None:
            bad = [i for i, (o, _) in enumerate(edits, 1) if o != "APPEND" and norm.count(o) != 1]
            print(f"RECUSADO: {rel}: trecho(s) {bad} não aparece(m) exatamente 1 vez; nada foi gravado")
            return 1
        out = result.replace("\n", "\r\n") if crlf else result
        staged.append((path, out.encode("utf-8")))
    if already == len(PLAN):
        print("já aplicado; nada a fazer")
        return 0
    if already:
        print("RECUSADO: só parte dos arquivos já estava aplicada; nada foi gravado")
        return 1
    for path, data in staged:
        path.write_bytes(data)
        print(f"aplicado em {path}; sha256 novo: {hashlib.sha256(data).hexdigest()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
