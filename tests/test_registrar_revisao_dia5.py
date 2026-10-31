"""Testes do script que registra a revisão adversarial do Dia 5 no PROJECT.md.

Tudo roda em pasta temporária. A barreira garante que nenhum teste toca no
PROJECT.md real.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts import registrar_revisao_dia5 as reg

ROOT = Path(__file__).resolve().parents[1]

BASE = "\n".join([
    "# Projeto",
    "",
    "<!-- dia5-gate:start -->",
    "### 16.3 Gate",
    "<!-- dia5-gate:end -->",
    "",
    "<!-- dia5-nota:start -->",
    "nota",
    reg.AFTER,
    "",
    "## 17. Limitações conhecidas",
    "",
    "### Limitações do Dia 5 (etapa 3: log encadeado)",
    "",
    reg.OLD_F2_LINE,
    "- O `fsync` pede ao sistema operacional que grave no disco.",
    "",
])


def _snapshot() -> list[tuple[str, int, int]]:
    path = ROOT / reg.PROJECT_REL
    if not path.is_file():
        return []
    st = path.stat()
    return [(str(reg.PROJECT_REL), st.st_size, st.st_mtime_ns)]


@pytest.fixture(autouse=True)
def _nunca_tocar_no_projeto_real():
    before = _snapshot()
    yield
    assert _snapshot() == before, "o teste mexeu no PROJECT.md real"


def put(root: Path, text: str, *, crlf: bool = False) -> Path:
    path = root / "PROJECT.md"
    path.write_bytes((text.replace("\n", "\r\n") if crlf else text).encode("utf-8"))
    return path


# ----------------------------------------------------------------- bloco 16.4

def test_bloco_entra_logo_depois_da_nota_e_antes_da_secao_17():
    out = reg.update_text(BASE)
    assert out.index(reg.AFTER) < out.index(reg.START) < out.index(reg.END) < out.index("## 17.")
    assert out.count(reg.START) == 1 and out.count(reg.END) == 1


def test_bloco_tem_titulo_commit_e_hashes_dos_arquivos_lidos():
    block = reg.render_block()
    assert "### 16.4 Revisão adversarial do Dia 5" in block
    assert "commit `90d15b8`" in block
    for path, sha in reg.PART1_FILES:
        assert f"`{path}` (SHA-256 `{sha}`)" in block


def test_tabela_tem_uma_linha_por_achado_com_cinco_colunas():
    lines = reg.render_block().split("\n")
    rows = [line for line in lines if line.startswith("| F")]
    assert [r.split("|")[1].strip() for r in rows] == ["F1", "F2", "F3", "F4", "F5", "F6"]
    header = next(line for line in lines if line.startswith("| ID |"))
    for row in rows:
        assert row.count("|") - row.count("\\|") == header.count("|")


def test_decisoes_registradas_para_cada_achado():
    rows = {r.split("|")[1].strip(): r for r in reg.render_block().split("\n") if r.startswith("| F")}
    assert "Corrigido" in rows["F1"] and "Corrigido" in rows["F4"]
    assert "Já estava documentado" in rows["F2"] and "Já estava documentado" in rows["F3"]
    assert "Aceito sem mudança" in rows["F5"]
    assert "A medir" in rows["F6"]


def test_achados_confirmados_por_execucao_estao_marcados():
    rows = {r.split("|")[1].strip(): r for r in reg.render_block().split("\n") if r.startswith("| F")}
    assert "Confirmado por execução" in rows["F1"]
    assert "Confirmado por execução" in rows["F2"]
    for other in ("F3", "F4", "F5", "F6"):
        assert "Confirmado por execução" not in rows[other]


def test_bloco_diz_que_leitura_nao_prova_ausencia_de_defeitos():
    assert "não prova ausência de defeitos" in reg.render_block()


def test_bloco_lista_os_pendentes_das_partes_2_e_3():
    block = reg.render_block()
    for word in ("save_issuer_key", "is_hex64", "to_dict()", "--bits", "validate_body"):
        assert word in block


def test_bloco_nao_usa_palavras_proibidas():
    lowered = reg.render_block().lower()
    for forbidden in ("certificad", "100%", "inquebr", "pronto para produção", "provado"):
        assert forbidden not in lowered


def test_celula_com_barra_vertical_e_escapada():
    assert reg._cell("a|b") == "a\\|b"


def test_bloco_antigo_e_substituido_pelo_atual():
    first = reg.update_text(BASE)
    stale = first.replace(reg.render_block(), reg.START + "\nvelho\n" + reg.END)
    out = reg.update_text(stale)
    assert "velho" not in out
    assert out == first


# --------------------------------------------------------------- linha de F2

def test_linha_de_f2_ganha_o_reparo_manual():
    lines = reg.update_text(BASE).split("\n")
    assert reg.NEW_F2_LINE in lines
    assert reg.OLD_F2_LINE not in lines


def test_reparo_cita_modo_binario_e_eal_verify():
    for word in ("modo binário", "`eal verify`", "linha incompleta", "não foi testado"):
        assert word in reg.NEW_F2_LINE


def test_linha_vizinha_continua_igual():
    assert "- O `fsync` pede ao sistema operacional que grave no disco." in reg.update_text(BASE).split("\n")


def test_so_a_linha_exata_e_trocada_mesmo_com_o_texto_dentro_de_outra_linha():
    copy_line = "> Citação: " + reg.OLD_F2_LINE
    text = BASE.replace("# Projeto", "# Projeto\n\n" + copy_line)
    out = reg.update_text(text).split("\n")
    assert copy_line in out
    assert reg.NEW_F2_LINE in out
    assert reg.OLD_F2_LINE not in out


def test_linha_de_f2_editada_a_mao_recusa():
    edited = BASE.replace(reg.OLD_F2_LINE, reg.OLD_F2_LINE + " (editado)")
    with pytest.raises(reg.RegError, match="não atômica"):
        reg.update_text(edited)


def test_linha_de_f2_ausente_recusa():
    with pytest.raises(reg.RegError, match="não atômica"):
        reg.update_text(BASE.replace(reg.OLD_F2_LINE, "outra coisa"))


def test_linha_de_f2_repetida_recusa():
    with pytest.raises(reg.RegError, match="não atômica"):
        reg.update_text(BASE + reg.OLD_F2_LINE + "\n")


def test_linha_antiga_e_nova_ao_mesmo_tempo_recusa():
    with pytest.raises(reg.RegError, match="não atômica"):
        reg.update_text(BASE + reg.NEW_F2_LINE + "\n")


# ------------------------------------------------------------------ âncoras

def test_sem_a_nota_do_gate_recusa():
    with pytest.raises(reg.RegError, match="nota"):
        reg.update_text(BASE.replace(reg.AFTER, ""))


def test_nota_do_gate_repetida_recusa():
    with pytest.raises(reg.RegError, match="nota"):
        reg.update_text(BASE.replace(reg.AFTER, reg.AFTER + "\n" + reg.AFTER))


@pytest.mark.parametrize("extra", [reg.START, reg.END, reg.START + "\n" + reg.START + "\n" + reg.END])
def test_ancoras_inconsistentes_recusam(extra):
    with pytest.raises(reg.RegError, match="âncoras"):
        reg.update_text(BASE + extra + "\n")


def test_ancora_de_fim_antes_da_de_inicio_recusa():
    with pytest.raises(reg.RegError, match="antes"):
        reg.update_text(BASE + reg.END + "\n" + reg.START + "\n")


# ----------------------------------------------------------- idempotência

def test_segunda_aplicacao_nao_muda_nada():
    once = reg.update_text(BASE)
    assert reg.update_text(once) == once


# ----------------------------------------------------------------- arquivo

def test_write_project_preserva_crlf_e_e_idempotente(tmp_path):
    path = put(tmp_path, BASE, crlf=True)
    assert reg.write_project(path) is True
    raw = path.read_bytes()
    assert raw.count(b"\n") == raw.count(b"\r\n")
    assert reg.write_project(path) is False
    assert path.read_bytes() == raw


def test_write_project_lf_continua_lf(tmp_path):
    path = put(tmp_path, BASE)
    assert reg.write_project(path) is True
    assert b"\r" not in path.read_bytes()


def test_write_project_mistura_recusa_sem_tocar(tmp_path):
    original = ("a\r\n" + BASE).encode("utf-8")
    path = tmp_path / "PROJECT.md"
    path.write_bytes(original)
    with pytest.raises(reg.RegError, match="mistura"):
        reg.write_project(path)
    assert path.read_bytes() == original


def test_write_project_nao_utf8_recusa_sem_tocar(tmp_path):
    original = b"\xff\n" + BASE.encode("utf-8")
    path = tmp_path / "PROJECT.md"
    path.write_bytes(original)
    with pytest.raises(reg.RegError, match="UTF-8"):
        reg.write_project(path)
    assert path.read_bytes() == original


def test_write_project_falha_de_conferencia_nao_grava(tmp_path):
    original = BASE.replace(reg.AFTER, "")
    path = put(tmp_path, original)
    with pytest.raises(reg.RegError):
        reg.write_project(path)
    assert path.read_text(encoding="utf-8") == original


# -------------------------------------------------------------------- main

def test_main_grava_e_devolve_0(tmp_path, capsys):
    put(tmp_path, BASE, crlf=True)
    assert reg.main([], _root=tmp_path) == 0
    assert "gravadas" in capsys.readouterr().out


def test_main_segunda_vez_diz_que_nada_mudou(tmp_path, capsys):
    put(tmp_path, BASE)
    reg.main([], _root=tmp_path)
    capsys.readouterr()
    assert reg.main([], _root=tmp_path) == 0
    assert "nada mudou" in capsys.readouterr().out


def test_main_falha_devolve_1_e_nao_grava(tmp_path, capsys):
    original = BASE.replace(reg.OLD_F2_LINE, "outra coisa")
    path = put(tmp_path, original)
    assert reg.main([], _root=tmp_path) == 1
    assert path.read_text(encoding="utf-8") == original
    assert "nada foi gravado" in capsys.readouterr().err


def test_main_sem_arquivo_devolve_1(tmp_path):
    assert reg.main([], _root=tmp_path) == 1


def test_main_rejeita_argumento_desconhecido():
    with pytest.raises(SystemExit):
        reg.main(["--nao-existe"])
