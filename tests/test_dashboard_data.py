"""Testes do painel (Dia 8): funções de carga e o app rodando sem exceção nos dados reais."""
import json
import shutil

import pandas as pd
import pytest

from dashboard import data

REAL = data.RESULTS.is_dir() and (data.RESULTS / "consolidado_gate.csv").is_file()
real = pytest.mark.skipif(not REAL, reason="data/results real ausente")


def test_read_arquivo_ausente_levanta(tmp_path):
    with pytest.raises(FileNotFoundError, match="ausente"):
        data.e2(tmp_path)


def test_last_receipt_sem_log_e_log_vazio(tmp_path):
    with pytest.raises(FileNotFoundError):
        data.last_receipt(tmp_path)
    (tmp_path / "chain.jsonl").write_bytes(b"")
    with pytest.raises(FileNotFoundError, match="vazia"):
        data.last_receipt(tmp_path)


def test_last_receipt_pega_a_ultima_linha(tmp_path):
    linhas = [{"receipt_id": "a"}, {"receipt_id": "b"}]
    (tmp_path / "chain.jsonl").write_bytes(b"".join(json.dumps(x).encode() + b"\n" for x in linhas))
    v = data.last_receipt(tmp_path)
    assert v.receipt["receipt_id"] == "b" and v.position == 2 and v.chain_length == 2


def test_receipt_sources_junta_motivos():
    r = {"sources": [{"source_id": "x", "source_type": "t", "status": "excluded", "approved": False, "reasons": ["a", "b"]}]}
    df = data.receipt_sources(r)
    assert df.loc[0, "Motivos"] == "a; b" and not df.loc[0, "Aprovada"]
    assert data.receipt_sources({}).empty


def test_min_entropia_exige_limiar_unico():
    df = pd.DataFrame({"coleta": [1, 1], "fonte": ["os", "os"], "lote": [1, 2],
                       "saude_h_estimated": [0.96, 0.97], "saude_h_threshold": [0.9, 0.8]})
    with pytest.raises(ValueError, match="não é único"):
        data.min_entropia(df)


def test_resolve_receipts_usa_a_real_so_com_log_e_chave(tmp_path):
    rec, keys, demo_r, demo_k = tmp_path / "r", tmp_path / "k", tmp_path / "dr", tmp_path / "dk"
    assert data.resolve_receipts(rec, keys, demo_r, demo_k) == (demo_r, demo_k, True)  # nada existe
    rec.mkdir(); keys.mkdir()
    (rec / "chain.jsonl").write_bytes(b"{}" + bytes([10]))
    assert data.resolve_receipts(rec, keys, demo_r, demo_k)[2] is True  # log sem chave pública
    (keys / "issuer_ml_dsa_65.pk").write_bytes(b"x")
    assert data.resolve_receipts(rec, keys, demo_r, demo_k) == (rec, keys, False)
    (rec / "chain.jsonl").write_bytes(b"")
    assert data.resolve_receipts(rec, keys, demo_r, demo_k)[2] is True  # log vazio


def test_cadeia_de_demonstracao_verifica():
    v = data.verify_last(data.DEMO_RECEIPTS, data.DEMO_KEYS)
    assert v.ok and v.chain_length == 3


@real
def test_lotes_reais_batem_com_o_consolidado():
    lotes = data.load_lotes()
    assert len(lotes) == 18 and set(lotes["coleta"]) == {1, 2, 3}
    r = data.fontes_resumo(lotes).set_index("Fonte")
    assert r.loc["Sistema operacional", "Aprovados"] == 6
    assert r.loc["QPU real (ibm_kingston)", "Aprovados"] == 0
    assert r.loc["Simulador com ruído", "Simulada"] == "sim"
    assert r.loc["Simulador com ruído", "Lotes distintos"] == 2  # semente fixa: os mesmos 2 lotes nas 3 coletas
    assert r.loc["QPU real (ibm_kingston)", "Lotes distintos"] == 6
    h, limiar = data.min_entropia(lotes)
    assert limiar == 0.9 and h["h_estimada"].between(0.9, 1).all()


@real
def test_saude_por_lote_tem_reprovacao_com_motivo():
    s = data.saude_por_lote(data.load_lotes())
    reprov = s[~s["Aprovado"]]
    assert len(reprov) == 12 and (reprov["Motivo"] != "").all()


@real
def test_vies_e_deriva_reais():
    for c in (1, 2, 3):
        q = data.vies_por_qubit(c)
        assert set(q["fonte"]) >= {"qpu_real", "simulador"} and q["p1"].between(0, 1).all()
    d = data.deriva_resumo()
    assert set(d["comparacao"]) == {"mesmo_dia", "coleta2_vs_coleta1", "coleta3_vs_coleta1"}


@real
def test_gate_tem_os_5_experimentos():
    assert list(data.experimentos_gate()["experimento"]) == ["E1", "E2", "E3", "E4", "E5"]


@pytest.mark.skipif(not (data.RECEIPTS / "chain.jsonl").is_file(), reason="cadeia real ausente")
def test_verifica_cadeia_real_e_detecta_adulteracao(tmp_path):
    assert data.verify_last().ok
    copia = tmp_path / "receipts"
    shutil.copytree(data.RECEIPTS, copia)
    log = copia / "chain.jsonl"
    log.write_bytes(log.read_bytes().replace(b'"mode":"keygen"', b'"mode":"keygeX"', 1))
    v = data.verify_last(copia)
    assert not v.ok and v.reasons


@real
def test_app_roda_sem_excecao():
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(str(data.ROOT / "dashboard" / "app.py"), default_timeout=120).run()
    assert not at.exception, [e.value for e in at.exception]
    assert not at.error
    assert len(at.dataframe) >= 6
    at.button[0].click().run()
    assert not at.exception and len(at.success) == 1
