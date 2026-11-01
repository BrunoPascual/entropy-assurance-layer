"""Testes do script que acrescenta a política de QPU e da IBM ao eal/config.py (Dia 6, 3a)."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "atualizar_config_politica_qpu.py"
_spec = importlib.util.spec_from_file_location("atualizar_config_politica_qpu", SCRIPT)
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)

BASE = (
    '"""Constantes do projeto."""\n'
    "\n"
    "# --- Orçamento de QPU (segundos de execução no chip) ---\n"
    "QPU_TOTAL_BUDGET_SECONDS = 600  # 10 minutos por janela de 28 dias\n"
    "\n"
    "# --- Dia 3 ---\n"
    "MCV_Z = 2.576\n"
)


def inserted(eol: str = "\n") -> str:
    return eol + eol + eol.join(mod.LINES)


# ---------------------------------------------------------------- apply

def test_bloco_entra_logo_depois_da_ancora_e_o_resto_fica_igual():
    result = mod.apply(BASE)
    assert result.count(mod.MARKER) == 1
    assert result.replace(inserted(), "") == BASE
    anchor_line = "QPU_TOTAL_BUDGET_SECONDS = 600  # 10 minutos por janela de 28 dias\n"
    assert anchor_line + "\n" + mod.MARKER + "\n" in result


def test_fim_de_linha_crlf_e_preservado():
    crlf = BASE.replace("\n", "\r\n")
    result = mod.apply(crlf)
    assert result.count("\n") == result.count("\r\n")
    assert result.replace(inserted("\r\n"), "") == crlf


def test_fim_de_linha_lf_nao_ganha_cr():
    assert "\r" not in mod.apply(BASE)


def test_idempotente():
    once = mod.apply(BASE)
    assert mod.apply(once) == once


def test_ancora_na_ultima_linha_sem_quebra_final():
    text = BASE.split("\n\n# --- Dia 3")[0].rstrip("\n")
    assert text.endswith("QPU_TOTAL_BUDGET_SECONDS = 600  # 10 minutos por janela de 28 dias")
    result = mod.apply(text)
    assert result.endswith(mod.LINES[-1] + "\n") and result.count(mod.MARKER) == 1
    compile(result, "config.py", "exec")


def test_ancora_ausente_e_recusada():
    with pytest.raises(ValueError, match="0 vez"):
        mod.apply("X = 1\n")


def test_ancora_duplicada_e_recusada():
    with pytest.raises(ValueError, match="2 vez"):
        mod.apply(BASE + "QPU_TOTAL_BUDGET_SECONDS = 600\n")


def test_bloco_alterado_e_recusado():
    altered = mod.apply(BASE).replace("QPU_DAILY_CAP_SECONDS = 330", "QPU_DAILY_CAP_SECONDS = 999")
    with pytest.raises(ValueError, match="diferente do esperado"):
        mod.apply(altered)


def test_bloco_pela_metade_e_recusado():
    half = BASE + "\n" + mod.MARKER + "\nQPU_BUDGET_MARGIN_SECONDS = 30\n"
    with pytest.raises(ValueError, match="diferente do esperado"):
        mod.apply(half)


@pytest.mark.parametrize("name", [
    "QPU_BUDGET_MARGIN_SECONDS", "QPU_BUDGET_WINDOW_DAYS", "QPU_DAILY_CAP_SECONDS",
    "QPU_MAX_JOB_RESERVE_SECONDS", "QPU_MAX_SHOTS_PER_JOB", "QPU_USAGE_LOG_NAME",
    "IBM_DEFAULT_BACKEND", "IBM_DEFAULT_INSTANCE", "IBM_TOKEN_ENV",
])
def test_constante_ja_existente_fora_do_bloco_e_recusada(name):
    with pytest.raises(ValueError, match=name):
        mod.apply(BASE + f"{name} = 1\n")


def test_nomes_das_constantes():
    assert mod._constant_names() == [
        "QPU_BUDGET_MARGIN_SECONDS", "QPU_BUDGET_WINDOW_DAYS", "QPU_DAILY_CAP_SECONDS",
        "QPU_MAX_JOB_RESERVE_SECONDS", "QPU_MAX_SHOTS_PER_JOB", "QPU_USAGE_LOG_NAME",
        "IBM_DEFAULT_BACKEND", "IBM_DEFAULT_INSTANCE", "IBM_TOKEN_ENV",
    ]


def test_o_resultado_compila_e_define_as_constantes():
    namespace: dict = {}
    exec(compile(mod.apply(BASE), "config.py", "exec"), namespace)
    assert namespace["QPU_TOTAL_BUDGET_SECONDS"] == 600
    assert namespace["QPU_BUDGET_MARGIN_SECONDS"] == 30
    assert namespace["QPU_MAX_SHOTS_PER_JOB"] == 100000
    assert namespace["IBM_TOKEN_ENV"] == "IBM_QUANTUM_TOKEN"


# ---------------------------------------------------------------- main (em disco)

@pytest.fixture
def project(tmp_path, monkeypatch):
    (tmp_path / "eal").mkdir()
    monkeypatch.chdir(tmp_path)
    return tmp_path / "eal" / "config.py"


def test_main_aplica_e_nao_deixa_temporario(project, capsys):
    project.write_bytes(BASE.encode("utf-8"))
    assert mod.main() == 0
    out = capsys.readouterr().out
    assert "aplicado" in out and "SHA-256 antes" in out and "SHA-256 depois" in out
    assert project.read_bytes().decode("utf-8") == mod.apply(BASE)
    assert not list(project.parent.glob("*.tmp"))


def test_main_segunda_vez_nao_muda_nada(project, capsys):
    project.write_bytes(BASE.encode("utf-8"))
    mod.main()
    before = project.read_bytes()
    capsys.readouterr()
    assert mod.main() == 0
    assert "já aplicado" in capsys.readouterr().out
    assert project.read_bytes() == before


def test_main_recusa_sem_gravar_quando_a_ancora_falta(project, capsys):
    project.write_bytes(b"X = 1\n")
    assert mod.main() == 1
    assert "RECUSADO" in capsys.readouterr().out
    assert project.read_bytes() == b"X = 1\n"
    assert not list(project.parent.glob("*.tmp"))


def test_main_recusa_arquivo_que_nao_e_utf8(project, capsys):
    project.write_bytes(b"\xff\xfe\x00")
    assert mod.main() == 1
    assert "UTF-8" in capsys.readouterr().out
    assert project.read_bytes() == b"\xff\xfe\x00"


def test_main_recusa_arquivo_ausente(project, capsys):
    assert mod.main() == 1
    assert "RECUSADO" in capsys.readouterr().out


def test_main_recusa_texto_novo_que_nao_compila(project, monkeypatch, capsys):
    project.write_bytes(BASE.encode("utf-8"))
    monkeypatch.setattr(mod, "LINES", (mod.MARKER, "QPU_BUDGET_MARGIN_SECONDS = = 30"))
    assert mod.main() == 1
    assert "RECUSADO" in capsys.readouterr().out
    assert project.read_bytes() == BASE.encode("utf-8")


def test_main_preserva_crlf_e_bom(project):
    original = ("\ufeff" + BASE).replace("\n", "\r\n").encode("utf-8")
    project.write_bytes(original)
    assert mod.main() == 0
    result = project.read_bytes()
    assert result.startswith("\ufeff".encode("utf-8"))
    assert result.count(b"\n") == result.count(b"\r\n")
    assert mod.MARKER.encode("utf-8") in result
