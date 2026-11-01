"""Mutações manuais do G6 (params do lote no recibo) em eal/receipt/builder.py e schema.py.

Fecha a pendência P2 do Dia 6. Cada mutação troca UM trecho de UM dos dois arquivos por uma
versão errada e roda os testes que falam do G6; a mutação "morre" se algum teste falhar. Os dois
arquivos são sempre restaurados ao final, mesmo com Ctrl-C. Isso mostra que os testes pegam
esses erros, não que o código esteja correto.

Os testes são descobertos sozinhos: todo ``tests/test_*.py`` que cita uma das funções do G6, o
campo ``batch_params``, o pacote ``eal.receipt`` ou uma mensagem de erro do G6. O script imprime
quais foram escolhidos.

Uso (na raiz do projeto):
    py -3.12 scripts\\mutacoes_g6.py
Código de saída: 0 se todas morreram; 1 se alguma sobreviveu ou se uma âncora não bateu.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

FILES = {
    "builder": Path("eal/receipt/builder.py"),
    "schema": Path("eal/receipt/schema.py"),
}
# Funções e campo do G6, o pacote do recibo e as mensagens de erro do G6: assim entram também os
# testes do construtor e do validador que não citam as funções pelo nome.
IDENTIFIERS = ("clean_batch_params", "batch_param_problems", "_check_batch_params",
               "_require_job_id", "batch_params", "eal.receipt", "sem job_id",
               "job_id ausente", "não é objeto")
TESTS_DIR = Path("tests")

# (arquivo, nome, trecho original, trecho errado). O original precisa aparecer EXATAMENTE uma
# vez no arquivo indicado.
MUTATIONS: list[tuple[str, str, str, str]] = [
    # ---- eal/receipt/builder.py: clean_batch_params e _require_job_id
    ("builder", "params None vira erro", "    if params is None:\n        return {}",
     "    if False:\n        return {}"),
    ("builder", "params que nao e objeto aceito",
     '    if not isinstance(params, dict):\n        raise ValueError("params do lote não é objeto")',
     '    if False:\n        raise ValueError("params do lote não é objeto")'),
    ("builder", "campos fora da lista fechada passam",
     "    for key in (*RECEIPT_BATCH_PARAM_TEXT_KEYS, *RECEIPT_BATCH_PARAM_INT_KEYS):\n        if key in params:",
     "    for key in params:\n        if key in params:"),
    ("builder", "inteiro do numpy nao convertido",
     "clean[key] = int(value) if isinstance(value, np.integer) else value", "clean[key] = value"),
    ("builder", "params invalidos nao recusam",
     '    if problems:\n        raise ValueError("params do lote inválidos: "',
     '    if False:\n        raise ValueError("params do lote inválidos: "'),
    ("builder", "job_id deixa de ser exigido", 'and "job_id" not in entry["batch_params"]):',
     "and False):"),
    ("builder", "job_id exigido tambem sem lote lido",
     "outcome.batch_id is not None\n            and str(src.source_type) in RECEIPT_JOB_ID_REQUIRED_TYPES",
     "True\n            and str(src.source_type) in RECEIPT_JOB_ID_REQUIRED_TYPES"),
    ("builder", "job_id exigido so de quem nao deve",
     "and str(src.source_type) in RECEIPT_JOB_ID_REQUIRED_TYPES",
     "and str(src.source_type) not in RECEIPT_JOB_ID_REQUIRED_TYPES"),
    ("builder", "params do lote nunca chegam ao recibo",
     '"batch_params": clean_batch_params(getattr(outcome, "params", None)),',
     '"batch_params": {},'),
    # ---- eal/receipt/schema.py: batch_param_problems e _check_batch_params
    ("schema", "params que nao e objeto passa",
     '    if not isinstance(params, dict):\n        return [f"{where} não é objeto"]',
     '    if False:\n        return [f"{where} não é objeto"]'),
    ("schema", "campos nao previstos aceitos",
     '    if extra:\n        problems.append(f"{where} com campos não previstos:',
     '    if False:\n        problems.append(f"{where} com campos não previstos:'),
    ("schema", "texto sem o padrao curto",
     "if not (type(value) is str and _PARAM_TEXT.fullmatch(value)):",
     "if not (type(value) is str):"),
    ("schema", "bool vale como inteiro",
     "if not (type(value) is int and 1 <= value <= RECEIPT_BATCH_PARAM_INT_MAX):",
     "if not (isinstance(value, int) and 1 <= value <= RECEIPT_BATCH_PARAM_INT_MAX):"),
    ("schema", "zero aceito como inteiro",
     "if not (type(value) is int and 1 <= value <= RECEIPT_BATCH_PARAM_INT_MAX):",
     "if not (type(value) is int and 0 <= value <= RECEIPT_BATCH_PARAM_INT_MAX):"),
    ("schema", "inteiro acima do teto aceito",
     "if not (type(value) is int and 1 <= value <= RECEIPT_BATCH_PARAM_INT_MAX):",
     "if not (type(value) is int and 1 <= value <= RECEIPT_BATCH_PARAM_INT_MAX + 1):"),
    ("schema", "batch_params deixa de ser opcional",
     'problems = batch_param_problems(params, where) if "batch_params" in src else []',
     "problems = batch_param_problems(params, where) if True else []"),
    ("schema", "falta de job_id aceita em fonte que exige",
     'if needs_job and not (isinstance(params, dict) and "job_id" in params):', "if False:"),
    ("schema", "job_id exigido de qualquer tipo de fonte",
     'src.get("source_type") in RECEIPT_JOB_ID_REQUIRED_TYPES', "True"),
    ("schema", "job_id exigido mesmo sem lote",
     ' and src.get("batch_hash") is not None', ""),
]


def discover_tests() -> list[str]:
    """Arquivos de teste que citam o G6 (funções ou o campo batch_params)."""
    found: list[str] = []
    for path in sorted(TESTS_DIR.glob("test_*.py")):
        text = path.read_text(encoding="utf-8", errors="replace")
        if any(name in text for name in IDENTIFIERS):
            found.append(path.as_posix())
    return found


def run_tests(tests: list[str]) -> bool:
    """True se os testes passam.

    Roda sem gravar bytecode: o Python valida o .pyc só por data (em segundos) e tamanho, e uma
    mutação de mesmo tamanho feita no mesmo segundo da anterior reaproveitaria o bytecode errado.
    """
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    done = subprocess.run([sys.executable, "-B", "-m", "pytest", "-q", "-x", *tests],
                          capture_output=True, text=True, env=env)
    return done.returncode == 0


def drop_bytecode() -> None:
    """Apaga o bytecode em cache dos dois módulos, para a próxima importação recompilar."""
    for path in FILES.values():
        for pyc in path.parent.glob(f"__pycache__/{path.stem}.*.pyc"):
            pyc.unlink(missing_ok=True)


def apply(text: str, old: str, new: str) -> str:
    """Troca ``old`` por ``new`` respeitando o fim de linha do arquivo; exige 1 ocorrência."""
    eol = "\r\n" if "\r\n" in text else "\n"
    old, new = old.replace("\n", eol), new.replace("\n", eol)
    if text.count(old) != 1:
        raise ValueError(f"âncora aparece {text.count(old)} vez(es)")
    return text.replace(old, new)


def main() -> int:
    """Roda todas as mutações; restaura os dois arquivos no final."""
    originals = {key: path.read_bytes() for key, path in FILES.items()}
    texts = {key: data.decode("utf-8") for key, data in originals.items()}
    tests = discover_tests()
    if not tests:
        print("Nenhum teste do G6 encontrado em tests/: nada a mutar.")
        return 1
    print(f"Testes escolhidos ({len(tests)}):", ", ".join(tests))
    if not run_tests(tests):
        print("Os testes NÃO passam no código original; corrija antes de mutar.")
        return 1
    survived: list[str] = []
    anchors: list[str] = []
    try:
        for key, name, old, new in MUTATIONS:
            label = f"{key}: {name}"
            try:
                mutated = apply(texts[key], old, new)
            except ValueError as exc:
                anchors.append(f"{label}: {exc}")
                print(f"[ÂNCORA] {label}: {exc}")
                continue
            FILES[key].write_bytes(mutated.encode("utf-8"))
            killed = not run_tests(tests)
            FILES[key].write_bytes(originals[key])
            print(f"[{'morta' if killed else 'SOBREVIVEU'}] {label}")
            if not killed:
                survived.append(label)
    finally:
        for key, path in FILES.items():
            path.write_bytes(originals[key])
        drop_bytecode()
    ok = len(MUTATIONS) - len(survived) - len(anchors)
    print(f"\n{len(MUTATIONS)} mutações: {ok} mortas, {len(survived)} sobreviveram, "
          f"{len(anchors)} com âncora inválida.")
    print("arquivos restaurados:", all(FILES[k].read_bytes() == originals[k] for k in FILES))
    return 0 if not survived and not anchors else 1


if __name__ == "__main__":
    raise SystemExit(main())
