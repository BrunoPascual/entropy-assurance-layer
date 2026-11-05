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
    assert set(df["bloco"]) == {"h_lotes", "frac1", "deriva_dp", "e2_fp", "e3_razao", "e4_hash_xor", "e5_s"}
    assert list(df.columns) == inc.COLUNAS
