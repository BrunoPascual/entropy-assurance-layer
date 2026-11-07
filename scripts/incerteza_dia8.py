"""Faixas de incerteza do Dia 8 (revisão crítica das conclusões E1 a E5).

Lê só CSVs de data/results e grava data/results/dia8_incerteza.csv (formato longo).
Nada é digitado à mão. Cada bloco responde a uma pergunta que a revisão levantou:

  h_lotes      A H estimada da QPU é mesmo menor que a da `os`? (permutação exata, 6 contra 6)
  frac1        O viés agregado da QPU tem sempre o mesmo sinal? (IC 95% binomial por lote)
  deriva_dp    O desvio-padrão do zdiff entre lotes passa de 1 por acaso? (bootstrap sobre os qubits)
  e2_fp        O falso positivo da `os` é o que os alfas dos testes prevêem?
  e3_razao     A razão de custo QPU/os resiste ao custo marginal e à máquina lenta?
  e3_ajuste    Quanto o arredondamento inteiro dos segundos da API move o custo marginal? (propagação exata de ±0,5 s)
  e4_hash_xor  A taxa de aprovação do hash difere da do XOR? (Fisher exato)
  e4_poder     Que poder tem o Fisher exato com 100 sequências por braço para uma diferença de 10 pontos percentuais?
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
ARRED_S = 0.5  # a API entrega quantum_seconds inteiros: o valor verdadeiro está a até 0,5 s do registrado
ALFA_E4 = 0.05
DIF_E4 = 0.10
PODER_E4 = ((0.97, "perto de 0,97"), (0.95, "perto de 0,95"), (0.90, "perto de 0,90"))  # taxa do braço de cima; o outro fica 10 pp abaixo
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
    rows += _ajuste_marginal(res, _csv(results, "e3_qpu.csv"), qubits, med, rapido, lento, limiar)
    return rows


def _ajuste_marginal(res: pd.Series, qpu: pd.DataFrame, qubits: int, med: float, rapido: float, lento: float, limiar: float) -> list[dict]:
    """Propaga ±0,5 s de arredondamento dos segundos inteiros da API até o custo marginal.

    O ajuste por mínimos quadrados é linear nos segundos: b = sum(w_i y_i), com w_i = (x_i - x̄)/Sxx. Cada y_i pode
    estar a até ARRED_S do registrado, então b varia no máximo ARRED_S * sum|w_i| (pior caso exato, não simulação).
    """
    x = qpu["shots"].to_numpy(float)
    y = qpu["quantum_seconds"].to_numpy(float)
    w = (x - x.mean()) / ((x - x.mean()) ** 2).sum()
    b = float((w * y).sum())
    if abs(b - float(res["ajuste_por_shot_s"])) > 1e-7:
        raise ValueError(f"ajuste recalculado {b} difere do registrado {res['ajuste_por_shot_s']}")
    db = ARRED_S * float(np.abs(w).sum())
    marg = [(b + d) / qubits * 1e6 for d in (0.0, -db, db)]
    n_tam = len(set(x))
    obs = f"{len(x)} jobs em {n_tam} tamanhos; ±{ARRED_S} s por job; pior caso exato do ajuste linear"
    return [
        _row("e3_ajuste", "ajuste marginal da QPU (s/Mbit)", marg[0], marg[1], marg[2], "propagação de ±0,5 s nos segundos inteiros", obs),
        _row("e3_ajuste", "razão marginal / mediana local (incerteza do ajuste)", marg[0] / med, marg[1] / med, marg[2] / med,
             "mesma propagação; mediana local fixa", f"limiar {limiar:g}; {obs}"),
        _row("e3_ajuste", "razão marginal / mais lenta (incerteza do ajuste)", marg[0] / lento, marg[1] / lento, marg[2] / lento,
             "mesma propagação; execução local mais lenta", f"limiar {limiar:g}"),
    ]


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
                         f"hash {kh}/{n}, xor {kx}/{n}; Fisher exato p = {p:.4f}"))
    return rows


def poder_fisher(p1: float, p2: float, n: int, alfa: float = ALFA_E4) -> float:
    """Poder exato do teste de Fisher bilateral (n por braço): P(p <= alfa) sob Binomial(n, p1) contra Binomial(n, p2)."""
    ks = np.arange(n + 1)
    rej = np.array([[stats.fisher_exact([[a, n - a], [b, n - b]]).pvalue <= alfa for b in ks] for a in ks])
    pa, pb = stats.binom.pmf(ks, n, p1), stats.binom.pmf(ks, n, p2)
    return float((pa[:, None] * pb[None, :] * rej).sum())


def bloco_e4_poder(results: Path) -> list[dict]:
    """Poder de enxergar uma diferença de 10 pp entre hash e XOR, com o n do experimento."""
    d = _csv(results, "e4_resumo.csv")
    n = int(d[d["cenario"] == "base_boa"]["n_seq"].iloc[0])
    return [_row("e4_poder", f"{rot}: {a:.2f} contra {a - DIF_E4:.2f}", poder_fisher(a, a - DIF_E4, n), None, None,
                 f"Fisher exato bilateral, alfa {ALFA_E4}, cálculo exato sobre Binomial(n, p)", f"n = {n} por braço; diferença de {DIF_E4 * 100:.0f} pontos percentuais")
            for a, rot in PODER_E4]


# ---------------------------------------------------------------- E5

def bloco_e5(results: Path) -> list[dict]:
    d = _csv(results, "e5_resumo.csv")
    return [_row("e5_s", r["configuracao"], float(r["s_media"]), float(r["s_min"]), float(r["s_max"]), "mínimo e máximo das repetições",
                 f"n = {int(r['n_reps'])}; DP entre repetições {float(r['s_dp']):.4f}") for _, r in d.iterrows()]


BLOCOS = (bloco_h_lotes, bloco_frac1, bloco_deriva, bloco_e2_fp, bloco_e3, bloco_e4, bloco_e4_poder, bloco_e5)


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
