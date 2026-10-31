"""F12, passo 2 (correção): o stub fake_keygen de tests/test_cli_revisao_parte1.py aceita o
argumento logs_dir que o _run_keygen passou a receber.

Causa: o stub substitui cli._run_keygen e tem assinatura fixa de três argumentos; o passo 2 chama
_run_keygen com um quarto argumento, então o stub levanta TypeError e os três testes test_f4_* quebram.
Correção: um parâmetro a mais, com default None (a chamada antiga continua válida).

Uso (na raiz do projeto):  py -3.12 scripts\\ajustar_stub_f12.py [caminho]

Uma âncora, exatamente uma ocorrência. Idempotente, preserva LF ou CRLF, recusa sem gravar.
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

OLD = "    def fake_keygen(sources, seed_source, n_bits):\n"
NEW = "    def fake_keygen(sources, seed_source, n_bits, logs_dir=None):  # F12: _run_keygen recebe logs_dir\n"
MARKER = "def fake_keygen(sources, seed_source, n_bits, logs_dir=None)"


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else root / "tests" / "test_cli_revisao_parte1.py"
    try:
        text = path.read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        print(f"RECUSADO: não consegui ler {path} ({type(exc).__name__}); nada foi gravado")
        return 1
    crlf = "\r\n" in text
    if crlf and text.count("\n") != text.count("\r\n"):
        print("RECUSADO: o arquivo mistura LF e CRLF; nada foi gravado")
        return 1
    norm = text.replace("\r\n", "\n")
    if MARKER in norm:
        print("já aplicado; nada a fazer")
        return 0
    n = norm.count(OLD)
    if n != 1:
        print(f"RECUSADO: a âncora aparece {n} vez(es), esperado 1; nada foi gravado")
        return 1
    norm = norm.replace(OLD, NEW, 1)
    out = norm.replace("\n", "\r\n") if crlf else norm
    data = out.encode("utf-8")
    path.write_bytes(data)
    print(f"aplicado em {path} ({'CRLF' if crlf else 'LF'}); sha256 novo: {hashlib.sha256(data).hexdigest()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
