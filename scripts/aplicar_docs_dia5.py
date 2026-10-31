"""Aplica de uma vez os tres scripts de documentacao do fechamento do Dia 5.

Ordem: THREAT_MODEL v1.2 -> secao 16.4 do PROJECT.md -> Status "Dia 5 concluido".
Cada script ja e idempotente e recusa sem gravar; este orquestrador acrescenta:

  1. Pre-condicao: PROJECT.md e THREAT_MODEL.md sem alteracao em relacao ao HEAD
     (ou ja exatamente no estado final esperado, o que permite rodar de novo).
  2. Copia dos bytes originais dos dois arquivos antes de comecar.
  3. Se QUALQUER passo falhar, ou o numstat final nao bater (PROJECT.md 15 e 3;
     THREAT_MODEL.md 14 e 3), os dois arquivos voltam byte a byte ao original.
  4. Nao faz commit, nao toca em codigo nem em testes.

Uso (raiz do projeto)::

    py -3.12 scripts\\aplicar_docs_dia5.py
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DOCS = ("PROJECT.md", "THREAT_MODEL.md")
STEPS = (
    "scripts.atualizar_threat_model_v12",
    "scripts.registrar_revisao_dia5",
    "scripts.atualizar_status_dia5",
)
EXPECTED = {"PROJECT.md": (15, 3), "THREAT_MODEL.md": (14, 3)}


def _git(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")


def _numstat(root: Path) -> dict:
    res = _git(root, "diff", "--numstat", "--", *DOCS)
    if res.returncode != 0:
        raise RuntimeError(f"git diff falhou: {res.stderr.strip()}")
    out: dict = {}
    for line in res.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) != 3:
            continue
        out[parts[2]] = (int(parts[0]), int(parts[1])) if parts[0].isdigit() and parts[1].isdigit() else None
    return out


def _restore(root: Path, originals: dict[str, bytes]) -> None:
    for name, data in originals.items():
        (root / name).write_bytes(data)
    print("Arquivos restaurados ao estado original (byte a byte).")


def _fmt(state: dict) -> str:
    return ", ".join(f"{k} {v}" for k, v in sorted(state.items())) or "sem alteracao"


def run(root: Path = PROJECT_ROOT, steps=STEPS, expected=None) -> int:
    expected = EXPECTED if expected is None else expected
    for name in DOCS:
        if not (root / name).is_file():
            print(f"RECUSADO: {name} nao encontrado em {root}")
            return 1
    try:
        before = _numstat(root)
    except (RuntimeError, OSError) as exc:
        print(f"RECUSADO: {exc}")
        return 1
    if before not in ({}, expected):
        print("RECUSADO: PROJECT.md/THREAT_MODEL.md ja tem alteracoes diferentes do esperado.")
        print(f"  encontrado: {_fmt(before)}")
        print("  Confira com 'git diff --stat' antes de seguir. Nada foi gravado.")
        return 1

    originals = {name: (root / name).read_bytes() for name in DOCS}
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    for module in steps:
        print(f"== {module}")
        res = subprocess.run([sys.executable, "-m", module], cwd=root, capture_output=True, env=env)
        text = (res.stdout + res.stderr).decode("utf-8", "replace").rstrip()
        for line in text.splitlines():
            print(f"   {line}")
        if res.returncode != 0:
            print(f"FALHOU: {module} saiu com codigo {res.returncode}.")
            _restore(root, originals)
            return 1

    try:
        after = _numstat(root)
    except (RuntimeError, OSError) as exc:
        print(f"FALHOU: {exc}")
        _restore(root, originals)
        return 1
    print(f"numstat final: {_fmt(after)}")
    if after != expected:
        print(f"FALHOU: numstat esperado {_fmt(expected)}.")
        _restore(root, originals)
        return 1
    print("Pronto. Documentacao do Dia 5 aplicada e conferida. Nada foi commitado.")
    return 0


def main(argv=None) -> int:
    try:
        sys.stdout.reconfigure(errors="replace")
    except (AttributeError, ValueError):
        pass
    argparse.ArgumentParser(description=__doc__.splitlines()[0]).parse_args(argv)
    return run()


if __name__ == "__main__":
    sys.exit(main())
