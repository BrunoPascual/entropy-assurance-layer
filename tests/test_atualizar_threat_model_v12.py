"""Testes do script que revisa o THREAT_MODEL.md para a v1.2 (achado F12).

Tudo roda em pasta temporária, com um texto de base que reproduz as linhas reais da v1.1.
A barreira garante que nenhum teste toca no THREAT_MODEL.md real.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts import atualizar_threat_model_v11 as v11
from scripts import atualizar_threat_model_v12 as tm

ROOT = Path(__file__).resolve().parents[1]
OLD_VERSION = "- **Versão do documento:** 1.1"
OLD_DATE = "- **Data:** 27/10/2026 (v1.0); revisada em 31/10/2026 (v1.1)"

BASE = "\n".join([
    "# Entropy Assurance Layer (EAL) — Modelo de ameaça",
    "",
    OLD_VERSION,
    OLD_DATE,
    "- **Autor:** Bruno Pascual",
    "",
    "## 5. Ameaças e mitigações",
    "",
    "| ID | Ameaça | Adversário | Mitigação | Como é testada | Risco residual |",
    "| --- | --- | --- | --- | --- | --- |",
    tm.OLD_T3,
    "| T4 | Gerador clássico disfarçado de QPU | ADV3 | Não detectável | E2, E5 | **Alto** |",
    "",
    "## 7. O que a EAL não garante",
    "",
    "| ID | Não garante | Por quê |",
    "| --- | --- | --- |",
    "| N12 | Resistência a ataques físicos | Fora do escopo |",
    tm.N13,
    "",
    "## 11. Quando revisar este documento",
    "",
    "- Ao adicionar uma fonte nova.",
    "",
    "<!-- revisao-v11:start -->",
    "## 12. Histórico de revisões",
    "",
    "### v1.1 (31/10/2026)",
    "<!-- revisao-v11:end -->",
    "",
])


def _snapshot() -> list[tuple[str, int, int]]:
    path = ROOT / tm.MODEL_REL
    if not path.is_file():
        return []
    st = path.stat()
    return [(str(tm.MODEL_REL), st.st_size, st.st_mtime_ns)]


@pytest.fixture(autouse=True)
def _nunca_tocar_no_modelo_real():
    before = _snapshot()
    yield
    assert _snapshot() == before, "o teste mexeu no THREAT_MODEL.md real"


def row(text: str, key: str) -> str:
    start = text.index(key)
    return text[start:text.index("\n", start)]


def put(root: Path, text: str, *, crlf: bool = False) -> Path:
    path = root / "THREAT_MODEL.md"
    path.write_bytes((text.replace("\n", "\r\n") if crlf else text).encode("utf-8"))
    return path


# ------------------------------------------------------------ coerência com a v1.1

def test_linha_n13_e_a_mesma_que_o_script_da_v1_1_grava():
    assert tm.N13 == v11.NEW_N13


def test_cabecalho_da_v1_1_e_o_que_o_script_da_v1_1_grava():
    assert OLD_VERSION == "- **Versão do documento:** 1.1"
    assert OLD_DATE.endswith("(v1.1)")
    assert any(old == "- **Versão do documento:** 1.0" and new == OLD_VERSION for _, old, new in v11.EDITS)


# --------------------------------------------------------------- cabeçalho

def test_versao_vira_1_2():
    out = tm.update_text(BASE)
    assert "- **Versão do documento:** 1.2" in out
    assert OLD_VERSION not in out.split("\n")


def test_data_registra_as_duas_revisoes():
    assert "- **Data:** 27/10/2026 (v1.0); revisada em 31/10/2026 (v1.1 e v1.2)" in tm.update_text(BASE)


# ---------------------------------------------------------------------- T3

def test_t3_separa_dentro_de_uma_execucao_e_entre_execucoes():
    t3 = row(tm.update_text(BASE), "| T3 |")
    assert "dentro de uma execução" in t3
    assert "**não detectado entre execuções**" in t3
    assert "alto para replay transformado" in t3
    assert "não é guardado entre execuções" in t3


def test_t3_antigo_some_e_nao_ha_duas_linhas_de_t3():
    out = tm.update_text(BASE)
    assert tm.OLD_T3 not in out.split("\n")
    assert out.count("| T3 |") == 1


def test_t3_mantem_o_numero_de_colunas():
    assert row(tm.update_text(BASE), "| T3 |").count("|") == tm.OLD_T3.count("|")


def test_t4_vizinha_continua_igual():
    assert "| T4 | Gerador clássico disfarçado de QPU | ADV3 | Não detectável | E2, E5 | **Alto** |" in tm.update_text(BASE).split("\n")


# --------------------------------------------------------------------- N14

def test_n14_vem_logo_depois_de_n13():
    lines = tm.update_text(BASE).split("\n")
    i13 = next(i for i, line in enumerate(lines) if line.startswith("| N13 |"))
    assert lines[i13 + 1].startswith("| N14 |")
    assert lines[i13 + 2] == ""


def test_n14_cita_a_ibm_e_a_memoria():
    n14 = row(tm.update_text(BASE), "| N14 |")
    assert "só em memória" in n14 and "Dia 6" in n14 and "IBM" in n14


def test_n14_tem_as_mesmas_colunas_de_n13():
    out = tm.update_text(BASE)
    assert row(out, "| N14 |").count("|") == row(out, "| N13 |").count("|")


def test_n13_continua_com_o_mesmo_texto():
    assert tm.N13 in tm.update_text(BASE).split("\n")


# --------------------------------------------------------------- só o previsto muda

def test_so_tres_linhas_previstas_saem_do_texto():
    out = tm.update_text(BASE)
    removed = [line for line in BASE.split("\n") if line not in out.split("\n")]
    assert set(removed) == {OLD_VERSION, OLD_DATE, tm.OLD_T3}


# --------------------------------------------------------------- histórico

def test_historico_v1_2_entra_depois_do_v1_1_com_ancoras_proprias():
    out = tm.update_text(BASE)
    assert out.index("<!-- revisao-v11:end -->") < out.index(tm.HIST_START) < out.index(tm.HIST_END)
    assert out.endswith(tm.HIST_END + "\n")
    assert out.count(tm.HIST_START) == 1 and out.count(tm.HIST_END) == 1
    assert out.count("<!-- revisao-v11:start -->") == 1


def test_historico_diz_que_a_persistencia_nao_foi_implementada():
    assert "não foi implementada" in tm.HIST_BLOCK
    assert "Dia 6" in tm.HIST_BLOCK


def test_historico_nao_usa_palavras_proibidas():
    lowered = tm.HIST_BLOCK.lower()
    for forbidden in ("certificad", "100%", "inquebr", "pronto para produção", "provado"):
        assert forbidden not in lowered


def test_historico_antigo_e_substituido():
    first = tm.update_text(BASE)
    stale = first.replace(tm.HIST_BLOCK, tm.HIST_START + "\nvelho\n" + tm.HIST_END)
    out = tm.update_text(stale)
    assert "velho" not in out
    assert out == first


# --------------------------------------------------------------- idempotência

def test_segunda_aplicacao_nao_muda_nada():
    once = tm.update_text(BASE)
    assert tm.update_text(once) == once


def test_n14_nao_duplica():
    assert tm.update_text(tm.update_text(BASE)).count("| N14 |") == 1


# ----------------------------------------------------------------- recusas

@pytest.mark.parametrize("old", [OLD_VERSION, OLD_DATE, tm.OLD_T3, tm.N13])
def test_linha_ausente_recusa(old):
    with pytest.raises(tm.ModelError, match="exatamente uma vez"):
        tm.update_text(BASE.replace(old, "outra coisa"))


@pytest.mark.parametrize("old", [OLD_VERSION, OLD_DATE, tm.OLD_T3, tm.N13])
def test_linha_repetida_recusa(old):
    with pytest.raises(tm.ModelError, match="exatamente uma vez"):
        tm.update_text(BASE + old + "\n")


@pytest.mark.parametrize("old", [OLD_VERSION, OLD_DATE, tm.OLD_T3, tm.N13])
def test_linha_com_texto_a_mais_recusa(old):
    with pytest.raises(tm.ModelError, match="exatamente uma vez"):
        tm.update_text(BASE.replace(old, old + " (editado)"))


def test_v1_1_nao_aplicada_recusa_em_vez_de_pular_etapas():
    with pytest.raises(tm.ModelError, match="exatamente uma vez"):
        tm.update_text(BASE.replace(OLD_VERSION, "- **Versão do documento:** 1.0"))


def test_ancoras_inconsistentes_recusam():
    for extra in (tm.HIST_START, tm.HIST_END, tm.HIST_START * 2 + tm.HIST_END):
        with pytest.raises(tm.ModelError, match="âncoras"):
            tm.update_text(BASE + "\n" + extra + "\n")


def test_ancora_de_fim_antes_da_de_inicio_recusa():
    with pytest.raises(tm.ModelError, match="antes"):
        tm.update_text(BASE + "\n" + tm.HIST_END + "\n" + tm.HIST_START + "\n")


def test_arquivo_sem_quebra_final_recusa():
    with pytest.raises(tm.ModelError, match="quebra de linha"):
        tm.update_text(BASE.rstrip("\n"))


# ----------------------------------------------------------------- arquivo

def test_write_model_preserva_crlf_e_e_idempotente(tmp_path):
    path = put(tmp_path, BASE, crlf=True)
    assert tm.write_model(path) is True
    raw = path.read_bytes()
    assert raw.count(b"\n") == raw.count(b"\r\n") and raw.endswith(b"\r\n")
    assert tm.write_model(path) is False
    assert path.read_bytes() == raw


def test_write_model_lf_continua_lf(tmp_path):
    path = put(tmp_path, BASE)
    assert tm.write_model(path) is True
    assert b"\r" not in path.read_bytes()


def test_write_model_mistura_recusa_sem_tocar(tmp_path):
    original = ("a\r\n" + BASE).encode("utf-8")
    path = tmp_path / "THREAT_MODEL.md"
    path.write_bytes(original)
    with pytest.raises(tm.ModelError, match="mistura"):
        tm.write_model(path)
    assert path.read_bytes() == original


def test_write_model_nao_utf8_recusa_sem_tocar(tmp_path):
    original = b"\xff\n" + BASE.encode("utf-8")
    path = tmp_path / "THREAT_MODEL.md"
    path.write_bytes(original)
    with pytest.raises(tm.ModelError, match="UTF-8"):
        tm.write_model(path)
    assert path.read_bytes() == original


def test_write_model_sem_arquivo_recusa(tmp_path):
    with pytest.raises(tm.ModelError):
        tm.write_model(tmp_path / "nao_existe.md")


def test_write_model_falha_nao_grava(tmp_path):
    original = BASE.replace(tm.OLD_T3, "outra coisa")
    path = put(tmp_path, original)
    with pytest.raises(tm.ModelError):
        tm.write_model(path)
    assert path.read_text(encoding="utf-8") == original


# -------------------------------------------------------------------- main

def test_main_grava_e_depois_diz_que_nada_mudou(tmp_path, capsys):
    put(tmp_path, BASE, crlf=True)
    assert tm.main([], _root=tmp_path) == 0
    assert "gravada" in capsys.readouterr().out
    assert tm.main([], _root=tmp_path) == 0
    assert "nada mudou" in capsys.readouterr().out


def test_main_falha_devolve_1_e_nao_grava(tmp_path, capsys):
    original = BASE.replace(tm.OLD_T3, "outra coisa")
    path = put(tmp_path, original)
    assert tm.main([], _root=tmp_path) == 1
    assert path.read_text(encoding="utf-8") == original
    assert "nada foi gravado" in capsys.readouterr().err


def test_main_sem_arquivo_devolve_1(tmp_path):
    assert tm.main([], _root=tmp_path) == 1


def test_main_rejeita_argumento_desconhecido():
    with pytest.raises(SystemExit):
        tm.main(["--nao-existe"])
