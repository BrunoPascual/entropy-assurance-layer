"""Testes de scripts/registrar_deriva_coleta2.py (registro da coleta 2 e da deriva, Dia 6)."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_PATH = Path(__file__).resolve().parent.parent / "scripts" / "registrar_deriva_coleta2.py"
_spec = importlib.util.spec_from_file_location("_registrar_deriva_coleta2", _PATH)
mod = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = mod
_spec.loader.exec_module(mod)

C1, C2 = "2026-11-01 11:57:51-03:00", "2026-11-01 16:56:51-03:00"
CSVS = {
    "dia6_coleta2_inventario.csv":
        "arquivo,job_id,backend,qubits,shots,n_bits,uso_qpu_s,reserva_s,calibracao,npy_sha256,"
        "json_sha256\r\n"
        f"a_coleta2_001.json,j3,ibm_kingston,156,9616,1500096,5,20,{C2},x,y\r\n"
        f"a_coleta2_002.json,j4,ibm_kingston,156,9616,1500096,5,20,{C2},x2,y2\r\n",
    "dia6_coleta2_qpu_vs_sim_lotes.csv":
        "fonte,lote,saude_approved,saude_h_estimated,ext_n_output_bits\n"
        "qpu_real,1,False,0.9597687287,0\nqpu_real,2,False,0.9553011824,0\n"
        "os,1,True,0.9664758866,1354932\n",
    "dia6_deriva_coleta2_lotes.csv":
        "lote,sessao,calibracao_no_envio,calibracao_execucao,retrato_leitura,"
        "calibracao_igual_coleta1,frac1\n"
        f"coleta1_001,coleta1,{C1},,envio,True,0.4964\n"
        f"coleta2_001,coleta2,{C2},{C2},execucao,False,0.5025\n",
    "dia6_deriva_coleta2_conjunto_fixo.csv":
        "tipo,grupo,id,lote,estimativa,z,z_esperado,testavel,sinal_igual,replica,"
        "magnitude_compativel\n"
        "qubit,vies_alem_da_leitura,14,coleta1_001,0.34,-31,,,,,\n"
        "qubit,vies_alem_da_leitura,14,coleta2_001,0.35,-29,30,True,True,True,True\n"
        "qubit,vies_alem_da_leitura,21,coleta2_001,0.40,-19,25,True,True,True,False\n"
        "qubit,vies_alem_da_leitura,138,coleta2_001,0.50,0.1,30,True,False,False,False\n"
        "par,par_replicado_coleta1,130-131,coleta2_001,0.01,1,2,False,True,,\n",
    "dia6_deriva_coleta2_estabilidade.csv":
        "lote_a,lote_b,zdiff_media,zdiff_dp,zdiff_n_acima3\ncoleta1_001,coleta2_001,0.5,1.2,3\n",
}
ORIGINAL = "# Projeto\r\n\r\nseção\r\n".encode("utf-8")


@pytest.fixture
def results(tmp_path):
    d = tmp_path / "results"
    d.mkdir()
    for name, text in CSVS.items():
        (d / name).write_bytes(text.encode("utf-8"))
    return d


@pytest.fixture
def doc(tmp_path):
    p = tmp_path / "PROJECT.md"
    p.write_bytes(ORIGINAL)
    return p


def block(results: Path) -> str:
    return mod.render(mod.load(results))


def test_hash_antes_e_o_do_commit_ca9e652():
    assert mod.HASH_ANTES == "295d7fa3e6f2abae2b2ac463354cec398abd4b17b947d84cee1f808b0f12c31e"


def test_classificacao_dos_itens(results):
    b = block(results)
    assert ("| qubit 14 | vies_alem_da_leitura | coleta2_001 | 0,3500 | -29,00 | 30,00 "
            "| replica |") in b
    assert "direção reproduzida, magnitude não |" in b
    assert "| qubit 138 |" in b and "não replica |" in b
    assert "| par 130-131 |" in b and "não testável |" in b
    assert "Contagem: direção reproduzida, magnitude não: 1; não replica: 1; " \
           "não testável: 1; replica: 1." in b


def test_linhas_da_coleta1_nao_entram_no_conjunto_fixo(results):
    assert "| qubit 14 | vies_alem_da_leitura | coleta1_001 |" not in block(results)


def test_totais_e_saude_saem_dos_csvs(results):
    b = block(results)
    assert "2 lotes, 3.000.192 bits, 10 s de QPU" in b
    assert "| qpu_real | 1 | não | 0,959769 | 0 |" in b
    assert "| os | 1 | sim | 0,966476 | 1.354.932 |" in b


def test_limite_de_calibracao_trocada(results):
    b = block(results)
    assert f"outra calibração ({C2}) que a coleta 1 ({C1})" in b


def test_mesma_calibracao_tem_outro_texto(results):
    p = results / "dia6_deriva_coleta2_lotes.csv"
    p.write_text(p.read_text().replace("execucao,False", "execucao,True"))
    assert "rodou sob a mesma calibração da coleta 1" in block(results)


def test_hashes_dos_csvs_no_bloco(results):
    b = block(results)
    for name in CSVS:
        assert f"`{name}`: `{mod.sha256((results / name).read_bytes())}`" in b


@pytest.mark.parametrize("name", list(CSVS))
def test_csv_ausente_recusa(results, name):
    (results / name).unlink()
    with pytest.raises(mod.Refused, match="ausente"):
        mod.load(results)


def test_coluna_ausente_recusa(results):
    p = results / "dia6_deriva_coleta2_conjunto_fixo.csv"
    p.write_text(p.read_text().replace("magnitude_compativel", "outra"))
    with pytest.raises(mod.Refused, match="colunas"):
        mod.load(results)


def test_aplica_no_fim_e_segunda_vez_nao_grava(doc, results):
    b = block(results)
    antes = mod.sha256(ORIGINAL)
    assert mod.apply(doc, b, antes) == "aplicado"
    data = doc.read_bytes()
    assert data.startswith(ORIGINAL) and data.endswith(b"\r\n")
    assert b"\n" not in data.replace(b"\r\n", b"")
    text = data.decode("utf-8")
    assert text.count(mod.START) == 1 and text.count(mod.END) == 1
    assert mod.apply(doc, b, antes) == "ja aplicado"
    assert doc.read_bytes() == data


def test_hash_diferente_recusa_sem_gravar(doc, results):
    with pytest.raises(mod.Refused):
        mod.apply(doc, block(results), "0" * 64)
    assert doc.read_bytes() == ORIGINAL


@pytest.mark.parametrize("data", [b"lf\n", b"misto\r\nx\n", b"sem fim\r\nx"])
def test_formato_errado_recusa(tmp_path, results, data):
    p = tmp_path / "P.md"
    p.write_bytes(data)
    with pytest.raises(mod.Refused):
        mod.apply(p, block(results), mod.sha256(data))
    assert p.read_bytes() == data


def test_marcador_existente_recusa(tmp_path, results):
    data = f"x\r\n{mod.START}\r\n".encode("utf-8")
    p = tmp_path / "P.md"
    p.write_bytes(data)
    with pytest.raises(mod.Refused):
        mod.apply(p, block(results), mod.sha256(data))


def test_main_recusa_sem_gravar(doc, results, capsys):
    assert mod.main(doc, results) == 1
    assert "RECUSADO" in capsys.readouterr().out and doc.read_bytes() == ORIGINAL


def test_bloco_sem_segredos():
    low = Path(_PATH).read_text(encoding="utf-8").lower()
    assert "ibm_quantum_token" not in low
