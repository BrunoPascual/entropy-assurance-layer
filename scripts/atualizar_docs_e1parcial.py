"""Dia 6: registra no PROJECT.md o E1 parcial (QPU real x simulador x os; jobs cal).

Nenhum número é digitado: o bloco inteiro sai dos CSVs de ``data/results``. O bloco fica entre
``<!-- dia6-e1parcial:start -->`` e ``<!-- dia6-e1parcial:end -->``, logo depois de
``<!-- dia6-gate:end -->``.

Regras:
  - por padrão só verifica e mostra o bloco; nada é gravado. ``--aplicar`` grava;
  - tudo ou nada: arquivo temporário e troca; qualquer problema recusa sem gravar;
  - preserva o fim de linha do arquivo (CRLF ou LF); fim de linha misto recusa;
  - idempotente: bloco igual ao existente = nada a fazer; bloco diferente = recusa;
  - não mexe no campo Status nem nas demais seções (pendências R11 e R12).

Uso (na raiz do projeto):
    py -3.12 scripts\\atualizar_docs_e1parcial.py            (mostra)
    py -3.12 scripts\\atualizar_docs_e1parcial.py --aplicar  (grava)
Código de saída: 0 ok; 1 recusado; 2 erro de uso.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import math
import os
import sys
from datetime import datetime
from pathlib import Path
from statistics import NormalDist
from typing import Any

PROJECT_PATH = Path("PROJECT.md")
RESULTS_DIR = Path("data/results")
START = "<!-- dia6-e1parcial:start -->"
END = "<!-- dia6-e1parcial:end -->"
ANCHOR = "<!-- dia6-gate:end -->"
FONTES = ("qpu_real", "simulador", "os")

CSV_COLUMNS: dict[str, tuple[str, ...]] = {
    "dia6_qpu_vs_sim_lotes.csv": (
        "fonte", "lote", "source_id", "n_bits", "saude_approved", "saude_h_estimated",
        "saude_h_threshold", "saude_stats_monobit", "saude_stats_block", "saude_stats_runs",
        "saude_rct_pass", "saude_apt_pass", "saude_replay_pass", "saude_h_health_pass",
        "saude_reasons", "ext_n_output_bits", "ext_rendimento"),
    "dia6_qpu_vs_sim_resumo.csv": (
        "fonte", "n_qubits", "n_shots", "frac1_lote1", "frac1_lote2", "zp1_max_abs_lote1",
        "zp1_max_abs_lote2", "zp1_n_acima3_lote1", "zp1_n_acima3_lote2",
        "corr_viz_n_acima3_lote1", "corr_viz_n_acima3_lote2", "corr_shot_n_acima3_lote1",
        "corr_shot_n_acima3_lote2", "zdiff_dp", "zdiff_n_acima3", "zdiff_max_abs",
        "zdiff_max_pos"),
    "dia6_qpu_excesso_leitura.csv": (
        "lote", "posicao", "n_shots", "p1", "erro_leitura", "excesso", "acima_do_limite"),
    "dia6_qpu_vs_sim_por_qubit.csv": (
        "fonte", "lote", "posicao", "n_shots", "p1", "corr_vizinho", "erro_leitura"),
    "dia6_deriva_dia_lotes.csv": (
        "lote", "n_shots", "criado_em", "calibracao_no_envio", "frac1", "conferencia"),
    "dia6_deriva_dia_conjunto_fixo.csv": (
        "tipo", "grupo", "id", "lote", "estimativa", "z", "z_esperado", "testavel", "replica",
        "magnitude_compativel"),
    "dia6_deriva_dia_estabilidade.csv": (
        "lote_a", "lote_b", "zdiff_media", "zdiff_dp", "zdiff_n_acima3", "zdiff_max_abs"),
}


class DocError(Exception):
    """Recusa: nada foi gravado."""


# ---------------------------------------------------------------- leitura

def read_csv(path: Path, required: tuple[str, ...]) -> list[dict[str, str]]:
    if not path.exists():
        raise DocError(f"não encontrado: {path}")
    with open(path, encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        missing = [c for c in required if c not in (reader.fieldnames or [])]
        if missing:
            raise DocError(f"{path.name}: faltam as colunas {missing}")
        rows = list(reader)
    if not rows:
        raise DocError(f"{path.name}: vazio")
    return rows


def load_inputs(results_dir: Path) -> tuple[dict[str, list[dict[str, str]]], dict[str, str]]:
    data, shas = {}, {}
    for name, cols in CSV_COLUMNS.items():
        path = results_dir / name
        data[name] = read_csv(path, cols)
        shas[name] = hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()
    return data, shas


# ---------------------------------------------------------------- formatação

def _flt(s: str, where: str) -> float:
    try:
        x = float(s)
    except ValueError:
        raise DocError(f"{where}: '{s}' não é número") from None
    if not math.isfinite(x):
        raise DocError(f"{where}: '{s}' não é finito")
    return x


def _int(s: str, where: str) -> int:
    try:
        return int(s)
    except ValueError:
        try:
            x = float(s)
        except ValueError:
            raise DocError(f"{where}: '{s}' não é inteiro") from None
        if x != int(x):
            raise DocError(f"{where}: '{s}' não é inteiro")
        return int(x)


def _bool(s: str, where: str) -> bool | None:
    if s == "":
        return None
    if s not in ("True", "False"):
        raise DocError(f"{where}: '{s}' não é True/False")
    return s == "True"


def fnum(x: float, nd: int = 4) -> str:
    return f"{x:.{nd}f}".replace(".", ",")


def fsci(x: float) -> str:
    if x == 0:
        return "0"
    return f"{x:.2e}".replace(".", ",")


def fsign(x: float, nd: int = 2) -> str:
    return f"{x:+.{nd}f}".replace(".", ",")


def yes(b: bool | None) -> str:
    return "—" if b is None else ("sim" if b else "não")


def table(headers: list[str], rows: list[list[str]]) -> list[str]:
    out = ["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"]
    out += ["| " + " | ".join(r) + " |" for r in rows]
    return out


def _minutes(a: str, b: str, where: str) -> int:
    try:
        ta = datetime.fromisoformat(a.replace("Z", "+00:00"))
        tb = datetime.fromisoformat(b.replace("Z", "+00:00"))
    except ValueError:
        raise DocError(f"{where}: data inválida") from None
    return round((tb - ta).total_seconds() / 60)


def _by(rows: list[dict[str, str]], key: str) -> dict[str, list[dict[str, str]]]:
    out: dict[str, list[dict[str, str]]] = {}
    for r in rows:
        out.setdefault(r[key], []).append(r)
    return out


# ---------------------------------------------------------------- seções

def sec_saude(d: dict[str, list[dict[str, str]]]) -> list[str]:
    rows = sorted(d["dia6_qpu_vs_sim_lotes.csv"], key=lambda r: (FONTES.index(r["fonte"]), r["lote"]))
    thr = _flt(rows[0]["saude_h_threshold"], "saude_h_threshold")
    out = ["#### Testes de saúde por lote", "",
           f"Limiar de H estimada: {fnum(thr, 2)} (seção 6.5, fixado antes dos dados reais e não ajustado).", ""]
    body = []
    for r in rows:
        w = f"lotes {r['fonte']} {r['lote']}"
        basic = [_bool(r[c], w) for c in ("saude_rct_pass", "saude_apt_pass", "saude_replay_pass")]
        body.append([
            f"{r['fonte']} ({r['source_id']})", r["lote"], yes(_bool(r["saude_approved"], w)),
            "ok" if all(basic) else "falhou", fnum(_flt(r["saude_h_estimated"], w), 4),
            yes(_bool(r["saude_h_health_pass"], w)),
            fsci(_flt(r["saude_stats_monobit"], w)), fnum(_flt(r["saude_stats_block"], w), 3),
            fsci(_flt(r["saude_stats_runs"], w)),
            str(_int(r["ext_n_output_bits"], w)), fnum(_flt(r["ext_rendimento"], w), 3)])
    out += table(["Fonte", "Lote", "Aprovado", "RCT, APT e replay", "H estimada", "H >= limiar",
                  "p monobit", "p blocos", "p runs", "Bits extraídos", "Rendimento"], body)
    out.append("")
    for r in rows:
        if _bool(r["saude_approved"], "saude_approved") is False:
            reasons = r["saude_reasons"].replace(" | ", "; ")
            out.append(f"- {r['fonte']} lote {r['lote']} reprovado: {reasons}")
    out += ["", "O `p = 0` do teste de runs, quando aparece, vem do pré-teste de frequência que "
            "falhou (SP 800-22, 2.3.4); não é evidência independente do monobit."]
    return out


def sec_resumo(d: dict[str, list[dict[str, str]]]) -> list[str]:
    rows = sorted(d["dia6_qpu_vs_sim_resumo.csv"], key=lambda r: FONTES.index(r["fonte"]))
    body = []
    for r in rows:
        w = f"resumo {r['fonte']}"
        body.append([
            r["fonte"], f"{fnum(_flt(r['frac1_lote1'], w), 4)} / {fnum(_flt(r['frac1_lote2'], w), 4)}",
            f"{fnum(_flt(r['zp1_max_abs_lote1'], w), 1)} / {fnum(_flt(r['zp1_max_abs_lote2'], w), 1)}",
            f"{r['zp1_n_acima3_lote1']} / {r['zp1_n_acima3_lote2']}",
            f"{r['corr_viz_n_acima3_lote1']} / {r['corr_viz_n_acima3_lote2']}",
            f"{r['corr_shot_n_acima3_lote1']} / {r['corr_shot_n_acima3_lote2']}",
            fnum(_flt(r["zdiff_dp"], w), 2), r["zdiff_n_acima3"]])
    first = rows[0]
    return ["#### Viés, correlação e estabilidade entre os dois lotes da coleta 1", "",
            f"{first['n_qubits']} qubits, {first['n_shots']} shots por lote. Em cada célula de "
            "dois valores: lote 1 / lote 2. O z de p1 é em relação a 0,5.", "",
            *table(["Fonte", "Fração de 1", "\\|z\\| máx. de p1", "Qubits com \\|z\\| > 3",
                    "Correlação com o vizinho, \\|z\\| > 3", "Correlação com o shot seguinte, \\|z\\| > 3",
                    "Desvio-padrão do zdiff", "\\|zdiff\\| > 3"], body),
            "", "O zdiff compara o p1 de cada qubit entre os lotes 1 e 2; sem deriva e sem "
            "estrutura, o desvio-padrão esperado é perto de 1. As fontes `simulador` e `os` servem de controle."]


def sec_excesso(d: dict[str, list[dict[str, str]]]) -> list[str]:
    lots = _by(d["dia6_qpu_excesso_leitura.csv"], "lote")
    out = ["#### QPU real: desvio de 0,5 acima do erro de leitura do retrato", ""]
    above: dict[str, list[int]] = {}
    for lote in sorted(lots):
        rs = lots[lote]
        above[lote] = [_int(r["posicao"], "excesso") for r in rs
                       if _bool(r["acima_do_limite"], "excesso") is True]
        out.append(f"- Lote {lote}: {len(above[lote])} de {len(rs)} qubits acima do limite "
                   f"(posições: {', '.join(map(str, above[lote])) or 'nenhuma'}).")
    common = sorted(set.intersection(*(set(v) for v in above.values())))
    n_q = len(next(iter(lots.values())))
    chance = n_q * 2 * (1 - NormalDist().cdf(3))
    out += [f"- Acima do limite em todos os lotes: {', '.join(map(str, common)) or 'nenhuma posição'}.",
            f"- Esperado ao acaso, sem viés além do erro de leitura: cerca de {fnum(chance, 2)} por lote.",
            "", "O limite é 3 erros-padrão de p1 (0,5 / raiz do número de shots) e o excesso é "
            "\\|p1 - 0,5\\| menos o erro de leitura do retrato gravado no envio."]
    return out


def sec_vizinhos(d: dict[str, list[dict[str, str]]]) -> list[str]:
    rows = [r for r in d["dia6_qpu_vs_sim_por_qubit.csv"] if r["corr_vizinho"] != ""]
    out = ["#### Correlação com a posição vizinha", ""]
    qpu_sets: dict[str, dict[int, float]] = {}
    for fonte in FONTES:
        by_lot = _by([r for r in rows if r["fonte"] == fonte], "lote")
        for lote in sorted(by_lot):
            rs = by_lot[lote]
            zcrit = NormalDist().inv_cdf(1 - 0.05 / (2 * len(rs)))
            hits = {}
            for r in rs:
                w = f"por_qubit {fonte} {lote}"
                z = _flt(r["corr_vizinho"], w) * math.sqrt(_int(r["n_shots"], w))
                if abs(z) > zcrit:
                    hits[_int(r["posicao"], w)] = z
            if fonte == "qpu_real":
                qpu_sets[lote] = hits
            lst = ", ".join(f"{p}-{p + 1} (z = {fnum(z, 2)})"
                            for p, z in sorted(hits.items(), key=lambda t: -abs(t[1])))
            out.append(f"- {fonte} lote {lote}: pares acima do limite de Bonferroni "
                       f"(|z| > {fnum(zcrit, 2)}, {len(rs)} pares): {lst or 'nenhum'}.")
    if qpu_sets:
        common = sorted(set.intersection(*(set(v) for v in qpu_sets.values())))
        out.append(f"- QPU real, acima do limite em todos os lotes: "
                   f"{', '.join(f'{p}-{p + 1}' for p in common) or 'nenhum par'}.")
    out += ["", "z = r vezes a raiz do número de shots (aproximação). \"Vizinho\" é a posição i + 1 "
            "do índice físico, não necessariamente um par acoplado no chip."]
    return out


def sec_leitura_alta(d: dict[str, list[dict[str, str]]]) -> list[str]:
    q = [r for r in d["dia6_qpu_vs_sim_por_qubit.csv"] if r["fonte"] == "qpu_real"]
    top = max(q, key=lambda r: _flt(r["erro_leitura"], "erro_leitura"))
    pos = top["posicao"]
    parts = []
    for r in sorted((r for r in q if r["posicao"] == pos), key=lambda r: r["lote"]):
        w = f"por_qubit posicao {pos}"
        p1, n = _flt(r["p1"], w), _int(r["n_shots"], w)
        parts.append(f"lote {r['lote']}: p1 = {fnum(p1, 4)}, z = {fnum((p1 - 0.5) / (0.5 / math.sqrt(n)), 2)}")
    return ["#### Maior erro de leitura do retrato", "",
            f"Posição {pos}: erro de leitura {fnum(_flt(top['erro_leitura'], 'erro_leitura'), 4)} "
            f"({'; '.join(parts)}). Com erro de leitura perto de 0,5, a saída tende a não depender do "
            "estado preparado e pode parecer sem viés. Isso é inferência a partir do retrato "
            "gravado, não medida desta coleta, e mostra que teste de saída não certifica a origem "
            "(hipótese do E2)."]


def sec_cal(d: dict[str, list[dict[str, str]]]) -> list[str]:
    lotes = {r["lote"]: r for r in d["dia6_deriva_dia_lotes.csv"]}
    fixo = d["dia6_deriva_dia_conjunto_fixo.csv"]
    cal_rows = [r for r in fixo if r["lote"].startswith("cal_")]
    if not cal_rows:
        raise DocError("conjunto fixo sem linhas de lotes cal")
    out = ["#### Jobs cal contra a coleta 1 (persistência dentro do dia)", ""]
    body = []
    for r in sorted(lotes.values(), key=lambda r: r["lote"]):
        body.append([r["lote"], r["criado_em"], r["calibracao_no_envio"], r["n_shots"],
                     fnum(_flt(r["frac1"], "frac1"), 4), r["conferencia"]])
    out += table(["Lote", "criado_em (UTC)", "Calibração no envio", "Shots", "Fração de 1", "Conferência"], body)
    try:
        gaps = [("cal_001", "cal_002"), ("cal_002", "coleta1_001"), ("cal_001", "coleta1_001")]
        txt = "; ".join(f"{a} → {b}: {_minutes(lotes[a]['criado_em'], lotes[b]['criado_em'], 'criado_em')} min"
                        for a, b in gaps)
    except KeyError as exc:
        raise DocError(f"deriva_dia_lotes sem o lote {exc}") from None
    out += ["", f"Intervalos pelo campo `criado_em`, que é o momento em que o lote foi salvo, não o da "
            f"execução na QPU: {txt}.", ""]
    body = []
    for r in sorted(cal_rows, key=lambda r: (r["tipo"], r["id"], r["lote"])):
        w = f"fixo {r['id']} {r['lote']}"
        body.append([f"{r['tipo']} {r['id']}", r["grupo"], r["lote"], fnum(_flt(r["estimativa"], w), 4),
                     fnum(_flt(r["z"], w), 2), fnum(_flt(r["z_esperado"], w), 2),
                     yes(_bool(r["testavel"], w)), yes(_bool(r["replica"], w)),
                     yes(_bool(r["magnitude_compativel"], w))])
    out += table(["Item", "Grupo", "Lote", "Estimativa", "z", "z esperado", "Testável", "Replica",
                  "Magnitude compatível"], body)
    out.append("")
    items: dict[tuple[str, str], list[dict[str, str]]] = {}
    for r in cal_rows:
        items.setdefault((r["tipo"], r["id"]), []).append(r)
    for (tipo, ident), rs in items.items():
        rep = [r["lote"] for r in rs if _bool(r["replica"], "replica") is True]
        nrep = [r["lote"] for r in rs if _bool(r["replica"], "replica") is False]
        nt = [r["lote"] for r in rs if _bool(r["testavel"], "testavel") is False]
        out.append(f"- {tipo} {ident}: replica em {', '.join(rep) or 'nenhum lote'}; não replica em "
                   f"{', '.join(nrep) or 'nenhum lote'}; não testável em {', '.join(nt) or 'nenhum lote'}.")
    out += ["", "Estabilidade do p1 dos qubits entre pares de lotes (zdiff, com shots diferentes):", ""]
    body = [[f"{r['lote_a']} x {r['lote_b']}", fsign(_flt(r["zdiff_media"], "est")),
             fnum(_flt(r["zdiff_dp"], "est"), 2), r["zdiff_n_acima3"],
             fnum(_flt(r["zdiff_max_abs"], "est"), 2)] for r in d["dia6_deriva_dia_estabilidade.csv"]]
    out += table(["Par de lotes", "zdiff médio", "Desvio-padrão do zdiff", "\\|zdiff\\| > 3", "\\|zdiff\\| máx."], body)
    return out


LIMITES = [
    "#### Limites desta análise", "",
    "- Uma sessão, num único dia, num único backend. O E1 completo pede sessões em outros horários "
    "e em outros dias (seção 9.3); nada aqui mede deriva entre dias.",
    "- O conjunto fixo e os critérios (testável, replica, magnitude compatível) estão como constantes "
    "em `scripts/analisar_cal.py` e foram fixados antes da leitura dos lotes cal, só com base na coleta 1. "
    "Uma das posições do conjunto fixo (112, do par 112-113) já tinha aparecido entre as colunas "
    "mais afastadas de 0,5 do `cal_001` no registro da seção 18; a correlação do par não tinha sido vista.",
    "- Os lotes cal não estão no inventário: a integridade deles é só o `batch_hash`. A coleta 1 é "
    "conferida também pelo SHA-256 do inventário.",
    "- O retrato de erro de leitura e a data de calibração gravados são os do envio, não os da "
    "execução (R8). Os quatro lotes têm o mesmo retrato de erro de leitura.",
    "- `criado_em` é o momento em que o lote foi salvo; os tempos de execução na QPU não estão nos "
    "dados e não entram nas conclusões.",
    "- O simulador usa a calibração congelada do FakeKingston, não a do dia da coleta; ele serve de "
    "referência qualitativa. O limiar de H estimada e os limiares dos testes de saúde não foram alterados.",
    "- Mais de um teste por qubit: os qubits e pares citados vêm de varreduras de 156 e 155 itens; "
    "só o que repete entre lotes independentes ou passa pelo limite de Bonferroni indicado tem peso.",
    "- Isto é um registro de medições. A causa do viés (leitura, porta, relaxação, calibração ou "
    "crosstalk) não foi determinada.",
]


def build_block(d: dict[str, list[dict[str, str]]], shas: dict[str, str]) -> str:
    lots = d["dia6_qpu_vs_sim_lotes.csv"]
    n_bits = lots[0]["n_bits"]
    L = [START, "### E1 parcial (Dia 6): QPU real, simulador e fonte os; jobs cal", "",
         "Gerado por `scripts/atualizar_docs_e1parcial.py`. Todo número abaixo vem dos CSVs de "
         "`data/results` (SHA-256 com fim de linha normalizado para LF):", ""]
    L += [f"- `{name}`: `{shas[name]}`" for name in CSV_COLUMNS]
    L += ["", f"Entrada: {len(_by(lots, 'lote'))} lotes por fonte, de {n_bits} bits cada, da sessão "
          "`coleta1`. O simulador é o `qpu_sim` com ruído do FakeKingston; a fonte `os` tem o mesmo formato.", ""]
    for sec in (sec_saude, sec_resumo, sec_excesso, sec_vizinhos, sec_leitura_alta, sec_cal):
        L += sec(d) + [""]
    L += LIMITES + ["", END]
    return "\n".join(L)


# ---------------------------------------------------------------- aplicação no PROJECT.md

def apply_block(data: bytes, block_lf: str) -> bytes | None:
    """Devolve os novos bytes do arquivo, ou None se o bloco já está lá, igual."""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        raise DocError("PROJECT.md não é UTF-8") from None
    crlf = "\r\n" in text
    text_lf = text.replace("\r\n", "\n") if crlf else text
    if "\r" in text_lf:
        raise DocError("PROJECT.md com fim de linha misto ou CR solto")
    if crlf and text_lf.replace("\n", "\r\n") != text:
        raise DocError("PROJECT.md com fim de linha misto (CRLF e LF)")
    n_start, n_end = text_lf.count(START), text_lf.count(END)
    if (n_start, n_end) == (0, 0):
        if text_lf.count(ANCHOR) != 1:
            raise DocError(f"âncora {ANCHOR} deve aparecer exatamente uma vez")
        idx = text_lf.index(ANCHOR) + len(ANCHOR)
        new_lf = text_lf[:idx] + "\n\n" + block_lf + text_lf[idx:]
    elif (n_start, n_end) == (1, 1) and text_lf.index(START) < text_lf.index(END):
        s, e = text_lf.index(START), text_lf.index(END) + len(END)
        if text_lf[s:e] == block_lf:
            return None
        raise DocError("já existe um bloco E1 parcial diferente; não sobrescrevo")
    else:
        raise DocError("marcadores do bloco E1 parcial inconsistentes")
    new = new_lf.replace("\n", "\r\n") if crlf else new_lf
    return new.encode("utf-8")


def write_atomic(path: Path, data: bytes) -> None:
    tmp = path.with_name(path.name + ".tmp")
    if tmp.exists():
        raise DocError(f"temporário esquecido: {tmp.name}")
    with open(tmp, "xb") as fh:
        fh.write(data)
    os.replace(tmp, path)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Dia 6: registra o E1 parcial no PROJECT.md")
    ap.add_argument("--projeto", type=Path, default=PROJECT_PATH)
    ap.add_argument("--results-dir", type=Path, default=RESULTS_DIR)
    ap.add_argument("--aplicar", action="store_true", help="grava no PROJECT.md (padrão: só mostra)")
    args = ap.parse_args(argv)
    try:
        d, shas = load_inputs(args.results_dir)
        block = build_block(d, shas)
        if not args.projeto.exists():
            raise DocError(f"não encontrado: {args.projeto}")
        new = apply_block(args.projeto.read_bytes(), block)
        if not args.aplicar:
            print(block)
            print("\n--- nada gravado (use --aplicar)" if new is not None
                  else "\n--- o PROJECT.md já tem este bloco, igual")
            return 0
        if new is None:
            print("já aplicado: nada a fazer")
            return 0
        write_atomic(args.projeto, new)
        print(f"gravado: {args.projeto} (+{block.count(chr(10)) + 3} linhas)")
    except DocError as exc:
        print(f"RECUSADO: {exc}")
        return 1
    except Exception as exc:  # texto de exceção não é impresso, só a classe
        print(f"erro inesperado: {type(exc).__name__}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
