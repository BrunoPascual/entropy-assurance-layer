"""Atualiza o cabeçalho de status do PROJECT.md e registra a nota do gate do Dia 5.

Duas mudanças, cada uma conferida antes de gravar:

1. A linha ``- **Status:** Dia 4 de 9 ...`` (ou uma versão anterior do Dia 5)
   vira a linha atual: Dia 5 concluído, com a revisão adversarial na seção 16.4.
   Se a linha já estiver como a atual, nada muda.
2. Logo depois da seção 16.3 (âncora ``dia5-gate:end``) entra uma nota com o
   fluxo real do gate. O texto é fixo e não tem números.

Uso (raiz do projeto)::

    py -3.12 -m scripts.atualizar_status_dia5

Sem argumentos e idempotente. Se algo não bater, para com código 1 sem gravar.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROJECT_REL = Path("PROJECT.md")
OLD_STATUS = "- **Status:** Dia 4 de 9"
NEW_STATUS = (
    "- **Status:** Dia 5 de 9 (concluído; gate do Dia 5 aprovado, ver seção 16.3; "
    "revisão adversarial na seção 16.4)"
)
# Textos que este script já gravou antes. Se o PROJECT.md ainda tiver uma destas linhas,
# ela é trocada pela atual.
PREVIOUS_STATUSES = (
    "- **Status:** Dia 5 de 9 (gate do Dia 5 aprovado, ver seção 16.3; "
    "fechamento do dia pendente: revisão adversarial, seção 11 do THREAT_MODEL "
    "e pendência do SOURCE.json)",
    "- **Status:** Dia 5 de 9 (gate do Dia 5 aprovado, ver seção 16.3; "
    "fechamento do dia pendente: revisão adversarial e seção 11 do THREAT_MODEL)",
)
GATE_END = "<!-- dia5-gate:end -->"
NOTE_START = "<!-- dia5-nota:start -->"
NOTE_END = "<!-- dia5-nota:end -->"
NOTE_BLOCK = "\n".join([
    NOTE_START,
    "**Nota sobre o gate do Dia 5.** O gate cumpre o fluxo abaixo. Não é um comando "
    "único que faz tudo:",
    "",
    "- `py -3.12 -m eal init-issuer` cria a chave do emissor de recibos. Precisa existir "
    "antes do primeiro `run`.",
    "- `py -3.12 -m eal run` deriva as chaves ML-KEM-768 e ML-DSA-65 da semente e grava "
    "no log encadeado o recibo assinado com ML-DSA-65. Ele não cria a chave do emissor.",
    "- `py -3.12 -m eal verify <recibo>` confere a assinatura, o formato e a posição do "
    "recibo na cadeia.",
    "",
    "As chaves privadas derivadas ficam só em memória (AT2 do THREAT_MODEL). A exceção "
    "`--export-demo` não faz parte deste gate.",
    NOTE_END,
])


class GateError(Exception):
    """Falha de conferência. Nada é gravado quando ela acontece."""


def _status_index(lines: list[str]) -> int:
    found = [i for i, line in enumerate(lines) if line.startswith("- **Status:**")]
    if len(found) != 1:
        raise GateError("esperava exatamente uma linha de Status no cabeçalho")
    return found[0]


def _upsert_note(text: str) -> str:
    starts, ends = text.count(NOTE_START), text.count(NOTE_END)
    if starts != ends or starts > 1:
        raise GateError("âncoras da nota do gate inconsistentes (devem aparecer em par, uma vez)")
    if starts == 0:
        if text.count(GATE_END) != 1:
            raise GateError("âncora de fim da seção 16.3 ausente ou repetida")
        return text.replace(GATE_END, GATE_END + "\n\n" + NOTE_BLOCK, 1)
    begin, finish = text.index(NOTE_START), text.index(NOTE_END)
    if finish < begin:
        raise GateError("âncora de fim da nota antes da de início")
    return text[:begin] + NOTE_BLOCK + text[finish + len(NOTE_END):]


def update_text(text: str) -> str:
    """Devolve o texto com o Status atualizado e a nota do gate. Texto em LF."""
    lines = text.split("\n")
    idx = _status_index(lines)
    line = lines[idx]
    if line == NEW_STATUS:
        pass
    elif line in PREVIOUS_STATUSES or line.startswith(OLD_STATUS):
        lines[idx] = NEW_STATUS
    else:
        raise GateError("a linha de Status não é a do Dia 4 nem a do Dia 5")
    return _upsert_note("\n".join(lines))


def write_project(path: Path) -> bool:
    """Atualiza o PROJECT.md mantendo as quebras de linha. True se mudou."""
    try:
        raw = Path(path).read_bytes()
    except OSError as exc:
        raise GateError("PROJECT.md não encontrado") from exc
    crlf = raw.count(b"\r\n")
    lf = raw.count(b"\n")
    if crlf not in (0, lf):
        raise GateError("o PROJECT.md mistura CRLF e LF")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise GateError("o PROJECT.md não é UTF-8") from exc
    norm = text.replace("\r\n", "\n")
    new_norm = update_text(norm)
    if new_norm == norm:
        return False
    new_text = new_norm.replace("\n", "\r\n") if crlf else new_norm
    Path(path).write_bytes(new_text.encode("utf-8"))
    return True


def build_parser() -> argparse.ArgumentParser:
    """Sem opções: o script só atualiza o PROJECT.md."""
    return argparse.ArgumentParser(
        prog="py -3.12 -m scripts.atualizar_status_dia5",
        description="Atualiza o Status do PROJECT.md e registra a nota do gate do Dia 5.")


def main(argv: Sequence[str] | None = None, *, _root: Path | None = None) -> int:
    """Ponto de entrada. ``_root`` existe só para testes."""
    build_parser().parse_args(argv)
    root = Path(_root) if _root is not None else PROJECT_ROOT
    try:
        changed = write_project(root / PROJECT_REL)
    except GateError as exc:
        print(f"erro: {exc}", file=sys.stderr)
        print("nada foi gravado", file=sys.stderr)
        return 1
    print("PROJECT.md: Status e nota do gate "
          + ("atualizados" if changed else "já estavam como esperado; nada mudou"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
