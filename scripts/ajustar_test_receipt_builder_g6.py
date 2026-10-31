"""G6, passo 2: o cenário ibm_x do test_receipt_builder.py passa a ter job_id nos params do lote.

Uso (na raiz do projeto):  py -3.12 scripts\\ajustar_test_receipt_builder_g6.py [caminho]

Só três trocas, cada uma precisa aparecer exatamente uma vez. Tudo ou nada, idempotente,
preserva LF ou CRLF e recusa sem gravar se qualquer conferência falhar.
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

EDITS: list[tuple[str, str]] = [
    (
        "def _outcome(sid, status, batch_id=None, reasons=()):\n"
        "    return SimpleNamespace(source_id=sid, status=status, batch_id=batch_id, reasons=reasons)\n",
        "def _outcome(sid, status, batch_id=None, reasons=(), params=None):\n"
        "    return SimpleNamespace(source_id=sid, status=status, batch_id=batch_id, reasons=reasons,\n"
        "                           params=params)\n",
    ),
    (
        '_outcome("ibm_x", "mixed", "b-x"),',
        '_outcome("ibm_x", "mixed", "b-x", params={"job_id": "job-x-1"}),',
    ),
    (
        '_outcome("ibm_ruim", "excluded", "b-r", ("APT: viés",)),',
        '_outcome("ibm_ruim", "excluded", "b-r", ("APT: viés",), params={"job_id": "job-r-1"}),',
    ),
]
MARKER = 'params={"job_id": "job-x-1"}'


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else root / "tests" / "test_receipt_builder.py"
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
    for i, (old, _) in enumerate(EDITS, start=1):
        n = norm.count(old)
        if n != 1:
            print(f"RECUSADO: trecho {i} aparece {n} vez(es), esperado 1; nada foi gravado")
            return 1
    for old, new in EDITS:
        norm = norm.replace(old, new, 1)
    out = norm.replace("\n", "\r\n") if crlf else norm
    data = out.encode("utf-8")
    path.write_bytes(data)
    print(f"aplicado em {path} ({'CRLF' if crlf else 'LF'}); sha256 novo: {hashlib.sha256(data).hexdigest()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
