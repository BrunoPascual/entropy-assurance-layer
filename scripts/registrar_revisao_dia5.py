"""Registro da revisão adversarial do Dia 5 no PROJECT.md (seção 16.4).

Duas mudanças, conferidas antes de gravar:

1. A seção 16.4, entre âncoras, logo depois da nota do gate do Dia 5
   (``<!-- dia5-nota:end -->``). Ela traz os achados das três partes revisadas
   (F1 a F12) e a decisão tomada em cada um. Rodar de novo substitui o bloco
   pelo texto atual deste script.
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

PARTS = (
    ("Parte 1", "90d15b8", (
        ("eal/cli.py", "0ADAC6167E0A570F56BA1D0C4A220AFB6F2A96F1BEBFFD9F564FBC076040DFA5"),
        ("eal/receipt/chain.py", "779BE0DA09A47EAC1F39AF65A7F9C89977FE67669D7FA7409DDBC1132D2685FE"),
        ("eal/receipt/verify.py", "371DD71FFA5B99078EB044008AFE7AB0D997FF070763D3D9C0956DAF5F598733"),
    )),
    ("Parte 2", "20e7055", (
        ("eal/pqc/keygen.py", "005C589DF037D54ACE97863BCA3B4CE5EAFE5723896D2BCE31A82B50AD6B4F81"),
        ("eal/receipt/builder.py", "313F49039BD338A7C0635FE3FF3C274945982CC8367FB04B16F0C9A47A31E7EA"),
        ("eal/receipt/sign.py", "496646F61566563C5F1DE6F3F715B6ACCF035D3E658E55C6CA111D71D923A3FB"),
        ("eal/receipt/schema.py", "731FCC7D8B52F54C8B603E51D21FFB722990B4C05939B1BA44B724AA9AE87AC3"),
    )),
    ("Parte 3", "20e7055", (
        ("eal/mix/mixer.py", "4B0D47C93C2F41152BCE47C834E01F085D7635214DA98CA7AE7B293A1B929807"),
        ("eal/pipeline.py", "5B6D4DFD862D81B390ACA90A41521ABC82057C7465D23A260A8F230628296A80"),
        ("eal/config.py", "98DB40E62374FB4A6458C730CCFDC97C4D453B2353C57DE98C9082D06093BD74"),
        ("eal/health/report.py", "FCAD8168F5AF5C34443C4CE4475EF44D31AAA53651DC5210BC69A1BDE12F8095"),
        ("eal/extract/toeplitz.py", "6930DFACEE5F36C3395CF849E6A22EA6044F4E0CC48B4C9E8B2F85AFA317D9AC"),
        ("eal/extract/budget.py", "AB3EE27C0E810A593381985BB344B70ED10F4B95BCAE445B5ADDF62F28FD4765"),
        ("eal/extract/blocks.py", "CF19EF4E795026914019626FC414AE75E0FCBCB3F0CD96170676E54AD04C64FA"),
        ("eal/extract/sha3.py", "1DD58535A853B1E2816E097F2E088D9186DADF83AD4F963611FD7125DEF416EC"),
    )),
)
ROWS = (
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
    ("F7", "Baixa (disponibilidade)", "`sign.py`, `cli.py`",
     "A `.pk` é gravada antes da `.sk`; se a segunda falhar, `init-issuer` recusa (\"já "
     "existe\") e `run` manda rodar `init-issuer`: um beco sem saída. Confirmado por "
     "execução no `sign.py`; o efeito na CLI é pela leitura.",
     "Corrigido: `init-issuer` e `run` detectam o par incompleto e dizem qual arquivo falta e "
     "o que fazer."),
    ("F8", "Baixa (mensagem)", "`schema.py`, `chain.py`, `cli.py`",
     "`--expected-head` em maiúsculas (como o `Get-FileHash` imprime) era recusado como "
     "cabeça diferente. Confirmado por execução.",
     "Corrigido: o argumento é normalizado para minúsculas e sem espaços; a comparação "
     "continua exata."),
    ("F9", "Baixa (endurecimento)", "`schema.py`, `report.py`, `builder.py`",
     "O validador não olha dentro de `mixer`, `sources[i]` etc., e `HealthReport.to_dict()` "
     "usa `asdict`: um campo novo iria para o recibo assinado sem alarme. Hoje nenhum desses "
     "objetos leva material secreto. Confirmado por execução: a aceitação de campo extra; o "
     "resto é leitura.",
     "Corrigido no construtor: lista fechada de campos nos objetos aninhados, recusa de texto "
     "hexadecimal longo e de lista longa de bits, e testes que travam os 35 campos do "
     "`HealthReport`. A verificação não mudou: recibos antigos continuam válidos."),
    ("F10", "Informativa", "`pipeline.py`",
     "O `except ValueError` gravava o texto de qualquer `ValueError` do `try`, inclusive o da "
     "leitura da semente.",
     "Corrigido: a leitura da semente tem `try` próprio, e só a mensagem do extrator (texto "
     "fixo e tamanhos) é gravada."),
    ("F11", "Baixa (latente)", "`toeplitz.py`",
     "A checagem da semente usava veracidade: `is_simulated=None`, `''` ou `0` e "
     "`is_local='não'` passavam. Confirmado por execução.",
     "Corrigido: booleano estrito, como no mixer e no construtor do recibo."),
    ("F12", "Média para o Dia 6, baixa hoje", "`pipeline.py`, `report.py`",
     "O detector de replay é criado a cada `eal run`: replay entre execuções não é detectado. "
     "Já estava na seção 17; o THREAT_MODEL (T3) dizia \"baixo para replay exato\".",
     "Documentado: T3 do THREAT_MODEL v1.2 e N14. A persistência do histórico não foi "
     "implementada."),
)
RESOLVED = (
    "`save_issuer_key` grava em modo exclusivo; os quatro prefixos de domínio da semente "
    "(`EAL-v1|ML-KEM-768|`, `EAL-v1|ML-DSA-65|`, `EAL-v1|issuer|ML-DSA-65|` e `EAL-v1-mix`) "
    "são distintos e nenhum é prefixo de outro (executado); `PipelineResult.to_dict()` e "
    "`MixResult.to_dict()` são listas fixas de campos; um `--bits` abaixo de 1.000.000 não "
    "aprova a fonte, porque o teste estatístico fica inconclusivo (leitura)."
)
DAY6 = (
    "persistir o histórico do detector de replay entre execuções antes de usar a fonte da "
    "IBM (F12). Hoje cada `eal run` começa com o histórico vazio."
)


class RegError(Exception):
    """Falha de conferência. Nada é gravado quando ela acontece."""


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def render_block() -> str:
    """Texto da seção 16.4, com as âncoras."""
    parts = [
        f"**{label} (31/10/2026), commit `{commit}`.** "
        + "; ".join(f"`{path}` (SHA-256 `{sha}`)" for path, sha in files) + "."
        for label, commit, files in PARTS
    ]
    rows = ["| " + " | ".join(_cell(c) for c in row) + " |" for row in ROWS]
    lines = [
        START,
        "### 16.4 Revisão adversarial do Dia 5",
        "",
        "Feita por leitura do código, em partes, a partir do arquivo que o coletor gera "
        "(`revisao_parteN_*.txt`), com o commit lido e o SHA-256 de cada arquivo. "
        "O que foi confirmado por execução está dito em cada achado; o resto é leitura e não "
        "prova ausência de defeitos.",
        "",
    ]
    for part in parts:
        lines += [part, ""]
    lines += [
        "| ID | Gravidade | Onde | Achado | Decisão |",
        "| --- | --- | --- | --- | --- |",
        *rows,
        "",
        f"**Resolvido sem mudança de código:** {RESOLVED}",
        "",
        f"**Pendência para o Dia 6, vinda da revisão:** {DAY6}",
        END,
    ]
    return "\n".join(lines)


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
