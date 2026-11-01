"""Mutações manuais das linhas novas de scripts/inventario_coleta1.py (DEP_SESSAO, passo 1).

Uso:  py -3.12 scripts\\mutacoes_inventario_sessao.py

Cada mutação troca um trecho único; se o trecho não aparecer exatamente uma vez, conta como
"âncora inválida". Os testes rodam sem cache e sem bytecode; o módulo é sempre restaurado.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODULE = Path("scripts/inventario_coleta1.py")
TESTS = ["tests/test_inventario_sessao.py", "tests/test_inventario_coleta1.py"]

MUTATIONS = [
    ("sessao sem validacao",
     "if not isinstance(session, str) or not SESSION_RE.fullmatch(session):",
     "if not isinstance(session, str):"),
    ("sublinhado aceito na sessao",
     'SESSION_RE = re.compile(r"[A-Za-z0-9]+")', 'SESSION_RE = re.compile(r"[A-Za-z0-9_]+")'),
    ("validacao parcial (match em vez de fullmatch)",
     "SESSION_RE.fullmatch(session)", "SESSION_RE.match(session)"),
    ("sessao nao repassada ao build_rows",
     "rows = build_rows(raw_dir, log_path, session)", "rows = build_rows(raw_dir, log_path)"),
    ("saida nao derivada da sessao",
     "out_path = out_path_for(session)", "out_path = OUT_PATH"),
    ("out_path explicito ignorado",
     "        if out_path is None:\n            out_path = out_path_for(session)",
     "        out_path = out_path_for(session)"),
    ("nome da saida errado",
     'return Path(f"data/results/dia6_{session}_inventario.csv")',
     'return Path(f"data/results/dia6_{session}.csv")'),
    ("sessao validada depois de ler",
     "        session = check_session(session)\n",
     ""),
    ("cli ignora --sessao",
     "return main(session=args.sessao)", "return main()"),
]


def _run_tests() -> bool:
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    done = subprocess.run([sys.executable, "-m", "pytest", "-q", "-x", "-p", "no:cacheprovider",
                           *TESTS], cwd=ROOT, env=env, capture_output=True, text=True)
    return done.returncode == 0


def _drop_bytecode() -> None:
    for pyc in (ROOT / MODULE.parent / "__pycache__").glob(MODULE.stem + ".*.pyc"):
        pyc.unlink(missing_ok=True)


def main() -> int:
    path = ROOT / MODULE
    raw = path.read_bytes()
    crlf = b"\r\n" in raw
    text = raw.decode("utf-8").replace("\r\n", "\n")
    killed = survived = invalid = 0
    try:
        _drop_bytecode()
        if not _run_tests():
            print("Os testes já falham sem mutação; nada foi mutado.")
            return 2
        for name, old, new in MUTATIONS:
            if text.count(old) != 1:
                print(f"[ancora invalida] {name}")
                invalid += 1
                continue
            mutated = text.replace(old, new)
            path.write_bytes((mutated.replace("\n", "\r\n") if crlf else mutated).encode("utf-8"))
            _drop_bytecode()
            try:
                if _run_tests():
                    print(f"[SOBREVIVEU] {name}")
                    survived += 1
                else:
                    print(f"[morta] {name}")
                    killed += 1
            finally:
                path.write_bytes(raw)
                _drop_bytecode()
    finally:
        path.write_bytes(raw)
    restored = path.read_bytes() == raw
    print(f"\n{len(MUTATIONS)} mutações: {killed} mortas, {survived} sobreviveram, "
          f"{invalid} com âncora inválida.")
    print(f"módulo restaurado: {restored}")
    return 0 if survived == 0 and invalid == 0 and restored else 1


if __name__ == "__main__":
    sys.exit(main())
