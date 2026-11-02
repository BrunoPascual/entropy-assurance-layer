"""Testes de scripts/registrar_deriva_coleta3.py (registro da coleta 3 e da deriva, Dia 7)."""
from __future__ import annotations

import hashlib
import importlib.util
import sys
from pathlib import Path

import pytest

_PATH = Path(__file__).resolve().parent.parent / "scripts" / "registrar_deriva_coleta3.py"
_spec = importlib.util.spec_from_file_location("_registrar_deriva_coleta3", _PATH)
mod = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = mod
_spec.loader.exec_module(mod)

C1 = "2026-11-01 11:57:51-03:00"
C3_ENVIO = "2026-11-02 16:36:41-03:00"
C3 = "2026-11-02 17:14:09-03:00"
BASE = b"# Projeto\r\n\r\ntexto\r\n<!-- dia6-coleta2:start -->\r\nx\r\n<!-- dia6-coleta2:end -->\r\n"

FIXO_CABECALHO = ("tipo,grupo,id,lote,estimativa,z,z_esperado,testavel,sinal_igual,replica,"
                  "magnitude_compativel\n")
Q = "vies_alem_da_leitura"
FIXO_LINHAS = [
    # referência (coleta 1): testavel vazio, não entra na tabela
    "qubit,vies_alem_da_leitura,14,coleta1_001,0.34,-31,,,,,",
    "qubit,vies_alem_da_leitura,14,coleta1_002,0.35,-30,,,,,",
    f"qubit,{Q},14,coleta3_001,0.48824875208,-2.30468307147,28.818736106,True,True,True,False",
    f"qubit,{Q},14,coleta3_002,0.500623960067,0.122372552467,28.818736106,True,False,False,False",
    f"qubit,{Q},21,coleta3_001,0.514663061564,2.87575498298,4.56857529211,True,True,True,True",
    f"qubit,{Q},21,coleta3_002,0.527454242928,5.38439230856,4.56857529211,True,True,True,True",
    f"qubit,{Q},138,coleta3_001,0.510087354409,1.97835626489,27.2176952112,True,True,False,False",
    f"qubit,{Q},138,coleta3_002,0.499168053245,-0.16316340329,27.2176952112,True,False,False,False",
    "qubit,controle_leitura,121,coleta3_001,0.441763727121,-11.4214382303,34.6314323482,True,True,True,False",
    "qubit,controle_leitura,121,coleta3_002,0.44571547421,-10.6464120646,34.6314323482,True,True,True,False",
    "qubit,controle_leitura,131,coleta3_001,0.66212562396,31.7964682161,28.0131168023,True,True,True,False",
    "qubit,controle_leitura,131,coleta3_002,0.658069883527,31.001046625,28.0131168023,True,True,True,True",
    "par,par_replicado_coleta1,112-113,coleta3_001,-0.0665792125875,-6.52883783939,6.11887023393,True,True,True,True",
    "par,par_replicado_coleta1,112-113,coleta3_002,-0.0628089260357,-6.1591189955,6.11887023393,True,True,True,True",
    "par,par_replicado_coleta1,130-131,coleta3_001,-0.0399213625485,-3.9147369318,3.31731834799,True,True,True,True",
    "par,par_replicado_coleta1,130-131,coleta3_002,-0.0287910249026,-2.82328260598,3.31731834799,True,True,True,True",
]

CSVS = {
    "dia6_coleta3_inventario.csv":
        "arquivo,job_id,backend,qubits,shots,n_bits,uso_qpu_s,reserva_s,calibracao,npy_sha256,"
        "json_sha256\r\n"
        f"2026-11-02_ibm_kingston_coleta3_001.json,dbkf24d6p51s73cmg7ng,ibm_kingston,156,9616,"
        f"1500096,5,20,{C3},x,y\r\n"
        f"2026-11-02_ibm_kingston_coleta3_002.json,dbkf4f1ffo6c73bbc8m0,ibm_kingston,156,9616,"
        f"1500096,5,20,{C3},x2,y2\r\n",
    "dia6_coleta3_qpu_vs_sim_lotes.csv":
        "fonte,lote,saude_approved,saude_h_estimated,ext_n_output_bits\n"
        "qpu_real,1,False,0.960593306672466,0\nqpu_real,2,False,0.95590377258674,0\n"
        "simulador,1,False,0.9591528149774433,0\nsimulador,2,False,0.9618374465765778,0\n"
        "os,1,True,0.9624628230555018,1349076\nos,2,True,0.9686252904913166,1357860\n",
    "dia6_deriva_coleta3_lotes.csv":
        "lote,sessao,calibracao_no_envio,calibracao_execucao,retrato_leitura,"
        "calibracao_igual_coleta1,frac1\n"
        f"coleta1_001,coleta1,{C1},,envio,True,0.496442227697\n"
        f"coleta1_002,coleta1,{C1},,envio,True,0.497970129912\n"
        f"coleta3_001,coleta3,{C3_ENVIO},{C3},execucao,False,0.502755157003\n"
        f"coleta3_002,coleta3,{C3},{C3},execucao,False,0.504835690516\n",
    "dia6_deriva_coleta3_conjunto_fixo.csv": FIXO_CABECALHO + "\n".join(FIXO_LINHAS) + "\n",
    "dia6_deriva_coleta3_estabilidade.csv":
        "lote_a,lote_b,zdiff_media,zdiff_dp,zdiff_n_acima3\n"
        "coleta1_001,coleta1_002,-0.212376798164,1.14453833441,3\n"
        "coleta1_001,coleta3_001,-0.882294511815,3.0634951651,12\n"
        "coleta1_001,coleta3_002,-1.17067129253,3.06697484855,14\n"
        "coleta1_002,coleta3_001,-0.670161792237,2.96523738244,11\n"
        "coleta1_002,coleta3_002,-0.95856395808,2.98325828064,11\n"
        "coleta3_001,coleta3_002,-0.288445358533,1.08886888903,1\n",
}


@pytest.fixture
def ambiente(tmp_path, monkeypatch):
    results = tmp_path / "results"
    results.mkdir()
    for nome, texto in CSVS.items():
        (results / nome).write_bytes(texto.encode("utf-8"))
    projeto = tmp_path / "PROJECT.md"
    projeto.write_bytes(BASE)
    monkeypatch.setattr(mod, "HASH_ANTES", hashlib.sha256(BASE).hexdigest())
    return projeto, results


def bloco_gerado(projeto: Path) -> list[str]:
    texto = projeto.read_bytes().decode("utf-8")
    return texto[texto.index(mod.START):].split("\r\n")


def aplicar(ambiente, capsys) -> tuple[int, str]:
    projeto, results = ambiente
    codigo = mod.main(projeto, results)
    return codigo, capsys.readouterr().out


# ---------------------------------------------------------------- aplicação

def test_aplica_no_fim_sem_mexer_no_resto(ambiente, capsys):
    projeto, results = ambiente
    codigo, out = aplicar(ambiente, capsys)
    dados = projeto.read_bytes()
    assert codigo == 0 and out.startswith("aplicado:")
    assert dados.startswith(BASE + b"\r\n" + mod.START.encode())
    assert dados.endswith(mod.END.encode() + b"\r\n")
    assert dados.count(b"\n") == dados.count(b"\r\n")
    assert hashlib.sha256(BASE).hexdigest().upper() in out
    assert hashlib.sha256(dados).hexdigest().upper() in out
    assert not list(projeto.parent.glob("*.tmp*"))


def test_idempotente(ambiente, capsys):
    projeto, _ = ambiente
    aplicar(ambiente, capsys)
    antes = projeto.read_bytes()
    codigo, out = aplicar(ambiente, capsys)
    assert codigo == 0 and out.startswith("já aplicado")
    assert projeto.read_bytes() == antes


# ---------------------------------------------------------------- conteúdo

def test_cabecalho_inventario_saude(ambiente, capsys):
    aplicar(ambiente, capsys)
    b = bloco_gerado(ambiente[0])
    assert b[0] == mod.START
    assert b[1] == "### Coleta 3 e deriva entre dias (Dia 7, registro gerado dos CSVs)"
    assert "**Lotes da coleta 3 (inventário):** 2 lotes, 3.000.192 bits, 10 s de QPU." in b
    assert "| 2026-11-02_ibm_kingston_coleta3_001.json | dbkf24d6p51s73cmg7ng | 1.500.096 | 5 |" in b
    assert "| qpu_real | 1 | não | 0,960593 | 0 |" in b
    assert "| simulador | 2 | não | 0,961837 | 0 |" in b
    assert "| os | 1 | sim | 0,962463 | 1.349.076 |" in b
    assert "| os | 2 | sim | 0,968625 | 1.357.860 |" in b


def test_tabela_de_calibracao_com_o_envio(ambiente, capsys):
    aplicar(ambiente, capsys)
    b = bloco_gerado(ambiente[0])
    assert ("| Lote | Sessão | Calibração no envio | Calibração em vigor | Retrato de leitura "
            "| Igual à coleta 1 | Fração de 1 |") in b
    assert (f"| coleta1_001 | coleta1 | {C1} | {C1} | envio | sim | 0,4964 |") in b
    assert (f"| coleta3_001 | coleta3 | {C3_ENVIO} | {C3} | execucao | não | 0,5028 |") in b
    assert (f"| coleta3_002 | coleta3 | {C3} | {C3} | execucao | não | 0,5048 |") in b


def test_conjunto_fixo_e_contagem(ambiente, capsys):
    aplicar(ambiente, capsys)
    b = bloco_gerado(ambiente[0])
    assert f"| qubit 14 | {Q} | coleta3_001 | 0,4882 | -2,30 | 28,82 | direção reproduzida, magnitude não |" in b
    assert f"| qubit 14 | {Q} | coleta3_002 | 0,5006 | 0,12 | 28,82 | não replica |" in b
    assert f"| qubit 138 | {Q} | coleta3_001 | 0,5101 | 1,98 | 27,22 | não replica |" in b
    assert f"| qubit 21 | {Q} | coleta3_002 | 0,5275 | 5,38 | 4,57 | replica |" in b
    assert "| par 130-131 | par_replicado_coleta1 | coleta3_002 | -0,0288 | -2,82 | 3,32 | replica |" in b
    assert "Contagem: direção reproduzida, magnitude não: 4; não replica: 3; replica: 7." in b
    # as linhas de referência (coleta 1, testavel vazio) não entram
    assert not any("coleta1_001 | 0,34" in l for l in b)
    assert sum(1 for l in b if l.startswith("| qubit ") or l.startswith("| par ")) == 14


def test_estabilidade_e_faixas(ambiente, capsys):
    aplicar(ambiente, capsys)
    b = bloco_gerado(ambiente[0])
    assert "| coleta1_001 | coleta1_002 | -0,212 | 1,145 | 3 |" in b
    assert "| coleta1_001 | coleta3_002 | -1,171 | 3,067 | 14 |" in b
    assert ("Desvio-padrão do zdiff entre lotes da mesma sessão: de 1,089 a 1,145. "
            "Entre lotes de sessões diferentes: de 2,965 a 3,067.") in b


def test_limites(ambiente, capsys):
    aplicar(ambiente, capsys)
    b = bloco_gerado(ambiente[0])
    texto = "\n".join(b)
    assert (f"- A coleta 3 rodou sob outra calibração ({C3}) que a coleta 1 ({C1}), em outro dia "
            "e em outra hora do dia (plano congelado). A diferença entre as coletas mistura o "
            "dia, a hora do dia e a troca de calibração, e estes dados não separam os três.") in b
    assert (f"- No lote coleta3_001, a calibração em vigor na execução ({C3}) difere da do envio "
            f"({C3_ENVIO}); a análise usa o retrato da execução (R8).") in b
    assert "No lote coleta3_002" not in texto and "No lote coleta1" not in texto
    assert "análise secundária prevista no plano (contra a coleta 2" in texto
    assert "não foi feita neste registro" in texto
    assert "A causa de qualquer diferença" in texto


def test_hashes_dos_csvs(ambiente, capsys):
    projeto, results = ambiente
    aplicar(ambiente, capsys)
    b = bloco_gerado(projeto)
    for nome in CSVS:
        h = hashlib.sha256((results / nome).read_bytes()).hexdigest()
        assert f"- `{nome}`: `{h}`" in b
    ordem = [l for l in b if l.startswith("- `dia6_")]
    assert ordem == sorted(ordem) and len(ordem) == 5


def test_mesma_calibracao_da_coleta_1(ambiente, capsys):
    projeto, results = ambiente
    p = results / "dia6_deriva_coleta3_lotes.csv"
    texto = CSVS["dia6_deriva_coleta3_lotes.csv"].replace(",execucao,False,", ",execucao,True,")
    p.write_bytes(texto.encode("utf-8"))
    aplicar(ambiente, capsys)
    b = "\n".join(bloco_gerado(projeto))
    assert "- A coleta 3 rodou sob a mesma calibração da coleta 1." in b
    assert "outra calibração" not in b


def test_sem_aviso_quando_envio_igual_a_execucao(ambiente, capsys):
    projeto, results = ambiente
    p = results / "dia6_deriva_coleta3_lotes.csv"
    p.write_bytes(CSVS["dia6_deriva_coleta3_lotes.csv"].replace(C3_ENVIO, C3).encode("utf-8"))
    aplicar(ambiente, capsys)
    assert "difere da do envio" not in "\n".join(bloco_gerado(projeto))


def test_sem_linha_de_faixas_se_so_ha_um_tipo_de_par(ambiente, capsys):
    projeto, results = ambiente
    linhas = CSVS["dia6_deriva_coleta3_estabilidade.csv"].splitlines()
    p = results / "dia6_deriva_coleta3_estabilidade.csv"
    p.write_bytes(("\n".join([linhas[0], linhas[2], linhas[3]]) + "\n").encode("utf-8"))  # só entre sessões
    aplicar(ambiente, capsys)
    texto = "\n".join(bloco_gerado(projeto))
    assert "Desvio-padrão do zdiff entre lotes da mesma sessão" not in texto
    assert "| coleta1_001 | coleta3_002 | -1,171 | 3,067 | 14 |" in texto


def test_nao_testavel_entra_na_contagem(ambiente, capsys):
    projeto, results = ambiente
    extra = f"qubit,{Q},77,coleta3_001,0.5,0.1,1.0,False,,,\n"
    p = results / "dia6_deriva_coleta3_conjunto_fixo.csv"
    p.write_bytes((CSVS["dia6_deriva_coleta3_conjunto_fixo.csv"] + extra).encode("utf-8"))
    aplicar(ambiente, capsys)
    b = bloco_gerado(projeto)
    assert "Contagem: direção reproduzida, magnitude não: 4; não replica: 3; não testável: 1; replica: 7." in b
    assert f"| qubit 77 | {Q} | coleta3_001 | 0,5000 | 0,10 | 1,00 | não testável |" in b


@pytest.mark.parametrize("linha,esperado", [
    (dict(testavel="False", replica="", magnitude_compativel=""), "não testável"),
    (dict(testavel="True", replica="True", magnitude_compativel="True"), "replica"),
    (dict(testavel="True", replica="True", magnitude_compativel="False"),
     "direção reproduzida, magnitude não"),
    (dict(testavel="True", replica="False", magnitude_compativel="True"), "não replica"),
    (dict(testavel="True", replica="False", magnitude_compativel="False"), "não replica"),
])
def test_outcome(linha, esperado):
    assert mod.outcome(linha) == esperado


def test_funcoes_de_formato():
    assert mod.num("0.4882", 2) == "0,49" and mod.num("", 2) == "-"
    assert mod.thousands("1500096") == "1.500.096" and mod.thousands("5.0") == "5"
    assert mod.yes_no("True") == "sim" and mod.yes_no("") == "-"
    assert mod.session_of("coleta3_001") == "coleta3"
    assert mod.sd_range([1.14453, 1.08886]) == "de 1,089 a 1,145"
    assert mod.calibration_used({"calibracao_execucao": "A", "calibracao_no_envio": "B"}) == "A"
    assert mod.calibration_used({"calibracao_execucao": "", "calibracao_no_envio": "B"}) == "B"


def test_bits_extraidos_vazio_vira_zero(ambiente, capsys):
    projeto, results = ambiente
    p = results / "dia6_coleta3_qpu_vs_sim_lotes.csv"
    p.write_bytes(CSVS["dia6_coleta3_qpu_vs_sim_lotes.csv"].replace(
        "0.960593306672466,0\n", "0.960593306672466,\n").encode("utf-8"))
    aplicar(ambiente, capsys)
    assert "| qpu_real | 1 | não | 0,960593 | 0 |" in bloco_gerado(projeto)


# ---------------------------------------------------------------- recusas

def estado(ambiente) -> dict[str, bytes]:
    base = ambiente[0].parent
    return {str(p.relative_to(base)): p.read_bytes() for p in sorted(base.rglob("*")) if p.is_file()}


def recusa(ambiente, capsys, trecho: str):
    antes = estado(ambiente)
    codigo, out = aplicar(ambiente, capsys)
    assert codigo == 1 and out.startswith("RECUSADO (nada foi gravado)") and trecho in out, out
    assert estado(ambiente) == antes


def test_recusa_hash_diferente(ambiente, capsys, monkeypatch):
    monkeypatch.setattr(mod, "HASH_ANTES", "0" * 64)
    recusa(ambiente, capsys, "difere do esperado")


@pytest.mark.parametrize("marcador", ["START", "END"])
def test_recusa_marcador_existente(ambiente, capsys, monkeypatch, marcador):
    projeto, _ = ambiente
    dados = BASE + getattr(mod, marcador).encode() + b"\r\n"
    projeto.write_bytes(dados)
    monkeypatch.setattr(mod, "HASH_ANTES", hashlib.sha256(dados).hexdigest())
    recusa(ambiente, capsys, "já existe")


@pytest.mark.parametrize("dados", [BASE.replace(b"\r\n", b"\n"), BASE + b"solto\n",
                                   BASE + b"cr\rsolto\r\n"])
def test_recusa_nao_crlf(ambiente, capsys, monkeypatch, dados):
    projeto, _ = ambiente
    projeto.write_bytes(dados)
    monkeypatch.setattr(mod, "HASH_ANTES", hashlib.sha256(dados).hexdigest())
    recusa(ambiente, capsys, "CRLF puro")


def test_recusa_sem_fim_de_linha(ambiente, capsys, monkeypatch):
    projeto, _ = ambiente
    dados = BASE + b"fim"
    projeto.write_bytes(dados)
    monkeypatch.setattr(mod, "HASH_ANTES", hashlib.sha256(dados).hexdigest())
    recusa(ambiente, capsys, "fim de linha")


@pytest.mark.parametrize("nome", list(CSVS))
def test_recusa_csv_ausente(ambiente, capsys, nome):
    (ambiente[1] / nome).unlink()
    recusa(ambiente, capsys, "CSV ausente")


@pytest.mark.parametrize("nome,coluna", [
    ("dia6_coleta3_inventario.csv", "uso_qpu_s"),
    ("dia6_coleta3_qpu_vs_sim_lotes.csv", "saude_h_estimated"),
    ("dia6_deriva_coleta3_lotes.csv", "calibracao_execucao"),
    ("dia6_deriva_coleta3_conjunto_fixo.csv", "magnitude_compativel"),
    ("dia6_deriva_coleta3_estabilidade.csv", "zdiff_dp"),
])
def test_recusa_coluna_faltando(ambiente, capsys, nome, coluna):
    p = ambiente[1] / nome
    p.write_bytes(p.read_bytes().replace(coluna.encode(), b"renomeada", 1))
    recusa(ambiente, capsys, "faltam as colunas")


@pytest.mark.parametrize("nome", list(CSVS))
def test_recusa_csv_sem_linhas(ambiente, capsys, nome):
    p = ambiente[1] / nome
    p.write_bytes(CSVS[nome].splitlines()[0].encode("utf-8") + b"\n")
    recusa(ambiente, capsys, "sem linhas")


def test_ja_aplicado_exige_o_prefixo_original(ambiente, capsys):
    projeto, results = ambiente
    bloco = mod.render(mod.load(results))
    dados = BASE + b"editado\r\n" + mod.tail_bytes(bloco)
    projeto.write_bytes(dados)
    recusa(ambiente, capsys, "difere do esperado")
    projeto.write_bytes(BASE + mod.tail_bytes(bloco))          # prefixo original: já aplicado
    assert mod.apply(projeto, bloco) == "ja aplicado"


def test_falha_na_troca_nao_deixa_temporario(ambiente, capsys, monkeypatch):
    def quebra(origem, destino):
        raise OSError("falha simulada")

    monkeypatch.setattr(mod.os, "replace", quebra)
    recusa(ambiente, capsys, "falha simulada")


def test_recusa_projeto_ausente(ambiente, capsys):
    ambiente[0].unlink()
    codigo, out = aplicar(ambiente, capsys)
    assert codigo == 1 and out.startswith("RECUSADO")


def test_hash_antes_e_marcadores_fixos():
    fonte = _PATH.read_text(encoding="utf-8")
    assert 'HASH_ANTES = "854abcba89c21f4affe315898b71fe1160090efea5c8b19b13301845fd9a8cbb"' in fonte
    assert mod.START == "<!-- dia7-coleta3:start -->" and mod.END == "<!-- dia7-coleta3:end -->"
