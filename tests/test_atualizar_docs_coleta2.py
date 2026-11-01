"""Testes do registro do plano congelado da coleta 2 no PROJECT.md (Dia 6)."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_PATH = Path(__file__).resolve().parent.parent / "scripts" / "atualizar_docs_coleta2.py"
_spec = importlib.util.spec_from_file_location("atualizar_docs_coleta2", _PATH)
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)

ORIGINAL = "# Projeto\r\n\r\nTexto com acento: seção.\r\n".encode("utf-8")


@pytest.fixture
def doc(tmp_path):
    p = tmp_path / "PROJECT.md"
    p.write_bytes(ORIGINAL)
    return p


def antes() -> str:
    return mod.sha256(ORIGINAL)


def test_hash_antes_e_o_do_commit_a593273():
    assert mod.HASH_ANTES == "ee16e117b65d795b791587204733b252804d3221e8b8313b31d4845a97e211f4"


def test_aplica_no_fim_sem_tocar_no_original(doc):
    assert mod.apply(doc, antes()) == "aplicado"
    data = doc.read_bytes()
    assert data.startswith(ORIGINAL)
    assert data == ORIGINAL + b"\r\n" + mod.block_bytes()


def test_resultado_e_crlf_puro_e_termina_em_fim_de_linha(doc):
    mod.apply(doc, antes())
    data = doc.read_bytes()
    assert b"\n" not in data.replace(b"\r\n", b"") and data.endswith(b"\r\n")


def test_marcadores_uma_vez_cada(doc):
    mod.apply(doc, antes())
    text = doc.read_bytes().decode("utf-8")
    assert text.count(mod.START) == 1 and text.count(mod.END) == 1
    assert text.index(mod.START) < text.index(mod.END)


def test_segunda_execucao_nao_altera_o_arquivo(doc):
    mod.apply(doc, antes())
    first = doc.read_bytes()
    assert mod.apply(doc, antes()) == "ja aplicado"
    assert doc.read_bytes() == first


def test_hash_diferente_recusa_sem_gravar(doc):
    with pytest.raises(mod.Refused):
        mod.apply(doc, "0" * 64)
    assert doc.read_bytes() == ORIGINAL


def test_bloco_com_original_alterado_nao_conta_como_aplicado(doc):
    mod.apply(doc, antes())
    doc.write_bytes(b"x" + doc.read_bytes())
    before = doc.read_bytes()
    with pytest.raises(mod.Refused):
        mod.apply(doc, antes())
    assert doc.read_bytes() == before


@pytest.mark.parametrize("data", [
    b"# Projeto\n\nsem CRLF\n",
    b"# Projeto\r\nmisto\n",
    b"# Projeto\r\nsem fim de linha",
])
def test_formato_errado_recusa_sem_gravar(tmp_path, data):
    p = tmp_path / "PROJECT.md"
    p.write_bytes(data)
    with pytest.raises(mod.Refused):
        mod.apply(p, mod.sha256(data))
    assert p.read_bytes() == data


@pytest.mark.parametrize("marker", ["START", "END"])
def test_marcador_ja_existente_recusa_sem_gravar(tmp_path, marker):
    data = ("# Projeto\r\n" + getattr(mod, marker) + "\r\n").encode("utf-8")
    p = tmp_path / "PROJECT.md"
    p.write_bytes(data)
    with pytest.raises(mod.Refused):
        mod.apply(p, mod.sha256(data))
    assert p.read_bytes() == data


def test_nao_deixa_temporario_quando_a_troca_falha(doc, monkeypatch):
    def boom(src, dst):
        raise OSError("troca falhou")
    monkeypatch.setattr(mod.os, "replace", boom)
    with pytest.raises(OSError):
        mod.apply(doc, antes())
    assert doc.read_bytes() == ORIGINAL
    assert [p.name for p in doc.parent.iterdir()] == ["PROJECT.md"]


def test_main_recusa_com_codigo_1(doc, capsys):
    assert mod.main(doc) == 1
    assert "RECUSADO" in capsys.readouterr().out
    assert doc.read_bytes() == ORIGINAL


@pytest.mark.parametrize("trecho", [
    "Sessão:** `coleta2`",
    "9.616",
    "1.500.096 bits por job e 3.000.192 no total",
    "Reserva por job:** 20 s",
    "17:00 (-03:00) de 01/11/2026",
    "Saldo antes do envio: 583 s",
    "commit e82e081",
    "qubits 14, 21 e 138",
    "controles 121 e 131",
    "pares 112-113 e 130-131",
    "mesmo sinal e |z| > 2",
    "limiar 0,9",
    "mais de 15 s",
    "DEP_SESSAO",
])
def test_bloco_traz_os_parametros_congelados(trecho):
    assert trecho in mod.BLOCK


def test_bloco_sem_segredos_nem_rascunho():
    low = mod.BLOCK.lower()
    assert "ibm_quantum_token" not in low and "api_key" not in low
    for draft in ("todo", "xxx", "tbd", "???"):
        assert draft not in low
