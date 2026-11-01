"""Dia 6, passo 4b: acrescenta ao eal/config.py as constantes de calibração e de metas da coleta.

Uso único, tudo ou nada, idempotente (na raiz do projeto):
    py -3.12 scripts\\atualizar_config_calibracao.py

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
ANCHOR = 'IBM_TOKEN_ENV = "IBM_QUANTUM_TOKEN"'
MARKER = "# --- Dia 6: reserva por job, calibração e metas da coleta ---"

# Linhas do bloco, sem fim de linha. O valor de cada constante está comentado em eal/config.py.
LINES: tuple[str, ...] = (
    MARKER,
    "QPU_RESERVE_SAFETY_FACTOR = 1.5  # reserva do job = ceil(custo alto x fator + extra)",
    "QPU_RESERVE_EXTRA_SECONDS = 2  # cobre o arredondamento do uso em segundos inteiros",
    "QPU_CALIBRATION_FIRST_SHOTS = 1000  # 1o job de calibração (156 qubits: 156 mil bits)",
    "QPU_CALIBRATION_FIRST_RESERVE_SECONDS = 20  # reserva do 1o job de calibração",
    "QPU_CALIBRATION_TARGET_SECONDS = 8  # duração alvo do 2o job de calibração",
    "QPU_TARGET_BITS_MIN = 2_000_000  # gate do Dia 6: 2 a 3 milhões de bits reais",
    "QPU_TARGET_BITS_MAX = 3_000_000",
    "QPU_BACKEND_QUBITS = 156  # num_qubits do ibm_kingston (lido em 31/10/2026)",
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
            raise ValueError("o bloco de calibração está presente, mas diferente do esperado")
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
