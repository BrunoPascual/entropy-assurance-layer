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


def test_menor_deteccao_plotada_ignora_o_prng():
    e2 = pd.DataFrame({"fonte": ["faulty_biased", "faulty_biased", "faulty_prng", "faulty_stuck"], "tipo": ["deteccao"] * 4,
                       "taxa": [0.30, 0.95, 0.03, 1.0]})
    assert rel.menor_deteccao_plotada(e2) == 0.30


@real
def test_titulo_do_e2_usa_so_o_plotado():
    e2 = pd.read_csv(rel.RESULTS / "e2_resumo.csv")
    assert e2[e2["tipo"] == "deteccao"]["taxa"].min() == pytest.approx(0.03)  # o prng existe no CSV...
    assert rel.menor_deteccao_plotada(e2) == pytest.approx(0.30)  # ...mas não é plotado


def test_deriva_unica_conta_cada_par_de_lotes_uma_vez():
    inc_df = pd.DataFrame({"bloco": ["deriva_dp"] * 4,
                           "item": ["a: l1 x l2", "b: l1 x l2", "b: l1 x l3", "c: l1 x l2"],
                           "estimativa": [1.1] * 4, "ic_inf": [0.9, 0.91, 1.0, 0.92], "ic_sup": [1.3] * 4})
    d = rel.deriva_unica(inc_df)
    assert list(d["par"]) == ["l1 x l2", "l1 x l3"]


@real
def test_deriva_real_tem_16_pares_distintos_em_18_linhas():
    d = pd.read_csv(rel.RESULTS / "dia8_incerteza.csv")
    assert (d["bloco"] == "deriva_dp").sum() == 18 and len(rel.deriva_unica(d)) == 16


def test_piso_trunca_em_vez_de_arredondar():
    assert rel._piso(0.4448, 2) == "0,44" and rel._piso(1.0, 2) == "1,00" and rel._f(0.4448, 2) == "0,44"
    assert rel._piso(0.4481, 2) == "0,44" and rel._f(0.4481, 2) == "0,45"


@real
def test_texto_real_traz_as_correcoes_do_revisor(tmp_path):
    texto = rel.montar(rel.RESULTS, tmp_path)
    assert "da ordem de 20%" not in texto and "não foi quantificada" not in texto
    assert "mesma calibração de execução" in texto and "não testa efeito de calibração" in texto
    assert "têm calibrações diferentes" not in texto and "a troca de calibração não aparece" not in texto
    assert "entre 0,44 e 1,00" in texto and "0,4448" in texto and "entre 0,45" not in texto
    assert "poder do teste exato de Fisher é de 59% a 69%" in texto and "44% perto de 0,90" in texto
    assert "uns 10 pontos percentuais seriam detectáveis" not in texto
    assert "±0,5 s" in texto and "1,40 a 3,10 s/Mbit" in texto and "6,4 a 14,3" in texto
    assert "Só a combinação marginal com a execução local mais lenta (8,8)" in texto and "médio na mais lenta (13,0)" in texto
    assert "16 pares distintos de lotes" in texto


@real
def test_recusa_se_a_calibracao_de_execucao_da_coleta3_diferir(tmp_path):
    res = tmp_path / "res"
    shutil.copytree(rel.RESULTS, res, ignore=shutil.ignore_patterns("*.npy"))
    f = res / "dia6_deriva_coleta3_lotes.csv"
    d = pd.read_csv(f)
    m = d["lote"] == "coleta3_001"
    d.loc[m, "calibracao_execucao"] = "2026-11-02 16:36:41-03:00"
    d.to_csv(f, index=False)
    with pytest.raises(rel.Recusa, match="calibração de execução"):
        rel.montar(res, tmp_path / "out")


@real
def test_recusa_se_o_poder_do_e4_passar_de_80_por_cento(tmp_path):
    res = tmp_path / "res"
    shutil.copytree(rel.RESULTS, res, ignore=shutil.ignore_patterns("*.npy"))
    d = pd.read_csv(res / "dia8_incerteza.csv")
    d.loc[d["bloco"] == "e4_poder", "estimativa"] = 0.9
    d.to_csv(res / "dia8_incerteza.csv", index=False)
    with pytest.raises(rel.Recusa, match="poder"):
        rel.montar(res, tmp_path / "out")
