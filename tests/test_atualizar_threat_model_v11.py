"""Testes do script que revisa o THREAT_MODEL.md para a v1.1.

Tudo roda em pasta temporária, com um texto de base que reproduz as linhas
reais da v1.0. A barreira garante que nenhum teste toca no THREAT_MODEL.md real.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts import atualizar_threat_model_v11 as tm

ROOT = Path(__file__).resolve().parents[1]

BASE = "\n".join([
    "# Entropy Assurance Layer (EAL) — Modelo de ameaça",
    "",
    "- **Versão do documento:** 1.0",
    "- **Data:** 27/10/2026",
    "- **Autor:** Bruno Pascual",
    "",
    "## 2. Ativos",
    "",
    "| ID | Ativo | Por que importa | Onde vive |",
    "| --- | --- | --- | --- |",
    tm.OLD_AT4,
    "",
    "## 5. Ameaças e mitigações",
    "",
    "| ID | Ameaça | Adversário | Mitigação | Como é testada | Risco residual |",
    "| --- | --- | --- | --- | --- | --- |",
    tm.OLD_T9,
    "",
    "## 6. O que a EAL garante",
    "",
    "| ID | Garantia | Condição |",
    "| --- | --- | --- |",
    tm.OLD_G4,
    "| G5 | Recibos não contêm segredos, somente hashes | Código conforme `PROJECT.md` |",
    "",
    "## 7. O que a EAL não garante",
    "",
    "| ID | Não garante | Por quê |",
    "| --- | --- | --- |",
    tm.OLD_N12,
    "",
    "## 11. Quando revisar este documento",
    "",
    "- Ao adicionar uma fonte nova.",
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
    data = text.replace("\n", "\r\n") if crlf else text
    path.write_bytes(data.encode("utf-8"))
    return path


# --------------------------------------------------------------- cabeçalho

def test_versao_vira_1_1():
    out = tm.update_text(BASE)
    assert "- **Versão do documento:** 1.1" in out
    assert "- **Versão do documento:** 1.0" not in out


def test_data_registra_a_original_e_a_revisao():
    out = tm.update_text(BASE)
    assert "- **Data:** 27/10/2026 (v1.0); revisada em 31/10/2026 (v1.1)" in out


# -------------------------------------------------------------------- G4

def test_g4_deixa_de_dizer_qualquer_alteracao():
    out = tm.update_text(BASE)
    assert "qualquer alteração é detectada" not in row(out, "| G4 |")
    # o histórico cita a frase antiga, entre aspas, de propósito
    assert "qualquer alteração é detectada" in out.split(tm.HIST_START)[1]


def test_g4_separa_alteracao_de_remocao_do_fim():
    g4 = row(tm.update_text(BASE), "| G4 |")
    assert "alteração de um recibo ou do meio da cadeia é detectada" in g4
    assert "`--expected-head`" in g4
    assert "ver N13" in g4


def test_g4_condicao_inclui_a_cabeca_guardada_fora_do_log():
    g4 = row(tm.update_text(BASE), "| G4 |")
    assert "cabeça guardada fora do log" in g4.split("|")[-2]


# -------------------------------------------------------------------- T9

def test_t9_inclui_a_remocao_do_fim_na_ameaca():
    t9 = row(tm.update_text(BASE), "| T9 |")
    assert "removido do fim da cadeia" in t9


def test_t9_risco_residual_separado_com_alto_em_negrito():
    t9 = row(tm.update_text(BASE), "| T9 |")
    residual = t9.split("|")[-2]
    assert "Baixo para alteração" in residual
    assert "**alto para a remoção dos últimos recibos sem cabeça guardada fora do log**" in residual


def test_t9_cita_a_evidencia_da_demo():
    t9 = row(tm.update_text(BASE), "| T9 |")
    assert "demo de 31/10/2026, passos 8 e 9" in t9


def test_t9_diz_que_o_prototipo_nao_guarda_a_cabeca():
    assert "o protótipo ainda não a guarda" in row(tm.update_text(BASE), "| T9 |")


# ------------------------------------------------------------------- N13

def test_n13_vem_logo_depois_de_n12():
    lines = tm.update_text(BASE).split("\n")
    i12 = next(i for i, line in enumerate(lines) if line.startswith("| N12 |"))
    assert lines[i12 + 1].startswith("| N13 |")
    assert lines[i12 + 2] == ""


def test_n13_diz_que_o_prototipo_nao_guarda_a_cabeca():
    n13 = row(tm.update_text(BASE), "| N13 |")
    assert "não a guarda" in n13
    assert "continua sendo uma cadeia válida" in n13


# ------------------------------------------------------------------- AT4

def test_at4_cita_a_cabeca_nao_guardada_e_o_log_de_falhas():
    at4 = row(tm.update_text(BASE), "| AT4 |")
    assert "não a guarda em lugar nenhum" in at4
    assert "`data/logs/eal_runs.jsonl`" in at4
    assert "não traz semente nem chaves privadas" in at4
    assert "`data/receipts/`" in at4


# ---------------------------------------------------- tabelas e linhas intactas

@pytest.mark.parametrize("key", ["| AT4 |", "| G4 |", "| T9 |", "| N12 |"])
def test_linhas_mexidas_mantem_o_numero_de_colunas(key):
    before = row(BASE, key).count("|")
    after_key = "| N13 |" if key == "| N12 |" else key
    assert row(tm.update_text(BASE), after_key).count("|") == before


def test_so_as_cinco_linhas_previstas_mudam():
    out = tm.update_text(BASE)
    original = BASE.split("\n")
    revised = out.split("\n")
    removed = [line for line in original if line not in revised]
    assert len(removed) == 5
    expected = {
        "- **Versão do documento:** 1.0", "- **Data:** 27/10/2026",
        tm.OLD_AT4, tm.OLD_G4, tm.OLD_T9,
    }
    assert set(removed) == expected


def test_g5_e_o_cabecalho_da_secao_11_continuam_iguais():
    out = tm.update_text(BASE)
    assert "| G5 | Recibos não contêm segredos, somente hashes | Código conforme `PROJECT.md` |" in out
    assert "## 11. Quando revisar este documento" in out


def test_n12_continua_com_o_mesmo_texto():
    assert tm.OLD_N12 in tm.update_text(BASE).split("\n")


# --------------------------------------------------------------- histórico

def test_historico_entra_no_fim_com_ancoras_e_motivo():
    out = tm.update_text(BASE)
    assert out.endswith(tm.HIST_END + "\n")
    assert out.count(tm.HIST_START) == 1 and out.count(tm.HIST_END) == 1
    assert "## 12. Histórico de revisões" in out
    assert "passos 8 e 9" in out
    assert "quarto item" in out


def test_historico_diz_que_o_codigo_nao_foi_revisado():
    assert "não passou pela revisão adversarial" in tm.HIST_BLOCK


def test_historico_nao_afirma_certificacao_nem_garantia_nova():
    lowered = tm.HIST_BLOCK.lower()
    for forbidden in ("certificad", "100%", "inquebr", "pronto para produção"):
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


def test_n13_nao_duplica_na_segunda_aplicacao():
    twice = tm.update_text(tm.update_text(BASE))
    assert twice.count("| N13 |") == 1


# ----------------------------------------------------------------- recusas

@pytest.mark.parametrize("old", [tm.OLD_AT4, tm.OLD_G4, tm.OLD_T9, tm.OLD_N12,
                                 "- **Versão do documento:** 1.0", "- **Data:** 27/10/2026"])
def test_trecho_ausente_recusa(old):
    with pytest.raises(tm.ModelError, match="exatamente uma vez"):
        tm.update_text(BASE.replace(old, "outra coisa"))


@pytest.mark.parametrize("old", [tm.OLD_AT4, tm.OLD_G4, tm.OLD_T9, tm.OLD_N12])
def test_trecho_repetido_recusa(old):
    with pytest.raises(tm.ModelError, match="exatamente uma vez"):
        tm.update_text(BASE + old + "\n")


@pytest.mark.parametrize("old", [tm.OLD_AT4, tm.OLD_G4, tm.OLD_T9, tm.OLD_N12,
                                 "- **Versão do documento:** 1.0", "- **Data:** 27/10/2026"])
def test_linha_com_texto_a_mais_no_fim_recusa(old):
    with pytest.raises(tm.ModelError, match="exatamente uma vez"):
        tm.update_text(BASE.replace(old, old + " (editado)"))


def test_linha_com_texto_a_mais_no_comeco_recusa():
    with pytest.raises(tm.ModelError, match="exatamente uma vez"):
        tm.update_text(BASE.replace(tm.OLD_T9, "x " + tm.OLD_T9))


def test_g4_editada_a_mao_recusa_em_vez_de_sobrescrever():
    edited = BASE.replace(tm.OLD_G4, tm.OLD_G4 + " (editado)")
    with pytest.raises(tm.ModelError, match="G4"):
        tm.update_text(edited)


def test_redacao_antiga_de_g4_em_outro_lugar_do_arquivo_recusa():
    stale = "Texto antigo: qualquer alteração é detectada pelo `eal verify`.\n"
    with pytest.raises(tm.ModelError, match="redação antiga"):
        tm.update_text(BASE + stale)


def test_ancoras_do_historico_inconsistentes_recusam():
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

def test_write_model_preserva_crlf(tmp_path):
    path = put(tmp_path, BASE, crlf=True)
    assert tm.write_model(path) is True
    raw = path.read_bytes()
    assert raw.count(b"\n") == raw.count(b"\r\n")
    assert raw.endswith(b"\r\n")


def test_write_model_segunda_vez_nao_muda_os_bytes(tmp_path):
    path = put(tmp_path, BASE, crlf=True)
    tm.write_model(path)
    first = path.read_bytes()
    assert tm.write_model(path) is False
    assert path.read_bytes() == first


def test_write_model_arquivo_lf_continua_lf(tmp_path):
    path = put(tmp_path, BASE)
    assert tm.write_model(path) is True
    assert b"\r" not in path.read_bytes()


def test_write_model_mistura_de_quebras_recusa_sem_tocar(tmp_path):
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


def test_write_model_falha_de_conferencia_nao_grava(tmp_path):
    original = BASE.replace(tm.OLD_G4, "outra coisa").encode("utf-8")
    path = tmp_path / "THREAT_MODEL.md"
    path.write_bytes(original)
    with pytest.raises(tm.ModelError):
        tm.write_model(path)
    assert path.read_bytes() == original


# -------------------------------------------------------------------- main

def test_main_grava_e_devolve_0(tmp_path, capsys):
    put(tmp_path, BASE, crlf=True)
    assert tm.main([], _root=tmp_path) == 0
    assert "gravada" in capsys.readouterr().out
    assert "1.1" in (tmp_path / "THREAT_MODEL.md").read_text(encoding="utf-8")


def test_main_segunda_vez_diz_que_nada_mudou(tmp_path, capsys):
    put(tmp_path, BASE)
    tm.main([], _root=tmp_path)
    capsys.readouterr()
    assert tm.main([], _root=tmp_path) == 0
    assert "nada mudou" in capsys.readouterr().out


def test_main_falha_devolve_1_e_nao_grava(tmp_path, capsys):
    original = BASE.replace(tm.OLD_T9, "outra coisa")
    path = put(tmp_path, original)
    assert tm.main([], _root=tmp_path) == 1
    assert path.read_text(encoding="utf-8") == original
    assert "nada foi gravado" in capsys.readouterr().err


def test_main_sem_arquivo_devolve_1(tmp_path):
    assert tm.main([], _root=tmp_path) == 1


def test_main_rejeita_argumento_desconhecido():
    with pytest.raises(SystemExit):
        tm.main(["--nao-existe"])
