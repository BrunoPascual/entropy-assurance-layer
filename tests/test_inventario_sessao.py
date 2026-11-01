"""DEP_SESSAO, passo 1: inventario_coleta1.py com --sessao (padrão coleta1)."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_PATH = Path(__file__).resolve().parent.parent / "scripts" / "inventario_coleta1.py"
_spec = importlib.util.spec_from_file_location("_inventario_sessao", _PATH)
mod = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = mod  # o @dataclass do módulo exige isso
_spec.loader.exec_module(mod)


def test_padrao_continua_coleta1_e_o_nome_de_sempre():
    assert mod.SESSION == "coleta1"
    assert mod.OUT_PATH == Path("data/results/dia6_coleta1_inventario.csv")
    assert mod.out_path_for("coleta1") == mod.OUT_PATH


def test_nome_da_saida_vem_da_sessao():
    assert mod.out_path_for("coleta2") == Path("data/results/dia6_coleta2_inventario.csv")


@pytest.mark.parametrize("session", ["coleta1", "coleta2", "cal", "C3"])
def test_sessao_valida(session):
    assert mod.check_session(session) == session


@pytest.mark.parametrize("session", ["", "coleta_2", "../x", "a*", "col eta", "coleta2\n",
                                     "seção", None, 2])
def test_sessao_invalida_recusa(session):
    with pytest.raises(mod.InventoryError):
        mod.check_session(session)


@pytest.fixture
def calls(monkeypatch):
    seen: dict = {}

    def fake_build(raw_dir, log_path, session=mod.SESSION):
        seen["build"] = (raw_dir, log_path, session)
        return []

    def fake_write(out_path, data):
        seen["write"] = out_path
        return "gravado"

    monkeypatch.setattr(mod, "build_rows", fake_build)
    monkeypatch.setattr(mod, "write", fake_write)
    return seen


def test_main_repassa_a_sessao_e_deriva_a_saida(calls, tmp_path):
    assert mod.main(tmp_path, tmp_path / "log.csv", session="coleta2") == 0
    assert calls["build"] == (tmp_path, tmp_path / "log.csv", "coleta2")
    assert calls["write"] == mod.out_path_for("coleta2")


def test_main_padrao_usa_coleta1_e_out_path(calls, tmp_path):
    assert mod.main(tmp_path, tmp_path / "log.csv") == 0
    assert calls["build"][2] == "coleta1"
    assert calls["write"] == mod.OUT_PATH


def test_out_path_explicito_prevalece(calls, tmp_path):
    out = tmp_path / "x.csv"
    assert mod.main(tmp_path, tmp_path / "log.csv", out, session="coleta2") == 0
    assert calls["write"] == out


def test_main_sessao_invalida_recusa_sem_ler_nada(calls, tmp_path, capsys):
    assert mod.main(tmp_path, tmp_path / "log.csv", session="../x") == 1
    assert "build" not in calls and "write" not in calls
    assert "RECUSADO" in capsys.readouterr().out


@pytest.mark.parametrize("argv, expected", [([], "coleta1"), (["--sessao", "coleta2"], "coleta2")])
def test_cli_repassa_sessao(monkeypatch, argv, expected):
    seen = {}
    monkeypatch.setattr(mod, "main", lambda **kw: seen.update(kw) or 0)
    assert mod.cli(argv) == 0
    assert seen == {"session": expected}
