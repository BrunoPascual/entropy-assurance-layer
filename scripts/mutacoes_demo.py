"""Mutações manuais da demo do Dia 5 (etapa 5).

Altera ``scripts/demo_dia5.py`` de propósito, uma mutação por vez, roda os
testes rápidos (``tests/test_demo_dia5.py``, sem a fonte ``os`` real) e
confere se algum teste acusa. Mutação sobrevivente = teste faltando.

Regras: cada trecho a mutar aparece exatamente uma vez (senão nada é
alterado); o arquivo original é restaurado depois de cada mutação e no
``finally``, e conferido byte a byte no fim.

Uso (raiz do projeto, saída ao vivo)::

    py -3.12 -u -m scripts.mutacoes_demo

Isso mostra que os testes pegam esses erros, não que a demo esteja correta.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "scripts" / "demo_dia5.py"
TESTS = "tests/test_demo_dia5.py"
TIMEOUT_SECONDS = 600

# (nome, trecho original, trecho mutado). Escritos com "\n"; o script troca
# por "\r\n" se o arquivo estiver com CRLF.
MUTATIONS: list[tuple[str, str, str]] = [
    ("aceita pasta que já existe",
     "    if demo_dir.exists():\n",
     "    if False and demo_dir.exists():\n"),
    ("aceita pasta nova dentro do projeto",
     "    return c == p or p in c.parents\n",
     "    return c == p\n"),
    ("should_retry repete em qualquer stage",
     '        and entry.get("stage") == RETRY_STAGE\n',
     "        and True\n"),
    ("should_retry ignora o command",
     '        entry.get("command") == command\n',
     "        True\n"),
    ("should_retry permite uma tentativa a mais",
     "    if code != 1 or attempt >= max_attempts or len(entries) != 1:\n",
     "    if code != 1 or attempt > max_attempts or len(entries) != 1:\n"),
    ("tamper_copy troca todas as ocorrências",
     "data.replace(TAMPER_OLD, TAMPER_NEW, 1)",
     "data.replace(TAMPER_OLD, TAMPER_NEW)"),
    ("truncate_chain_copy não tira o último recibo",
     r'write_bytes(b"\n".join(lines[:-1]) + b"\n")',
     r'write_bytes(b"\n".join(lines) + b"\n")'),
    ("_step ignora o texto esperado",
     "    ok = result.code == expected and not missing and extra_ok\n",
     "    ok = result.code == expected and extra_ok\n"),
    ("passo 7 usa a cabeça certa",
     '"--expected-head", WRONG_HEAD], demo)',
     '"--expected-head", head], demo)'),
    ("run_demo roda init/run fora da pasta da demo",
     "        result = runner(args, demo)\n",
     "        result = runner(args, demo.parent)\n"),
    ("build_cli_env sem PYTHONIOENCODING",
     '    env["PYTHONIOENCODING"] = "utf-8"\n',
     "    pass\n"),
    ("main devolve sempre 0",
     "    return EXIT_OK if report.ok else EXIT_DEMO_FAILED\n",
     "    return EXIT_OK\n"),
    ("main mostra a mensagem da exceção inesperada",
     'print(f"erro inesperado: {type(exc).__name__}", file=sys.stderr)',
     'print(f"erro inesperado: {type(exc).__name__}: {exc}", file=sys.stderr)'),
    ("run_demo não confere o recibo novo do run",
     "        extra_ok = ids is not None and len(ids) == expected_receipts\n",
     "        extra_ok = True\n"),
]


def run_tests() -> int:
    """Roda os testes rápidos da demo e devolve o código de saída do pytest."""
    env = dict(os.environ)
    env.pop("EAL_E2E", None)  # nunca roda o teste com a os real aqui
    env["PYTHONDONTWRITEBYTECODE"] = "1"  # evita bytecode velho da versão mutada
    proc = subprocess.run(
        [sys.executable, "-B", "-m", "pytest", TESTS, "-q", "-x", "-p", "no:cacheprovider"],
        cwd=str(ROOT), env=env, capture_output=True, timeout=TIMEOUT_SECONDS, check=False,
    )
    return proc.returncode


def _anchors(original: bytes) -> list[tuple[str, bytes, bytes]] | None:
    newline = "\r\n" if b"\r\n" in original else "\n"
    out: list[tuple[str, bytes, bytes]] = []
    for name, old, new in MUTATIONS:
        old_b = old.replace("\n", newline).encode("utf-8")
        new_b = new.replace("\n", newline).encode("utf-8")
        count = original.count(old_b)
        if count != 1:
            print(f"trecho de '{name}' aparece {count} vez(es); nada foi alterado")
            return None
        out.append((name, old_b, new_b))
    return out


def main() -> int:
    """Roda todas as mutações; 0 só se todas morrerem e o arquivo voltar intacto."""
    original = TARGET.read_bytes()
    anchors = _anchors(original)
    if anchors is None:
        return 2
    print(f"{len(anchors)} mutações; linha de base (sem mutação)...", flush=True)
    base = run_tests()
    if base != 0:
        print(f"os testes não estão verdes sem mutação (pytest saiu com {base}); abortado")
        return 2
    survivors: list[str] = []
    try:
        for index, (name, old_b, new_b) in enumerate(anchors, start=1):
            mutated = original.replace(old_b, new_b, 1)
            TARGET.write_bytes(mutated)
            start = time.monotonic()
            try:
                code = run_tests()
            finally:
                TARGET.write_bytes(original)
            verdict = "morta" if code != 0 else "SOBREVIVEU"
            print(f"[{index:2}/{len(anchors)}] {verdict} (pytest {code}, "
                  f"{time.monotonic() - start:.1f} s): {name}", flush=True)
            if code == 0:
                survivors.append(name)
    finally:
        TARGET.write_bytes(original)
    intact = TARGET.read_bytes() == original
    print(f"arquivo restaurado byte a byte: {'sim' if intact else 'NÃO'}")
    print(f"resultado: {len(anchors) - len(survivors)} de {len(anchors)} mortas")
    for name in survivors:
        print(f"  sobrevivente: {name}")
    return 0 if intact and not survivors else 1


if __name__ == "__main__":
    sys.exit(main())
