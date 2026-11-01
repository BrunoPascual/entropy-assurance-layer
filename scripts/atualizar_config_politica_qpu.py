"""Dia 6, passo 3a: acrescenta ao eal/config.py as constantes da política de QPU e da IBM.

Uso único, tudo ou nada, idempotente (na raiz do projeto):
    py -3.12 scripts\\atualizar_config_politica_qpu.py

- recusa, sem gravar nada, se a âncora não aparecer exatamente uma vez;
- recusa se o bloco estiver só pela metade, alterado, ou se uma das constantes já existir
  fora dele;
- preserva o fim de linha do arquivo (LF ou CRLF) e a codificação UTF-8;
- confere que o texto novo compila antes de gravar, e grava por arquivo temporário.

Rodar de novo com o bloco já aplicado não muda nada.
"""
from __future__ import annotations

import hashlib
import os
import re
import sys
from pathlib import Path

CONFIG = Path("eal/config.py")
ANCHOR = "QPU_TOTAL_BUDGET_SECONDS = 600"
MARKER = "# --- Dia 6: limite duro do orçamento de QPU (G7/T12) e acesso à IBM ---"

# Linhas do bloco, sem fim de linha. O valor de cada constante está comentado em eal/config.py.
LINES: tuple[str, ...] = (
    MARKER,
    "QPU_BUDGET_MARGIN_SECONDS = 30  # reserva que nunca é gasta (o consumo tem granularidade de 1 s)",
    "QPU_BUDGET_WINDOW_DAYS = 28  # janela móvel do plano Open (usage_period conferido em 31/10/2026)",
    "QPU_DAILY_CAP_SECONDS = 330  # teto das últimas 24 h (tabela 9.3: 5,5 min no Dia 6)",
    "QPU_MAX_JOB_RESERVE_SECONDS = 60  # maior max_execution_time aceito num job (rever após a calibração)",
    "QPU_MAX_SHOTS_PER_JOB = 100_000  # max_shots do ibm_kingston (backend.configuration(), 31/10/2026)",
    'QPU_USAGE_LOG_NAME = "qpu_usage.csv"  # em data/logs/, só com acréscimos',
    'IBM_DEFAULT_BACKEND = "ibm_kingston"',
    'IBM_DEFAULT_INSTANCE = "open-instance"',
    'IBM_TOKEN_ENV = "IBM_QUANTUM_TOKEN"  # nome da variável do .env; o valor nunca vai ao código',
)


def _constant_names() -> list[str]:
    """Nomes das constantes definidas pelo bloco (as linhas com ``=``, menos o marcador)."""
    return [line.split("=")[0].strip() for line in LINES[1:]]


def apply(text: str) -> str:
    """Devolve o texto com o bloco inserido logo depois da linha da âncora.

    ValueError se algo estiver fora do esperado. Se o bloco já está lá, devolve o texto igual.
    """
    eol = "\r\n" if "\r\n" in text else "\n"
    inserted = eol + eol + eol.join(LINES)
    if MARKER in text:
        if text.count(inserted) != 1:
            raise ValueError("o bloco do Dia 6 está presente, mas diferente do esperado")
        return text
    for name in _constant_names():
        if re.search(rf"^{re.escape(name)}\s*=", text, flags=re.MULTILINE):
            raise ValueError(f"a constante {name} já existe fora do bloco")
    if text.count(ANCHOR) != 1:
        raise ValueError(f"a âncora aparece {text.count(ANCHOR)} vez(es), esperado 1")
    start = text.index(ANCHOR)
    end = text.find(eol, start)
    if end == -1:  # a âncora está na última linha, sem quebra de linha final
        return text + inserted + eol
    return text[:end] + inserted + text[end:]


def _sha256(data: bytes) -> str:
    """SHA-256 em maiúsculas, igual ao Get-FileHash do PowerShell."""
    return hashlib.sha256(data).hexdigest().upper()


def main() -> int:
    """Aplica o bloco ao eal/config.py; devolve 0 se aplicou ou já estava aplicado."""
    try:
        original = CONFIG.read_bytes()
        text = original.decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        print(f"RECUSADO (nada foi gravado): não consegui ler {CONFIG} como UTF-8 ({type(exc).__name__})")
        return 1
    try:
        new = apply(text)
        if new == text:
            print("já aplicado: nada a fazer")
            return 0
        compile(new.removeprefix("\ufeff"), str(CONFIG), "exec")  # o BOM vale em arquivo, não em texto
    except (ValueError, SyntaxError) as exc:
        print(f"RECUSADO (nada foi gravado): {exc}")
        return 1
    tmp = CONFIG.with_name(CONFIG.name + ".tmp")
    tmp.write_bytes(new.encode("utf-8"))
    os.replace(tmp, CONFIG)
    final = CONFIG.read_bytes()
    if final != new.encode("utf-8"):
        print("ERRO: o arquivo gravado não confere com o texto novo")
        return 1
    print(f"aplicado: {len(LINES)} linhas acrescentadas em {CONFIG}")
    print(f"SHA-256 antes:  {_sha256(original)}")
    print(f"SHA-256 depois: {_sha256(final)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
