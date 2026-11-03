"""Testes de scripts/e3_vazao_custo.py com o log de uso real e um motor falso."""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import math
import sys
from decimal import Decimal
from fractions import Fraction
from pathlib import Path

import numpy as np
import pytest

_CAMINHO = Path(__file__).resolve().parents[1] / "scripts" / "e3_vazao_custo.py"
_spec = importlib.util.spec_from_file_location("e3_vazao_custo", _CAMINHO)
e3 = importlib.util.module_from_spec(_spec)
sys.modules["e3_vazao_custo"] = e3
_spec.loader.exec_module(e3)

LOG = """ts,event,job_id,backend,qubits,shots,reserve_seconds,quantum_seconds,output_file,note
2026-11-01T11:22:15.627127+00:00,submitted,dbji1pgnceqs73ak2c8g,ibm_kingston,156,1000,20.0,,,session=cal
2026-11-01T14:30:26.492055+00:00,final,dbji1pgnceqs73ak2c8g,,,,,2.0,2026-11-01_ibm_kingston_cal_001.npy,status=DONE
2026-11-01T15:05:38.920518+00:00,submitted,dbjlaghkdqps7390qbq0,ibm_kingston,156,4000,14.0,,,session=cal
2026-11-01T15:09:16.861566+00:00,final,dbjlaghkdqps7390qbq0,,,,,3.0,2026-11-01_ibm_kingston_cal_002.npy,status=DONE
2026-11-01T15:17:53.324229+00:00,submitted,dbjlg80nceqs73ak89g0,ibm_kingston,156,9616,20.0,,,session=coleta1
2026-11-01T15:24:24.545280+00:00,final,dbjlg80nceqs73ak89g0,,,,,5.0,2026-11-01_ibm_kingston_coleta1_001.npy,status=DONE
2026-11-01T15:26:35.467110+00:00,submitted,dbjlkahffo6c73b9t1u0,ibm_kingston,156,9616,20.0,,,session=coleta1
2026-11-01T15:28:12.861337+00:00,final,dbjlkahffo6c73b9t1u0,,,,,5.0,2026-11-01_ibm_kingston_coleta1_002.npy,status=DONE
2026-11-01T20:24:39.469840+00:00,submitted,dbjq01pffo6c73ba4lo0,ibm_kingston,156,9616,20.0,,,session=coleta2
2026-11-01T20:32:06.815182+00:00,final,dbjq01pffo6c73ba4lo0,,,,,5.0,2026-11-01_ibm_kingston_coleta2_001.npy,status=DONE
2026-11-01T20:34:02.973616+00:00,submitted,dbjq4ehkdqps73912u30,ibm_kingston,156,9616,20.0,,,session=coleta2
2026-11-01T20:37:16.061782+00:00,final,dbjq4ehkdqps73912u30,,,,,5.0,2026-11-01_ibm_kingston_coleta2_002.npy,status=DONE
2026-11-02T20:22:41.516788+00:00,submitted,dbkf24d6p51s73cmg7ng,ibm_kingston,156,9616,20.0,,,session=coleta3
2026-11-02T20:23:49.403856+00:00,final,dbkf24d6p51s73cmg7ng,,,,,5.0,2026-11-02_ibm_kingston_coleta3_001.npy,status=DONE
2026-11-02T20:27:40.848320+00:00,submitted,dbkf4f1ffo6c73bbc8m0,ibm_kingston,156,9616,20.0,,,session=coleta3
2026-11-02T20:28:55.175062+00:00,final,dbkf4f1ffo6c73bbc8m0,,,,,5.0,2026-11-02_ibm_kingston_coleta3_002.npy,status=DONE
"""

H_QPU = {"coleta1": ("0.962254117749", "0.955501817198"),
         "coleta2": ("0.959768728725", "0.955301182366"),
         "coleta3": ("0.960593306672", "0.955903772587")}
H_OS = {"coleta1": ("0.97", "0.965"), "coleta2": ("0.966475886629", "0.966475886629"),
        "coleta3": ("0.962462823056", "0.968625290491")}


def ref_bits(n_input: int, h: float) -> int:
    """Referência independente: floor(2048 * H) - 128 por bloco de 2048 bits."""
    m = max(math.floor(Fraction(min(1.0, h)) * 2048) - 128, 0)
    return (n_input // 2048) * m


def fake_block_output_bits(h, n, eps):
    return max(math.floor(Fraction(h) * n) + 2 * eps, 0)


class Relogio:
    def __init__(self, tempos):
        self.tempos = list(tempos)
        self.chamadas = 0

    def __call__(self, n_bits):
        assert n_bits == e3.N_BITS_LOCAL
        self.chamadas += 1
        t = self.tempos.pop(0) if self.tempos else 0.1
        return {"t_s": t, "semente_gerada": True, "bits_extraidos": 1354932, "status_os": "mixed"}


def motor(tempos=(0.5, 0.10, 0.12, 0.11)):
    return e3.Motor(block_output_bits=fake_block_output_bits, extractor_entropy=lambda d, e: min(d, e),
                    n_extrator=2048, epsilon_log2=-64, h_declarada=1.0, executar_local=Relogio(tempos))


@pytest.fixture(autouse=True)
def poucas(monkeypatch):
    monkeypatch.setattr(e3, "REPS_LOCAL", 3)
    monkeypatch.setattr(e3, "REPS_MEDIR_TEMPO", 2)


def montar(raiz: Path, log: str = LOG, h_os=None, extra_saude=None) -> None:
    (raiz / "data" / "logs").mkdir(parents=True)
    (raiz / "data" / "raw").mkdir(parents=True)
    (raiz / "data" / "results").mkdir(parents=True)
    (raiz / "data" / "logs" / "qpu_usage.csv").write_text(log, encoding="utf-8")
    for l in csv.DictReader(log.splitlines()):
        if l["event"] == "final":
            nome_npy = l["output_file"]
            shots = 1000 if "_cal_001" in nome_npy else 4000 if "_cal_002" in nome_npy else 9616
            meta = {"n_bits": shots * 156, "params": {"job_id": l["job_id"], "shots": shots,
                    "circuit": "hadamard_all_measure", "rep_delay_seconds": 0.00025}}
            nome = l["output_file"][:-4] + ".json"
            (raiz / "data" / "raw" / nome).write_text(json.dumps(meta), encoding="utf-8")
    h_os = h_os or H_OS
    for sessao, nome in e3.SAUDE.items():
        linhas = ["fonte,lote,saude_approved,saude_h_estimated,ext_n_output_bits"]
        for i, h in enumerate(H_QPU[sessao], start=1):
            linhas.append(f"qpu_real,{i},False,{h},0")
        for i, h in enumerate(h_os[sessao], start=1):
            linhas.append(f"os,{i},True,{h},{ref_bits(1500096, float(h))}")
        linhas += (extra_saude or {}).get(sessao, [])
        (raiz / "data" / "results" / nome).write_text("\n".join(linhas) + "\n", encoding="utf-8")


def res_dict(raiz: Path) -> dict[str, str]:
    with (raiz / "data" / "results" / "e3_resumo.csv").open(encoding="utf-8", newline="") as f:
        return {r["metrica"]: r["valor"] for r in csv.DictReader(f)}


# ---------------------------------------------------------------- pré-registro
def test_pre_registro():
    fonte = _CAMINHO.read_text(encoding="utf-8")
    for trecho in (
        'PRECOS = (("pay_as_you_go", Decimal("96")), ("flex", Decimal("72")), ("premium", Decimal("48")))',
        'FONTE_PRECO = "https://www.ibm.com/quantum/pricing"', 'DATA_CONSULTA_PRECO = "2026-11-03"',
        "N_BITS_LOCAL = 1_500_096", "REPS_LOCAL = 20", 'RAZAO_MUITO = Decimal("10")',
        'CIRCUITO = "hadamard_all_measure"', "REP_DELAY_S = 0.00025", "MBIT = Decimal(1_000_000)",
        '"coleta1": "dia6_qpu_vs_sim_lotes.csv"',
    ):
        assert trecho in fonte, trecho


def test_formatacao():
    assert e3.dec("3.33312", 4) == "3.3331" and e3.dec(Decimal("56"), 2) == "56.00"
    assert e3.dec("0.00005", 4) == "0.0000"      # meio-par


# ---------------------------------------------------------------- QPU
def test_ler_log_pareia_os_8_jobs(tmp_path):
    montar(tmp_path)
    jobs = e3.ler_log(tmp_path)
    assert len(jobs) == 8
    assert [j["sessao"] for j in jobs].count("cal") == 2
    assert sum(j["quantum_seconds"] for j in jobs) == Decimal("35.0")
    assert jobs[0]["arquivo"] == "2026-11-01_ibm_kingston_cal_001.npy" and jobs[0]["shots"] == 1000


@pytest.mark.parametrize("troca,trecho", [
    (lambda t: t.replace("status=DONE", "status=ERROR", 1), "não terminou"),
    (lambda t: t.replace(",5.0,2026-11-02_ibm_kingston_coleta3_002.npy", ",x,2026-11-02_ibm_kingston_coleta3_002.npy"), "número inválido"),
    (lambda t: t.replace(",2.0,2026-11-01_ibm_kingston_cal_001", ",0,2026-11-01_ibm_kingston_cal_001"), "não positivos"),
    (lambda t: "\n".join(l for l in t.splitlines() if "coleta3_002.npy" not in l) + "\n", "sem par"),
    (lambda t: t + t.splitlines()[1] + "\n", "dois eventos"),
    (lambda t: t.replace("session=cal", "sessao=cal", 1), "sem sessão"),
    (lambda t: t.replace(",submitted,dbji1", ",enviado,dbji1", 1), "evento desconhecido"),
    (lambda t: t.splitlines()[0] + "\n", "sem jobs"),
])
def test_ler_log_recusa(tmp_path, troca, trecho):
    montar(tmp_path, log=troca(LOG))
    with pytest.raises(e3.E3Erro, match=trecho):
        e3.ler_log(tmp_path)


def test_ler_log_ausente(tmp_path):
    with pytest.raises(e3.E3Erro, match="ausente"):
        e3.ler_log(tmp_path)


@pytest.mark.parametrize("campo,valor,trecho", [
    ("job_id", "outro", "job_id"), ("shots", 9615, "shots"), ("circuit", "outro", "circuito"),
    ("rep_delay_seconds", 0.004, "rep_delay"), ("n_bits", 1, "n_bits"),
])
def test_conferir_cru_recusa(tmp_path, campo, valor, trecho):
    montar(tmp_path)
    p = tmp_path / "data" / "raw" / "2026-11-01_ibm_kingston_coleta2_001.json"
    m = json.loads(p.read_text())
    if campo == "n_bits":
        m["n_bits"] = valor
    else:
        m["params"][campo] = valor
    p.write_text(json.dumps(m))
    with pytest.raises(e3.E3Erro, match=trecho):
        e3.linhas_qpu(tmp_path, motor())


def test_conferir_cru_ausente_e_extensao(tmp_path):
    montar(tmp_path)
    (tmp_path / "data" / "raw" / "2026-11-01_ibm_kingston_cal_002.json").unlink()
    with pytest.raises(e3.E3Erro, match="JSON do cru ausente"):
        e3.linhas_qpu(tmp_path, motor())
    with pytest.raises(e3.E3Erro, match="inesperado"):
        e3.conferir_cru(tmp_path, {"arquivo": "x.bin"})


def test_linhas_qpu_valores(tmp_path):
    montar(tmp_path)
    ls = e3.linhas_qpu(tmp_path, motor())
    assert len(ls) == 8 and tuple(ls[0]) == e3.CAMPOS_QPU
    cal = ls[0]
    assert (cal["n_bits"], cal["quantum_seconds"], cal["custo_usd_payg"]) == ("156000", "2.0", "3.2000")
    assert cal["saude_aprovada"] == cal["bits_uteis"] == cal["bits_uteis_hipoteticos"] == ""
    c3 = next(l for l in ls if l["job_id"] == "dbkf4f1ffo6c73bbc8m0")
    assert (c3["bits_por_s"], c3["custo_usd_payg"]) == ("300019.2000", "8.0000")
    assert c3["custo_usd_por_mbit_payg"] == e3.dec(Decimal(8) / (Decimal(1500096) / 1000000))
    assert (c3["saude_aprovada"], c3["bits_uteis"], c3["h_estimada"]) == ("False", "0", "0.955903772587")
    assert c3["bits_uteis_hipoteticos"] == str(ref_bits(1500096, 0.955903772587))
    raw = (tmp_path / "data" / "raw" / "2026-11-02_ibm_kingston_coleta3_002.json").read_bytes()
    assert c3["json_sha256"] == hashlib.sha256(raw).hexdigest()


def test_lote_da_saude_vai_para_o_arquivo_certo(tmp_path):
    montar(tmp_path)
    ls = {l["job_id"]: l for l in e3.linhas_qpu(tmp_path, motor())}
    assert ls["dbjlg80nceqs73ak89g0"]["h_estimada"] == "0.962254117749"     # coleta1_001 = lote 1
    assert ls["dbjlkahffo6c73b9t1u0"]["h_estimada"] == "0.955501817198"     # coleta1_002 = lote 2


def test_bits_hipoteticos_respeita_h_declarada():
    m = e3.Motor(**{**motor().__dict__, "h_declarada": 0.5})
    assert e3.bits_hipoteticos(m, 4096 + 100, 0.9) == 2 * (1024 - 128)
    assert e3.bits_hipoteticos(motor(), 4096, 0.9) == 2 * (math.floor(Fraction(0.9) * 2048) - 128)


def test_lote_reprovado_nao_conta_bits_uteis(tmp_path):
    montar(tmp_path)
    p = tmp_path / "data" / "results" / "dia6_coleta2_qpu_vs_sim_lotes.csv"
    p.write_text(p.read_text().replace("qpu_real,1,False,0.959768728725,0", "qpu_real,1,False,0.959768728725,555"))
    ls = {l["job_id"]: l for l in e3.linhas_qpu(tmp_path, motor())}
    assert ls["dbjq01pffo6c73ba4lo0"]["bits_uteis"] == "0"


def test_hipotetico_indefinido_quando_nao_ha_rendimento(tmp_path, monkeypatch):
    monkeypatch.setattr(sys.modules[__name__], "H_QPU",
                        {k: ("0.05", "0.05") for k in H_QPU})
    r = resumo_de(tmp_path)
    assert r["coleta_bits_uteis_hipoteticos"] == "0"
    assert r["coleta_custo_por_mbit_util_hipotetico_pay_as_you_go"] == "indefinido"


def test_lote_aprovado_conta_bits_uteis(tmp_path):
    montar(tmp_path)
    p = tmp_path / "data" / "results" / "dia6_coleta2_qpu_vs_sim_lotes.csv"
    p.write_text(p.read_text().replace("qpu_real,1,False,0.959768728725,0", "qpu_real,1,True,0.959768728725,777"))
    ls = {l["job_id"]: l for l in e3.linhas_qpu(tmp_path, motor())}
    assert ls["dbjq01pffo6c73ba4lo0"]["bits_uteis"] == "777"


def test_formula_do_extrator_conferida_na_os(tmp_path):
    montar(tmp_path)
    p = tmp_path / "data" / "results" / "dia6_coleta3_qpu_vs_sim_lotes.csv"
    p.write_text(p.read_text().replace(f",{ref_bits(1500096, 0.962462823056)}\n", ",1349077\n"))
    with pytest.raises(e3.E3Erro, match="fórmula do extrator"):
        e3.linhas_qpu(tmp_path, motor())


@pytest.mark.parametrize("sessao,acao,trecho", [
    ("coleta2", "sem_os", "sem lote aprovado da os"),
    ("coleta2", "sem_qpu", "sem linhas qpu_real"),
    ("coleta1", "tres_qpu", "3 lotes qpu_real"),
    ("coleta3", "ausente", "CSV de saúde ausente"),
    ("coleta1", "aprovada_invalida", "saude_approved"),
])
def test_saude_recusa(tmp_path, sessao, acao, trecho):
    montar(tmp_path)
    p = tmp_path / "data" / "results" / e3.SAUDE[sessao]
    linhas = p.read_text().splitlines()
    if acao == "sem_os":
        linhas = [l for l in linhas if not l.startswith("os,")]
    elif acao == "sem_qpu":
        linhas = [l for l in linhas if not l.startswith("qpu_real,")]
    elif acao == "tres_qpu":
        linhas.append("qpu_real,3,False,0.95,0")
    elif acao == "aprovada_invalida":
        linhas = [l.replace("qpu_real,1,False", "qpu_real,1,talvez") for l in linhas]
    if acao == "ausente":
        p.unlink()
    else:
        p.write_text("\n".join(linhas) + "\n")
    with pytest.raises(e3.E3Erro, match=trecho):
        e3.linhas_qpu(tmp_path, motor())


# ---------------------------------------------------------------- local
def test_linhas_local_descarta_aquecimento():
    m = motor((9.9, 0.10, 0.12, 0.11))
    ls = e3.linhas_local(m, 3, "c" * 40)
    assert [l["t_s"] for l in ls] == ["0.100000", "0.120000", "0.110000"]
    assert m.executar_local.chamadas == 4 and tuple(ls[0]) == e3.CAMPOS_LOCAL
    assert {l["commit"] for l in ls} == {"c" * 40}


def test_linhas_local_recusa_sem_semente():
    def ruim(n):
        return {"t_s": 0.1, "semente_gerada": False, "bits_extraidos": 0, "status_os": "excluded"}

    m = e3.Motor(**{**motor().__dict__, "executar_local": ruim})
    with pytest.raises(e3.E3Erro, match="sem semente"):
        e3.linhas_local(m, 1, "c")


# ---------------------------------------------------------------- resumo
def resumo_de(tmp_path, tempos=(0.5, 0.10, 0.12, 0.11)):
    montar(tmp_path)
    m = motor(tempos)
    return {r["metrica"]: r["valor"] for r in e3.resumir(e3.linhas_qpu(tmp_path, m),
                                                          e3.linhas_local(m, 3, "c" * 40))}


def test_resumo_qpu(tmp_path):
    r = resumo_de(tmp_path)
    assert (r["qpu_jobs"], r["qpu_segundos"], r["qpu_bits_brutos"]) == ("8", "35.0", "9780576")
    assert (r["qpu_custo_pay_as_you_go"], r["qpu_custo_flex"], r["qpu_custo_premium"]) == ("56.00", "42.00", "28.00")
    assert (r["coleta_jobs"], r["coleta_segundos"], r["coleta_bits_brutos"]) == ("6", "30.0", "9000576")
    assert r["coleta_bits_por_s"] == "300019.2000"
    mb = Decimal(9000576) / 1000000
    assert r["coleta_s_por_mbit_bruto"] == e3.dec(Decimal(30) / mb)
    assert r["coleta_custo_por_mbit_bruto_pay_as_you_go"] == e3.dec(Decimal(48) / mb) == "5.3330"
    assert r["coleta_custo_por_mbit_bruto_flex"] == e3.dec(Decimal(36) / mb)
    assert r["coleta_custo_por_mbit_bruto_premium"] == e3.dec(Decimal(24) / mb)
    assert r["preco_fonte"] == e3.FONTE_PRECO and r["preco_data_consulta"] == "2026-11-03"


def test_resumo_ajuste_contra_numpy(tmp_path):
    r = resumo_de(tmp_path)
    b, a = np.polyfit([1000, 4000] + [9616] * 6, [2, 3] + [5] * 6, 1)
    assert float(r["ajuste_fixo_s"]) == pytest.approx(a, abs=1e-4)
    assert float(r["ajuste_por_shot_s"]) == pytest.approx(b, abs=1e-8)
    assert float(r["ajuste_custo_marginal_por_mbit_pay_as_you_go"]) == pytest.approx(b / 156 * 1e6 * 1.6, abs=1e-3)


def test_resumo_util_indefinido_e_hipotetico(tmp_path):
    r = resumo_de(tmp_path)
    assert (r["coleta_lotes_aprovados"], r["coleta_bits_uteis"]) == ("0", "0")
    assert r["coleta_custo_por_mbit_util_pay_as_you_go"] == "indefinido"
    hip = sum(ref_bits(1500096, float(h)) for hs in H_QPU.values() for h in hs)
    assert r["coleta_bits_uteis_hipoteticos"] == str(hip)
    assert r["coleta_custo_por_mbit_util_hipotetico_pay_as_you_go"] == e3.dec(Decimal(48) / (Decimal(hip) / 1000000))


def test_resumo_local_e_criterio(tmp_path):
    r = resumo_de(tmp_path, tempos=(0.5, 0.10, 0.30, 0.11))   # média 0,17; mediana 0,11
    assert (r["local_execucoes"], r["local_t_mediana_s"]) == ("3", "0.110000")
    assert (r["local_t_min_s"], r["local_t_max_s"]) == ("0.100000", "0.300000")
    lmb = Decimal(1500096) / 1000000
    assert r["local_s_por_mbit_bruto"] == e3.dec(Decimal("0.11") / lmb, 6)
    assert r["local_bits_por_s"] == e3.dec(Decimal(1500096) / Decimal("0.11"))
    razao = (Decimal(30) / (Decimal(9000576) / 1000000)) / (Decimal("0.11") / lmb)
    assert r["razao_s_por_mbit_qpu_sobre_os"] == e3.dec(razao, 2)
    assert r["criterio_muito_mais_caro"] == "True" and r["criterio_limiar"] == "10"


def test_resumo_bits_extraidos_mediana(tmp_path):
    montar(tmp_path)
    m = motor()
    qpu, local = e3.linhas_qpu(tmp_path, m), e3.linhas_local(m, 3, "c")
    for l, b in zip(local, ("100", "300", "200")):
        l["bits_extraidos"] = b
    r = {x["metrica"]: x["valor"] for x in e3.resumir(qpu, local)}
    assert r["local_bits_extraidos_mediana"] == "200"


def test_criterio_falso_quando_a_os_e_lenta(tmp_path):
    r = resumo_de(tmp_path, tempos=(1, 1.0, 1.0, 1.0))
    assert r["criterio_muito_mais_caro"] == "False"       # razão ~ 5


def test_criterio_no_limiar(tmp_path, monkeypatch):
    r = resumo_de(tmp_path, tempos=(1, 0.5, 0.5, 0.5))
    razao = Decimal(r["razao_s_por_mbit_qpu_sobre_os"])
    monkeypatch.setattr(e3, "RAZAO_MUITO", razao)
    montar_dir = tmp_path / "b"
    montar_dir.mkdir()
    r2 = resumo_de(montar_dir, tempos=(1, 0.5, 0.5, 0.5))
    assert r2["criterio_muito_mais_caro"] == "True"         # >= (empate conta)


def test_resumo_recusa(tmp_path):
    montar(tmp_path)
    m = motor()
    qpu, local = e3.linhas_qpu(tmp_path, m), e3.linhas_local(m, 3, "c")
    with pytest.raises(e3.E3Erro):
        e3.resumir([], local)
    with pytest.raises(e3.E3Erro, match="schema da QPU"):
        e3.resumir([dict(qpu[0], schema="x")] + qpu[1:], local)
    with pytest.raises(e3.E3Erro, match="schema local"):
        e3.resumir(qpu, [dict(local[0], schema="x")])
    with pytest.raises(e3.E3Erro, match="nenhum job de coleta"):
        e3.resumir([l for l in qpu if l["sessao"] == "cal"], local)
    with pytest.raises(e3.E3Erro, match="tamanhos diferentes"):
        e3.resumir(qpu, [dict(local[0], n_bits="10")] + local[1:])
    with pytest.raises(e3.E3Erro, match="qubits"):
        e3.resumir([dict(qpu[0], qubits="127")] + qpu[1:], local)
    with pytest.raises(e3.E3Erro, match="sem dado de saúde"):
        e3.resumir([dict(l, bits_uteis="") if l["sessao"] == "coleta1" else l for l in qpu], local)


def test_ajuste_sem_variacao():
    with pytest.raises(e3.E3Erro, match="mesmo número de shots"):
        e3.ajuste([Decimal(5), Decimal(5)], [Decimal(1), Decimal(2)])


# ---------------------------------------------------------------- main
def _main(tmp_path, *args, limpo=True, m=None):
    saida: list[str] = []
    codigo = e3.main(list(args), raiz=tmp_path, motor=m or motor(), git=lambda r: ("f" * 40, limpo),
                     saida=saida.append)
    return codigo, saida


def test_rodar_grava_os_tres(tmp_path):
    montar(tmp_path)
    codigo, saida = _main(tmp_path, "--rodar")
    assert codigo == 0, saida
    pasta = tmp_path / "data" / "results"
    for nome in ("e3_qpu.csv", "e3_local.csv", "e3_resumo.csv"):
        dados = (pasta / nome).read_bytes()
        assert f"{nome}: {hashlib.sha256(dados).hexdigest()}" in saida and b"\r\n" not in dados
    assert len(e3.ler_csv(pasta / "e3_qpu.csv", e3.CAMPOS_QPU)) == 8
    loc = e3.ler_csv(pasta / "e3_local.csv", e3.CAMPOS_LOCAL)
    assert len(loc) == 3 and {l["commit"] for l in loc} == {"f" * 40}
    assert res_dict(tmp_path)["criterio_muito_mais_caro"] == "True"
    assert not list(pasta.glob("*.tmp"))


def test_rodar_recusa_arvore_suja(tmp_path):
    montar(tmp_path)
    codigo, saida = _main(tmp_path, "--rodar", limpo=False)
    assert codigo == 1 and "RECUSADO" in saida[-1]
    assert not (tmp_path / "data" / "results" / "e3_qpu.csv").exists()


@pytest.mark.parametrize("nome", ["e3_qpu.csv", "e3_local.csv", "e3_resumo.csv"])
def test_rodar_recusa_se_saida_existe(tmp_path, nome):
    montar(tmp_path)
    (tmp_path / "data" / "results" / nome).write_bytes(b"x")
    m = motor()
    codigo, saida = _main(tmp_path, "--rodar", m=m)
    assert codigo == 1 and "já existe" in saida[-1] and m.executar_local.chamadas == 0
    assert sorted(p.name for p in (tmp_path / "data" / "results").glob("e3_*")) == [nome]


def test_gravar_novo_nao_sobrescreve(tmp_path):
    alvo = tmp_path / "a.csv"
    e3.gravar_novo(alvo, b"um")
    with pytest.raises(e3.E3Erro, match="já existe"):
        e3.gravar_novo(alvo, b"dois")
    assert alvo.read_bytes() == b"um"


def test_resumir_idempotente_e_recusa(tmp_path):
    montar(tmp_path)
    assert _main(tmp_path, "--rodar")[0] == 0
    p = tmp_path / "data" / "results" / "e3_resumo.csv"
    codigo, saida = _main(tmp_path, "--resumir")
    assert codigo == 0 and "já existia igual" in saida[-1]
    p.write_bytes(b"outro")
    codigo, saida = _main(tmp_path, "--resumir")
    assert codigo == 1 and "difere" in saida[-1] and p.read_bytes() == b"outro"
    p.unlink()
    assert _main(tmp_path, "--resumir")[0] == 0


def test_resumir_recusa_cabecalho(tmp_path):
    montar(tmp_path)
    assert _main(tmp_path, "--rodar")[0] == 0
    q = tmp_path / "data" / "results" / "e3_local.csv"
    q.write_bytes(q.read_bytes().replace(b"t_s", b"tempo", 1))
    codigo, saida = _main(tmp_path, "--resumir")
    assert codigo == 1 and "cabeçalho" in saida[-1]
    (tmp_path / "data" / "results" / "e3_qpu.csv").unlink()
    codigo, saida = _main(tmp_path, "--resumir")
    assert codigo == 1 and "não existe" in saida[-1]


def test_medir_tempo_nao_grava_nem_calcula_razao(tmp_path):
    montar(tmp_path)
    m = motor((0.5, 0.2, 0.4))
    codigo, saida = _main(tmp_path, "--medir-tempo", m=m)
    assert codigo == 0 and m.executar_local.chamadas == 3
    assert not list((tmp_path / "data" / "results").glob("e3_*"))
    texto = "\n".join(saida).lower()
    assert "0.300 s em média" in texto and "4 execuções" in texto
    for proibido in ("razão =", "true", "false", "usd", "custo"):
        assert proibido not in texto


def test_modos_exclusivos(tmp_path):
    with pytest.raises(SystemExit):
        _main(tmp_path, "--rodar", "--resumir")
    with pytest.raises(SystemExit):
        _main(tmp_path)
