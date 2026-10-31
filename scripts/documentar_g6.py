"""Documentação do G6 no PROJECT.md (Dia 6): seções 6.2, 6.11, 16.4 e 17.

Uso (na raiz do projeto):  py -3.12 scripts\\documentar_g6.py

Cada trecho de ancoragem precisa aparecer exatamente uma vez. Tudo ou nada: se qualquer
conferência falhar, nada é gravado. Idempotente. Preserva CRLF. Imprime o numstat.
"""
from __future__ import annotations

import difflib
import hashlib
import sys
from pathlib import Path

MARKER = "G6 (Dia 6, resolvido)"

EDITS: list[tuple[str, str]] = [
    # 6.2: a linha do params passa a dizer o que chega ao recibo
    (
        "| `params` | dict | Ex.: backend, qubits, shots, job_id, modelo de ruído |",
        "| `params` | dict | Ex.: backend, qubits, shots, job_id, modelo de ruído. "
        "Só as chaves da lista fechada de `eal/config.py` (`RECEIPT_BATCH_PARAM_*`) chegam ao recibo (G6) |",
    ),
    # 6.11: nova regra do bloco "Regras" (depois da regra 4)
    (
        "4. Verificação (`eal verify`): recalcula o JSON canônico, confere a assinatura com a chave pública do emissor e confere o encadeamento.",
        "4. Verificação (`eal verify`): recalcula o JSON canônico, confere a assinatura com a chave pública do emissor e confere o encadeamento.\n"
        "5. Params do lote (G6, Dia 6): só as chaves da lista fechada em `eal/config.py` entram no bloco `batch_params` "
        "de cada fonte; token, semente e demais campos ficam de fora. Fonte `qpu_ibm` com lote exige `job_id` "
        "(recusa o recibo). Recibos anteriores ao G6 não têm o bloco e continuam válidos.",
    ),
    # 16.4: registro do G6 antes do marcador de fim da seção
    (
        "<!-- dia5-revisao:end -->",
        f"**{MARKER}:** params do lote no recibo. Passo 1 (`df231d7`): `SourceOutcome` carrega os params, fora do "
        "`to_dict()`. Passo 2 (`e0b4dd4`): lista fechada em `config.py`, bloco `batch_params` no builder e no esquema, "
        "`job_id` obrigatório em `qpu_ibm`. Verificação: suíte com 1623 passed e 1 skipped; cadeia real válida "
        "(posição 2 de 2, cabeça conferida); recibos antigos sem o bloco continuam válidos.\n\n"
        "<!-- dia5-revisao:end -->",
    ),
    # 17: a pendência de G6 vira resolvida
    (
        "- Os `params` do lote (ex.: `job_id` da IBM) não chegam ao recibo, porque o `PipelineResult` não guarda os lotes. Pendente antes da coleta do Dia 6 (G6).",
        "- Os `params` do lote (ex.: `job_id` da IBM) não chegavam ao recibo. Resolvido no Dia 6 (G6): ver a seção "
        "\"Limitações do Dia 6 (G6)\" abaixo.",
    ),
    # 17: nova subseção antes da etapa 3 do Dia 5
    (
        "### Limitações do Dia 5 (etapa 3: log encadeado)",
        "### Limitações do Dia 6 (G6: params do lote)\n\n"
        "- Recibos anteriores ao G6 não têm o bloco `batch_params`; a verificação aceita a ausência, então eles "
        "continuam válidos, mas não provam o `job_id` de nenhuma coleta.\n"
        "- Os nomes das chaves (`backend`, `job_id`, `shots`, `qubits`) e os formatos (texto de até 64 caracteres, "
        "inteiros de 1 a 10⁹) são as premissas deste protótipo. O adaptador da IBM ainda não existe: os nomes e os "
        "formatos reais do `job_id` e do número de qubits precisam ser conferidos na documentação do "
        "qiskit-ibm-runtime antes da coleta. Se o provedor usar outro formato, o recibo é recusado (fail-closed).\n"
        "- O `job_id` é guardado em claro no recibo. Ele não é segredo, mas revela que o job existiu na conta.\n"
        "- O recibo prova os params que o código entregou ao builder, não que a API da IBM devolveu esses valores.\n\n"
        "### Limitações do Dia 5 (etapa 3: log encadeado)",
    ),
]


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    path = root / "PROJECT.md"
    try:
        raw = path.read_bytes()
        text = raw.decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        print(f"RECUSADO: não consegui ler {path} ({type(exc).__name__}); nada foi gravado")
        return 1
    crlf = "\r\n" in text
    if crlf and text.count("\n") != text.count("\r\n"):
        print("RECUSADO: PROJECT.md mistura LF e CRLF; nada foi gravado")
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
    new = norm
    for old, repl in EDITS:
        new = new.replace(old, repl, 1)
    added = removed = 0
    for line in difflib.ndiff(norm.splitlines(), new.splitlines()):
        if line.startswith("+ "):
            added += 1
        elif line.startswith("- "):
            removed += 1
    out = new.replace("\n", "\r\n") if crlf else new
    data = out.encode("utf-8")
    path.write_bytes(data)
    print(f"aplicado em {path}: +{added} -{removed} linhas (conferir com git diff --numstat)")
    print(f"sha256 novo: {hashlib.sha256(data).hexdigest()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
