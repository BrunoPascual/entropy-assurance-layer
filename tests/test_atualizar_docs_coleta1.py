"""Testes de scripts/atualizar_docs_coleta1.py (Dia 6, R4: plano congelado da coleta 1).

Usam um PROJECT.md sintético em pasta temporária, com os hashes passados explicitamente; o
arquivo real só é tocado pela execução do script, que confere os hashes reais.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "atualizar_docs_coleta1",
    Path(__file__).resolve().parents[1] / "scripts" / "atualizar_docs_coleta1.py")
mod = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(mod)

BASE = "# Projeto\r\n\r\nLinha com acentuação.\r\n## 18. Dia 6\r\nÚltima linha.\r\n".encode("utf-8")


def hashes(base: bytes = BASE) -> tuple[str, str]:
    return mod.sha256(base), mod.sha256(mod.build(base))


@pytest.fixture
def doc(tmp_path):
    path = tmp_path / "PROJECT.md"
    path.write_bytes(BASE)
    return path


def test_aplica_e_acrescenta_so_ao_fim(doc):
    antes, depois = hashes()
    assert mod.apply(doc, antes, depois) == "aplicado"
    new = doc.read_bytes()
    assert new.startswith(BASE) and mod.sha256(new) == depois
    assert new[len(BASE):] == b"\r\n" + mod.block_bytes()


def test_resultado_e_crlf_puro_e_termina_em_fim_de_linha(doc):
    mod.apply(doc, *hashes())
    rest = doc.read_bytes().replace(b"\r\n", b"")
    assert b"\n" not in rest and b"\r" not in rest
    assert doc.read_bytes().endswith(mod.END.encode() + b"\r\n")


def test_bloco_tem_marcadores_uma_vez_e_linhas_em_branco(doc):
    mod.apply(doc, *hashes())
    text = doc.read_bytes().decode("utf-8")
    assert text.count(mod.START) == 1 and text.count(mod.END) == 1
    assert "\r\n\r\n" + mod.START in text
    assert "envio)\r\n\r\nRegistrado" in text and "(seção 6.5).\r\n\r\n- **Backend:**" in text


def test_idempotente_segunda_execucao_nao_grava(doc):
    antes, depois = hashes()
    mod.apply(doc, antes, depois)
    first = doc.read_bytes()
    mtime = doc.stat().st_mtime_ns
    assert mod.apply(doc, antes, depois) == "ja aplicado"
    assert doc.read_bytes() == first and doc.stat().st_mtime_ns == mtime


def test_recusa_hash_diferente_sem_gravar(doc):
    _, depois = hashes()
    with pytest.raises(mod.Refused, match="difere do esperado"):
        mod.apply(doc, "0" * 64, depois)
    assert doc.read_bytes() == BASE


def test_recusa_se_o_resultado_nao_tiver_o_hash_esperado(doc):
    antes, _ = hashes()
    with pytest.raises(mod.Refused, match="resultado teria"):
        mod.apply(doc, antes, "f" * 64)
    assert doc.read_bytes() == BASE


@pytest.mark.parametrize("marker", ["START", "END"])
def test_recusa_marcador_ja_existente(tmp_path, marker):
    base = BASE + getattr(mod, marker).encode() + b"\r\n"
    path = tmp_path / "PROJECT.md"
    path.write_bytes(base)
    with pytest.raises(mod.Refused, match="já existe"):
        mod.apply(path, mod.sha256(base), "f" * 64)
    assert path.read_bytes() == base


@pytest.mark.parametrize("base", [
    b"# so LF\nlinha\n",
    b"# misto\r\nlinha\n",
    b"# CR solto\r\nlin\rha\r\n",
    b"# sem fim de linha no final\r\nlinha",
])
def test_recusa_fim_de_linha_errado(tmp_path, base):
    path = tmp_path / "PROJECT.md"
    path.write_bytes(base)
    with pytest.raises(mod.Refused):
        mod.apply(path, mod.sha256(base), "f" * 64)
    assert path.read_bytes() == base


def test_nao_deixa_arquivo_temporario(doc):
    mod.apply(doc, *hashes())
    assert sorted(p.name for p in doc.parent.iterdir()) == ["PROJECT.md"]


def test_nao_deixa_temporario_quando_a_troca_falha(doc, monkeypatch):
    def boom(src, dst):
        raise OSError("troca falhou")
    monkeypatch.setattr(mod.os, "replace", boom)
    with pytest.raises(OSError):
        mod.apply(doc, *hashes())
    assert doc.read_bytes() == BASE
    assert sorted(p.name for p in doc.parent.iterdir()) == ["PROJECT.md"]


def test_main_recusa_com_codigo_1_e_mensagem(doc, capsys):
    assert mod.main(doc) == 1
    assert "RECUSADO (nada foi gravado)" in capsys.readouterr().out
    assert doc.read_bytes() == BASE


def test_main_arquivo_ausente_recusa(tmp_path, capsys):
    assert mod.main(tmp_path / "nao_existe.md") == 1
    assert "RECUSADO" in capsys.readouterr().out


def test_constantes_do_plano_aprovado():
    text = mod.BLOCK
    for trecho in ("ibm_kingston", "os 156 operacionais, todos", "`coleta1`", "**Jobs:** 2",
                   "9.616", "1.500.096", "3.000.192", "**Reserva por job:** 20 s",
                   "mais de 15 s", "dca8fb6", "780.000 bits", "0,00025 s"):
        assert trecho in text, trecho
    assert mod.HASH_ANTES == "b7284816dda2796c7fc418f17de620a01a0fc41760a6b1bc0133b2d5ba64c4fa"
    assert len(mod.HASH_DEPOIS) == 64 and mod.HASH_DEPOIS != mod.HASH_ANTES


def test_numeros_do_plano_batem_com_a_conta():
    shots, qubits, jobs = 9616, 156, 2
    assert shots * qubits == 1_500_096 and shots * qubits * jobs == 3_000_192
    assert (1_000 + 4_000) * qubits == 780_000
    fixo, por_shot = 5 / 3, 1 / 3000  # reta pelos pontos (1000, 2 s) e (4000, 3 s)
    assert round(fixo + por_shot * shots, 1) == 4.9
    pior = 3.5 + (3.5 - 1.5) / 3000 * (shots - 4000)  # +-0,5 s em cada ponto
    assert round(pior, 1) == 7.2 and pior < 20 and 15 >= 3 * 4.9
    assert "cerca de 7,2 s por job" in mod.BLOCK
