"""Testes das faixas de incerteza do Dia 8: respostas conhecidas e conferência com os CSVs reais."""
import math

import numpy as np
import pandas as pd
import pytest

from scripts import incerteza_dia8 as inc

REAL = (inc.RESULTS / "e2_resumo.csv").is_file()
real = pytest.mark.skipif(not REAL, reason="data/results real ausente")


def test_clopper_pearson_extremos_e_regra_dos_tres():
    lo, hi = inc.clopper_pearson(0, 100)
    assert lo == 0.0 and hi == pytest.approx(1 - 0.025 ** (1 / 100), rel=1e-9)
    lo, hi = inc.clopper_pearson(100, 100)
    assert hi == 1.0 and lo == pytest.approx(0.025 ** (1 / 100), rel=1e-9)


def test_clopper_pearson_conhecido():
    lo, hi = inc.clopper_pearson(52, 2000)  # os, 1M bits; limites conferidos contra o e2_resumo.csv
    assert (round(lo, 4), round(hi, 4)) == (0.0195, 0.0340)


def test_zdiff_pondera_pelos_shots_e_da_zero_para_lotes_iguais():
    q = pd.DataFrame({"lote": ["a"] * 3 + ["b"] * 3, "posicao": [0, 1, 2] * 2, "n_shots": [1000] * 3 + [4000] * 3,
                      "p1": [0.5, 0.4, 0.6, 0.5, 0.4, 0.6]})
    assert np.allclose(inc._zdiff(q, "a", "b"), 0)
    q.loc[q["lote"] == "b", "p1"] = [0.52, 0.4, 0.6]
    z = inc._zdiff(q, "a", "b")
    pool = (1000 * 0.5 + 4000 * 0.52) / 5000
    assert z[0] == pytest.approx((0.5 - 0.52) / math.sqrt(pool * (1 - pool) * (1 / 1000 + 1 / 4000)))


def test_bootstrap_dp_e_reprodutivel_e_cobre_o_dp():
    z = np.random.default_rng(1).normal(size=156)
    a = inc._boot_dp(z, np.random.default_rng(7))
    assert a == inc._boot_dp(z, np.random.default_rng(7))
    assert a[0] < z.std(ddof=1) < a[1]


@real
def test_dp_recalculado_bate_com_o_registrado():
    df = inc.bloco_deriva(inc.RESULTS)  # levanta ValueError se algum dp divergir
    assert len(df) == 18 and all(r["ic_inf"] < r["estimativa"] < r["ic_sup"] for r in df)


@real
def test_simulador_conta_so_lotes_distintos():
    rows = {r["item"]: r for r in inc.bloco_h_lotes(inc.RESULTS)}
    assert any("simulador (n=2 lotes distintos)" in k for k in rows)
    assert any("QPU real (n=6" in k for k in rows)
    assert rows["p exato qpu_real contra os"]["estimativa"] == pytest.approx(2 / math.comb(12, 6))


@real
def test_e3_faixa_cruza_o_limiar():
    r = {x["item"]: x for x in inc.bloco_e3(inc.RESULTS)}
    medio = r["critério registrado: custo médio da QPU / mediana local"]
    marginal = r["custo marginal da QPU / mediana local"]
    assert medio["estimativa"] == pytest.approx(15.3976, abs=1e-3)  # o 15,40 do PROJECT.md
    assert marginal["ic_inf"] < 10 < medio["estimativa"]


@real
def test_e4_hash_xor_nao_difere():
    for r in inc.bloco_e4(inc.RESULTS):
        assert float(r["observacao"].split("p = ")[1]) > 0.05


@real
def test_calcular_gera_todos_os_blocos():
    df = inc.calcular(inc.RESULTS)
    assert set(df["bloco"]) == {"h_lotes", "frac1", "deriva_dp", "e2_fp", "e3_razao", "e3_ajuste", "e4_hash_xor", "e4_poder", "e5_s"}
    assert list(df.columns) == inc.COLUNAS


@real
def test_e4_p_exato_sai_com_4_casas_e_o_minimo_e_0_4448():
    ps = [float(r["observacao"].split("p = ")[1]) for r in inc.bloco_e4(inc.RESULTS)]
    assert min(ps) == pytest.approx(0.4448, abs=1e-4) and min(ps) < 0.445


def test_poder_fisher_conhecido_e_sem_diferenca_nao_passa_do_alfa():
    assert inc.poder_fisher(0.95, 0.85, 100) == pytest.approx(0.586, abs=2e-3)
    assert inc.poder_fisher(0.90, 0.80, 100) == pytest.approx(0.444, abs=2e-3)
    assert inc.poder_fisher(0.9, 0.9, 30) <= inc.ALFA_E4  # Fisher é conservador: nunca excede o alfa
    assert inc.poder_fisher(0.99, 0.30, 30) > 0.99


@real
def test_bloco_e4_poder_abaixo_de_80_por_cento_com_n_100():
    rows = inc.bloco_e4_poder(inc.RESULTS)
    assert len(rows) == 3 and all(0.4 < r["estimativa"] < 0.8 for r in rows)
    assert "n = 100" in rows[0]["observacao"]


@real
def test_ajuste_marginal_propaga_meio_segundo_e_bate_com_os_cantos():
    r = {x["item"]: x for x in inc.bloco_e3(inc.RESULTS)}
    c = r["ajuste marginal da QPU (s/Mbit)"]
    assert c["estimativa"] == pytest.approx(2.2456, abs=1e-3)
    assert (round(c["ic_inf"], 2), round(c["ic_sup"], 2)) == (1.40, 3.10)
    # força bruta: ±0,5 s em cada job, todos os 2^8 cantos; o extremo do ajuste linear está num canto
    q = pd.read_csv(inc.RESULTS / "e3_qpu.csv")
    x, y = q["shots"].to_numpy(float), q["quantum_seconds"].to_numpy(float)
    bs = []
    for m in range(2 ** len(y)):
        d = np.array([0.5 if m >> i & 1 else -0.5 for i in range(len(y))])
        bs.append(np.polyfit(x, y + d, 1)[0] / 156 * 1e6)
    assert min(bs) == pytest.approx(c["ic_inf"], rel=1e-6) and max(bs) == pytest.approx(c["ic_sup"], rel=1e-6)
    razao = r["razão marginal / mediana local (incerteza do ajuste)"]
    assert razao["ic_inf"] < 10 < razao["ic_sup"] and 6.4 < razao["ic_inf"] < 6.5 and 14.2 < razao["ic_sup"] < 14.4
