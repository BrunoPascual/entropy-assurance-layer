"""Dia 4, etapa 5: documentação do mixer, do pipeline e do gate de resiliência.

Uso (a partir da raiz do projeto):
    py -3.12 -m scripts.gerar_docs_dia4 --resilience-meta data\\results\\dia4_resilience_<ts>.meta.json [--dry-run]

Confere o SHA3-256 do CSV contra o meta e RECALCULA resumo, gate e contagem de falsos
alarmes a partir das linhas, exigindo igualdade com o que o meta registrou. Só então
atualiza o PROJECT.md:
  - 16.2 Resultado do gate do Dia 4 (gerado do CSV), antes de "## 17.";
  - 6.9.1 Mixer: o que o código fixa, antes de "### 6.10";
  - 6.14 Pipeline, antes do "---" que precede "## 7.";
  - Limitações do Dia 4 (mixer, pipeline e resiliência), antes de "## 18.";
  - corrige os itens 2 e 3 da política do 6.9 (o mixer relaxa a exigência em `experiment`);
  - atualiza a linha de Status e a árvore de pastas (pipeline.py, blocks.py, budget.py).
Os blocos usam marcadores HTML: reexecutar substitui, não duplica. Os números do 16.2 vêm
do CSV; os blocos 6.9.1, 6.14 e as limitações são texto fixo escrito a partir do código.
Se faltar âncora, o texto antigo da política não for encontrado ou algo não conferir,
nada é escrito.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import re
import sys
from pathlib import Path
from typing import Any

from eal.config import MIN_LOCAL_OUTPUT_BITS
from scripts import gerar_secao_rendimento as g
from scripts import resilience_dia4 as rs

Row = dict[str, Any]
GATE = ("<!-- dia4-gate:start -->", "<!-- dia4-gate:end -->", r"(?m)^## 17\.")
MIXER = ("<!-- dia4-mixer:start -->", "<!-- dia4-mixer:end -->", r"(?m)^### 6\.10\b")
PIPELINE = ("<!-- dia4-pipeline:start -->", "<!-- dia4-pipeline:end -->", r"(?m)^---\n\n## 7\.")
LIMITS = ("<!-- dia4-limitacoes-pipeline:start -->", "<!-- dia4-limitacoes-pipeline:end -->", r"(?m)^## 18\.")
KINDS = ("ok", "ok_experiment_only", "ok_fail_closed", "DETECTION_MISS", "UNEXPECTED", "VIOLATION")
REASON_CELL_LIMIT = 110

POLICY_OLD = (
    "2. É obrigatório **pelo menos 1 fonte local aprovada e não simulada** (na prática, `os`). "
    "Motivo: o provedor da QPU conhece os bits que gerou.\n"
    "3. Fontes simuladas só entram em modo experimento, nunca em modo de geração de chave real."
)
POLICY_NEW = (
    f"2. Em modo `keygen` é obrigatório **pelo menos 1 fonte local aprovada e não simulada** (na prática, `os`), "
    f"cujas saídas extraídas somem pelo menos {MIN_LOCAL_OUTPUT_BITS} bits (o tamanho da semente). "
    "Motivo: o provedor da QPU conhece os bits que gerou.\n"
    "3. Fontes simuladas só entram em modo `experiment`, nunca em `keygen`: em `keygen`, uma fonte simulada na "
    "lista é erro de configuração, mesmo reprovada. Em `experiment` basta 1 fonte local aprovada (simulada ou "
    f"não), com o mesmo piso de {MIN_LOCAL_OUTPUT_BITS} bits, e a semente sai marcada `usable_for_key = False`."
)


# ------------------------------------------------------- leitura verificada


def _sha3(data: bytes) -> str:
    return hashlib.sha3_256(data).hexdigest()


def _flag(text: str, field: str, *, allow_empty: bool) -> bool | None:
    if text == "" and allow_empty:
        return None
    if text in ("True", "False"):
        return text == "True"
    raise ValueError(f"valor inválido em {field}: {text!r}")


def typed(row: dict[str, str]) -> Row:
    """Converte uma linha do CSV (texto) para os tipos que `resilience_dia4.gate` espera."""
    out: Row = dict(row)
    try:
        out["rep"], out["n_bits"] = int(row["rep"]), int(row["n_bits"])
    except ValueError as exc:
        raise ValueError(f"rep ou n_bits inválido: {exc}") from exc
    for field in ("os_expected_to_fail", "seed_generated"):
        out[field] = _flag(row[field], field, allow_empty=False)
    for field in ("usable_for_key", "seed_equals_without_bad"):
        out[field] = _flag(row[field], field, allow_empty=True)
    return out


def load_resilience(meta_path: Path) -> tuple[dict[str, Any], list[Row]]:
    """Lê o meta e o CSV, confere o hash e recalcula o que o meta registrou."""
    meta = g.load_meta(meta_path)
    try:
        data = Path(meta["csv"]).read_bytes()
    except (OSError, KeyError) as exc:
        raise ValueError(f"não consegui ler o CSV do meta: {exc}") from exc
    if _sha3(data) != meta.get("csv_sha3_256"):
        raise ValueError(f"SHA3-256 de {Path(meta['csv']).name} não confere com o meta")
    reader = csv.DictReader(io.StringIO(data.decode("utf-8"), newline=""))
    if reader.fieldnames != rs.CSV_FIELDS:
        raise ValueError("cabeçalho do CSV difere do esperado por resilience_dia4")
    rows = [typed(r) for r in reader]
    checks = (
        (len(rows), meta.get("n_rows"), "número de linhas"),
        (rs.summarize(rows), meta.get("verdicts_by_scenario"), "vereditos por cenário"),
        (rs.os_false_alarms(rows), meta.get("os_false_alarms"), "falsos alarmes da os"),
        (list(rs.gate(rows)), [meta.get("gate", {}).get("ok"), meta.get("gate", {}).get("problems")], "gate"),
    )
    for recomputed, recorded, label in checks:
        if recomputed != recorded:
            raise ValueError(f"{label} recalculado do CSV difere do registrado no meta")
    return meta, rows


# --------------------------------------------------- tabelas e frases do 16.2


def needs_attention(row: Row) -> bool:
    """Execuções fora do esperado: tudo que não é `ok`, exceto o fail-closed previsto dos cenários C5."""
    verdict = rs.kind(row["verdict"])
    if verdict == "ok":
        return False
    return not (row["os_expected_to_fail"] and verdict in ("ok_fail_closed", "ok_experiment_only"))


def counts_table(rows: list[Row]) -> list[str]:
    body = []
    for name in dict.fromkeys(r["scenario"] for r in rows):
        group = [r for r in rows if r["scenario"] == name]
        counts = {k: sum(rs.kind(r["verdict"]) == k for r in group) for k in KINDS}
        body.append([f"`{name}`", group[0]["mode"], str(len(group)), *[str(counts[k]) if counts[k] else "-" for k in KINDS]])
    return g.table(["Cenário", "Modo", "Execuções", *KINDS], body)


def attention_table(rows: list[Row]) -> list[str]:
    odd = [r for r in rows if needs_attention(r)]
    if not odd:
        return ["Nenhuma execução fora do esperado."]
    body = []
    for r in odd:
        reason = r["not_mixed_reasons"].replace("|", "/")
        if len(reason) > REASON_CELL_LIMIT:
            reason = reason[:REASON_CELL_LIMIT] + "..."
        body.append([f"`{r['scenario']}`", str(r["rep"]), f"`{r['statuses']}`", r["verdict"], reason or "-"])
    return g.table(["Cenário", "Rep.", "Estados", "Veredito", "Motivo registrado"], body)


def _scenario(rows: list[Row], name: str) -> list[Row]:
    return [r for r in rows if r["scenario"] == name]


def sentences(rows: list[Row]) -> list[str]:
    """Frases geradas dos dados. Cenário ausente do CSV: a frase correspondente é omitida."""
    out: list[str] = []
    outside = [r for r in rows if not r["os_expected_to_fail"]]
    failed = [r for r in outside if r["os_status"] != "mixed"]
    out.append(f"A `os` não entrou na mistura em {len(failed)} de {len(outside)} execuções fora dos cenários em que "
               "ela falha de propósito (reprovação pelos testes de saúde ou falha de leitura). Referência da seção "
               "16.1: cerca de 3% por lote. Esta contagem não inclui reprovações do stand-in remoto (ver a tabela de atenção).")
    bad = [r for r in rows if r["must_exclude"] and "os" not in r["must_exclude"].split(";") and r["os_status"] == "mixed"]
    if bad:
        names = ", ".join(f"`{n}`" for n in dict.fromkeys(r["scenario"] for r in bad))
        missed = sum(rs.kind(r["verdict"]) == "DETECTION_MISS" for r in bad)
        tail = ("nenhuma fonte defeituosa entrou na mistura." if missed == 0 else
                f"em {missed} delas uma fonte defeituosa entrou na mistura (DETECTION_MISS: medida do E2, "
                "não falha do pipeline).")
        out.append(f"Em {len(bad)} execuções com fontes defeituosas ou indisponíveis e a `os` aprovada ({names}), {tail}")
    c6 = [r for r in _scenario(rows, "C6_prng") if r["os_status"] == "mixed"]
    if c6:
        n_in = sum("faulty_prng" in r["mixed"].split(";") for r in c6)
        out.append(f"A `faulty_prng` entrou na mistura em {n_in} de {len(c6)} execuções com a `os` aprovada (C6): "
                   "testes de saída não distinguem um gerador clássico bom (limitação T4).")
    g2 = _scenario(rows, "C5a_os_down") + _scenario(rows, "C5b_os_tampered")
    if g2:
        generated = sum(r["seed_generated"] is True for r in g2)
        out.append(f"Em `keygen`, com a `os` fora (leitura falha ou lote adulterado) e a remota no ar, a semente foi "
                   f"gerada em {generated} de {len(g2)} execuções (esperado: 0; G2).")
    k1 = _scenario(rows, "K1_keygen_standin")
    if k1:
        usable = sum(r["seed_generated"] is True and r["usable_for_key"] is True for r in k1)
        unexpected = sum(rs.kind(r["verdict"]) == "UNEXPECTED" for r in k1)
        out.append(f"K1: semente utilizável em {usable} de {len(k1)} execuções; {unexpected} com UNEXPECTED (ver a tabela de atenção).")
    c5c = _scenario(rows, "C5c_os_down_experiment")
    if c5c:
        marked = sum(r["seed_generated"] is True and r["usable_for_key"] is False for r in c5c)
        out.append(f"C5c: em `experiment`, com a `os` fora, a `qpu_sim` sozinha gerou semente marcada como inutilizável em "
                   f"{marked} de {len(c5c)} execuções.")
    violations = sum(rs.kind(r["verdict"]) == "VIOLATION" for r in rows)
    out.append(f"Execuções com VIOLATION (política ou isolamento do pipeline quebrados): {violations}.")
    return out


# -------------------------------------------------------------------- blocos


def build_gate(meta: dict[str, Any], rows: list[Row]) -> str:
    gate = meta["gate"]
    params = meta["params"]
    lines = [GATE[0], "### 16.2 Resultado do gate do Dia 4 (resiliência do pipeline)", "",
             f"Medido em {meta['created_at']} (commit `{str(meta['git_commit'])[:7]}`"
             + (", **medido com mudanças sem commit: o `git_commit` não descreve o código exato**" if meta.get("git_dirty") else "")
             + f"). Tabela: `{meta['csv']}`, SHA3-256 `{meta['csv_sha3_256']}`. "
             f"Parâmetros: {params['reps']} repetições por cenário, lotes de {g.bits(params['n_bits'])} bits, "
             f"backend de ruído `{params['noise_backend']}`; {meta['n_rows']} execuções. "
             "Gerado por `scripts/gerar_docs_dia4.py`; resumo, gate e contagem de falsos alarmes foram recalculados do CSV.", "",
             "**Regras do gate.**",
             "- Nenhuma execução com VIOLATION em nenhum cenário.",
             "- No cenário BASE, em toda execução com a `os` aprovada: semente de 64 bytes gerada e `usable_for_key = False` "
             "(modo `experiment`), e pelo menos uma execução assim.", "",
             f"**Resultado do gate: {'CUMPRIDO' if gate['ok'] else 'NÃO CUMPRIDO'}.**"]
    lines += [f"- {p}" for p in gate["problems"]]
    lines += ["", "**Vereditos por cenário.** `DETECTION_MISS` é uma fonte defeituosa que passou nos testes (medida do E2, "
              "não falha do pipeline); `UNEXPECTED`, uma fonte que deveria entrar e não entrou; `VIOLATION`, política ou "
              "isolamento quebrados.", "", *counts_table(rows), "",
              "**Execuções fora do esperado** (tudo que não é `ok`, exceto o fail-closed previsto dos cenários C5):", "",
              *attention_table(rows), "", "**Leitura dos resultados** (frases geradas do CSV):",
              *[f"- {s}" for s in sentences(rows)], "",
              "**O que este gate não mostra.** A fonte \"remota\" dos cenários `keygen` é um stand-in (bits da `os` com rótulo "
              "de fonte remota não simulada), não a QPU da IBM. O gate verifica política, isolamento e fail-closed; não "
              "mede a qualidade estatística da semente (o SHA3-512 de lixo também parece uniforme) nem a taxa de detecção de "
              f"fontes defeituosas, com {params['reps']} repetições por cenário (isso é o E2). O CSV guarda só o SHA3-256 da "
              "semente; nenhuma semente nem bit é gravado.", GATE[1]]
    return "\n".join(lines)


def build_mixer() -> str:
    return "\n".join([
        MIXER[0], "### 6.9.1 Mixer: o que o código fixa (Dia 4)", "",
        "Texto escrito a partir de `eal/mix/mixer.py`; complementa o 6.9, que não dizia como codificar os tamanhos.", "",
        "**Modos.** `keygen`: fonte simulada na lista é erro (mesmo reprovada); exige pelo menos 1 fonte local, não simulada e "
        f"aprovada, e a parte local deve somar {MIN_LOCAL_OUTPUT_BITS} bits extraídos; a semente sai com `usable_for_key = True`. "
        f"`experiment`: aceita fontes simuladas; exige pelo menos 1 fonte local aprovada (simulada ou não) com o mesmo piso de "
        f"{MIN_LOCAL_OUTPUT_BITS} bits; a semente sai sempre com `usable_for_key = False`.", "",
        "**Codificação.** `SHA3-512( MIX_DOMAIN || para cada fonte incluída, em ordem de código Unicode do source_id: "
        "len(id em UTF-8) [8 bytes, big-endian] || id || n_bits [8 bytes, big-endian] || packbits(saída) )`. O contador é de "
        "BITS, não de bytes: `packbits` preenche o último byte com zeros, e sem o contador `[1]` e `[1,0,0,0,0,0,0,0]` "
        "dariam a mesma semente.", "",
        "**Pareamento.** `make_mix_input` amarra o relatório de saúde e a extração aos bits do lote pelo `input_hash` "
        "(`hash_bits` dos bits do lote), pelo `batch_id`, pelo `source_id` e pelo tamanho. `source_id`, `batch_id` e "
        "`input_hash` repetidos entre as contribuições são recusados.", "",
        "**Flags.** `is_local` só vale se for booleano verdadeiro; `is_simulated`, só se for booleano falso; `approved`, só "
        "se for booleano verdadeiro (`bool` ou `numpy.bool_`). Qualquer outro valor conta como o pior caso.", "",
        "**Registro.** Fonte reprovada ou sem saída é excluída e registrada com `source_id`, `batch_id` e os motivos, em "
        "ordem de `source_id`. `MixResult.to_dict()` traz modo, `usable_for_key`, texto da política, `seed_hash` e, por "
        "fonte incluída, `source_id`, `batch_id`, `input_hash`, flags e bits misturados; nenhum byte de semente.",
        MIXER[1]])


def build_pipeline() -> str:
    return "\n".join([
        PIPELINE[0], "### 6.14 Pipeline (`eal/pipeline.py`, Dia 4)", "",
        "`run_pipeline(sources, seed_source, mode, n_bits, h_declared, detector, health_fn)` devolve um `PipelineResult`. "
        "`health_fn` e `detector` são opcionais: sem eles, o pipeline importa `build_health_report` e `ReplayDetector` "
        "(os testes de política injetam versões falsas).", "",
        "**Fluxo por fonte.** (1) lê um lote; (2) roda o teste de saúde, com o mesmo detector de replay para todas as fontes; "
        "(3) se aprovada, extrai com Toeplitz usando uma semente de uma leitura SEPARADA de `seed_source` (uma leitura nova "
        "por fonte aprovada); se reprovada, cria uma extração vazia ligada ao lote pelo hash, sem gastar semente; "
        "(4) monta o `MixInput`. No fim chama `mix`.", "",
        "**Princípio.** A falha de uma fonte nunca derruba o pipeline; só a política do mixer derruba a semente. Sem "
        "política satisfeita, `mix = None`, o motivo vai em `error` e nenhuma semente é gerada (fail-closed).", "",
        "**Estados de cada fonte** (`SourceOutcome.status`):", "",
        *g.table(["Estado", "Significado"], [
            ["`mixed`", "entrou na mistura"],
            ["`excluded`", "reprovada ou sem saída; registrada com o motivo"],
            ["`not_mixed`", "aprovada, mas a política falhou e nenhuma semente saiu"],
            ["`read_failed`", "a leitura levantou exceção"],
            ["`health_failed`", "o teste de saúde levantou exceção"],
            ["`extraction_failed`", "semente de extração indisponível ou recusada, ou H estimada ausente"]]), "",
        "**Regras.** Só `Exception` é capturada (`KeyboardInterrupt` passa). A mensagem de uma exceção de fonte ou de teste "
        "não é gravada, só o nome da classe, porque pode conter dados do provedor; a única mensagem gravada é a do "
        "`ValueError` do próprio extrator. `to_dict()` não traz bit nem byte de semente. O detector de replay vale por "
        "execução; para detectar replay entre execuções seguidas, o chamador passa o mesmo `detector`.",
        PIPELINE[1]])


def build_limits() -> str:
    return "\n".join([
        LIMITS[0], "### Limitações do Dia 4 (etapas 2 e 4: mixer, pipeline e resiliência)", "",
        "- Um `MixInput` montado à mão, sem `make_mix_input`, pode declarar um `input_hash` falso: o pareamento só vale "
        "para quem usa o ponto de entrada normal.",
        "- A semente fica em `bytes`, que o Python não consegue apagar da memória; é aceitável no protótipo e coberto pela "
        "premissa P1 (host íntegro).",
        f"- O piso de {MIN_LOCAL_OUTPUT_BITS} bits conta bits extraídos, não entropia provada; vale sob as mesmas premissas do extrator "
        "(P4 e independência entre blocos).",
        "- Em `experiment`, o mixer não exige fonte local não simulada (ver o 6.9); a semente sai inutilizável para chave, "
        "mas uma execução sem a `os` ainda gera semente.",
        "- Os testes de política do pipeline usam funções de saúde falsas; o comportamento com os testes estatísticos "
        "reais só aparece na execução do script de resiliência.",
        "- A fonte remota dos cenários `keygen` é um stand-in (bits da `os` com rótulo remoto), não a QPU: o gate não diz "
        "nada sobre a QPU real nem sobre a independência do provedor (N7).",
        "- O cenário C5b adultera o lote da `os` com um trecho de zeros, que só exercita o RCT; não cobre viés nem correlação "
        "na `os`.",
        "- O teste com fonte adaptativa mostra que o SHA3-512 resiste a cancelar a entropia da `os` (cancelar exigiria "
        "colisões), mas não protege quem vê a saída da `os` (G3 vale só para quem não a conhece), e uma fonte "
        "adaptativa pode \"moer\" candidatos, a um custo de 2^k para fixar k bits da semente.",
        "- Poucas repetições por cenário: as contagens do 16.2 não estimam taxas (nem a de falso alarme da `os`, nem a de "
        "detecção); isso é o E2.",
        LIMITS[1]])


# ------------------------------------------------------------ edição do PROJECT.md


def _replace_once(text: str, old: str, new: str, what: str) -> str:
    if old in text:
        if text.count(old) != 1:
            raise ValueError(f"{what}: texto antigo encontrado {text.count(old)} vezes; esperava 1")
        return text.replace(old, new)
    if new in text:
        return text
    raise ValueError(f"{what}: nem o texto antigo nem o novo foram encontrados; ajuste o PROJECT.md à mão")


def status_line(gate_ok: bool) -> str:
    if gate_ok:
        return "- **Status:** Dia 4 de 9 (concluído; gate do Dia 4 aprovado, ver seção 16.2)"
    return "- **Status:** Dia 4 de 9 (em andamento; gate do Dia 4 não cumprido, ver seção 16.2)"


def update_status(text: str, gate_ok: bool) -> str:
    pattern = re.compile(r"(?m)^- \*\*Status:\*\* .*$")
    if len(pattern.findall(text)) != 1:
        raise ValueError("linha de Status não encontrada (ou repetida) no PROJECT.md")
    return pattern.sub(lambda _m: status_line(gate_ok), text)


def update_tree(text: str) -> tuple[str, list[str]]:
    """Edita a árvore de pastas; se não achar as linhas, avisa em vez de falhar."""
    warnings: list[str] = []
    extract = re.compile(r"(?m)^(.*extract/ +# )toeplitz\.py, sha3\.py$")
    if extract.search(text):
        text = extract.sub(r"\1blocks.py, budget.py, toeplitz.py, sha3.py", text)
    elif "blocks.py, budget.py" not in text:
        warnings.append("árvore de pastas: linha de extract/ não encontrada; ajuste à mão")
    if re.search(r"(?m)^.*├── pipeline\.py", text) is None:
        storage = re.compile(r"(?m)^(?P<line>(?P<pre>.*?├── )storage\.py(?P<pad> +)# .*)$")
        if storage.search(text):
            text = storage.sub(lambda m: m["line"] + "\n" + m["pre"] + "pipeline.py" + m["pad"][:-1]
                               + "# fontes -> saúde -> extração -> mixer -> semente (Dia 4)", text, count=1)
        else:
            warnings.append("árvore de pastas: linha de storage.py não encontrada; ajuste à mão")
    return text, warnings


def update_project(path: Path, blocks: list[tuple[str, tuple[str, str, str]]], gate_ok: bool) -> tuple[str, list[str]]:
    """Aplica tudo preservando a quebra de linha. Nada é escrito aqui; devolve (texto novo, avisos)."""
    raw = path.read_bytes().decode("utf-8")
    eol = "\r\n" if "\r\n" in raw else "\n"
    text = raw.replace("\r\n", "\n")
    text = _replace_once(text, POLICY_OLD, POLICY_NEW, "política do 6.9")
    text = update_status(text, gate_ok)
    text, warnings = update_tree(text)
    for block, spec in blocks:
        text = g.upsert_block(text, block, spec)
    return text.replace("\n", eol), warnings


def main() -> None:
    parser = argparse.ArgumentParser(description="Documentação do Dia 4 (mixer, pipeline e gate de resiliência)")
    parser.add_argument("--resilience-meta", type=Path, required=True)
    parser.add_argument("--project", type=Path, default=g.PROJECT)
    parser.add_argument("--dry-run", action="store_true", help="mostra os blocos e não escreve")
    args = parser.parse_args()
    try:
        meta, rows = load_resilience(args.resilience_meta)
        blocks = [(build_gate(meta, rows), GATE), (build_mixer(), MIXER), (build_pipeline(), PIPELINE),
                  (build_limits(), LIMITS)]
        new_text, warnings = update_project(args.project, blocks, bool(meta["gate"]["ok"]))
    except ValueError as exc:
        print(f"ERRO: {exc}", file=sys.stderr)
        sys.exit(1)
    for w in warnings:
        print(f"AVISO: {w}", file=sys.stderr)
    if args.dry_run:
        print("\n\n".join(b for b, _ in blocks))
        return
    args.project.write_bytes(new_text.encode("utf-8"))
    print(f"{args.project} atualizado: 16.2, 6.9.1, 6.14, limitações, política do 6.9, status e árvore de pastas.")


if __name__ == "__main__":
    main()
