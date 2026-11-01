"""Dia 6: resumo da comparação QPU real x simulador x os, a partir do CSV por qubit.

Só lê ``data/results/dia6_qpu_vs_sim_por_qubit.csv`` (gerado por ``analisar_coleta1.py``) e
não regera dados. Grava dois CSVs determinísticos:

``dia6_qpu_vs_sim_resumo.csv``: uma linha por fonte, com
  - fração global de 1 por lote (média de p1; todos os qubits têm os mesmos shots);
  - por lote: maior |z| de p1 e quantos qubits têm |z| > 3;
  - por lote: correlação com a posição vizinha (z = r * sqrt(shots)) e com o shot seguinte
    (z = r * sqrt(shots - 1)): maior |r| e quantos qubits têm |z| > 3;
  - estabilidade entre os lotes 1 e 2: zdiff = (p1_lote1 - p1_lote2) / sqrt(2 pm (1 - pm) / shots),
    com pm a média dos dois; desvio-padrão amostral, quantos |zdiff| > 3 e o maior |zdiff|.

``dia6_qpu_excesso_leitura.csv``: uma linha por qubit e lote da QPU real, com
  desvio = |p1 - 0,5|, excesso = desvio - erro_leitura e limite = 3 erros-padrão
  (0,5 / sqrt(shots)). ``acima_do_limite`` marca excesso > limite. Pela definição do erro de
  leitura (média dos dois erros de atribuição), só a leitura não leva o desvio além dele.

Regras: entrada inválida recusa. Saída igual à existente (ignorando CRLF/LF): nada é gravado.
Saída diferente da existente: recusa, sem gravar nenhum dos dois.

Uso (na raiz do projeto):
    py -3.12 scripts\\resumo_coleta1.py
    py -3.12 scripts\\resumo_coleta1.py --sessao coleta2
Com ``--sessao`` diferente de ``coleta1``, a entrada padrão e as saídas ganham o prefixo
``dia6_<sessao>_`` (os mesmos nomes que ``analisar_coleta1.py --sessao`` grava).
Código de saída: 0 gravado ou já igual; 1 recusado; 2 erro de uso.
"""
from __future__ import annotations

import argparse
import csv
import io
import math
import os
import re
import sys
from pathlib import Path
from typing import Any

IN_PATH = Path("data/results/dia6_qpu_vs_sim_por_qubit.csv")
OUT_DIR = Path("data/results")
RESUMO_NAME = "dia6_qpu_vs_sim_resumo.csv"
EXCESSO_NAME = "dia6_qpu_excesso_leitura.csv"
SESSION = "coleta1"
SESSION_RE = re.compile(r"[A-Za-z0-9]+")
REAL = "qpu_real"
LOTS = ("1", "2")
Z_LIMIT = 3.0
COLUMNS_IN = ("fonte", "lote", "posicao", "qubit_fisico", "n_shots", "p1",
              "corr_vizinho", "corr_prox_shot", "erro_leitura")


class SummaryError(Exception):
    """Recusa: nada foi gravado."""


def check_session(session: str) -> str:
    """Só letras e dígitos: entra em nomes de arquivo, e ``_`` separa o rótulo."""
    if not isinstance(session, str) or not SESSION_RE.fullmatch(session):
        raise SummaryError(f"sessão inválida: {session!r}")
    return session


def session_file(name: str, session: str) -> str:
    """``coleta1`` mantém o nome de sempre; outra sessão ganha o prefixo ``dia6_<sessao>_``."""
    if session == SESSION:
        return name
    return name.replace("dia6_", f"dia6_{session}_", 1)


def input_for(session: str) -> Path:
    """CSV por qubit que ``analisar_coleta1.py --sessao`` grava para a sessão."""
    return IN_PATH.with_name(session_file(IN_PATH.name, session))


# ---------------------------------------------------------------- leitura

def _num(value: str, name: str, where: str, *, empty_ok: bool = False) -> float | None:
    if value == "":
        if empty_ok:
            return None
        raise SummaryError(f"{where}: {name} vazio")
    try:
        x = float(value)
    except ValueError:
        raise SummaryError(f"{where}: {name} não é número") from None
    if not math.isfinite(x):
        raise SummaryError(f"{where}: {name} não é finito")
    return x


def _parse(raw: dict[str, str], line: int) -> dict[str, Any]:
    where = f"linha {line}"
    try:
        pos, shots = int(raw["posicao"]), int(raw["n_shots"])
    except ValueError:
        raise SummaryError(f"{where}: posicao ou n_shots não é inteiro") from None
    if pos < 0 or shots < 3:
        raise SummaryError(f"{where}: posicao negativa ou n_shots < 3")
    p1 = _num(raw["p1"], "p1", where)
    if not 0.0 <= p1 <= 1.0:
        raise SummaryError(f"{where}: p1 fora de [0, 1]")
    return {"pos": pos, "fisico": raw["qubit_fisico"], "n_shots": shots, "p1": p1,
            "viz": _num(raw["corr_vizinho"], "corr_vizinho", where, empty_ok=True),
            "shot": _num(raw["corr_prox_shot"], "corr_prox_shot", where, empty_ok=True),
            "erro": _num(raw["erro_leitura"], "erro_leitura", where, empty_ok=True)}


def read_table(path: Path) -> dict[str, dict[str, list[dict[str, Any]]]]:
    """{fonte: {lote: [linhas ordenadas por posição]}}, na ordem em que as fontes aparecem."""
    if not path.exists():
        raise SummaryError(f"entrada não encontrada: {path}")
    with open(path, encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        missing = [c for c in COLUMNS_IN if c not in (reader.fieldnames or [])]
        if missing:
            raise SummaryError(f"entrada sem as colunas {missing}")
        table: dict[str, dict[str, list[dict[str, Any]]]] = {}
        for line, raw in enumerate(reader, start=2):
            table.setdefault(raw["fonte"], {}).setdefault(raw["lote"], []).append(_parse(raw, line))
    if not table:
        raise SummaryError("entrada vazia")
    if REAL not in table:
        raise SummaryError(f"entrada sem a fonte {REAL}")
    for fonte, lots in table.items():
        if tuple(sorted(lots)) != LOTS:
            raise SummaryError(f"{fonte}: lotes {sorted(lots)}, esperado {list(LOTS)}")
        for rows in lots.values():
            rows.sort(key=lambda r: r["pos"])
        ref = lots[LOTS[0]]
        n = len(ref)
        for lote, rows in lots.items():
            if [r["pos"] for r in rows] != list(range(n)):
                raise SummaryError(f"{fonte} lote {lote}: posições não são 0..{n - 1} sem repetição")
            if [r["fisico"] for r in rows] != [r["fisico"] for r in ref]:
                raise SummaryError(f"{fonte} lote {lote}: mapa de qubits difere do lote {LOTS[0]}")
            if {r["n_shots"] for r in rows} != {ref[0]["n_shots"]}:
                raise SummaryError(f"{fonte}: n_shots não é o mesmo em todas as linhas")
    for lote, rows in table[REAL].items():
        if any(r["erro"] is None for r in rows):
            raise SummaryError(f"{REAL} lote {lote}: erro_leitura vazio")
    return table


# ---------------------------------------------------------------- contas

def _max_abs(values: list[float]) -> float | None:
    return max((abs(v) for v in values), default=None)


def _count_above(values: list[float], limit: float = Z_LIMIT) -> int:
    return sum(1 for v in values if abs(v) > limit)


def sample_sd(values: list[float]) -> float | None:
    if len(values) < 2:
        return None
    m = sum(values) / len(values)
    return math.sqrt(sum((v - m) ** 2 for v in values) / (len(values) - 1))


def zdiff(a: list[dict[str, Any]], b: list[dict[str, Any]], shots: int) -> list[tuple[int, float]]:
    """(posição, zdiff) dos qubits com média entre 0 e 1 exclusivos."""
    out = []
    for ra, rb in zip(a, b):
        pm = (ra["p1"] + rb["p1"]) / 2
        if 0.0 < pm < 1.0:
            out.append((ra["pos"], (ra["p1"] - rb["p1"]) / math.sqrt(2 * pm * (1 - pm) / shots)))
    return out


def summary_row(fonte: str, lots: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    shots = lots[LOTS[0]][0]["n_shots"]
    row: dict[str, Any] = {"fonte": fonte, "n_qubits": len(lots[LOTS[0]]), "n_shots": shots}
    for k in LOTS:
        rs = lots[k]
        row[f"frac1_lote{k}"] = sum(r["p1"] for r in rs) / len(rs)
    for k in LOTS:
        z = [(r["p1"] - 0.5) / math.sqrt(0.25 / shots) for r in lots[k]]
        row[f"zp1_max_abs_lote{k}"] = _max_abs(z)
        row[f"zp1_n_acima3_lote{k}"] = _count_above(z)
    for key, col, n_eff in (("viz", "corr_viz", shots), ("shot", "corr_shot", shots - 1)):
        for k in LOTS:
            r_vals = [r[key] for r in lots[k] if r[key] is not None]
            row[f"{col}_n_validos_lote{k}"] = len(r_vals)
            row[f"{col}_max_abs_lote{k}"] = _max_abs(r_vals)
            row[f"{col}_n_acima3_lote{k}"] = _count_above([v * math.sqrt(n_eff) for v in r_vals])
    zd = zdiff(lots[LOTS[0]], lots[LOTS[1]], shots)
    values = [z for _, z in zd]
    row["zdiff_n"] = len(values)
    row["zdiff_dp"] = sample_sd(values)
    row["zdiff_n_acima3"] = _count_above(values)
    top = max(zd, key=lambda t: abs(t[1]), default=None)
    row["zdiff_max_abs"] = None if top is None else abs(top[1])
    row["zdiff_max_pos"] = None if top is None else top[0]
    return row


def excess_rows(lots: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    rows = []
    for k in LOTS:
        for r in lots[k]:
            limit = 3 * 0.5 / math.sqrt(r["n_shots"])
            desvio = abs(r["p1"] - 0.5)
            excesso = desvio - r["erro"]
            rows.append({"lote": k, "posicao": r["pos"], "qubit_fisico": r["fisico"],
                         "n_shots": r["n_shots"], "p1": r["p1"], "desvio": desvio,
                         "erro_leitura": r["erro"], "excesso": excesso, "limite_3ep": limit,
                         "acima_do_limite": excesso > limit})
    return rows


# ---------------------------------------------------------------- CSV

def _cell(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return "True" if v else "False"
    if isinstance(v, float):
        return f"{v:.12g}"
    return str(v)


def csv_text(rows: list[dict[str, Any]]) -> str:
    cols = list(rows[0])
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(cols)
    for r in rows:
        w.writerow([_cell(r[c]) for c in cols])
    return buf.getvalue()


def _normalized(data: bytes) -> bytes:
    return data.replace(b"\r\n", b"\n")


def write_deterministic(targets: list[tuple[Path, str]]) -> list[str]:
    """Grava os ausentes; igual = nada; diferente = recusa sem gravar nenhum."""
    states = []
    for path, text in targets:
        if path.with_name(path.name + ".tmp").exists():
            raise SummaryError(f"temporário esquecido: {path.name}.tmp")
        if path.exists():
            if _normalized(path.read_bytes()) != text.encode("utf-8"):
                raise SummaryError(f"{path} já existe com conteúdo diferente; não sobrescrevo")
            states.append("igual")
        else:
            states.append("novo")
    new = [(p, t) for (p, t), s in zip(targets, states) if s == "novo"]
    tmps = []
    try:
        for path, text in new:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_name(path.name + ".tmp")
            with open(tmp, "x", encoding="utf-8", newline="") as fh:
                fh.write(text)
            tmps.append((tmp, path))
    except BaseException:
        for tmp, _ in tmps:
            tmp.unlink(missing_ok=True)
        raise
    for tmp, path in tmps:
        os.rename(tmp, path)
    return states


def build(path: Path) -> tuple[str, str, list[dict[str, Any]]]:
    table = read_table(path)
    summary = [summary_row(f, lots) for f, lots in table.items()]
    return csv_text(summary), csv_text(excess_rows(table[REAL])), summary


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Dia 6: resumo QPU x simulador x os")
    ap.add_argument("--sessao", default=SESSION)
    ap.add_argument("--entrada", type=Path, default=None)
    ap.add_argument("--out-dir", type=Path, default=OUT_DIR)
    args = ap.parse_args(argv)
    try:
        session = check_session(args.sessao)
        resumo, excesso, summary = build(args.entrada or input_for(session))
        targets = [(args.out_dir / session_file(RESUMO_NAME, session), resumo),
                   (args.out_dir / session_file(EXCESSO_NAME, session), excesso)]
        states = write_deterministic(targets)
    except SummaryError as exc:
        print(f"RECUSADO: {exc}")
        return 1
    for (path, _), state in zip(targets, states):
        print(f"{state}: {path}")
    for r in summary:
        print(f"{r['fonte']}: frac1 {_cell(r['frac1_lote1'])} / {_cell(r['frac1_lote2'])} | "
              f"zdiff dp {_cell(r['zdiff_dp'])}, |z|>3: {r['zdiff_n_acima3']} | "
              f"corr_viz |z|>3: {r['corr_viz_n_acima3_lote1']} / {r['corr_viz_n_acima3_lote2']} | "
              f"corr_shot |z|>3: {r['corr_shot_n_acima3_lote1']} / {r['corr_shot_n_acima3_lote2']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
