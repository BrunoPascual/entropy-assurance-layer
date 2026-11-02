"""Testes de scripts/atualizar_docs_coleta3.py (plano congelado da coleta 3, Dia 7)."""
from __future__ import annotations

import hashlib
import importlib.util
import sys
from pathlib import Path

import pytest

_PATH = Path(__file__).resolve().parent.parent / "scripts" / "atualizar_docs_coleta3.py"
_spec = importlib.util.spec_from_file_location("_atualizar_docs_coleta3", _PATH)
mod = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = mod
_spec.loader.exec_module(mod)

BASE = b"# Projeto\r\n\r\ntexto\r\n<!-- coleta2-plano:start -->\r\nx\r\n<!-- coleta2-plano:end -->\r\n"


@pytest.fixture
def ambiente(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "PROJECT.md").write_bytes(BASE)
    monkeypatch.setattr(mod, "HASH_ANTES", hashlib.sha256(BASE).hexdigest())
    return tmp_path


def rodar(capsys) -> tuple[int, str]:
    codigo = mod.main()
    return codigo, capsys.readouterr().out


def arquivos(raiz: Path) -> dict[str, bytes]:
    return {p.name: p.read_bytes() for p in raiz.iterdir() if p.is_file()}


def test_aplica_no_fim_sem_mexer_no_resto(ambiente, capsys):
    codigo, out = rodar(capsys)
    dados = (ambiente / "PROJECT.md").read_bytes()
    assert codigo == 0 and out.startswith("aplicado; PROJECT.md: ")
    assert hashlib.sha256(dados).hexdigest() in out
    assert dados == BASE + b"\r\n" + mod.block_bytes()
    assert dados.endswith(mod.END.encode() + b"\r\n")
    assert dados.count(b"\n") == dados.count(b"\r\n")
    assert sorted(arquivos(ambiente)) == ["PROJECT.md"]


def test_idempotente(ambiente, capsys):
    rodar(capsys)
    antes = (ambiente / "PROJECT.md").read_bytes()
    codigo, out = rodar(capsys)
    assert codigo == 0 and out.startswith("já aplicado")
    assert (ambiente / "PROJECT.md").read_bytes() == antes


def recusa(ambiente, capsys, trecho: str):
    antes = arquivos(ambiente)
    codigo, out = rodar(capsys)
    assert codigo == 1 and out.startswith("RECUSADO") and trecho in out, out
    assert arquivos(ambiente) == antes


def test_recusa_hash_diferente(ambiente, capsys, monkeypatch):
    monkeypatch.setattr(mod, "HASH_ANTES", "0" * 64)
    recusa(ambiente, capsys, "difere de HASH_ANTES")


@pytest.mark.parametrize("marcador", ["START", "END"])
def test_recusa_marcador_existente(ambiente, capsys, monkeypatch, marcador):
    dados = BASE + getattr(mod, marcador).encode() + b"\r\n"
    (ambiente / "PROJECT.md").write_bytes(dados)
    monkeypatch.setattr(mod, "HASH_ANTES", hashlib.sha256(dados).hexdigest())
    recusa(ambiente, capsys, "já existe")


@pytest.mark.parametrize("dados", [BASE.replace(b"\r\n", b"\n"), BASE + b"solto\n",
                                   BASE + b"cr\rsolto\r\n"])
def test_recusa_nao_crlf(ambiente, capsys, monkeypatch, dados):
    (ambiente / "PROJECT.md").write_bytes(dados)
    monkeypatch.setattr(mod, "HASH_ANTES", hashlib.sha256(dados).hexdigest())
    recusa(ambiente, capsys, "CRLF puro")


def test_recusa_sem_fim_de_linha(ambiente, capsys, monkeypatch):
    dados = BASE + b"fim"
    (ambiente / "PROJECT.md").write_bytes(dados)
    monkeypatch.setattr(mod, "HASH_ANTES", hashlib.sha256(dados).hexdigest())
    recusa(ambiente, capsys, "fim de linha")


def test_recusa_arquivo_ausente(ambiente, capsys):
    (ambiente / "PROJECT.md").unlink()
    codigo, out = rodar(capsys)
    assert codigo == 1 and "arquivo ausente" in out


def test_ja_aplicado_exige_o_prefixo_original(ambiente, capsys):
    dados = BASE + b"editado\r\n" + mod.tail()
    (ambiente / "PROJECT.md").write_bytes(dados)
    recusa(ambiente, capsys, "já existe")
    assert not mod.ja_aplicado(dados)
    assert mod.ja_aplicado(BASE + mod.tail())


def test_bloco_tem_os_parametros_do_plano():
    b = mod.BLOCK
    assert b.startswith(mod.START + "\n") and b.endswith(mod.END + "\n")
    for trecho in (
        "Registrado em 02/11/2026 sobre o commit 01666ec.",
        "- **Sessão:** `coleta3`.",
        "- **Jobs:** 2, enviados um de cada vez.",
        "- **Shots por job:** 9.616, o que dá 1.500.096 bits por job e 3.000.192 no total.",
        "- **Reserva por job:** 20 s.",
        "entre 17:00 e 20:00 (-03:00) de 02/11/2026",
        "este plano não vale e é refeito",
        "parar se o primeiro job usar mais de 15 s",
        "qubits 14, 21 e 138; controles 121 e 131; pares 112-113 e 130-131",
        "análise principal: contra a coleta 1, com `analisar_deriva.py --sessao coleta3`",
        "mistura o dia com a hora do dia",
        "análise secundária, opcional: contra a coleta 2",
        "Se não for feita, o registro diz que não foi feita",
        "limiar 0,9",
    ):
        assert trecho in b, trecho
    assert "\r" not in b


def test_hash_antes_e_marcadores_fixos():
    assert mod.HASH_ANTES == "ec6847c6dd4ac0874f9566c8f154fc6925da10bc790dd961fd9ceba54f320d01"
    assert mod.START == "<!-- coleta3-plano:start -->"
    assert mod.END == "<!-- coleta3-plano:end -->"
