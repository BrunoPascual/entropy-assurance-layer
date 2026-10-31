"""Revisão do THREAT_MODEL.md para a v1.2 (fechamento do Dia 5, achado F12).

Motivo: a revisão adversarial do código (partes 2 e 3) mostrou que o detector de replay
guarda o histórico só em memória e começa vazio a cada ``eal run`` (``eal/pipeline.py`` cria
um detector novo; ``eal/health/report.py`` avisa "primeiro lote da execução"). O PROJECT.md já
registra isso (seção 17, limitações do Dia 3), mas o T3 da v1.1 dizia "baixo para replay
exato", o que só vale dentro de uma execução.

Mudanças, cada uma conferida antes de gravar (linhas INTEIRAS, nunca trechos):

1. Cabeçalho: versão 1.2 e data da revisão.
2. T3: mitigação e risco residual separados (dentro de uma execução x entre execuções).
3. N14: nova "não garante" (replay entre execuções), logo depois da N13.
4. Seção 12: entrada v1.2 do histórico, entre âncoras, no fim do arquivo.

Não muda adversários, premissas nem as demais garantias e não garantias. Pré-condição: a
v1.1 já aplicada. Idempotente; se algo não bater, para com código 1 sem gravar nada.

Uso (raiz do projeto)::

    py -3.12 -m scripts.atualizar_threat_model_v12
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MODEL_REL = Path("THREAT_MODEL.md")
HIST_START = "<!-- revisao-v12:start -->"
HIST_END = "<!-- revisao-v12:end -->"

OLD_T3 = '| T3 | Replay de lote ou de bloco | ADV3 | Hash de cada lote e de blocos de 4096 bits; reprova repetição | E2 | Baixo para replay exato; alto para replay transformado |'
NEW_T3 = '| T3 | Replay de lote ou de bloco | ADV3 | Hash de cada lote e de blocos de 4096 bits; reprova repetição dentro de uma execução (o histórico do detector não é guardado entre execuções do `eal run`) | E2 | Baixo para replay exato dentro de uma execução; **não detectado entre execuções**; alto para replay transformado |'
N13 = '| N13 | Detectar a remoção dos últimos recibos da cadeia sem uma cabeça guardada fora do log | Um log sem o fim continua sendo uma cadeia válida; o protótipo imprime a cabeça no `run`, mas não a guarda |'
NEW_N14 = '| N14 | Detectar replay de lote entre execuções do `eal run` | O detector de replay guarda o histórico só em memória e começa vazio a cada execução; isso importa a partir da fonte da IBM (Dia 6), porque um lote antigo devolvido numa execução seguinte não seria visto |'
EDITS: list[tuple[str, str, str]] = [
    ("versão", "- **Versão do documento:** 1.1", "- **Versão do documento:** 1.2"),
    ("data", "- **Data:** 27/10/2026 (v1.0); revisada em 31/10/2026 (v1.1)",
     "- **Data:** 27/10/2026 (v1.0); revisada em 31/10/2026 (v1.1 e v1.2)"),
    ("T3", OLD_T3, NEW_T3),
    ("N14", N13, N13 + "\n" + NEW_N14),
]
HIST_BLOCK = "\n".join([
    HIST_START,
    "### v1.2 (31/10/2026)",
    "",
    "**Motivo.** A revisão adversarial do código (partes 2 e 3) mostrou que o detector de "
    "replay guarda o histórico só em memória e começa vazio a cada `eal run` (já registrado "
    "no PROJECT.md, seção 17, limitações do Dia 3). O T3 da v1.1 dizia \"baixo para replay "
    "exato\", o que só vale dentro de uma execução.",
    "",
    "**O que mudou.** T3 com a mitigação e o risco residual separados; N14 criada; versão e "
    "data no cabeçalho.",
    "",
    "**O que não mudou.** Adversários, premissas e as demais garantias e não garantias. A "
    "persistência do histórico do detector não foi implementada: é pendência antes da fonte "
    "da IBM (Dia 6).",
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
        raise ModelError("âncoras do histórico v1.2 inconsistentes (devem aparecer em par, uma vez)")
    if starts == 0:
        if not text.endswith("\n"):
            raise ModelError("o arquivo não termina em quebra de linha")
        return text + "\n" + HIST_BLOCK + "\n"
    begin, finish = text.index(HIST_START), text.index(HIST_END)
    if finish < begin:
        raise ModelError("âncora de fim do histórico v1.2 antes da de início")
    return text[:begin] + HIST_BLOCK + text[finish + len(HIST_END):]


def _check_result(text: str) -> None:
    for key in ("| T3 |", "| N13 |", "| N14 |"):
        if text.count(key) != 1:
            raise ModelError(f"a linha {key.strip('| ')} não ficou exatamente uma vez")


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
        prog="py -3.12 -m scripts.atualizar_threat_model_v12",
        description="Revisa o THREAT_MODEL.md para a v1.2.")


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
    print("THREAT_MODEL.md: revisão v1.2 " + ("gravada" if changed else "já estava aplicada; nada mudou"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
