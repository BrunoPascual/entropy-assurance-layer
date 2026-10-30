"""Dia 4, etapa 3 (passo 5): gera a documentação de rendimento a partir dos CSVs.

Uso (a partir da raiz do projeto):
    py -3.12 -m scripts.gerar_secao_rendimento ^
        --yield-meta data\\results\\dia4_yield_<ts>.meta.json ^
        --estimator-meta data\\results\\dia4_estimator_<ts>.meta.json [--dry-run]

Confere o SHA3-256 de cada arquivo contra o meta e só então escreve dois blocos
no PROJECT.md, entre marcadores HTML (reexecutar substitui o bloco, não duplica):
  - "6.8.1 Rendimento do extrator", antes do título "### 6.9";
  - "Limitações do Dia 4 (etapa 3)", antes do título "## 18.".
Todo número do texto vem dos CSVs. Se faltar âncora, marcador ou o hash não
conferir, nada é escrito. A quebra de linha do PROJECT.md é preservada.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
import sys
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any

PROJECT = Path("PROJECT.md")
RENDIMENTO = ("<!-- dia4-rendimento:start -->", "<!-- dia4-rendimento:end -->", r"(?m)^### 6\.9\b")
LIMITACOES = ("<!-- dia4-limitacoes:start -->", "<!-- dia4-limitacoes:end -->", r"(?m)^## 18\.")
Row = dict[str, str]


# ------------------------------------------------------------ formatação


def dec(x: float, d: int = 3) -> str:
    """Número com vírgula decimal e arredondamento meio para cima (3,125 -> 3,13)."""
    q = Decimal(repr(float(x))).quantize(Decimal(1).scaleb(-d), rounding=ROUND_HALF_UP)
    return format(q, "f").replace(".", ",")


def pct(x: float, d: int = 2) -> str:
    return dec(x * 100, d) + "%"


def bits(n: int | float) -> str:
    return f"{int(Decimal(repr(float(n))).quantize(Decimal(1), rounding=ROUND_HALF_UP)):,}".replace(",", ".")


def num(text: str) -> float | None:
    return float(text) if text != "" else None


# ------------------------------------------------------ leitura verificada


def _sha3(data: bytes) -> str:
    return hashlib.sha3_256(data).hexdigest()


def load_meta(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"não consegui ler o meta {path}: {exc}") from exc


def verified_rows(meta: dict[str, Any], key: str) -> tuple[list[Row], dict[str, str]]:
    """Lê um CSV listado no meta depois de conferir o SHA3-256 dele."""
    info = meta.get("outputs", {}).get(key)
    if not info:
        raise ValueError(f"o meta não lista a saída {key!r}")
    path = Path(info["path"])
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise ValueError(f"não consegui ler {path}: {exc}") from exc
    if _sha3(data) != info["sha3_256"]:
        raise ValueError(f"SHA3-256 de {path.name} não confere com o meta")
    rows = list(csv.DictReader(io.StringIO(data.decode("utf-8"), newline="")))
    if not rows:
        raise ValueError(f"{path.name} sem linhas")
    return rows, {"path": path.as_posix(), "sha3_256": info["sha3_256"]}


def check_source(meta: dict[str, Any]) -> dict[str, str]:
    """Confere o CSV de comparação de onde a análise saiu."""
    path = Path(meta["source_csv"])
    try:
        digest = _sha3(path.read_bytes())
    except OSError as exc:
        raise ValueError(f"não consegui ler {path}: {exc}") from exc
    if digest != meta["source_csv_sha3_256"]:
        raise ValueError(f"SHA3-256 de {path.name} não confere com o registrado na análise")
    return {"path": path.as_posix(), "sha3_256": digest}


# ---------------------------------------------------- frases geradas dos dados


def sentence_margin(n: int, epsilon_log2: int) -> str:
    margin = -2 * epsilon_log2
    return (f"A margem de segurança é fixa: {margin} bits por bloco de {n} bits "
            f"({pct(margin / n)} da entrada), qualquer que seja H.")


def sentence_comparison(analysis: list[Row]) -> str:
    h = [float(r["h_used"]) for r in analysis]
    y = [float(r["frac_output"]) for r in analysis]
    return (f"Nas {len(analysis)} leituras do CSV de comparação, a H usada ficou entre {dec(min(h))} e "
            f"{dec(max(h))} e a saída ficou entre {pct(min(y))} e {pct(max(y))} da entrada.")


def sentence_trend(summary: list[Row]) -> list[str]:
    by_size = sorted(summary, key=lambda r: int(r["size_bits"]))
    first, last = by_size[0], by_size[-1]
    out = [f"A H estimada média vai de {dec(float(first['h_est_mean']))} com {bits(int(first['size_bits']))} bits "
           f"a {dec(float(last['h_est_mean']))} com {bits(int(last['size_bits']))} bits."]
    means = [float(r["h_est_mean"]) for r in by_size]
    if all(a <= b for a, b in zip(means, means[1:], strict=False)):
        out.append("A média cresce com o tamanho do lote em todos os tamanhos medidos.")
    else:
        out.append("A média não cresce estritamente entre todos os tamanhos medidos; "
                   "onde inverte, os tamanhos são próximos (ver o desvio entre leituras).")
    return out


def sentence_health_gate(summary: list[Row], threshold: float) -> str:
    failing = [r for r in sorted(summary, key=lambda r: int(r["size_bits"])) if float(r["frac_h_health_ok"]) < 1.0]
    if not failing:
        return f"Todas as leituras de todos os tamanhos passaram em H ≥ {dec(threshold, 1)}."
    parts = [f"{bits(int(r['size_bits']))} bits ({pct(float(r['frac_h_health_ok']), 0)} das leituras passou)"
             for r in failing]
    return (f"O teste de saúde pela H (limiar {dec(threshold, 1)}) reprovou parte ou todas as leituras com: "
            + "; ".join(parts) + ".")


def sentence_limiting_branch(summary: list[Row]) -> tuple[str, bool]:
    all_byte = all(float(r["frac_limited_by_byte"]) == 1.0 for r in summary)
    if all_byte:
        return "Em todos os tamanhos, o ramo por byte limitou a H em 100% das leituras.", True
    parts = [f"{bits(int(r['size_bits']))} bits: {pct(float(r['frac_limited_by_byte']), 0)}"
             for r in sorted(summary, key=lambda r: int(r["size_bits"]))]
    return "Fração das leituras em que o ramo por byte limitou a H: " + "; ".join(parts) + ".", False


def sentence_reference(summary: list[Row], all_byte: bool) -> str:
    big = max(summary, key=lambda r: int(r["size_bits"]))
    text = (f"Com {bits(int(big['size_bits']))} bits, a referência analítica do ramo por bit (p̂ = 0,5) é "
            f"{dec(float(big['h_bit_reference']), 4)} e o H_bit médio medido é {dec(float(big['h_bit_mean']), 4)}")
    if all_byte:
        return text + f"; a H estimada ({dec(float(big['h_est_mean']), 4)}) fica abaixo disso por causa do ramo por byte."
    return text + "."


def sentence_between_reads(summary: list[Row], analysis: list[Row]) -> str | None:
    """Compara a amplitude da H entre as leituras do CSV de comparação com o desvio entre leituras da os."""
    ref = next((r for r in summary if int(r["size_bits"]) == 1_000_000 and num(r["h_est_sd"]) is not None), None)
    if ref is None:
        return None
    sd = float(ref["h_est_sd"])
    h = [float(r["h_used"]) for r in analysis]
    spread = max(h) - min(h)
    head = (f"A amplitude da H entre as {len(h)} leituras do CSV de comparação ({dec(min(h))} a {dec(max(h))}, "
            f"diferença {dec(spread, 4)}) deve ser lida contra o desvio entre leituras da `os` com 1.000.000 bits "
            f"({dec(sd, 4)}, {ref['n_reads']} leituras). ")
    if spread <= 4 * sd:
        return head + ("A amplitude é de no máximo 4 desvios: essa comparação, com poucas leituras por fonte, "
                       "não distingue uma fonte da outra.")
    return head + ("A amplitude passa de 4 desvios; pode haver diferença entre fontes, mas poucas leituras por fonte "
                   "não bastam para afirmar.")


# ------------------------------------------------------------- tabelas


def table(header: list[str], rows: list[list[str]]) -> list[str]:
    out = ["| " + " | ".join(header) + " |", "| " + " | ".join("---" for _ in header) + " |"]
    out += ["| " + " | ".join(r) + " |" for r in rows]
    return out


def table_analysis(analysis: list[Row]) -> list[str]:
    rows = [[f"`{r['label']}`", r["reading"], dec(float(r["h_used"])), r["m"], pct(float(r["frac_output"])),
             pct(float(r["frac_deficit"])), pct(float(r["frac_rounding"])), pct(float(r["frac_margin"])),
             pct(float(r["frac_tail"]))] for r in analysis]
    return table(["Fonte", "Leitura", "H usada", "m", "Saída", "Déficit", "Arredondamento", "Margem", "Resto"], rows)


def table_curve_h(curve: list[Row]) -> list[str]:
    wanted = (0.5, 0.9, 0.954, 1.0)
    picked = [r for r in curve if float(r["h"]) in wanted]
    rows = [[dec(float(r["h"])), r["k_floor"], r["m"], dec(float(r["yield_block"]), 4),
             dec(float(r["deficit_per_block"]), 1), dec(float(r["rounding_per_block"]), 3), r["margin_per_block"]]
            for r in picked]
    return table(["H", "k = floor(n·H)", "m", "m/n", "Déficit/bloco", "Arredond./bloco", "Margem/bloco"], rows)


def table_curve_n(curve: list[Row], h: float = 0.954) -> list[str]:
    rows = [[r["n"], r["m"], r["n_blocks"], dec(float(r["yield_block"]), 4), pct(float(r["margin_frac_of_block"])),
             dec(float(r["batch_epsilon_log2"]), 2)] for r in curve if float(r["h"]) == h]
    return table(["n", "m", "Blocos em 1M bits", "m/n", "Margem/bloco", "log2(ε do lote)"], rows)


def table_estimator(summary: list[Row]) -> list[str]:
    rows = []
    for r in sorted(summary, key=lambda r: int(r["size_bits"])):
        sd = num(r["h_est_sd"])
        rows.append([bits(int(r["size_bits"])), r["n_reads"], dec(float(r["h_est_mean"]), 4),
                     "-" if sd is None else dec(sd, 4), f"{dec(float(r['h_est_min']), 4)} a {dec(float(r['h_est_max']), 4)}",
                     dec(float(r["h_bit_mean"]), 4), dec(float(r["h_byte_mean"]), 4), dec(float(r["h_bit_reference"]), 4),
                     pct(float(r["frac_limited_by_byte"]), 0), pct(float(r["frac_h_health_ok"]), 0),
                     bits(float(r["mean_output_bits"]))])
    return table(["Bits", "Leituras", "H estimada", "dp", "Mín a máx", "H_bit", "H_byte", "Ref. bit (p̂=0,5)",
                  "Limitou (byte)", "Passa H ≥ 0,9", "Saída média"], rows)


# ------------------------------------------------------------- blocos


def _sizes_text(analysis: list[Row]) -> str:
    sizes = sorted({int(r["n_input_bits"]) for r in analysis})
    return f"lote de {bits(sizes[0])} bits" if len(sizes) == 1 else "lotes de tamanhos variados"


def _first_positive(curve: list[Row]) -> str:
    h = min(float(r["h"]) for r in curve if int(r["m"]) > 0)
    return dec(h)


def _dirty_note(label: str, meta: dict[str, Any]) -> list[str]:
    if meta.get("git_dirty"):
        return [f"- Atenção: a medição de {label} foi feita com mudanças sem commit; o `git_commit` do metadado "
                "não descreve o código exato."]
    return []


def build_rendimento(ymeta: dict[str, Any], emeta: dict[str, Any]) -> str:
    analysis, a_info = verified_rows(ymeta, "analysis")
    curve_h, h_info = verified_rows(ymeta, "curve_h")
    curve_n, n_info = verified_rows(ymeta, "curve_n")
    readings, r_info = verified_rows(emeta, "readings")
    summary, s_info = verified_rows(emeta, "summary")
    source = check_source(ymeta)
    n, eps = int(ymeta["params"]["n"]), int(ymeta["params"]["epsilon_log2"])
    threshold = float(emeta["params"]["h_min_health"])
    branch_text, all_byte = sentence_limiting_branch(summary)
    between = sentence_between_reads(summary, analysis)

    lines = [RENDIMENTO[0], "### 6.8.1 Rendimento do extrator (Dia 4, etapa 3)", "",
             "Gerado por `scripts/gerar_secao_rendimento.py` a partir dos arquivos listados abaixo, com o SHA3-256 "
             "conferido contra o meta. Nenhum número foi digitado à mão. As tabelas A, B e C vêm do modelo de perdas "
             "(`eal/extract/budget.py`) e valem para qualquer H; a tabela A parte das leituras do CSV de comparação "
             "e a D mede o estimador.", "",
             f"**Contabilidade.** Por bloco de n = {n} bits, com k = floor(n·H) e margem 2·log2(1/ε) = {-2 * eps}: "
             "cada bit de entrada vai para o déficit de entropia (n − n·H), o arredondamento (n·H − k), a margem, a "
             "saída m = k − margem ou o resto (bits que não completam um bloco). A soma é exatamente a entrada. "
             "Se m = 0, o lote inteiro é descartado por entropia insuficiente.", "",
             "**Origem dos dados.**",
             f"- Comparação de extratores: `{source['path']}`, SHA3-256 `{source['sha3_256']}`.",
             f"- Análise de rendimento: `{a_info['path']}` (`{a_info['sha3_256']}`), `{h_info['path']}` "
             f"(`{h_info['sha3_256']}`), `{n_info['path']}` (`{n_info['sha3_256']}`); medida em {ymeta['created_at']}.",
             f"- Estimador × tamanho: `{r_info['path']}` (`{r_info['sha3_256']}`), `{s_info['path']}` "
             f"(`{s_info['sha3_256']}`); medida em {emeta['created_at']}; {len(readings)} leituras da fonte "
             f"`{emeta['source_id']}`.",
             *_dirty_note("rendimento", ymeta), *_dirty_note("estimador", emeta), "",
             f"**Tabela A: para onde foi cada bit de entrada (leituras do CSV de comparação, {_sizes_text(analysis)}).** "
             "As fontes `qpu_sim_*` são simuladas (gerador clássico) e não representam entropia real.", "",
             *table_analysis(analysis), "",
             "**Tabela B: rendimento por bloco em função de H (n = 2048).** "
             f"Primeiro H da grade (passo 0,001) com saída positiva: {_first_positive(curve_h)}.", "",
             *table_curve_h(curve_h), "",
             f"**Tabela C: rendimento em função de n, com H = 0,954 e lote de 1.000.000 bits** (a H é suposta a mesma "
             "para todo n; o CSV traz também H = 0,9 e 1,0).", "", *table_curve_n(curve_n), "",
             f"**Tabela D: H estimada da fonte `{emeta['source_id']}` em função do tamanho do lote.** "
             "Mede o estimador, não a fonte. Lotes menores que 1.000.000 bits não passariam no gate "
             "(estatísticos inconclusivos).", "", *table_estimator(summary), "",
             "**Leitura dos resultados** (frases geradas dos CSVs):",
             f"- {sentence_margin(n, eps)}",
             f"- {sentence_comparison(analysis)}",
             *[f"- {s}" for s in sentence_trend(summary)],
             f"- {sentence_health_gate(summary, threshold)}",
             f"- {branch_text}",
             f"- {sentence_reference(summary, all_byte)}"]
    if between:
        lines.append(f"- {between}")
    lines += ["",
              "**Interpretação (não medida).** O estimador usa um limite superior de 99% e, no ramo por byte, o "
              "máximo entre 256 contagens de símbolos; por construção ele fica abaixo de 1 mesmo para uma fonte "
              "uniforme. Esta medição não separa entropia real de "
              "conservadorismo do estimador. Pela premissa P3 a `os` tem H próxima de 1, mas isso é premissa, não "
              "resultado. O rendimento do extrator herda esse conservadorismo.",
              RENDIMENTO[1]]
    return "\n".join(lines)


def build_limitacoes(ymeta: dict[str, Any], emeta: dict[str, Any]) -> str:
    summary, _ = verified_rows(emeta, "summary")
    reads = {int(r["n_reads"]) for r in summary}
    reads_text = bits(min(reads)) if len(reads) == 1 else f"{min(reads)} a {max(reads)}"
    lines = [LIMITACOES[0], "### Limitações do Dia 4 (etapa 3: rendimento do extrator)", "",
             "- O modelo de perdas é conta, não medida: ele diz o que o extrator faz com a H que recebe, e não se "
             "essa H está certa (T8).",
             "- A curva em função de n supõe a mesma H para todo n; o ε do lote (n_blocos · ε) vale sob a premissa "
             "de independência entre blocos.",
             "- A H estimada da `os` fica abaixo de 1 por construção do estimador, e o teste de saúde pela H "
             "(limiar 0,9) reprova lotes pequenos mesmo vindos de uma fonte que a premissa P3 considera boa; "
             "ver a tabela D para os tamanhos afetados.",
             f"- A tabela D tem {reads_text} leituras por tamanho: o desvio entre leituras é reportado, "
             "mas não há intervalo de confiança.",
             "- A fonte `os` não é reprodutível e os bits dessa medição não foram guardados; só estimativas e hashes de lote.",
             "- Com poucas leituras por fonte, diferenças de H entre `os`, `qpu_sim` ideal e `qpu_sim` com ruído "
             "não são conclusivas; a comparação entre fontes é do E1.",
             *_dirty_note("rendimento", ymeta), *_dirty_note("estimador", emeta),
             LIMITACOES[1]]
    return "\n".join(lines)


# ------------------------------------------------------- edição do PROJECT.md


def upsert_block(text: str, block: str, spec: tuple[str, str, str]) -> str:
    """Substitui o bloco entre marcadores ou o insere antes da âncora. Erro se algo estiver ambíguo."""
    start, end, anchor = spec
    n_start, n_end = text.count(start), text.count(end)
    if (n_start, n_end) == (1, 1):
        i, j = text.index(start), text.index(end) + len(end)
        if i > j:
            raise ValueError("marcadores fora de ordem")
        return text[:i] + block + text[j:]
    if (n_start, n_end) != (0, 0):
        raise ValueError(f"marcadores inconsistentes: {n_start} de início, {n_end} de fim")
    matches = list(re.finditer(anchor, text))
    if len(matches) != 1:
        raise ValueError(f"âncora {anchor!r} encontrada {len(matches)} vez(es); esperava 1")
    pos = matches[0].start()
    return text[:pos] + block + "\n\n" + text[pos:]


def update_project(path: Path, blocks: list[tuple[str, tuple[str, str, str]]]) -> str:
    """Aplica os blocos preservando a quebra de linha do arquivo. Devolve o novo texto."""
    raw = path.read_bytes().decode("utf-8")
    eol = "\r\n" if "\r\n" in raw else "\n"
    text = raw.replace("\r\n", "\n")
    for block, spec in blocks:
        text = upsert_block(text, block, spec)
    return text.replace("\n", eol)


def main() -> None:
    parser = argparse.ArgumentParser(description="Gera a documentação de rendimento (Dia 4, etapa 3)")
    parser.add_argument("--yield-meta", type=Path, required=True)
    parser.add_argument("--estimator-meta", type=Path, required=True)
    parser.add_argument("--project", type=Path, default=PROJECT)
    parser.add_argument("--dry-run", action="store_true", help="mostra os blocos e não escreve")
    args = parser.parse_args()
    try:
        ymeta, emeta = load_meta(args.yield_meta), load_meta(args.estimator_meta)
        blocks = [(build_rendimento(ymeta, emeta), RENDIMENTO), (build_limitacoes(ymeta, emeta), LIMITACOES)]
        new_text = update_project(args.project, blocks)
    except ValueError as exc:
        print(f"ERRO: {exc}", file=sys.stderr)
        sys.exit(1)
    if args.dry_run:
        print("\n\n".join(b for b, _ in blocks))
        return
    args.project.write_bytes(new_text.encode("utf-8"))
    print(f"{args.project} atualizado: 6.8.1 e limitações do Dia 4 (etapa 3).")


if __name__ == "__main__":
    main()
