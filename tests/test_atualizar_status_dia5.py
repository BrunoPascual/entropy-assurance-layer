"""Testes do script que atualiza o Status do PROJECT.md e registra a nota do gate.

Tudo roda em pasta temporária. A barreira no início garante que nenhum teste
toca no PROJECT.md real.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts import atualizar_status_dia5 as upd

ROOT = Path(__file__).resolve().parents[1]

BASE = (
    "# Projeto\n\n"
    "- **Status:** Dia 4 de 9 (concluído; gate do Dia 4 aprovado, ver seção 16.2)\n\n"
    "<!-- dia4-gate:start -->\n### 16.2 Antigo\n<!-- dia4-gate:end -->\n\n"
    "<!-- dia5-gate:start -->\n### 16.3 Gate\nconteúdo\n<!-- dia5-gate:end -->\n\n"
    "## 17. Limitações conhecidas\n\n- item\n"
)


def _snapshot() -> list[tuple[str, int, int]]:
    project = ROOT / "PROJECT.md"
    if not project.is_file():
        return []
    st = project.stat()
    return [("PROJECT.md", st.st_size, st.st_mtime_ns)]


@pytest.fixture(autouse=True)
def _nunca_tocar_no_projeto_real():
    before = _snapshot()
    yield
    assert _snapshot() == before, "o teste mexeu no PROJECT.md real"


def _put(root: Path, text: str) -> Path:
    path = root / "PROJECT.md"
    path.write_bytes(text.encode("utf-8"))
    return path


# ------------------------------------------------------------- status

def test_status_do_dia4_vira_o_do_dia5():
    out = upd.update_text(BASE)
    assert upd.NEW_STATUS in out.split("\n")
    assert upd.OLD_STATUS not in out


def test_status_ja_novo_nao_muda_a_linha():
    text = BASE.replace(upd.OLD_STATUS + " (concluído; gate do Dia 4 aprovado, ver seção 16.2)",
                        upd.NEW_STATUS)
    assert upd.update_text(text).split("\n").count(upd.NEW_STATUS) == 1


@pytest.mark.parametrize("previous", upd.PREVIOUS_STATUSES)
def test_status_de_versao_anterior_do_dia5_e_trocado(previous):
    text = BASE.replace(upd.OLD_STATUS + " (concluído; gate do Dia 4 aprovado, ver seção 16.2)", previous)
    out = upd.update_text(text).split("\n")
    assert upd.NEW_STATUS in out
    assert previous not in out


def test_as_duas_redacoes_anteriores_sao_diferentes_da_atual():
    assert len(set(upd.PREVIOUS_STATUSES)) == 2
    assert upd.NEW_STATUS not in upd.PREVIOUS_STATUSES


def test_status_atual_diz_concluido_e_aponta_a_secao_da_revisao():
    assert "concluído" in upd.NEW_STATUS
    assert "seção 16.4" in upd.NEW_STATUS
    assert "seção 16.3" in upd.NEW_STATUS
    assert "pendente" not in upd.NEW_STATUS


def test_status_atual_nao_cita_mais_o_source():
    assert "SOURCE" not in upd.NEW_STATUS


def test_status_com_texto_inesperado_recusa():
    text = BASE.replace("Dia 4 de 9", "Dia 3 de 9")
    with pytest.raises(upd.GateError, match="Status"):
        upd.update_text(text)


def test_sem_linha_de_status_recusa():
    with pytest.raises(upd.GateError, match="Status"):
        upd.update_text(BASE.replace("- **Status:**", "Status:"))


def test_duas_linhas_de_status_recusam():
    with pytest.raises(upd.GateError, match="Status"):
        upd.update_text(BASE + "- **Status:** outra\n")


def test_so_o_status_e_trocado_no_cabecalho():
    out = upd.update_text(BASE)
    before = BASE.split("\n")
    after = out.split("\n")
    changed = [a for a, b in zip(after, before) if a != b]
    assert changed[0] == upd.NEW_STATUS


# --------------------------------------------------------------- nota

def test_nota_entra_logo_depois_da_secao_16_3_e_antes_da_17():
    out = upd.update_text(BASE)
    gate_end = out.index(upd.GATE_END)
    note = out.index(upd.NOTE_START)
    assert gate_end < note < out.index("## 17. Limitações conhecidas")
    assert out.count(upd.NOTE_START) == 1 and out.count(upd.NOTE_END) == 1


def test_nota_cita_o_fluxo_real_do_gate():
    for word in ("init-issuer", "`run`", "eal verify <recibo>", "ML-DSA-65", "--export-demo"):
        assert word in upd.NOTE_BLOCK


def test_nota_nao_diz_que_um_comando_faz_tudo():
    assert "Não é um comando único" in upd.NOTE_BLOCK


def test_idempotente_nao_duplica_a_nota():
    once = upd.update_text(BASE)
    twice = upd.update_text(once)
    assert twice == once
    assert twice.count(upd.NOTE_START) == 1


def test_nota_antiga_e_substituida_pelo_texto_atual():
    old = BASE.replace(upd.GATE_END,
                       upd.GATE_END + "\n\n" + upd.NOTE_START + "\nvelho\n" + upd.NOTE_END)
    out = upd.update_text(old)
    assert "velho" not in out
    assert out.count(upd.NOTE_START) == 1


def test_sem_ancora_de_fim_da_16_3_recusa():
    text = BASE.replace(upd.GATE_END, "")
    with pytest.raises(upd.GateError, match="16.3"):
        upd.update_text(text)


def test_ancora_de_fim_da_16_3_repetida_recusa():
    text = BASE.replace(upd.GATE_END, upd.GATE_END + "\n" + upd.GATE_END)
    with pytest.raises(upd.GateError, match="16.3"):
        upd.update_text(text)


def test_nota_com_inicio_sem_fim_recusa():
    text = BASE.replace(upd.GATE_END, upd.GATE_END + "\n" + upd.NOTE_START)
    with pytest.raises(upd.GateError, match="nota"):
        upd.update_text(text)


def test_nota_com_fim_antes_do_inicio_recusa():
    text = BASE.replace(upd.GATE_END, upd.GATE_END + "\n" + upd.NOTE_END + "\n" + upd.NOTE_START)
    with pytest.raises(upd.GateError):
        upd.update_text(text)


# ------------------------------------------------------ arquivo (CRLF)

def test_write_project_preserva_crlf_e_e_idempotente(tmp_path):
    path = _put(tmp_path, BASE.replace("\n", "\r\n"))
    assert upd.write_project(path) is True
    raw = path.read_bytes()
    assert raw.count(b"\n") == raw.count(b"\r\n")
    first = raw
    assert upd.write_project(path) is False
    assert path.read_bytes() == first


def test_write_project_arquivo_lf_continua_lf(tmp_path):
    path = _put(tmp_path, BASE)
    assert upd.write_project(path) is True
    assert b"\r" not in path.read_bytes()


def test_write_project_recusa_mistura_sem_tocar(tmp_path):
    original = ("a\r\n" + BASE).encode("utf-8")
    path = tmp_path / "PROJECT.md"
    path.write_bytes(original)
    with pytest.raises(upd.GateError, match="mistura"):
        upd.write_project(path)
    assert path.read_bytes() == original


def test_write_project_recusa_nao_utf8_sem_tocar(tmp_path):
    original = b"\xff\n" + BASE.encode("utf-8")
    path = tmp_path / "PROJECT.md"
    path.write_bytes(original)
    with pytest.raises(upd.GateError, match="UTF-8"):
        upd.write_project(path)
    assert path.read_bytes() == original


def test_write_project_sem_arquivo_recusa(tmp_path):
    with pytest.raises(upd.GateError):
        upd.write_project(tmp_path / "nao_existe.md")


def test_write_project_recusa_sem_gravar_quando_a_conferencia_falha(tmp_path):
    original = BASE.replace("Dia 4 de 9", "Dia 3 de 9").encode("utf-8")
    path = tmp_path / "PROJECT.md"
    path.write_bytes(original)
    with pytest.raises(upd.GateError):
        upd.write_project(path)
    assert path.read_bytes() == original


# ---------------------------------------------------------------- main

def test_main_atualiza_e_devolve_0(tmp_path, capsys):
    _put(tmp_path, BASE)
    assert upd.main([], _root=tmp_path) == 0
    assert "atualizados" in capsys.readouterr().out
    assert upd.NEW_STATUS in (tmp_path / "PROJECT.md").read_text(encoding="utf-8")


def test_main_segunda_vez_nao_muda(tmp_path, capsys):
    _put(tmp_path, BASE)
    upd.main([], _root=tmp_path)
    capsys.readouterr()
    assert upd.main([], _root=tmp_path) == 0
    assert "nada mudou" in capsys.readouterr().out


def test_main_falha_devolve_1_e_nao_grava(tmp_path, capsys):
    original = BASE.replace("Dia 4 de 9", "Dia 3 de 9")
    path = _put(tmp_path, original)
    assert upd.main([], _root=tmp_path) == 1
    assert path.read_text(encoding="utf-8") == original
    assert "nada foi gravado" in capsys.readouterr().err


def test_main_sem_arquivo_devolve_1(tmp_path):
    assert upd.main([], _root=tmp_path) == 1


def test_main_rejeita_argumento_desconhecido():
    with pytest.raises(SystemExit):
        upd.main(["--nao-existe"])
