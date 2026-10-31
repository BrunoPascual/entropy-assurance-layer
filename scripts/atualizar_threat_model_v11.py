"""Revisão do THREAT_MODEL.md para a v1.1 (item 3 do fechamento do Dia 5).

Motivo: a seção 11 manda revisar o modelo quando um experimento contradiz uma
garantia. Na demo de 31/10/2026 (passos 8 e 9), um log sem o último recibo
continuou válido no ``eal verify``; só a cabeça guardada fora do log o
reprovou. A redação da v1.0 de G4 ("qualquer alteração é detectada") dizia mais
do que o protótipo entrega.

Mudanças, cada uma conferida antes de gravar:

1. Cabeçalho: versão 1.1 e data da revisão.
2. AT4: a cabeça da cadeia é impressa, mas não guardada; o log de falhas.
3. G4: reescrita, com o caso da remoção do fim da cadeia.
4. T9: a ameaça inclui a remoção do fim; risco residual separado.
5. N13: nova "não garante" (remoção dos últimos recibos).
6. Seção 12 (histórico de revisões), entre âncoras, no fim do arquivo.

Não muda adversários, premissas nem as demais garantias e não garantias.
Idempotente; se algum trecho esperado não estiver exatamente uma vez, para com
código 1 sem gravar nada.

Uso (raiz do projeto)::

    py -3.12 -m scripts.atualizar_threat_model_v11
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MODEL_REL = Path("THREAT_MODEL.md")
HIST_START = "<!-- revisao-v11:start -->"
HIST_END = "<!-- revisao-v11:end -->"

OLD_AT4 = "| AT4 | Integridade dos recibos | É a evidência de auditoria do produto | `data/receipts/` |"
NEW_AT4 = (
    "| AT4 | Integridade dos recibos | É a evidência de auditoria do produto. A cabeça da cadeia "
    "é impressa pelo `run`, mas o protótipo não a guarda em lugar nenhum | `data/receipts/` "
    "(recibos e `chain.jsonl`); `data/logs/eal_runs.jsonl` registra as falhas da CLI e não "
    "traz semente nem chaves privadas |"
)
OLD_G4 = (
    "| G4 | Todo recibo é assinado com ML-DSA-65 e encadeado ao anterior; qualquer alteração "
    "é detectada pelo `eal verify` | Chave do emissor não comprometida |"
)
NEW_G4 = (
    "| G4 | Todo recibo é assinado com ML-DSA-65 e encadeado ao anterior; a alteração de um "
    "recibo ou do meio da cadeia é detectada pelo `eal verify`. A remoção dos últimos recibos "
    "só é detectada se o verificador tiver a cabeça da cadeia guardada fora do log "
    "(`--expected-head`); sem ela, uma cadeia sem o fim continua válida (ver N13) | Chave do "
    "emissor não comprometida; para a remoção do fim, cabeça guardada fora do log |"
)
OLD_T9 = (
    "| T9 | Recibo alterado ou forjado | ADV5 | Assinatura ML-DSA-65 sobre JSON canônico; "
    "cadeia de hashes; `eal verify` | Testes de adulteração | Baixo, se a chave do emissor "
    "estiver protegida |"
)
NEW_T9 = (
    "| T9 | Recibo alterado, forjado ou removido do fim da cadeia | ADV5 | Assinatura "
    "ML-DSA-65 sobre JSON canônico; cadeia de hashes; `eal verify`; para a remoção do fim, "
    "cabeça da cadeia guardada fora do log e passada em `--expected-head` (o protótipo ainda "
    "não a guarda) | Testes de adulteração; demo de 31/10/2026, passos 8 e 9 | Baixo para "
    "alteração, se a chave do emissor estiver protegida; **alto para a remoção dos últimos "
    "recibos sem cabeça guardada fora do log** |"
)
OLD_N12 = "| N12 | Resistência a ataques físicos ou de canal lateral | Fora do escopo do protótipo |"
NEW_N13 = (
    "| N13 | Detectar a remoção dos últimos recibos da cadeia sem uma cabeça guardada fora do "
    "log | Um log sem o fim continua sendo uma cadeia válida; o protótipo imprime a cabeça "
    "no `run`, mas não a guarda |"
)
EDITS: list[tuple[str, str, str]] = [
    ("versão", "- **Versão do documento:** 1.0", "- **Versão do documento:** 1.1"),
    ("data", "- **Data:** 27/10/2026",
     "- **Data:** 27/10/2026 (v1.0); revisada em 31/10/2026 (v1.1)"),
    ("AT4", OLD_AT4, NEW_AT4),
    ("G4", OLD_G4, NEW_G4),
    ("T9", OLD_T9, NEW_T9),
    ("N13", OLD_N12, OLD_N12 + "\n" + NEW_N13),
]
HIST_BLOCK = "\n".join([
    HIST_START,
    "## 12. Histórico de revisões",
    "",
    "### v1.1 (31/10/2026)",
    "",
    "**Motivo.** Um experimento contradisse uma garantia (seção 11, quarto item). Na demo "
    "ponta a ponta de 31/10/2026 (`scripts/demo_dia5.py`, passos 8 e 9), um log com o último "
    "recibo apagado continuou válido no `eal verify`, e só a cabeça da cadeia anotada antes "
    "(`--expected-head`) o reprovou. Isso contradiz a redação da v1.0 de G4 (\"qualquer "
    "alteração é detectada\").",
    "",
    "**O que mudou.** G4 reescrita; T9 com risco residual separado; N13 criada; AT4 "
    "atualizada; versão e data no cabeçalho.",
    "",
    "**O que não mudou.** Adversários, premissas, G1 a G3, G5 a G8 e as demais não "
    "garantias. Nenhum resultado do Dia 5 os contradisse. O código da CLI e da cadeia ainda "
    "não passou pela revisão adversarial do fechamento do Dia 5, e esta revisão do modelo "
    "não o cobre.",
    HIST_END,
])


class ModelError(Exception):
    """Falha de conferência. Nada é gravado quando ela acontece."""


def _apply_edits(text: str) -> str:
    """Troca linhas INTEIRAS: uma linha editada à mão não é aceita nem sobrescrita."""
    for name, old, new in EDITS:
        if ("\n" + new + "\n") in ("\n" + text + "\n"):
            continue
        lines = text.split("\n")
        if lines.count(old) != 1:
            raise ModelError(f"a linha de '{name}' não aparece exatamente uma vez")
        index = lines.index(old)
        lines[index:index + 1] = new.split("\n")
        text = "\n".join(lines)
    return text


def _apply_history(text: str) -> str:
    starts, ends = text.count(HIST_START), text.count(HIST_END)
    if starts != ends or starts > 1:
        raise ModelError("âncoras do histórico inconsistentes (devem aparecer em par, uma vez)")
    if starts == 0:
        if not text.endswith("\n"):
            raise ModelError("o arquivo não termina em quebra de linha")
        return text + "\n" + HIST_BLOCK + "\n"
    begin, finish = text.index(HIST_START), text.index(HIST_END)
    if finish < begin:
        raise ModelError("âncora de fim do histórico antes da de início")
    return text[:begin] + HIST_BLOCK + text[finish + len(HIST_END):]


def _check_result(text: str) -> None:
    for key in ("| G4 |", "| T9 |", "| N13 |", "| AT4 |"):
        if text.count(key) != 1:
            raise ModelError(f"a linha {key.strip('| ')} não ficou exatamente uma vez")
    if "qualquer alteração é detectada pelo `eal verify`" in text:
        raise ModelError("a redação antiga de G4 continua no texto")


def update_text(text: str) -> str:
    """Devolve o texto revisado (em LF). Levanta ModelError se algo não bater."""
    out = _apply_history(_apply_edits(text))
    _check_result(out)
    return out


def write_model(path: Path) -> bool:
    """Atualiza o arquivo mantendo as quebras de linha. True se mudou."""
    try:
        raw = Path(path).read_bytes()
    except OSError as exc:
        raise ModelError("THREAT_MODEL.md não encontrado") from exc
    crlf = raw.count(b"\r\n")
    if crlf not in (0, raw.count(b"\n")):
        raise ModelError("o THREAT_MODEL.md mistura CRLF e LF")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ModelError("o THREAT_MODEL.md não é UTF-8") from exc
    norm = text.replace("\r\n", "\n")
    new_norm = update_text(norm)
    if new_norm == norm:
        return False
    new_text = new_norm.replace("\n", "\r\n") if crlf else new_norm
    Path(path).write_bytes(new_text.encode("utf-8"))
    return True


def build_parser() -> argparse.ArgumentParser:
    """Sem opções: o script só atualiza o THREAT_MODEL.md."""
    return argparse.ArgumentParser(
        prog="py -3.12 -m scripts.atualizar_threat_model_v11",
        description="Revisa o THREAT_MODEL.md para a v1.1.")


def main(argv: Sequence[str] | None = None, *, _root: Path | None = None) -> int:
    """Ponto de entrada. ``_root`` existe só para testes."""
    build_parser().parse_args(argv)
    root = Path(_root) if _root is not None else PROJECT_ROOT
    try:
        changed = write_model(root / MODEL_REL)
    except ModelError as exc:
        print(f"erro: {exc}", file=sys.stderr)
        print("nada foi gravado", file=sys.stderr)
        return 1
    print("THREAT_MODEL.md: revisão v1.1 " + ("gravada" if changed else "já estava aplicada; nada mudou"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
