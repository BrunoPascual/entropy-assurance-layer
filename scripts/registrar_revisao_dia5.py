"""Registro da revisão adversarial do Dia 5 no PROJECT.md (seção 16.4).

Duas mudanças, conferidas antes de gravar:

1. A seção 16.4, entre âncoras, logo depois da nota do gate do Dia 5
   (``<!-- dia5-nota:end -->``). Ela traz os achados de cada parte revisada e a
   decisão tomada. Rodar de novo substitui o bloco pelo texto atual deste
   script, então as partes 2 e 3 entram atualizando este arquivo.
2. A limitação já existente sobre a gravação não atômica do log (achado F2)
   ganha o procedimento de reparo manual. A linha antiga precisa estar INTEIRA
   e uma vez só; se tiver sido editada à mão, o script recusa.

Idempotente. Se algo não bater, para com código 1 sem gravar nada.

Uso (raiz do projeto)::

    py -3.12 -m scripts.registrar_revisao_dia5
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROJECT_REL = Path("PROJECT.md")
AFTER = "<!-- dia5-nota:end -->"
START = "<!-- dia5-revisao:start -->"
END = "<!-- dia5-revisao:end -->"

OLD_F2_LINE = (
    "- A gravação em dois arquivos não é atômica. Se o processo cair entre a linha e o "
    "`<receipt_id>.json`, o log fica com uma linha sem arquivo e passa a recusar novas "
    "gravações (fail-closed) até uma intervenção manual; não há comando de reparo."
)
NEW_F2_LINE = (
    OLD_F2_LINE + " O reparo é recriar `<receipt_id>.json` com os mesmos bytes da linha do "
    "log seguidos de `\\n`, gravado em modo binário (um editor pode trocar `\\n` por "
    "`\\r\\n`), e conferir com `eal verify`. Se a queda deixar uma linha incompleta no fim do "
    "log, o reparo é outro (remover essa linha) e não foi testado. Ver achado F2 na seção 16.4."
)

PART1_FILES = (
    ("eal/cli.py", "0ADAC6167E0A570F56BA1D0C4A220AFB6F2A96F1BEBFFD9F564FBC076040DFA5"),
    ("eal/receipt/chain.py", "779BE0DA09A47EAC1F39AF65A7F9C89977FE67669D7FA7409DDBC1132D2685FE"),
    ("eal/receipt/verify.py", "371DD71FFA5B99078EB044008AFE7AB0D997FF070763D3D9C0956DAF5F598733"),
)
PART1_ROWS = (
    ("F1", "Baixa", "`cli.py`, `verify`",
     "`--sem-cadeia` com `--expected-head` ignorava a cabeça em silêncio; só aparecia o "
     "aviso de cadeia não conferida. Confirmado por execução.",
     "Corrigido: juntas, as duas opções são erro de uso (código 2), antes de ler o arquivo. "
     "Testes em `tests/test_cli_revisao_parte1.py`."),
    ("F2", "Baixa (disponibilidade)", "`chain.py`, `append_receipt`",
     "Uma linha no log sem o arquivo individual deixa a cadeia inválida, e o `run` recusa "
     "antes do pipeline. Confirmado por execução, numa cópia.",
     "Já estava documentado (seção 17, etapa 3). A limitação ganhou o procedimento de reparo "
     "manual."),
    ("F3", "Baixa", "`chain.py`",
     "Sem trava contra duas gravações simultâneas: a cadeia é acusada como quebrada e para; "
     "não aceita o recibo errado.",
     "Já estava documentado; sem mudança."),
    ("F4", "Baixa (latente)", "`cli.py`, `run`",
     "`--sources` era validado e nunca lido.",
     "Corrigido: a lista que valida o argumento é a mesma que cria as fontes "
     "(`_SOURCE_FACTORIES`). Testes no mesmo arquivo de F1."),
    ("F5", "Informativa", "`verify.py`, `verify_receipt_text`",
     "O motivo \"JSON inválido\" inclui o texto do erro do parser de JSON.",
     "Aceito sem mudança: o texto traz só a posição e mensagens fixas, nunca conteúdo do "
     "recibo, e ajuda a diagnosticar."),
    ("F6", "Informativa", "`cli.py` e `chain.py`",
     "O `run` verifica a cadeia inteira duas vezes (uma verificação ML-DSA por linha).",
     "A medir quando a cadeia crescer. A primeira passada é a que evita gastar entropia com "
     "log ruim."),
)
PART1_PENDING = (
    "se `save_issuer_key` grava em modo exclusivo (o `init-issuer` confere a existência da "
    "chave antes de rodar o pipeline); se `is_hex64` aceita só minúsculas; o que "
    "`PipelineResult.to_dict()` leva ao log de falhas; o mínimo aceito em `--bits`; e se "
    "`validate_body` recusa campos a mais no corpo assinado."
)


class RegError(Exception):
    """Falha de conferência. Nada é gravado quando ela acontece."""


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def render_block() -> str:
    """Texto da seção 16.4, com as âncoras."""
    files = "; ".join(f"`{path}` (SHA-256 `{sha}`)" for path, sha in PART1_FILES)
    rows = ["| " + " | ".join(_cell(c) for c in row) + " |" for row in PART1_ROWS]
    return "\n".join([
        START,
        "### 16.4 Revisão adversarial do Dia 5",
        "",
        "Feita por leitura do código, em partes, a partir do arquivo que o coletor gera "
        "(`revisao_adversarial_parteN_*.txt`), com o commit lido e o SHA-256 de cada arquivo. "
        "O que foi confirmado por execução está dito em cada achado; o resto é leitura e não "
        "prova ausência de defeitos.",
        "",
        f"**Parte 1 (31/10/2026), commit `90d15b8`.** {files}.",
        "",
        "| ID | Gravidade | Onde | Achado | Decisão |",
        "| --- | --- | --- | --- | --- |",
        *rows,
        "",
        f"**Pendente para as partes 2 e 3:** {PART1_PENDING}",
        END,
    ])


def _upsert_block(text: str, block: str) -> str:
    starts, ends = text.count(START), text.count(END)
    if starts != ends or starts > 1:
        raise RegError("âncoras da seção 16.4 inconsistentes (devem aparecer em par, uma vez)")
    if starts == 0:
        if text.count(AFTER) != 1:
            raise RegError("âncora da nota do gate do Dia 5 ausente ou repetida")
        return text.replace(AFTER, AFTER + "\n\n" + block, 1)
    begin, finish = text.index(START), text.index(END)
    if finish < begin:
        raise RegError("âncora de fim da seção 16.4 antes da de início")
    return text[:begin] + block + text[finish + len(END):]


def _update_f2_line(text: str) -> str:
    lines = text.split("\n")
    n_new, n_old = lines.count(NEW_F2_LINE), lines.count(OLD_F2_LINE)
    if (n_new, n_old) == (1, 0):
        return text
    if (n_new, n_old) != (0, 1):
        raise RegError("a linha da limitação de gravação não atômica não aparece inteira, uma vez")
    lines[lines.index(OLD_F2_LINE)] = NEW_F2_LINE
    return "\n".join(lines)


def update_text(text: str) -> str:
    """Devolve o texto (em LF) com a seção 16.4 e a limitação de F2 atualizadas."""
    return _upsert_block(_update_f2_line(text), render_block())


def write_project(path: Path) -> bool:
    """Atualiza o PROJECT.md mantendo as quebras de linha. True se mudou."""
    try:
        raw = Path(path).read_bytes()
    except OSError as exc:
        raise RegError("PROJECT.md não encontrado") from exc
    crlf = raw.count(b"\r\n")
    if crlf not in (0, raw.count(b"\n")):
        raise RegError("o PROJECT.md mistura CRLF e LF")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise RegError("o PROJECT.md não é UTF-8") from exc
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
        prog="py -3.12 -m scripts.registrar_revisao_dia5",
        description="Registra a revisão adversarial do Dia 5 no PROJECT.md (seção 16.4).")


def main(argv: Sequence[str] | None = None, *, _root: Path | None = None) -> int:
    """Ponto de entrada. ``_root`` existe só para testes."""
    build_parser().parse_args(argv)
    root = Path(_root) if _root is not None else PROJECT_ROOT
    try:
        changed = write_project(root / PROJECT_REL)
    except RegError as exc:
        print(f"erro: {exc}", file=sys.stderr)
        print("nada foi gravado", file=sys.stderr)
        return 1
    print("PROJECT.md: seção 16.4 e limitação de F2 "
          + ("gravadas" if changed else "já estavam como esperado; nada mudou"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
