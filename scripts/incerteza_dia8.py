"""Faixas de incerteza do Dia 8 (revisão crítica das conclusões E1 a E5).

Lê só CSVs de data/results e grava data/results/dia8_incerteza.csv (formato longo).
Nada é digitado à mão. Cada bloco responde a uma pergunta que a revisão levantou:

  h_lotes      A H estimada da QPU é mesmo menor que a da `os`? (permutação exata, 6 contra 6)
  frac1        O viés agregado da QPU tem sempre o mesmo sinal? (IC 95% binomial por lote)
  deriva_dp    O desvio-padrão do zdiff entre lotes passa de 1 por acaso? (bootstrap sobre os qubits)
  e2_fp        O falso positivo da `os` é o que os alfas dos testes prevêem?
  e3_razao     A razão de custo QPU/os resiste ao custo marginal e à máquina lenta?
  e4_hash_xor  A taxa de aprovação do hash difere da do XOR? (Fisher exato)
  e5_s         A faixa de S em cada configuração.

Uso (na raiz do projeto): py -3.12 -m scripts.incerteza_dia8
"""
from __future__ import annotations

import argparse
import math
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

RESULTS = Path("data/results")
OUT_NAME = "dia8_incerteza.csv"
COLUNAS = ["bloco", "item", "estimativa", "ic_inf", "ic_sup", "metodo", "observacao"]
COLETAS = {1: "dia6_", 2: "dia6_coleta2_", 3: "dia6_coleta3_"}
DERIVA = {"mesmo_dia": "dia6_deriva_dia", "coleta2_vs_coleta1": "dia6_deriva_coleta2", "coleta3_vs_coleta1": "dia6_deriva_coleta3"}
BOOT_N = 5000
BOOT_SEED = 20261104
TOL_DP = 1e-6  # o dp recalculado precisa bater com o registrado
ALFA_TESTE = 0.01  # nível de cada um dos 3 testes SP 800-22 do pipeline
N_TESTES = 3
FONTES = {"qpu_real": "QPU real", "simulador": "simulador", "os": "os"}


def _row(bloco: str, item: str, est: float, lo: float | None, hi: float | None, metodo: str, obs: str = "") -> dict:
    return {"bloco": bloco, "item": item, "estimativa": est, "ic_inf": lo, "ic_sup": hi, "metodo": metodo, "observacao": obs}


def _csv(results: Path, name: str) -> pd.DataFrame:
    return pd.read_csv(Path(results) / name, encoding="utf-8-sig")


def clopper_pearson(k: int, n: int, conf: float = 0.95) -> tuple[float, float]:
    """IC exato para uma proporção k/n."""
    a = (1 - conf) / 2
    lo = 0.0 if k == 0 else float(stats.beta.ppf(a, k, n - k + 1))
    hi = 1.0 if k == n else float(stats.beta.ppf(1 - a, k + 1, n - k))
    return lo, hi


# ---------------------------------------------------------------- E1

def bloco_h_lotes(results: Path) -> list[dict]:
    """H estimada por fonte nos lotes distintos e teste de permutação exato QPU real contra os."""
    frames = [_csv(results, f"{p}qpu_vs_sim_lotes.csv").assign(coleta=c) for c, p in COLETAS.items()]
    d = pd.concat(frames, ignore_index=True)
    # o simulador usa semente fixa: o mesmo lote reaparece nas 3 coletas; conta-se cada lote distinto uma vez
    d = d.drop_duplicates(subset=["fonte", "batch_hash"])
    h = {f: d.loc[d["fonte"] == f, "saude_h_estimated"].to_numpy(float) for f in FONTES}
    rows = []
    for f, v in h.items():
        rows.append(_row("h_lotes", f"{FONTES[f]} (n={len(v)} lotes distintos)", float(np.median(v)), float(v.min()), float(v.max()),
                         "mediana, mínimo e máximo dos lotes distintos"))
    p = float(stats.mannwhitneyu(h["qpu_real"], h["os"], method="exact", alternative="two-sided").pvalue)
    rows.append(_row("h_lotes", "p exato qpu_real contra os", p, None, None, "Mann-Whitney exato, 6 contra 6",
                     "os 2 lotes de uma coleta não são independentes (mesmo job ou mesma sessão): p é indicativo, não confirmatório"))
    return rows


def bloco_frac1(results: Path) -> list[dict]:
    """Fração de uns por lote e IC 95% (normal, bits tratados como independentes)."""
    rows = []
    for c, p in COLETAS.items():
        r = _csv(results, f"{p}qpu_vs_sim_resumo.csv").set_index("fonte")
        for f in ("qpu_real", "simulador"):
            n = int(r.loc[f, "n_qubits"] * r.loc[f, "n_shots"])
            for lote in (1, 2):
                p1 = float(r.loc[f, f"frac1_lote{lote}"])
                se = math.sqrt(p1 * (1 - p1) / n)
                rows.append(_row("frac1", f"coleta {c} lote {lote} {FONTES[f]}", p1, p1 - 1.96 * se, p1 + 1.96 * se,
                                 "p ± 1,96·raiz(p(1-p)/n)", f"n = {n} bits"))
    return rows


def _zdiff(q: pd.DataFrame, a: str, b: str) -> np.ndarray:
    """zdiff por qubit com p combinado ponderado pelos shots (reproduz o dp registrado em *_estabilidade.csv)."""
    qa = q[q["lote"] == a].sort_values("posicao")
    qb = q[q["lote"] == b].sort_values("posicao")
    pa, pb = qa["p1"].to_numpy(float), qb["p1"].to_numpy(float)
    na, nb = qa["n_shots"].to_numpy(float), qb["n_shots"].to_numpy(float)
    pool = (na * pa + nb * pb) / (na + nb)
    return (pa - pb) / np.sqrt(pool * (1 - pool) * (1 / na + 1 / nb))


def _boot_dp(z: np.ndarray, rng: np.random.Generator) -> tuple[float, float]:
    idx = rng.integers(0, z.size, size=(BOOT_N, z.size))
    dps = z[idx].std(axis=1, ddof=1)
    return float(np.percentile(dps, 2.5)), float(np.percentile(dps, 97.5))


def bloco_deriva(results: Path) -> list[dict]:
    """DP do zdiff entre pares de lotes com IC bootstrap; confere o dp contra o CSV registrado."""
    rng = np.random.default_rng(BOOT_SEED)
    rows = []
    for rotulo, base in DERIVA.items():
        q = _csv(results, f"{base}_por_qubit.csv")
        est = _csv(results, f"{base}_estabilidade.csv")
        for _, e in est.iterrows():
            z = _zdiff(q, e["lote_a"], e["lote_b"])
            dp = float(z.std(ddof=1))
            if abs(dp - float(e["zdiff_dp"])) > TOL_DP:
                raise ValueError(f"dp recalculado {dp} difere do registrado {e['zdiff_dp']} em {e['lote_a']} x {e['lote_b']}")
            lo, hi = _boot_dp(z, rng)
            acima = int((np.abs(z) > 3).sum())
            esperado = z.size * 2 * stats.norm.sf(3)
            rows.append(_row("deriva_dp", f"{rotulo}: {e['lote_a']} x {e['lote_b']}", dp, lo, hi, f"bootstrap de {BOOT_N} sobre os {z.size} qubits",
                             f"|z|>3: {acima} (esperado {esperado:.2f} se só houvesse amostragem)"))
    return rows


# ---------------------------------------------------------------- E2

def bloco_e2_fp(results: Path) -> list[dict]:
    d = _csv(results, "e2_resumo.csv")
    nominal = 1 - (1 - ALFA_TESTE) ** N_TESTES
    rows = [_row("e2_fp", "nominal 1-(1-0,01)^3", nominal, None, None, "aproximação: 3 testes independentes",
                 "os 3 testes sobre o mesmo lote não são independentes; serve como ordem de grandeza")]
    for _, r in d[d["tipo"] == "falso_positivo"].iterrows():
        lo, hi = clopper_pearson(int(r["n_reprovados"]), int(r["n_lotes"]))
        rows.append(_row("e2_fp", f"os, {int(r['n_bits']):,} bits".replace(",", "."), float(r["taxa"]), lo, hi, "Clopper-Pearson 95%",
                         f"{int(r['n_reprovados'])} de {int(r['n_lotes'])} lotes"))
    return rows


# ---------------------------------------------------------------- E3

def bloco_e3(results: Path) -> list[dict]:
    """Razão de custo QPU/os sob 4 definições: o critério registrado usa só a primeira."""
    res = _csv(results, "e3_resumo.csv").set_index("metrica")["valor"]
    loc = _csv(results, "e3_local.csv")
    lot = _csv(results, "dia6_coleta3_qpu_vs_sim_resumo.csv").set_index("fonte")
    qubits = int(lot.loc["qpu_real", "n_qubits"])
    mbit_local = loc["n_bits"].to_numpy(float) / 1e6
    s_mbit = loc["t_s"].to_numpy(float) / mbit_local
    med, rapido, lento = float(np.median(s_mbit)), float(s_mbit.min()), float(s_mbit.max())
    medio_qpu = float(res["coleta_s_por_mbit_bruto"])
    marginal_qpu = float(res["ajuste_por_shot_s"]) / qubits * 1e6
    limiar = float(res["criterio_limiar"])
    rows = [
        _row("e3_razao", "critério registrado: custo médio da QPU / mediana local", medio_qpu / med, medio_qpu / lento, medio_qpu / rapido,
             "faixa = execução local mais lenta e mais rápida", f"limiar {limiar:g}"),
        _row("e3_razao", "custo marginal da QPU / mediana local", marginal_qpu / med, marginal_qpu / lento, marginal_qpu / rapido,
             "ajuste por shot do e3_resumo", f"limiar {limiar:g}; marginal = {marginal_qpu:.4f} s/Mbit contra médio {medio_qpu:.4f}"),
    ]
    g1 = loc.sort_values("repeticao")["t_s"].to_numpy(float)
    corte = np.argmax(np.diff(np.sort(g1))) + 1
    rapidos, lentos = np.sort(s_mbit)[:corte], np.sort(s_mbit)[corte:]
    rows.append(_row("e3_razao", "custo marginal / mediana do grupo lento", marginal_qpu / float(np.median(lentos)), None, None,
                     "maior salto entre tempos ordenados separa dois grupos", f"{len(rapidos)} execuções rápidas e {len(lentos)} lentas; causa não investigada"))
    return rows


# ---------------------------------------------------------------- E4

def bloco_e4(results: Path) -> list[dict]:
    d = _csv(results, "e4_resumo.csv")
    rows = []
    for cen in ("base_boa", "enviesada", "travada", "constante"):
        h = d[(d["cenario"] == cen) & (d["combinador"] == "hash")].iloc[0]
        x = d[(d["cenario"] == cen) & (d["combinador"] == "xor")].iloc[0]
        kh, kx, n = int(h["n_aprovadas"]), int(x["n_aprovadas"]), int(h["n_seq"])
        p = float(stats.fisher_exact([[kh, n - kh], [kx, n - kx]]).pvalue)
        rows.append(_row("e4_hash_xor", cen, (kh - kx) / n, None, None, "diferença hash menos xor na taxa de aprovação",
                         f"hash {kh}/{n}, xor {kx}/{n}; Fisher exato p = {p:.3f}"))
    return rows


# ---------------------------------------------------------------- E5

def bloco_e5(results: Path) -> list[dict]:
    d = _csv(results, "e5_resumo.csv")
    return [_row("e5_s", r["configuracao"], float(r["s_media"]), float(r["s_min"]), float(r["s_max"]), "mínimo e máximo das repetições",
                 f"n = {int(r['n_reps'])}; DP entre repetições {float(r['s_dp']):.4f}") for _, r in d.iterrows()]


BLOCOS = (bloco_h_lotes, bloco_frac1, bloco_deriva, bloco_e2_fp, bloco_e3, bloco_e4, bloco_e5)


def calcular(results: Path = RESULTS) -> pd.DataFrame:
    """Todos os blocos num só DataFrame."""
    rows: list[dict] = []
    for fn in BLOCOS:
        rows += fn(Path(results))
    return pd.DataFrame(rows, columns=COLUNAS)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--results", type=Path, default=RESULTS)
    args = ap.parse_args(argv)
    df = calcular(args.results)
    path = args.results / OUT_NAME
    df.to_csv(path, index=False, encoding="utf-8", lineterminator="\n", float_format="%.6g")
    print(f"{len(df)} linhas em {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
