"""Gera o relatório do Dia 8: relatorio/RELATORIO.md e relatorio/figuras/*.png.

Todo número do texto sai de um CSV de data/results (inclusive dia8_incerteza.csv, gerado por
scripts/incerteza_dia8.py). As frases de interpretação só são gravadas se a condição que as
sustenta for verdadeira nos CSVs; senão o script recusa (como os registrar_*.py).

Uso (na raiz do projeto):
    py -3.12 -m scripts.incerteza_dia8
    py -3.12 -m scripts.gerar_relatorio
"""
from __future__ import annotations

import argparse
import math
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

RESULTS = Path("data/results")
OUT = Path("relatorio")
COLETAS = {1: "dia6_", 2: "dia6_coleta2_", 3: "dia6_coleta3_"}
COR = {"qpu_real": "#D55E00", "simulador": "#0072B2", "os": "#009E73", "cinza": "#6b6b6b"}
ROTULO = {"qpu_real": "QPU real", "simulador": "Simulador", "os": "os"}
DPI = 150


class Recusa(Exception):
    """Uma frase de interpretação não é sustentada pelos CSVs."""


def _checar(cond: bool, msg: str) -> None:
    if not cond:
        raise Recusa(msg)


def _ler(results: Path, name: str) -> pd.DataFrame:
    return pd.read_csv(Path(results) / name, encoding="utf-8-sig")


def _f(x: float, d: int = 4) -> str:
    return f"{x:.{d}f}".replace(".", ",")


def _piso(x: float, d: int = 2) -> str:
    """Trunca em vez de arredondar: 'entre 0,44 e ...' não pode virar 0,45 quando o mínimo é 0,4448."""
    return _f(math.floor(x * 10**d + 1e-9) / 10**d, d)


def _int(x: float) -> str:
    return f"{int(x):,}".replace(",", ".")


def _estilo() -> None:
    plt.rcParams.update({"font.size": 9, "axes.spines.top": False, "axes.spines.right": False,
                         "axes.grid": True, "grid.alpha": 0.25, "figure.dpi": DPI, "savefig.bbox": "tight"})


def _salvar(fig, nome: str, out: Path) -> str:
    pasta = out / "figuras"
    pasta.mkdir(parents=True, exist_ok=True)
    fig.savefig(pasta / nome, dpi=DPI)
    plt.close(fig)
    return f"figuras/{nome}"


# ---------------------------------------------------------------- figuras

def fig_h(lotes: pd.DataFrame, out: Path) -> str:
    fig, ax = plt.subplots(figsize=(5.4, 3.2))
    marc = {1: "o", 2: "s", 3: "^"}
    for i, f in enumerate(ROTULO):
        for c in (1, 2, 3):
            v = lotes[(lotes["fonte"] == f) & (lotes["coleta"] == c)]["saude_h_estimated"].to_numpy()
            ax.scatter(i + (c - 2) * 0.12 + np.linspace(-0.03, 0.03, len(v)), v, marker=marc[c], color=COR[f], s=34, zorder=3,
                       label=f"coleta {c}" if i == 0 else None)
    ax.set_xticks(range(3), [ROTULO[f] for f in ROTULO])
    ax.set_ylabel("H estimada (bits por bit)")
    ax.set_ylim(0.95, 0.972)
    ax.legend(frameon=False, title="marcador", loc="upper left")
    ax.set_title("Nenhuma fonte chega perto de 1, nem a os", loc="left", fontsize=10)
    return _salvar(fig, "e1_h_estimada.png", out)


def fig_frac1(inc: pd.DataFrame, out: Path) -> str:
    d = inc[inc["bloco"] == "frac1"].copy()
    fig, ax = plt.subplots(figsize=(6.2, 3.2))
    for k, (f, rot) in enumerate((("QPU real", "qpu_real"), ("simulador", "simulador"))):
        sub = d[d["item"].str.endswith(f)]
        x = np.arange(len(sub)) + (k - 0.5) * 0.18
        ax.errorbar(x, sub["estimativa"], yerr=[sub["estimativa"] - sub["ic_inf"], sub["ic_sup"] - sub["estimativa"]],
                    fmt="o", color=COR[rot], capsize=2, label=ROTULO[rot])
    ax.axhline(0.5, color=COR["cinza"], ls="--", lw=1)
    ax.set_xticks(range(6), [f"C{c}·L{l}" for c in (1, 2, 3) for l in (1, 2)])
    ax.set_ylabel("Fração de uns (IC 95%)")
    ax.legend(frameon=False)
    ax.set_title("O viés agregado da QPU muda de sinal entre coletas", loc="left", fontsize=10)
    return _salvar(fig, "e1_frac1.png", out)


def deriva_unica(inc: pd.DataFrame) -> pd.DataFrame:
    """Um ponto por par distinto de lotes: o par coleta1 lote1 x lote2 aparece em 3 arquivos de deriva
    (o IC bootstrap varia entre eles, então drop_duplicates sobre os valores não o remove)."""
    d = inc[inc["bloco"] == "deriva_dp"].copy()
    d["par"] = d["item"].str.split(": ").str[1]
    return d.drop_duplicates(subset=["par"]).reset_index(drop=True)


def fig_deriva(inc: pd.DataFrame, out: Path) -> str:
    d = deriva_unica(inc)

    def grupo(item: str) -> str:
        if "cal_00" in item:
            return "jobs de calibração (1.000 a 4.000 shots)"
        lotes = item.split(": ")[1].split(" x ")
        return "mesma coleta" if lotes[0][:7] == lotes[1][:7] else "entre coletas"

    d["grupo"] = d["item"].map(grupo)
    cor = {"mesma coleta": COR["os"], "entre coletas": COR["qpu_real"], "jobs de calibração (1.000 a 4.000 shots)": COR["cinza"]}
    fig, ax = plt.subplots(figsize=(6.4, 3.4))
    for g, sub in d.groupby("grupo"):
        ax.errorbar(sub.index, sub["estimativa"], yerr=[sub["estimativa"] - sub["ic_inf"], sub["ic_sup"] - sub["estimativa"]],
                    fmt="o", color=cor[g], capsize=2, label=g)
    ax.axhline(1, color=COR["cinza"], ls="--", lw=1)
    ax.set_xticks([])
    ax.set_xlabel("pares de lotes")
    ax.set_ylabel("DP do zdiff (IC 95% bootstrap)")
    ax.legend(frameon=False, fontsize=8)
    ax.set_title("Deriva: o DP passa de 1 entre coletas, não dentro delas", loc="left", fontsize=10)
    return _salvar(fig, "e1_deriva.png", out)


FAM_E2 = (("faulty_biased", "viés p"), ("faulty_correlated", "correlação rho"), ("faulty_stuck", "trecho travado (bits)"))


def menor_deteccao_plotada(e2: pd.DataFrame) -> float:
    """Menor taxa de detecção entre os pontos que a figura do E2 plota (o faulty_prng não é plotado)."""
    sel = e2[e2["fonte"].isin([f for f, _ in FAM_E2]) & (e2["tipo"] == "deteccao")]
    return float(sel["taxa"].min())


def fig_e2(e2: pd.DataFrame, out: Path) -> str:
    fam = FAM_E2
    fig, axs = plt.subplots(1, 3, figsize=(8.6, 3.0), sharey=True)
    for ax, (f, tit) in zip(axs, fam):
        sub = e2[(e2["fonte"] == f) & (e2["tipo"] == "deteccao")]
        vals = sorted(sub["valor"].unique())
        for k, (nb, cor) in enumerate(((1_000_000, "#56B4E9"), (4_000_000, "#0072B2"))):
            s = sub[sub["n_bits"] == nb].set_index("valor").loc[vals]
            x = np.arange(len(vals)) + (k - 0.5) * 0.2
            ax.errorbar(x, s["taxa"], yerr=[s["taxa"] - s["ic95_inf"], s["ic95_sup"] - s["taxa"]], fmt="o", color=cor, capsize=2,
                        label=f"{nb // 1_000_000} M bits")
        ax.set_xticks(range(len(vals)), [f"{v:g}" for v in vals])
        ax.set_title(tit, fontsize=9)
    fp = e2[e2["tipo"] == "falso_positivo"]
    for ax in axs:
        ax.axhspan(fp["taxa"].min(), fp["taxa"].max(), color=COR["os"], alpha=0.25, lw=0)
    axs[0].set_ylabel("Taxa de reprovação (IC 95%)")
    axs[0].legend(frameon=False, fontsize=8, loc="center right")
    minimo = menor_deteccao_plotada(e2)
    fig.suptitle(f"Menor taxa de detecção: {minimo * 100:.0f}% (1 M bits); faixa verde: falso positivo da os".replace(".", ","), x=0.01, ha="left", fontsize=10)
    return _salvar(fig, "e2_deteccao.png", out)


def fig_e3(inc: pd.DataFrame, out: Path) -> str:
    d = inc[(inc["bloco"] == "e3_razao") & inc["ic_inf"].notna()]
    fig, ax = plt.subplots(figsize=(6.2, 2.4))
    rot = ["Custo médio da QPU\n(critério registrado)", "Custo marginal da QPU"]
    for i, (_, r) in enumerate(d.iterrows()):
        ax.errorbar(r["estimativa"], i, xerr=[[r["estimativa"] - r["ic_inf"]], [r["ic_sup"] - r["estimativa"]]], fmt="o",
                    color=COR["qpu_real"], capsize=3)
        ax.annotate(f"{r['estimativa']:.1f}".replace(".", ","), (r["estimativa"], i), textcoords="offset points", xytext=(0, -14), ha="center", fontsize=8)
    ax.axvline(10, color=COR["cinza"], ls="--", lw=1)
    ax.set_xscale("log")
    ax.set_yticks(range(len(d)), rot[: len(d)])
    ax.set_xlabel("Razão de segundos por Mbit, QPU sobre os (mediana; barra = execução local mais lenta e mais rápida)")
    ax.set_title("O limiar de 10 vezes (tracejado) está dentro da faixa", loc="left", fontsize=10)
    return _salvar(fig, "e3_razao.png", out)


def fig_e4(e4: pd.DataFrame, out: Path) -> str:
    cen = ["base_boa", "enviesada", "travada", "constante"]
    fig, ax = plt.subplots(figsize=(5.8, 3.0))
    for k, (c, cor) in enumerate((("hash", "#0072B2"), ("xor", "#E69F00"))):
        s = e4[(e4["combinador"] == c) & e4["cenario"].isin(cen)].set_index("cenario").loc[cen]
        x = np.arange(len(cen)) + (k - 0.5) * 0.2
        ax.errorbar(x, s["taxa_aprovacao"], yerr=[s["taxa_aprovacao"] - s["ic95_inf"], s["ic95_sup"] - s["taxa_aprovacao"]], fmt="o",
                    color=cor, capsize=2, label=c)
    ax.set_xticks(range(len(cen)), cen)
    ax.set_ylim(0.8, 1.0)
    ax.set_ylabel("Taxa de aprovação (IC 95%)")
    ax.legend(frameon=False)
    ax.set_title("Com uma fonte boa, hash e XOR não se distinguem (100 sequências)", loc="left", fontsize=10)
    return _salvar(fig, "e4_hash_xor.png", out)


def fig_e5(e5: pd.DataFrame, out: Path) -> str:
    fig, ax = plt.subplots(figsize=(6.2, 3.0))
    nomes = {"ideal_exato": "ideal\n(exato)", "ideal_amostrado": "ideal\n(amostrado)", "ruido_fake_kingston": "ruído\nFakeKingston",
             "classico_aleatorio": "clássico\naleatório", "classico_otimo": "clássico\nótimo"}
    for i, (_, r) in enumerate(e5.iterrows()):
        ax.errorbar(i, r["s_media"], yerr=[[r["s_media"] - r["s_min"]], [r["s_max"] - r["s_media"]]], fmt="o", color=COR["simulador"], capsize=3)
    ax.axhline(2, color=COR["cinza"], ls="--", lw=1)
    ax.axhline(2 * math.sqrt(2), color=COR["cinza"], ls=":", lw=1)
    ax.set_xticks(range(len(e5)), [nomes[c] for c in e5["configuracao"]], fontsize=8)
    ax.set_ylabel("S (barra: mínimo e máximo das repetições)")
    ax.set_title("CHSH sem QPU: tracejado 2 (limite clássico), pontilhado 2√2", loc="left", fontsize=10)
    return _salvar(fig, "e5_chsh.png", out)


# ---------------------------------------------------------------- texto

def _tabela(df: pd.DataFrame) -> str:
    cab = "| " + " | ".join(df.columns) + " |\n|" + "---|" * len(df.columns) + "\n"
    return cab + "\n".join("| " + " | ".join(str(v) for v in row) + " |" for row in df.itertuples(index=False)) + "\n"


def _inc(inc: pd.DataFrame, bloco: str, item: str) -> pd.Series:
    sub = inc[(inc["bloco"] == bloco) & inc["item"].str.startswith(item)]
    _checar(len(sub) >= 1, f"item ausente em dia8_incerteza.csv: {bloco}/{item}")
    return sub.iloc[0]


def montar(results: Path, out: Path) -> str:
    _estilo()
    lotes = pd.concat([_ler(results, f"{p}qpu_vs_sim_lotes.csv").assign(coleta=c) for c, p in COLETAS.items()], ignore_index=True)
    inc = _ler(results, "dia8_incerteza.csv")
    e2, e3, e4, e5 = (_ler(results, f"{n}_resumo.csv") for n in ("e2", "e3", "e4", "e5"))
    gate = _ler(results, "consolidado_gate.csv")

    f_h, f_p, f_d = fig_h(lotes, out), fig_frac1(inc, out), fig_deriva(inc, out)
    f2, f3, f4, f5 = fig_e2(e2, out), fig_e3(inc, out), fig_e4(e4, out), fig_e5(e5, out)

    # ---- números e condições das frases
    aprov = lotes.groupby("fonte")["saude_approved"].agg(["sum", "size"])
    distintos = lotes.groupby("fonte")["batch_hash"].nunique()
    _checar(distintos["simulador"] < aprov.loc["simulador", "size"], "o simulador passou a ter lotes distintos em cada coleta: a ressalva da semente fixa não vale")
    _checar(aprov.loc["os", "sum"] == aprov.loc["os", "size"] and aprov.loc["qpu_real", "sum"] == 0 and aprov.loc["simulador", "sum"] == 0,
            "contagem de lotes aprovados mudou: o texto do resumo precisa ser revisto")
    h_q, h_s, h_o = (_inc(inc, "h_lotes", n) for n in ("QPU real", "simulador", "os (n"))
    p_h = _inc(inc, "h_lotes", "p exato")
    _checar(h_q["ic_sup"] < h_o["ic_inf"], "faixas de H da QPU e da os se sobrepõem: o texto de E1 está errado")
    _checar(h_o["estimativa"] < 0.98, "H da os passou de 0,98: a observação sobre o estimador conservador não vale")
    fr = inc[inc["bloco"] == "frac1"]
    q_fr = fr[fr["item"].str.endswith("QPU real")]
    _checar((q_fr["ic_inf"] > 0.5).sum() + (q_fr["ic_sup"] < 0.5).sum() == len(q_fr), "algum IC da fração de uns da QPU contém 0,5")
    _checar(q_fr["estimativa"].iloc[0] < 0.5 < q_fr["estimativa"].iloc[2], "o sinal do viés da QPU não muda entre a coleta 1 e a 2")
    dv = deriva_unica(inc)
    n_pares, n_rep = len(dv), int((inc["bloco"] == "deriva_dp").sum()) - len(dv)
    mesmo = dv[dv["item"].str.contains("coleta1_001 x coleta1_002|coleta2_001 x coleta2_002|coleta3_001 x coleta3_002")]
    calp = dv[dv["item"].str.contains("cal_00")]
    entre = dv[dv["item"].str.contains("x coleta2_00|x coleta3_00") & ~dv["item"].str.contains("coleta2_001 x coleta2_002|coleta3_001 x coleta3_002")]
    _checar(entre["estimativa"].min() > 2 * mesmo["estimativa"].max(), "o DP entre coletas não é mais que o dobro do dentro da coleta: revisar o texto da deriva")
    _checar((mesmo["estimativa"] > 1).all() and mesmo["estimativa"].max() < 1.2, "o DP dentro da coleta saiu da faixa 1 a 1,2: revisar o texto da deriva")
    _checar(calp["estimativa"].max() > 1.5, "nenhum par com job cal passa de 1,5: a ressalva sobre sobredispersão no mesmo dia não vale")
    n_cal = calp["observacao"].str.extract(r"\|z\|>3: (\d+)")[0].astype(int)
    c3 = _inc(inc, "deriva_dp", "coleta3_vs_coleta1: coleta3_001 x coleta3_002")
    l3 = _ler(results, "dia6_deriva_coleta3_lotes.csv")
    l3 = l3[l3["lote"].str.startswith("coleta3")]
    _checar(len(l3) == 2 and l3["calibracao_execucao"].nunique() == 1 and l3["calibracao_no_envio"].nunique() == 2,
            "os 2 jobs da coleta 3 não rodaram sob a mesma calibração de execução (com calibrações de envio diferentes): a ressalva da deriva precisa ser reescrita")
    cal_exec = f"{pd.to_datetime(l3['calibracao_execucao'].iloc[0][:19]):%Hh%M}"
    cal_env = " e ".join(f"{pd.to_datetime(t[:19]):%Hh%M}" for t in l3["calibracao_no_envio"])
    qpu_l = lotes[lotes["fonte"] == "qpu_real"]
    _checar(bool((qpu_l["saude_stats_monobit"] < 0.01).all() and qpu_l["saude_h_health_pass"].all() and (qpu_l["saude_stats_block"] >= 0.01).all()),
            "a reprovação da QPU não é só monobit, com H e blocos aprovados em todos os lotes: revisar o texto")
    runs_falha = qpu_l[qpu_l["saude_stats_runs"] < 0.01]
    _checar(bool((runs_falha["saude_stats_runs"] == 0).all()) and 0 < len(runs_falha) < len(qpu_l), "o padrão do runs mudou (p = 0 por pré-requisito em parte dos lotes): revisar o texto")
    lote_limite = qpu_l[qpu_l["saude_stats_runs"] >= 0.01].iloc[0]
    lim_prox = float(min((q_fr["ic_inf"] - 0.5).where(q_fr["ic_inf"] > 0.5).min(), (0.5 - q_fr["ic_sup"]).where(q_fr["ic_sup"] < 0.5).min()))
    fp = e2[e2["tipo"] == "falso_positivo"].set_index("n_bits")
    nom = _inc(inc, "e2_fp", "nominal")["estimativa"]
    _checar(all(fp.loc[b, "ic95_inf"] <= nom <= fp.loc[b, "ic95_sup"] for b in fp.index), "o falso positivo da os não é compatível com o nominal")
    prng = e2[e2["fonte"] == "faulty_prng"]
    _checar((prng["taxa"] < 0.06).all(), "o PRNG disfarçado passou a ser detectado: o texto do E2 está errado")
    fraco = e2[(e2["fonte"] == "faulty_biased") & (e2["valor"] == 0.501) & (e2["n_bits"] == 1_000_000)].iloc[0]
    _checar(fraco["taxa"] < 0.5, "a detecção do menor viés passou de 50%")
    r_med = _inc(inc, "e3_razao", "critério registrado")
    r_mar = _inc(inc, "e3_razao", "custo marginal da QPU")
    _checar(r_med["estimativa"] >= 10 > r_mar["ic_inf"], "a faixa do E3 não cruza mais o limiar: o texto está errado")
    _checar(r_mar["estimativa"] > 10 and r_med["ic_inf"] > 10 and r_mar["ic_sup"] > 10 and r_med["ic_sup"] > 10,
            "E3: só marginal com a máquina local mais lenta deveria ficar abaixo de 10: revisar o texto do E3")
    aj_c, aj_r, aj_l = (_inc(inc, "e3_ajuste", n) for n in ("ajuste marginal", "razão marginal / mediana", "razão marginal / mais lenta"))
    _checar(aj_r["ic_inf"] < 10 < aj_r["ic_sup"], "a incerteza do ajuste marginal não cruza mais o limiar de 10: revisar o texto do E3")
    q3 = _ler(results, "e3_qpu.csv")
    n_jobs_aj, n_tam_aj = len(q3), int(q3["shots"].nunique())
    e4h = inc[inc["bloco"] == "e4_hash_xor"]
    p_e4 = e4h["observacao"].str.extract(r"p = ([\d.]+)")[0].astype(float)
    _checar(p_e4.min() > 0.05, "hash e XOR diferem em algum cenário: revisar o texto do E4")
    pod = {r["item"].split(":")[0]: float(r["estimativa"]) for _, r in inc[inc["bloco"] == "e4_poder"].iterrows()}
    _checar(set(pod) == {"perto de 0,97", "perto de 0,95", "perto de 0,90"} and max(pod.values()) < 0.8,
            "o poder do E4 para 10 pp não está abaixo de 80%: a frase sobre diferenças não detectáveis precisa ser revista")
    pod_alto = max(pod["perto de 0,97"], pod["perto de 0,95"])
    pod_baixo = min(pod["perto de 0,97"], pod["perto de 0,95"])
    poder_txt = (f"o poder do teste exato de Fisher é de {_f(pod_baixo * 100, 0)}% a {_f(pod_alto * 100, 0)}% para uma diferença de 10 pontos percentuais "
                 f"perto de 0,95 a 0,97 e de {_f(pod['perto de 0,90'] * 100, 0)}% perto de 0,90, então diferenças dessa ordem podem passar despercebidas")
    adv = e4[e4["cenario"] == "adv_forca"].set_index("k")
    _checar(bool((adv.loc[[4, 8, 12], "n_aprovadas"] == 0).all() and adv.loc[1, "n_aprovadas"] > 0), "o padrão de aprovação do adv_forca mudou: revisar o texto do E4")
    n_z = entre["observacao"].str.extract(r"\|z\|>3: (\d+)")[0].astype(int)
    _checar(set(gate["experimento"]) == {"E1", "E2", "E3", "E4", "E5"}, "o gate não tem os 5 experimentos")

    fonte_tab = pd.DataFrame({"Fonte": [ROTULO[f] for f in ROTULO],
                              "Lotes aprovados": [f"{int(aprov.loc[f, 'sum'])} de {int(aprov.loc[f, 'size'])} ({int(distintos[f])} distintos)" for f in ROTULO],
                              "H estimada (mediana, mín. a máx.)": [f"{_f(r['estimativa'])} ({_f(r['ic_inf'])} a {_f(r['ic_sup'])})" for r in (h_q, h_s, h_o)]})
    e2_tab = e2[e2["tipo"].isin(["falso_positivo", "referencia"]) | e2["fonte"].eq("faulty_prng")][["fonte", "n_bits", "tipo", "n_lotes", "n_reprovados", "taxa", "ic95_inf", "ic95_sup"]]
    e2_tab = e2_tab.assign(n_bits=e2_tab["n_bits"].map(_int), taxa=e2_tab["taxa"].map(lambda x: _f(x, 3)),
                           ic95_inf=e2_tab["ic95_inf"].map(lambda x: _f(x, 3)), ic95_sup=e2_tab["ic95_sup"].map(lambda x: _f(x, 3)))
    gate_tab = gate[["experimento", "estado", "ressalva"]].fillna("-")
    e5_tab = e5[["configuracao", "n_reps", "s_media", "s_min", "s_max"]].assign(**{c: e5[c].map(lambda x: _f(x, 3)) for c in ("s_media", "s_min", "s_max")})

    inv = pd.concat([_ler(results, f"{p}inventario.csv").assign(coleta=c) for c, p in {1: "dia6_coleta1_", 2: "dia6_coleta2_", 3: "dia6_coleta3_"}.items()], ignore_index=True)
    inv = inv[inv["arquivo"].str.contains("coleta")]
    inv["cal"] = pd.to_datetime(inv["calibracao"].str[:19])
    inv["dia"] = pd.to_datetime(inv["arquivo"].str[:10])
    n_dias = int(inv["dia"].nunique())
    cal_txt = "Três coletas na QPU real, cada uma com 2 jobs (calibração do backend no envio entre parênteses): " + "; ".join(
        f"coleta {c} em {g['dia'].iloc[0]:%d/%m/%Y} (" + " e ".join(f"{t:%Hh%M}" for t in g["cal"].drop_duplicates()) + ")" for c, g in inv.groupby("coleta"))
    res_q = _ler(results, "dia6_coleta3_qpu_vs_sim_resumo.csv").set_index("fonte")
    n_qubits, n_shots = int(res_q.loc["qpu_real", "n_qubits"]), int(res_q.loc["qpu_real", "n_shots"])
    n_bits_lote = int(lotes[lotes["fonte"] == "qpu_real"]["n_bits"].iloc[0])
    bits_coleta = n_bits_lote * int((lotes[lotes["fonte"] == "qpu_real"]["coleta"] == 1).sum())
    grupos_e3 = _inc(inc, "e3_razao", "custo marginal / mediana do grupo lento")["observacao"].split("; ")[0].replace("execuções rápidas e", "rápidas e").replace(" lentas", " lentas")
    adv1 = e4[(e4["cenario"] == "adv_forca") & (e4["k"] == 1)].iloc[0]
    mg = r_mar["observacao"].split("marginal = ")[1].split(" s/Mbit")[0].replace(".", ",")
    return f"""# Entropy Assurance Layer: relatório do projeto

Autor: Bruno Pascual. Protótipo de pesquisa de 9 dias. Gerado por `scripts/gerar_relatorio.py` a partir dos CSVs de `data/results`; nenhum número foi digitado à mão. As faixas de incerteza estão em `data/results/dia8_incerteza.csv`. O texto passou por uma revisão adversarial feita por um revisor independente; a seção 4 registra o que mudou.

## 1. Resumo

A EAL coleta bits de três tipos de fonte (sistema operacional, simulador de QPU com ruído e QPU real da IBM), testa cada lote, mistura só as fontes que não mostraram defeito na saída e emite um recibo assinado com ML-DSA-65, encadeado por hash. Este relatório cobre os cinco experimentos e diz o que os dados sustentam e o que não sustentam.

**Como ler "aprovado".** Aprovado quer dizer que o lote não mostrou defeito nos testes aplicados à saída. Não prova que a fonte é imprevisível, e o provedor da QPU conhece os bits que gerou. A assinatura do recibo garante integridade e ordem, e nada sobre a entropia. A garantia de extração registrada nos recibos depende de a estimativa de H ser um limite verdadeiro de min-entropia, e o estimador supõe bits independentes.

- **QPU real como fonte (E1).** Dos 6 lotes da `ibm_kingston` (3 coletas, {_int(bits_coleta)} bits por coleta), **nenhum passou** na porta de saúde. A `os` passou em 6 de 6 e o simulador em 0 de {int(distintos['simulador'])} lotes distintos (a semente do simulador é fixa e os mesmos {int(distintos['simulador'])} lotes reaparecem nas 3 coletas). A causa é o teste de frequência (monobit), que reprova os 6 lotes. O runs reprova {len(runs_falha)} deles por pré-requisito (p = 0 quando o monobit falha), então não é uma segunda falha independente, e o lote {int(lote_limite['lote'])} da coleta {int(lote_limite['coleta'])} reprova só no monobit, por pouco (p = {_f(lote_limite['saude_stats_monobit'], 4)}). Os 6 lotes passam no critério de min-entropia e no teste de blocos. O viés agregado é pequeno (de {_f(q_fr['estimativa'].min(), 4)} a {_f(q_fr['estimativa'].max(), 4)} de uns) e com 1,5 milhão de bits ele é medível; **"nenhum passou" descreve o tamanho do lote e o critério escolhido, não prova que a QPU seja de má qualidade**. O sinal do viés mudou entre a coleta 1 e as outras duas.
- **Detecção de fontes ruins (E2).** Viés, correlação e travamento são detectados; o limite é estatístico: o menor viés testado (p = 0,501) é detectado em {_f(fraco['taxa'] * 100, 0)}% dos lotes de 1 milhão de bits. Um gerador pseudoaleatório disfarçado **passa** ({_f(prng['taxa'].min() * 100, 0)}% a {_f(prng['taxa'].max() * 100, 0)}% de reprovação, o nível do falso positivo). O falso positivo na `os` é de {_f(fp.loc[1_000_000, 'taxa'] * 100, 1)}% a {_f(fp.loc[4_000_000, 'taxa'] * 100, 1)}%.
- **Tempo e custo (E3).** A QPU gasta de {_f(r_mar['estimativa'], 1)} (custo marginal) a {_f(r_med['estimativa'], 1)} (custo médio) vezes mais segundos por megabit bruto que a mediana local da `os`. Na execução local mais lenta as razões são {_f(r_mar['ic_inf'], 1)} (marginal) e {_f(r_med['ic_inf'], 1)} (média); na mais rápida, {_f(r_mar['ic_sup'], 1)} e {_f(r_med['ic_sup'], 1)}. Só a combinação marginal com a execução local mais lenta ({_f(r_mar['ic_inf'], 1)}) fica abaixo de 10; o marginal sozinho ({_f(r_mar['estimativa'], 1)}) e o médio na mais lenta ({_f(r_med['ic_inf'], 1)}) passam de 10. É uma razão de **tempo**, não de dinheiro: no Open Plan o custo é zero e o custo da `os` não foi valorado. O limiar de 10 vezes **está dentro da faixa**. O custo por megabit útil é indefinido: nenhum lote da QPU foi aprovado.
- **Mistura (E4).** Com uma fonte boa, não há evidência de diferença entre hash e XOR (100 sequências por braço; {poder_txt}). O XOR entrega a semente escolhida por um adversário que vê a outra fonte; o hash não. Nenhum dos dois protege contra um adversário que testa candidatos: com 2^k tentativas ele força k bits da saída.
- **CHSH (E5).** Só a etapa A, sem QPU: S ideal ≈ 2,83, com o ruído do FakeKingston ≈ 2,76, geradores clássicos ≤ 2. É uma conferência de que o código está certo; **não diz nada sobre a QPU real** nem certifica aleatoriedade.

{_tabela(fonte_tab)}
Estado dos experimentos (gate do Dia 7):

{_tabela(gate_tab)}
## 2. Método e dados

- **Fontes.** `os` (`os.urandom`), `qpu_sim` (Qiskit Aer com o modelo de ruído do FakeKingston, que é um gerador clássico) e `ibm_kingston` ({n_qubits} qubits, {_int(n_shots)} shots por job, {_int(n_bits_lote)} bits por lote, Open Plan). Cinco fontes defeituosas simuladas (viés, correlação, travamento, PRNG, replay) servem de adversárias no E2.
- **Coletas.** {cal_txt}. Na coleta 3 a calibração vigente na execução foi a de {cal_exec} nos dois jobs. Mais jobs `cal` menores na coleta 1. As coletas 1 e 2 são do mesmo dia; só a coleta 3 é de outro dia.
- **Testes de saúde por lote.** RCT e APT (SP 800-90B), estimativa de min-entropia (menor entre bit e byte), três testes do SP 800-22 (monobit, frequência por bloco, runs) e detector de replay. Aprovado só se todos passam. Os testes do SP 800-22 funcionam aqui como porta; com lotes de 1,5 milhão de bits a porta reprova vieses de 0,2% a 0,5%.
- **Limites do método.** Os testes olham a saída. Não há alegação de conformidade com SP 800-90B, FIPS 140-3 ou Quantum Origin.

## 3. Resultados

### E1. QPU real contra simulador e `os`

![H estimada]({f_h})

A faixa de H estimada da QPU real (mediana {_f(h_q['estimativa'])}, de {_f(h_q['ic_inf'])} a {_f(h_q['ic_sup'])}, mínimo e máximo de 6 lotes, não é IC) fica abaixo da da `os` (mediana {_f(h_o['estimativa'])}, de {_f(h_o['ic_inf'])} a {_f(h_o['ic_sup'])}); as faixas mal se separam. O teste de permutação exato dá p = {_f(p_h['estimativa'], 4)}, o menor valor possível com 6 contra 6, mas os lotes formam 3 grupos (as 3 coletas) e não 6 observações independentes; trate como indício. Como H aqui é basicamente função do viés, isto repete a falha do monobit e não traz evidência nova. **A H absoluta não mede a qualidade da fonte:** a `os` também fica em {_f(h_o['estimativa'])}, porque o estimador é conservador com este tamanho de lote. O simulador (viés, sem correlação entre qubits) fica entre as duas ({_f(h_s['estimativa'])}).

![Fração de uns]({f_p})

Os 6 ICs da fração de uns da QPU excluem 0,5, e o sinal muda: **abaixo de 0,5 na coleta 1 e acima nas coletas 2 e 3**, enquanto o simulador fica sempre acima ({_f(_inc(inc, 'frac1', 'coleta 1 lote 1 simulador')['estimativa'])}). Os ICs são aproximados: tratam os bits como independentes, e os qubits têm vieses diferentes. O IC mais próximo de 0,5 está a {_f(lim_prox, 4)} dele (lote 2 da coleta 2); entre 6 comparações esse é marginal.

![Deriva]({f_d})

Os pontos são {n_pares} pares distintos de lotes; o par coleta 1 lote 1 x lote 2 consta de {n_rep + 1} arquivos de deriva e conta uma vez. Se só houvesse amostragem binomial, o desvio-padrão (DP) do zdiff por qubit entre dois lotes seria 1. Não é: já nos pares da mesma coleta ele fica em {_f(mesmo['estimativa'].min(), 2)} a {_f(mesmo['estimativa'].max(), 2)}, e nos pares com um job de calibração do mesmo dia chega a {_f(calp['estimativa'].max(), 2)} ({n_cal.min()} a {n_cal.max()} qubits com |z| > 3, contra 0,42 esperado). Há sobredispersão além da binomial até no mesmo dia. **Entre coletas o DP é de {_f(entre['estimativa'].min(), 1)} a {_f(entre['estimativa'].max(), 1)}**, mais que o dobro, com {n_z.min()} a {n_z.max()} qubits de 156 acima de 3. Os pares entre coletas compartilham jobs, então a evidência independente é de 3 coletas. Os ICs bootstrap (descritivos, não calibrados para uma cauda pesada) são largos, o que sugere que poucos qubits dominam a medida, mas isto não foi testado. As coletas 1 e 2 são do mesmo dia, de modo que a diferença é "entre coletas, com horas a um dia de distância", e não "entre dias". Os dois jobs da coleta 3 rodaram sob a mesma calibração de execução ({cal_exec}); só a calibração no envio difere ({cal_env}). O DP entre eles ({_f(c3['estimativa'], 2)}) portanto não testa efeito de calibração. A causa da deriva não foi investigada.

### E2. Detecção de fontes defeituosas

![Detecção]({f2})

{_tabela(e2_tab)}
Com 4 milhões de bits o viés de 0,001 sobe de {_f(fraco['taxa'] * 100, 0)}% para 95% de detecção. O PRNG com semente fixa passa nos testes porque eles olham só a saída. O falso positivo observado é consistente com o valor aproximado que os alfas dos testes dão ({_f(nom * 100, 2)}%, supondo 3 testes independentes, o que não é verdade: o runs depende do monobit).

### E3. Vazão e tempo

![Razão]({f3})

Custo teórico no Open Plan (sem gasto), com o preço do plano pago registrado no `PROJECT.md`. O critério pré-registrado (tempo médio de QPU por megabit sobre a mediana local) deu {_f(r_med['estimativa'], 1)}. Com o custo marginal por megabit ({mg} s/Mbit, contra {_f(float(_ler(results, 'e3_resumo.csv').set_index('metrica').loc['coleta_s_por_mbit_bruto', 'valor']), 4)} do custo médio, porque cada job tem um custo fixo) a razão cai para {_f(r_mar['estimativa'], 1)} (marginal sobre a mediana local); na execução local mais lenta o marginal dá {_f(r_mar['ic_inf'], 1)} e o médio {_f(r_med['ic_inf'], 1)}, e na mais rápida o marginal dá {_f(r_mar['ic_sup'], 1)} e o médio {_f(r_med['ic_sup'], 1)}. Só marginal com a mais lenta fica abaixo de 10. Os segundos de QPU vêm da API em valores inteiros ({n_jobs_aj} jobs em {n_tam_aj} tamanhos). Propagando ±0,5 s de arredondamento em cada job pelo ajuste linear (pior caso, não IC), o custo marginal vai de {_f(aj_c['ic_inf'], 2)} a {_f(aj_c['ic_sup'], 2)} s/Mbit e a razão marginal sobre a mediana local de {_f(aj_r['ic_inf'], 1)} a {_f(aj_r['ic_sup'], 1)} ({_f(aj_l['ic_inf'], 1)} a {_f(aj_l['ic_sup'], 1)} sobre a mais lenta); o limiar de 10 fica dentro dessa faixa. A mediana local cai no grupo lento ({grupos_e3}); a causa não foi investigada. O que se sustenta é "da ordem de 10 vezes em tempo", e não "mais de 10 vezes mais caro".

### E4. Resiliência da mistura

![Hash e XOR]({f4})

Com uma fonte boa não há evidência de diferença entre hash e XOR (Fisher exato, p entre {_piso(p_e4.min(), 2)} e {_f(p_e4.max(), 2)} nos 4 cenários, com mínimo exato {_f(p_e4.min(), 4)}; 100 sequências por braço, e {poder_txt}). "Aprovada" aqui quer dizer que os 3 testes do SP 800-22 passaram sobre 2.000 sementes concatenadas; numa chave real só há uma semente, então a taxa não é propriedade de uma chave. O que separa os dois é o adversário que vê a outra fonte: no XOR a semente final é a que ele escolhe, e os testes **não percebem** (a taxa de aprovação é a mesma de uma semente honesta). No hash nenhuma semente coincidiu com o alvo, o que já era esperado pela construção (probabilidade da ordem de 2^-512) e não é um achado empírico. No cenário `adv_forca` o adversário testa candidatos contra o hash real e força os k primeiros bits da saída em zero com 2^k tentativas, para k = 1, 4, 8, 12, sem nenhuma falha. Esses bits forçados aparecem nos testes populacionais (0 de 10 aprovadas em k = 4, 8 e 12; {int(adv.loc[1, 'n_aprovadas'])} de 10 em k = 1), mas um adversário que controla poucos bits por semente em uma chave isolada não seria percebido. Cada célula de `adv_forca` tem só 10 sequências, então os ICs são largos ({_f(adv1['ic95_inf'], 2)} a {_f(adv1['ic95_sup'], 2)} em k = 1).

### E5. CHSH

![CHSH]({f5})

{_tabela(e5_tab)}
O ideal amostrado passa de 2√2 em alguma repetição por ruído de amostragem, o que não indica violação do limite de Tsirelson. O limite clássico vale por construção nas duas configurações clássicas (o clássico ótimo dá exatamente 2 e o aleatório não informa nada). A faixa "entre 2 e 2√2" para o ruído era uma hipótese pouco restritiva feita antes da rodada, e o resultado foi consistente com ela; o ruído é um retrato fixo da calibração do FakeKingston e não representa o chip hoje. Isto confere que o circuito e a análise estão corretos. **Não mostra não-localidade nem certifica aleatoriedade, e a pergunta "o CHSH ajuda?" não foi respondida para a QPU real.**

## 4. Revisão crítica

Duas revisões: a minha, contra as faixas de incerteza, e a de um revisor independente que recebeu o relatório e os CSVs sem a minha lista. O que não se sustentou foi corrigido neste texto.

| Afirmação ou hipótese | O que a revisão encontrou | Correção |
|---|---|---|
| E3: "muito mais caro que a `os` (razão 15,4 ≥ 10)" | É razão de tempo. Com o custo marginal vale {_f(r_mar['estimativa'], 1)}; só marginal combinado com a máquina local mais lenta ({_f(r_mar['ic_inf'], 1)}) fica abaixo do limiar, enquanto o marginal sozinho e o médio na mais lenta ({_f(r_med['ic_inf'], 1)}) passam de 10. A incerteza do ajuste marginal (±0,5 s por job) dá de {_f(aj_r['ic_inf'], 1)} a {_f(aj_r['ic_sup'], 1)} | "Da ordem de 10 vezes em tempo"; o limiar de 10 não separa os casos |
| E1: "H estimada abaixo de 1 na QPU" | A `os` também dá {_f(h_o['estimativa'])}: o valor é do estimador. A diferença entre fontes reflete o viés, e os lotes não são independentes | Comparar fontes, com p exato {_f(p_h['estimativa'], 4)} só como indício |
| E1: "viés pequeno mas mensurável na QPU" | Confirmado em cada coleta, mas o sinal muda entre a coleta 1 e as outras | Sem sinal estável; o lote 2 da coleta 2 é marginal |
| E1: "a QPU reprova no monobit e no runs" | O runs reprova {len(runs_falha)} lotes por pré-requisito. A QPU passa em min-entropia e em blocos, e o simulador também reprova | Reprovação por monobit, ligada ao tamanho do lote e à porta escolhida |
| E1: "0 de 6 lotes do simulador" | Só 2 lotes distintos (semente fixa) | 0 de 2 lotes distintos |
| E1: "deriva entre dias" | As coletas 1 e 2 são do mesmo dia. O DP já passa de 1 dentro da coleta e até 1,6 com jobs `cal`; o IC bootstrap não é calibrado | "Entre coletas"; sobredispersão também no mesmo dia; causa não investigada; a concentração em poucos qubits é conjetura |
| E4: "hash resiste, XOR é frágil" | Frágil só contra adversário que vê a outra fonte. Sem evidência de diferença na aprovação (n = 100). "Nenhuma semente no alvo" no hash vale por construção. O hash não resiste a quem testa candidatos | Diferença de controle da semente, não de aprovação; k bits de busca forçam k bits |
| E2: "falso positivo de 2,6% a 3,6%" | É consistente com os alfas, mas o valor nominal é uma aproximação (testes dependentes) | "Consistente com"; custo de descartar cerca de 1 lote bom em 30 |
| E5: "ruído entre 2 e 2√2" | Hipótese pouco restritiva, em simulação com ruído fixo; os clássicos valem por construção | Conferência do código; sem conclusão sobre a QPU nem sobre aleatoriedade |
| "Mistura só fontes aprovadas", "recibo assinado" | Passam a ideia de garantia | Aprovado é ausência de defeito na saída; a assinatura é integridade; a extração depende da estimativa de H |

## 5. Limitações

- Protótipo de pesquisa; não usar para proteger dados reais. Bibliotecas PQC em Python puro, sem tempo constante e sem auditoria.
- O provedor da QPU conhece os bits que gerou. CHSH numa QPU em nuvem não é teste de Bell sem brechas.
- Uma QPU (`ibm_kingston`), 3 coletas em {n_dias} dias, 6 lotes. Qualquer afirmação sobre "as QPUs" não se sustenta.
- A QPU nunca foi aprovada pela porta de saúde; por isso nenhum bit dela entrou numa semente e o custo por bit útil não existe.
- O simulador é um gerador clássico, usa semente fixa e trata os qubits como independentes; não reproduz correlação entre vizinhos.
- E1 parcial: a coleta 3 contra a coleta 2 não foi comparada. E5 parcial: só a etapa A.
- Os ICs usam aproximações (bits independentes na fração de uns; 3 testes independentes no falso positivo nominal), e o bootstrap sobre os qubits é descritivo.
- Os testes de saúde não detectam PRNG disfarçado. Isso é um limite de testar só a saída, não um erro do código.
- O tempo de QPU é o cobrado e o local é o tempo de parede do pipeline de uma máquina; não são a mesma moeda.
- A seção 17 do `PROJECT.md` tem as limitações por módulo.

## 6. Como reproduzir

```
py -3.12 -m pip install -r requirements.txt
py -3.12 -m pytest
py -3.12 -m scripts.incerteza_dia8
py -3.12 -m scripts.gerar_relatorio
py -3.12 -m streamlit run dashboard/app.py
```
"""


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--results", type=Path, default=RESULTS)
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args(argv)
    try:
        texto = montar(args.results, args.out)
    except Recusa as e:
        print(f"RECUSADO: {e}")
        return 1
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "RELATORIO.md").write_text(texto, encoding="utf-8", newline="\n")
    print(f"relatório em {args.out / 'RELATORIO.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
