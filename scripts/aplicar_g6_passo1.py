"""G6, passo 1: o SourceOutcome passa a carregar os params do lote (eal/pipeline.py).

Uso (na raiz do projeto):  py -3.12 scripts\\aplicar_g6_passo1.py [caminho do pipeline.py]

Idempotente, preserva LF ou CRLF e recusa sem gravar se qualquer conferência falhar.
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

MARKER = "def _batch_params("

EDITS: list[tuple[str, str]] = [
    (
        "    reasons: tuple[str, ...] = ()\n",
        "    reasons: tuple[str, ...] = ()\n"
        "    # G6: cópia rasa dos params do lote (job_id etc.), só para o recibo. Fica fora do\n"
        "    # to_dict() e da comparação; quem decide o que vai para o recibo é o builder.\n"
        "    params: dict[str, Any] | None = field(default=None, repr=False, compare=False)\n",
    ),
    (
        "def _process(\n",
        "def _batch_params(batch: Any) -> dict[str, Any] | None:\n"
        '    """Cópia rasa dos params do lote (G6); None se o lote não tiver um dict."""\n'
        '    params = getattr(batch, "params", None)\n'
        "    return dict(params) if isinstance(params, dict) else None\n"
        "\n\n"
        "def _process(\n",
    ),
    (
        'return SourceOutcome(sid, "health_failed", batch.batch_id, (reason,)), None',
        'return SourceOutcome(sid, "health_failed", batch.batch_id, (reason,), _batch_params(batch)), None',
    ),
    (
        'return SourceOutcome(sid, "extraction_failed", batch.batch_id, (str(problem),)), None',
        'return SourceOutcome(\n'
        '            sid, "extraction_failed", batch.batch_id, (str(problem),), _batch_params(batch)\n'
        '        ), None',
    ),
    (
        'return SourceOutcome(sid, "candidate", batch.batch_id), make_mix_input(batch, report, extraction)',
        'outcome = SourceOutcome(sid, "candidate", batch.batch_id, (), _batch_params(batch))\n'
        "    return outcome, make_mix_input(batch, report, extraction)",
    ),
]


def main() -> int:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[1] / "eal" / "pipeline.py"
    try:
        raw = path.read_bytes()
        text = raw.decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        print(f"RECUSADO: não consegui ler {path} ({type(exc).__name__})")
        return 1
    crlf = "\r\n" in text
    if crlf and text.count("\n") != text.count("\r\n"):
        print("RECUSADO: o arquivo mistura LF e CRLF; nada foi gravado")
        return 1
    norm = text.replace("\r\n", "\n")
    if MARKER in norm:
        if all(new in norm for _, new in EDITS):
            print("já aplicado; nada a fazer")
            return 0
        print("RECUSADO: aplicação parcial anterior; nada foi gravado")
        return 1
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
