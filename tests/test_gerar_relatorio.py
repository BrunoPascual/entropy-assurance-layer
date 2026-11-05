"""Testes do gerador do relatório (Dia 8): recusa quando os CSVs não sustentam o texto; saída sobre os dados reais."""
import shutil

import pandas as pd
import pytest

from scripts import gerar_relatorio as rel
from scripts import incerteza_dia8 as inc

REAL = (rel.RESULTS / "dia8_incerteza.csv").is_file()
real = pytest.mark.skipif(not REAL, reason="data/results real ausente")


def test_checar_levanta_recusa():
    with pytest.raises(rel.Recusa, match="x"):
        rel._checar(False, "x")
    rel._checar(True, "nunca")


def test_formatacao_brasileira():
    assert rel._f(0.4964, 4) == "0,4964" and rel._int(3000192) == "3.000.192"


def test_tabela_markdown():
    t = rel._tabela(pd.DataFrame({"a": [1], "b": ["x"]}))
    assert t.splitlines()[0] == "| a | b |" and t.splitlines()[-1] == "| 1 | x |"


@real
def test_relatorio_real_tem_secoes_numeros_e_5_experimentos(tmp_path):
    texto = rel.montar(rel.RESULTS, tmp_path)
    for secao in ("## 1. Resumo", "## 4. Revisão crítica", "## 5. Limitações", "### E1.", "### E2.", "### E3.", "### E4.", "### E5."):
        assert secao in texto
    assert "0 de 2 lotes distintos" in texto and "3.000.192 bits por coleta" in texto
    assert "{_" not in texto and "{n_" not in texto  # nenhuma expressão f-string vazou
    assert len(list((tmp_path / "figuras").glob("*.png"))) == 7


@real
def test_recusa_se_o_simulador_tiver_lotes_distintos(tmp_path):
    res = tmp_path / "res"
    shutil.copytree(rel.RESULTS, res, ignore=shutil.ignore_patterns("*.npy"))
    f = res / "dia6_coleta2_qpu_vs_sim_lotes.csv"
    d = pd.read_csv(f)
    d.loc[d["fonte"] == "simulador", "batch_hash"] = ["a" * 64, "b" * 64]
    d.to_csv(f, index=False)
    f3 = res / "dia6_coleta3_qpu_vs_sim_lotes.csv"
    d3 = pd.read_csv(f3)
    d3.loc[d3["fonte"] == "simulador", "batch_hash"] = ["c" * 64, "d" * 64]
    d3.to_csv(f3, index=False)
    with pytest.raises(rel.Recusa, match="simulador"):
        rel.montar(res, tmp_path / "out")


@real
def test_recusa_se_o_limiar_do_e3_deixar_de_cruzar(tmp_path):
    res = tmp_path / "res"
    shutil.copytree(rel.RESULTS, res, ignore=shutil.ignore_patterns("*.npy"))
    d = pd.read_csv(res / "dia8_incerteza.csv")
    m = d["item"].str.startswith("custo marginal da QPU")
    d.loc[m, "ic_inf"] = 10.2  # abaixo da estimativa (10,37) mas acima do limiar de 10
    d.to_csv(res / "dia8_incerteza.csv", index=False)
    with pytest.raises(rel.Recusa, match="E3"):
        rel.montar(res, tmp_path / "out")


@real
def test_csv_de_incerteza_em_disco_e_o_que_o_script_gera(tmp_path):
    novo = inc.calcular(inc.RESULTS)
    velho = pd.read_csv(inc.RESULTS / inc.OUT_NAME)
    assert len(novo) == len(velho) and list(novo.columns) == list(velho.columns)
    assert (novo["estimativa"] - velho["estimativa"]).abs().max() < 1e-4
