"""F12, passo 3: documentação e nota do relatório (report.py, THREAT_MODEL.md, PROJECT.md).

Uso (na raiz do projeto):  py -3.12 scripts\\aplicar_f12_passo3.py [raiz do projeto]

Altera três arquivos, tudo ou nada: se qualquer âncora não aparecer exatamente uma vez, nada
é gravado. Idempotente (o marcador de cada arquivo mostra se já foi aplicado). Preserva LF ou
CRLF de cada arquivo.

  - eal/health/report.py: a nota de replay deixa de dizer "primeiro lote da execução", que
    ficou falso com o histórico carregado.
  - THREAT_MODEL.md v1.3: T3 e N14 atualizados, cabeçalho e entrada na seção 12.
  - PROJECT.md: F12 resolvido na seção 16.4 e limitações do F12 na seção 17.
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

REPORT_OLD = 'notes.append("replay: primeiro lote da execução; não há histórico para comparar")'
REPORT_NEW = 'notes.append("replay: primeiro lote do histórico; não há lotes anteriores para comparar")'

THREAT_EDITS: list[tuple[str, str]] = [
    ("- **Versão do documento:** 1.2", "- **Versão do documento:** 1.3"),
    ("- **Data:** 27/10/2026 (v1.0); revisada em 31/10/2026 (v1.1 e v1.2)",
     "- **Data:** 27/10/2026 (v1.0); revisada em 31/10/2026 (v1.1, v1.2 e v1.3)"),
    ("Hash de cada lote e de blocos de 4096 bits; reprova repetição dentro de uma execução "
     "(o histórico do detector não é guardado entre execuções do `eal run`) | E2 |",
     "Hash de cada lote e de blocos de 4096 bits; o histórico é guardado em "
     "`data/logs/replay_history.json` e carregado antes de qualquer leitura de fonte, então reprova "
     "repetição dentro de uma execução e entre execuções (F12, Dia 6) | E2; testes do F12 |"),
    ("Baixo para replay exato dentro de uma execução; **não detectado entre execuções**; "
     "alto para replay transformado |",
     "Baixo para replay exato; **apagar ou trocar o arquivo de histórico zera a proteção sem alarme**; "
     "alto para replay transformado; replay deslocado para fora de bloco de 4096 bits não detectado |"),
    ("| N14 | Detectar replay de lote entre execuções do `eal run` |",
     "| N14 | Detectar replay de lote entre execuções do `eal run` quando o arquivo de histórico é apagado, "
     "trocado ou refeito |"),
    ("O detector de replay guarda o histórico só em memória e começa vazio a cada execução; isso importa "
     "a partir da fonte da IBM (Dia 6), porque um lote antigo devolvido numa execução seguinte não seria visto |",
     "O histórico (`data/logs/replay_history.json`, F12) é um arquivo local: quem tem acesso ao disco pode "
     "apagá-lo ou refazê-lo, e o `state_hash` detecta só corrupção acidental; não há trava para execuções "
     "simultâneas; apagá-lo zera a proteção sem alarme |"),
    ("<!-- revisao-v12:end -->",
     "<!-- revisao-v12:end -->\n"
     "<!-- revisao-v13:start -->\n"
     "### v1.3 (31/10/2026)\n\n"
     "**Motivo.** O F12 da revisão adversarial do Dia 5: o detector de replay começava vazio a cada `eal run`, "
     "então um lote antigo devolvido numa execução seguinte não era visto. Era pendência antes da fonte da IBM "
     "(Dia 6).\n\n"
     "**O que mudou.** T3: o histórico é guardado em `data/logs/replay_history.json` e carregado antes de "
     "qualquer leitura de fonte; a gravação acontece antes de qualquer recibo; falha de leitura ou de gravação "
     "recusa a execução (fail-closed). N14 reescrita: a não garantia agora é o arquivo apagado, trocado ou "
     "refeito, e o risco residual está separado. Versão e data no cabeçalho.\n\n"
     "**O que não mudou.** Adversários, premissas e as demais garantias e não garantias. Replay transformado e "
     "replay deslocado continuam fora do alcance do detector. Lotes de execuções anteriores ao commit "
     "`e4b9f1d` não estão no histórico.\n"
     "<!-- revisao-v13:end -->"),
]

PROJECT_EDITS: list[tuple[str, str]] = [
    ("Documentado: T3 do THREAT_MODEL v1.2 e N14. A persistência do histórico não foi implementada.",
     "Resolvido no Dia 6 (passos 1 e 2, commits e25e8dd e e4b9f1d): o histórico é salvo em "
     "`data/logs/replay_history.json` e carregado antes de qualquer leitura de fonte; T3 e N14 atualizados "
     "no THREAT_MODEL v1.3."),
    ("**Pendência para o Dia 6, vinda da revisão:** persistir o histórico do detector de replay entre "
     "execuções antes de usar a fonte da IBM (F12). Hoje cada `eal run` começa com o histórico vazio.",
     "**F12 resolvido no Dia 6** (passos 1 e 2, commits e25e8dd e e4b9f1d): o histórico do detector de replay "
     "é salvo entre execuções e carregado antes de qualquer leitura de fonte; a gravação acontece antes de "
     "qualquer recibo. Falha de leitura ou de gravação recusa a execução (fail-closed). Limitações na seção 17."),
    ("### Limitações do Dia 5 (etapa 3: log encadeado)",
     "### Limitações do Dia 6 (F12: histórico de replay)\n\n"
     "- O histórico começa no primeiro `eal run` depois do commit `e4b9f1d`. Lotes de execuções anteriores não "
     "estão nele, então o replay de um lote antigo não é detectado.\n"
     "- O `state_hash` detecta corrupção acidental, não adulteração: quem tem acesso ao disco pode refazer o "
     "arquivo, e apagá-lo zera a proteção sem alarme. A cabeça da cadeia anotada fora do repositório não cobre "
     "este arquivo.\n"
     "- Não há trava para dois `eal run` simultâneos (como a F3): a última gravação vence.\n"
     "- O arquivo cresce com os lotes; acima de 64 MiB o `run` recusa, até que alguém o arquive à mão.\n"
     "- Replay transformado e replay deslocado para fora de múltiplos de 4096 bits continuam não detectados "
     "(ver as limitações do Dia 3).\n\n"
     "### Limitações do Dia 5 (etapa 3: log encadeado)"),
]

PLAN: list[tuple[str, str, list[tuple[str, str]]]] = [
    ("eal/health/report.py", "primeiro lote do histórico", [(REPORT_OLD, REPORT_NEW)]),
    ("THREAT_MODEL.md", "- **Versão do documento:** 1.3", THREAT_EDITS),
    ("PROJECT.md", "F12 resolvido no Dia 6", PROJECT_EDITS),
]


def _load(path: Path) -> tuple[str, bool] | str:
    try:
        text = path.read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return f"não consegui ler {path} ({type(exc).__name__})"
    crlf = "\r\n" in text
    if crlf and text.count("\n") != text.count("\r\n"):
        return f"{path} mistura LF e CRLF"
    return text.replace("\r\n", "\n"), crlf


def main() -> int:
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[1]
    staged: list[tuple[Path, bytes]] = []
    applied = 0
    for rel, marker, edits in PLAN:
        path = root / rel
        loaded = _load(path)
        if isinstance(loaded, str):
            print(f"RECUSADO: {loaded}; nada foi gravado")
            return 1
        norm, crlf = loaded
        if marker in norm:
            applied += 1
            continue
        for i, (old, _) in enumerate(edits, start=1):
            n = norm.count(old)
            if n != 1:
                print(f"RECUSADO: {rel}: trecho {i} aparece {n} vez(es), esperado 1; nada foi gravado")
                return 1
        for old, new in edits:
            norm = norm.replace(old, new, 1)
        out = norm.replace("\n", "\r\n") if crlf else norm
        staged.append((path, out.encode("utf-8")))
    if applied == len(PLAN):
        print("já aplicado; nada a fazer")
        return 0
    if applied:
        print("RECUSADO: só parte dos arquivos já estava aplicada; nada foi gravado")
        return 1
    for path, data in staged:
        path.write_bytes(data)
        print(f"aplicado em {path}; sha256 novo: {hashlib.sha256(data).hexdigest()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
