"""Testes do script que registra o commit verificado dos vetores ACVP.

Tudo roda em pasta temporária. A barreira garante que nenhum teste toca no
SOURCE.json ou no PROJECT.md reais.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from scripts import corrigir_source_kat_dia5 as corr

ROOT = Path(__file__).resolve().parents[1]
SUBSET = {
    "ml_kem_768_keygen.json": "8f656a8297358b31a2ecd7a900955d84f2eb265541b1384e6a08d620a4a77431",
    "ml_dsa_65_keygen.json": "979d8586651fd425c5f4680830b43638f2f78bca595f035d892377ce71cdad64",
}
PROJECT_BASE = (
    "# Projeto\n\n### Limitações do Dia 5 (etapa 1: derivação PQC)\n\n"
    "- Os vetores são o subconjunto de ML-KEM-768 e ML-DSA-65 do branch master do "
    "ACVP-Server, " + corr.OLD_SENTENCE + "\n\n## 17. Limitações conhecidas\n"
)


def _snapshot() -> list[tuple[str, int, int]]:
    items = []
    for rel in (corr.SOURCE_REL, corr.PROJECT_REL):
        path = ROOT / rel
        if path.is_file():
            st = path.stat()
            items.append((str(rel), st.st_size, st.st_mtime_ns))
    return items


@pytest.fixture(autouse=True)
def _nunca_tocar_no_projeto_real():
    before = _snapshot()
    yield
    assert _snapshot() == before, "o teste mexeu em arquivo real do projeto"


def original_source() -> dict:
    """Mesma forma do SOURCE.json registrado antes da correção."""
    files = {}
    for name, ver in corr.VERIFIED.items():
        files[name] = {
            "url": corr.URL_BASE + ver["caminho"],
            "parameterSet": "ML-KEM-768" if "kem" in name else "ML-DSA-65",
            "vsId": 42,
            "testes": 25,
            "original_bytes": ver["original_bytes"],
            "original_sha3_256_bytes": ver["original_sha3_256_bytes"],
            "subconjunto_sha3_256_canonico": SUBSET[name],
        }
    return {
        "fonte": "https://github.com/usnistgov/ACVP-Server (gen-val/json-files)",
        "branch": "master",
        "commit": "não registrado (a API do GitHub estava com limite de requisições)",
        "baixado_em": "2026-10-30T18:27:24.422057+00:00",
        "arquivos": files,
    }


def original_bytes(obj: dict | None = None) -> bytes:
    return (json.dumps(obj or original_source(), indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def _load(raw: bytes) -> dict:
    return json.loads(raw.decode("utf-8"))


# ----------------------------------------------------------- SOURCE.json

def test_commits_sao_registrados_por_arquivo():
    out = _load(corr.corrigir_source(original_bytes()))
    assert out["arquivos"]["ml_kem_768_keygen.json"]["commit"] == corr.VERIFIED["ml_kem_768_keygen.json"]["commit"]
    assert out["arquivos"]["ml_dsa_65_keygen.json"]["commit"] == corr.VERIFIED["ml_dsa_65_keygen.json"]["commit"]
    assert out["arquivos"]["ml_kem_768_keygen.json"]["commit_data"] == "2026-04-16T16:41:44-04:00"


def test_commit_do_ml_kem_e_o_que_o_handoff_citava():
    assert corr.VERIFIED["ml_kem_768_keygen.json"]["commit"].startswith("15c0f3de")


def test_rotulo_de_topo_deixa_de_dizer_nao_registrado():
    out = _load(corr.corrigir_source(original_bytes()))
    assert out["commit"] == corr.COMMIT_LABEL
    assert "não registrado" not in json.dumps(out)


def test_vetores_nao_mudam():
    before = original_source()
    out = _load(corr.corrigir_source(original_bytes(before)))
    for name in corr.VERIFIED:
        for key in ("subconjunto_sha3_256_canonico", "original_bytes",
                    "original_sha3_256_bytes", "parameterSet", "vsId", "testes", "url"):
            assert out["arquivos"][name][key] == before["arquivos"][name][key]
    assert out["baixado_em"] == before["baixado_em"]
    assert out["fonte"] == before["fonte"]
    assert out["branch"] == before["branch"]


def test_metodo_e_data_da_verificacao_registrados():
    out = _load(corr.corrigir_source(original_bytes()))
    assert out["verificado_em"] == corr.VERIFIED_EM
    assert out["metodo_verificacao"] == corr.METODO
    assert out["master_consultado"] == corr.MASTER_CONSULTADO


def test_saida_e_idempotente():
    once = corr.corrigir_source(original_bytes())
    assert corr.corrigir_source(once) is None


def test_crlf_do_arquivo_original_e_preservado():
    raw = original_bytes().replace(b"\n", b"\r\n")
    out = corr.corrigir_source(raw)
    assert out.count(b"\n") == out.count(b"\r\n")


def test_recusa_sha3_registrado_diferente_do_verificado():
    obj = original_source()
    obj["arquivos"]["ml_kem_768_keygen.json"]["original_sha3_256_bytes"] = "0" * 64
    with pytest.raises(corr.CorrError, match="SHA3-256"):
        corr.corrigir_source(original_bytes(obj))


def test_recusa_tamanho_diferente_do_verificado():
    obj = original_source()
    obj["arquivos"]["ml_dsa_65_keygen.json"]["original_bytes"] = 1
    with pytest.raises(corr.CorrError, match="tamanho"):
        corr.corrigir_source(original_bytes(obj))


def test_recusa_url_que_nao_bate_com_o_caminho():
    obj = original_source()
    obj["arquivos"]["ml_kem_768_keygen.json"]["url"] = "https://exemplo.invalido/x.json"
    with pytest.raises(corr.CorrError, match="URL"):
        corr.corrigir_source(original_bytes(obj))


def test_recusa_arquivo_a_mais_ou_a_menos():
    obj = original_source()
    obj["arquivos"]["outro.json"] = obj["arquivos"].pop("ml_dsa_65_keygen.json")
    with pytest.raises(corr.CorrError, match="arquivos"):
        corr.corrigir_source(original_bytes(obj))


def test_recusa_campo_de_topo_estranho():
    obj = original_source()
    obj["sobra"] = "x"
    with pytest.raises(corr.CorrError, match="campos de topo"):
        corr.corrigir_source(original_bytes(obj))


def test_recusa_commit_que_nao_e_o_esperado():
    obj = original_source()
    obj["commit"] = "abc123"
    with pytest.raises(corr.CorrError, match="commit"):
        corr.corrigir_source(original_bytes(obj))


def test_recusa_json_invalido():
    with pytest.raises(corr.CorrError):
        corr.corrigir_source(b"{nao e json")


def test_recusa_chave_repetida():
    raw = b'{"fonte": 1, "fonte": 2}'
    with pytest.raises(corr.CorrError):
        corr.corrigir_source(raw)


# ------------------------------------------------------------ PROJECT.md

def test_frase_do_projeto_e_trocada_uma_vez():
    out = corr.corrigir_projeto(PROJECT_BASE)
    assert corr.NEW_SENTENCE in out
    assert corr.OLD_SENTENCE not in out


def test_frase_do_projeto_e_idempotente():
    once = corr.corrigir_projeto(PROJECT_BASE)
    assert corr.corrigir_projeto(once) is None


def test_frase_do_projeto_ausente_recusa():
    with pytest.raises(corr.CorrError, match="PROJECT.md"):
        corr.corrigir_projeto(PROJECT_BASE.replace(corr.OLD_SENTENCE, "outra coisa"))


def test_frase_do_projeto_repetida_recusa():
    with pytest.raises(corr.CorrError, match="PROJECT.md"):
        corr.corrigir_projeto(PROJECT_BASE + "\n" + corr.OLD_SENTENCE)


# ------------------------------------------------------------------ main

def _tree(root: Path, source: bytes, project: str) -> tuple[Path, Path]:
    src = root / corr.SOURCE_REL
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_bytes(source)
    prj = root / corr.PROJECT_REL
    prj.write_bytes(project.encode("utf-8"))
    return src, prj


def test_main_corrige_as_duas_partes(tmp_path, capsys):
    src, prj = _tree(tmp_path, original_bytes(), PROJECT_BASE)
    assert corr.main([], _root=tmp_path) == 0
    assert corr.NEW_SENTENCE in prj.read_text(encoding="utf-8")
    assert _load(src.read_bytes())["commit"] == corr.COMMIT_LABEL
    assert "já estava" not in capsys.readouterr().out


def test_main_segunda_vez_nao_muda_nada(tmp_path, capsys):
    src, prj = _tree(tmp_path, original_bytes(), PROJECT_BASE)
    corr.main([], _root=tmp_path)
    before = (src.read_bytes(), prj.read_bytes())
    capsys.readouterr()
    assert corr.main([], _root=tmp_path) == 0
    assert (src.read_bytes(), prj.read_bytes()) == before
    assert "nada mudou" in capsys.readouterr().out


def test_main_se_o_projeto_falha_nao_grava_o_source(tmp_path, capsys):
    original_src = original_bytes()
    src, prj = _tree(tmp_path, original_src, PROJECT_BASE.replace(corr.OLD_SENTENCE, "outra"))
    assert corr.main([], _root=tmp_path) == 1
    assert src.read_bytes() == original_src
    assert "nada foi gravado" in capsys.readouterr().err


def test_main_se_o_source_falha_nao_grava_o_projeto(tmp_path):
    bad = original_source()
    bad["arquivos"]["ml_kem_768_keygen.json"]["original_bytes"] = 1
    src, prj = _tree(tmp_path, original_bytes(bad), PROJECT_BASE)
    assert corr.main([], _root=tmp_path) == 1
    assert prj.read_text(encoding="utf-8") == PROJECT_BASE


def test_main_sem_arquivos_devolve_1(tmp_path):
    assert corr.main([], _root=tmp_path) == 1


def test_main_projeto_com_mistura_de_quebras_recusa(tmp_path):
    original = b"a\r\n" + PROJECT_BASE.encode("utf-8")
    src = tmp_path / corr.SOURCE_REL
    src.parent.mkdir(parents=True)
    src.write_bytes(original_bytes())
    prj = tmp_path / corr.PROJECT_REL
    prj.write_bytes(original)
    assert corr.main([], _root=tmp_path) == 1
    assert prj.read_bytes() == original


def test_main_preserva_crlf_do_projeto(tmp_path):
    crlf = PROJECT_BASE.replace("\n", "\r\n")
    _, prj = _tree(tmp_path, original_bytes(), crlf)
    assert corr.main([], _root=tmp_path) == 0
    raw = prj.read_bytes()
    assert raw.count(b"\n") == raw.count(b"\r\n")
