"""Testes do script que registra o Dia 6 em PROJECT.md e THREAT_MODEL.md."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "atualizar_docs_dia6.py"
_spec = importlib.util.spec_from_file_location("atualizar_docs_dia6", SCRIPT)
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)

PROJECT_BASE = "# Projeto\n\n## 9. Orçamento\n\nTexto.\n"
THREAT_BASE = "# Modelo de ameaças\n\n## 12. Histórico\n\nTexto.\n"


@pytest.fixture
def docs(tmp_path):
    project, threat = tmp_path / "PROJECT.md", tmp_path / "THREAT_MODEL.md"
    project.write_bytes(PROJECT_BASE.encode("utf-8"))
    threat.write_bytes(THREAT_BASE.encode("utf-8"))
    return project, threat


def expected(text: str, marker: str, lines, eol: str = "\n") -> str:
    return text + eol + mod.block_text(marker, lines, eol)


# ------------------------------------------------------------------ plan (texto)

def test_bloco_vai_para_o_fim_e_o_original_fica_intacto():
    new = mod.plan(PROJECT_BASE, mod.PROJECT_MARKER, mod.PROJECT_LINES, "P")
    assert new.startswith(PROJECT_BASE)
    assert new == expected(PROJECT_BASE, mod.PROJECT_MARKER, mod.PROJECT_LINES)
    assert new.count(mod.PROJECT_MARKER) == 1


def test_fim_de_linha_crlf_e_preservado():
    crlf = PROJECT_BASE.replace("\n", "\r\n")
    new = mod.plan(crlf, mod.PROJECT_MARKER, mod.PROJECT_LINES, "P")
    assert new.count("\n") == new.count("\r\n")
    assert new == expected(crlf, mod.PROJECT_MARKER, mod.PROJECT_LINES, "\r\n")


def test_lf_nao_ganha_cr():
    assert "\r" not in mod.plan(PROJECT_BASE, mod.PROJECT_MARKER, mod.PROJECT_LINES, "P")


def test_arquivo_sem_quebra_final_ganha_uma():
    new = mod.plan("# Projeto", mod.PROJECT_MARKER, mod.PROJECT_LINES, "P")
    assert new.startswith("# Projeto\n\n## 18.")


def test_segunda_passada_nao_muda_nada():
    once = mod.plan(PROJECT_BASE, mod.PROJECT_MARKER, mod.PROJECT_LINES, "P")
    assert mod.plan(once, mod.PROJECT_MARKER, mod.PROJECT_LINES, "P") is None


def test_bloco_alterado_e_recusado():
    once = mod.plan(PROJECT_BASE, mod.PROJECT_MARKER, mod.PROJECT_LINES, "P")
    changed = once.replace("reserva de 20 s", "reserva de 21 s")
    with pytest.raises(ValueError, match="diferente do esperado"):
        mod.plan(changed, mod.PROJECT_MARKER, mod.PROJECT_LINES, "P")


def test_bloco_que_nao_esta_no_fim_e_recusado():
    once = mod.plan(PROJECT_BASE, mod.PROJECT_MARKER, mod.PROJECT_LINES, "P")
    moved = once + "\nNovo texto depois do bloco.\n"
    with pytest.raises(ValueError, match="não está no fim"):
        mod.plan(moved, mod.PROJECT_MARKER, mod.PROJECT_LINES, "P")


def test_bloco_duplicado_e_recusado():
    once = mod.plan(PROJECT_BASE, mod.PROJECT_MARKER, mod.PROJECT_LINES, "P")
    with pytest.raises(ValueError, match="mais de uma vez"):
        mod.plan(once + "\n" + mod.PROJECT_MARKER + "\n", mod.PROJECT_MARKER, mod.PROJECT_LINES, "P")


def test_textos_do_bloco_sao_planos_e_sem_marcadores_de_rascunho():
    everything = " ".join(mod.PROJECT_LINES + mod.THREAT_LINES)
    for forbidden in ("TODO", "XXX", "???", "{", "}", "<", ">", "\t"):
        assert forbidden not in everything, forbidden
    for line in mod.PROJECT_LINES + mod.THREAT_LINES:
        assert "\n" not in line and "\r" not in line


def test_nenhum_segredo_no_texto_do_bloco():
    text = " ".join(mod.PROJECT_LINES + mod.THREAT_LINES).lower()
    assert "token" not in text or "variável" not in text
    assert "ibm_quantum_token=" not in text and "api_key" not in text


def test_afirmacoes_de_numeros_batem_com_a_saida_real():
    text = " ".join(mod.PROJECT_LINES)
    assert "dbji1pgnceqs73ak2c8g" in text and "156 bits" in text and "1000 shots" in text
    assert "0,4971" in text and "0,3450" in text and "0,4080" in text and "0,5740" in text
    assert "0,00134" in text and "0,00989" in text and "0,49451" in text
    assert "qpu_charge_time_seconds" in text and "quantum_seconds" in text


# ------------------------------------------------------------------ apply_all (em disco)

def test_aplica_nos_dois_arquivos(docs):
    project, threat = docs
    summary = mod.apply_all(project, threat)
    assert summary.startswith("aplicado:")
    assert project.read_text(encoding="utf-8").count(mod.PROJECT_MARKER) == 1
    assert threat.read_text(encoding="utf-8").count(mod.THREAT_MARKER) == 1
    assert not list(project.parent.glob("*.tmp"))


def test_segunda_execucao_nao_altera_os_arquivos(docs):
    project, threat = docs
    mod.apply_all(project, threat)
    before = (project.read_bytes(), threat.read_bytes())
    assert mod.apply_all(project, threat) == "já aplicado: nada a fazer"
    assert (project.read_bytes(), threat.read_bytes()) == before


def test_arquivo_ausente_recusa_sem_tocar_no_outro(docs):
    project, threat = docs
    threat.unlink()
    before = project.read_bytes()
    with pytest.raises(ValueError, match="não encontrado"):
        mod.apply_all(project, threat)
    assert project.read_bytes() == before


def test_nao_utf8_recusa_sem_tocar_em_nada(docs):
    project, threat = docs
    project.write_bytes(b"\xff\xfe\x00 projeto")
    before = threat.read_bytes()
    with pytest.raises(ValueError, match="não é UTF-8"):
        mod.apply_all(project, threat)
    assert threat.read_bytes() == before


def test_bloco_do_threat_alterado_recusa_sem_gravar_o_projeto(docs):
    project, threat = docs
    mod.apply_all(project, threat)
    threat.write_text(threat.read_text(encoding="utf-8").replace("Observado:", "Visto:", 1),
                      encoding="utf-8")
    project.write_bytes(PROJECT_BASE.encode("utf-8"))           # PROJECT sem o bloco
    before = project.read_bytes()
    with pytest.raises(ValueError, match="THREAT_MODEL.md"):
        mod.apply_all(project, threat)
    assert project.read_bytes() == before


def test_falha_na_segunda_troca_restaura_a_primeira(docs, monkeypatch):
    project, threat = docs
    before = (project.read_bytes(), threat.read_bytes())
    real_replace = mod.os.replace
    calls = {"n": 0}

    def flaky(src, dst):
        calls["n"] += 1
        if calls["n"] == 2:
            raise OSError("disco cheio")
        return real_replace(src, dst)

    monkeypatch.setattr(mod.os, "replace", flaky)
    with pytest.raises(OSError, match="disco cheio"):
        mod.apply_all(project, threat)
    assert (project.read_bytes(), threat.read_bytes()) == before
    assert not list(project.parent.glob("*.tmp"))


def test_main_mostra_recusa_e_codigo_1(docs, monkeypatch, capsys, tmp_path):
    project, threat = docs
    threat.unlink()
    monkeypatch.chdir(project.parent)
    assert mod.main() == 1
    assert "RECUSADO" in capsys.readouterr().out


def test_main_aplica_e_devolve_0(docs, monkeypatch, capsys):
    project, threat = docs
    monkeypatch.chdir(project.parent)
    assert mod.main() == 0
    out = capsys.readouterr().out
    assert "aplicado:" in out and "SHA-256 antes" in out and "SHA-256 depois" in out
