"""Testes das correções da revisão adversarial do Dia 5, parte 1 (eal/cli.py).

F1: ``verify --sem-cadeia --expected-head`` ignorava a cabeça em silêncio.
    Agora as duas opções juntas são erro de uso (código 2), antes de ler o arquivo.
F4: ``run --sources`` era validado e nunca usado. Agora a lista de fontes aceitas
    (``_SOURCE_FACTORIES``) é a mesma que cria as fontes do ``run``.

Nenhum teste aqui roda o pipeline real nem grava fora de ``tmp_path``.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from types import SimpleNamespace

import pytest

from eal import cli

ROOT = Path(__file__).resolve().parents[1]
GUARDED = (Path("keys"), Path("data") / "receipts", Path("data") / "logs", Path("data") / "public_keys")
HEAD = "0" * 64


def _snapshot() -> list[tuple[str, int, int]]:
    items: list[tuple[str, int, int]] = []
    for rel in GUARDED:
        base = ROOT / rel
        if base.is_dir():
            for path in sorted(base.rglob("*")):
                if path.is_file():
                    st = path.stat()
                    items.append((str(path.relative_to(ROOT)), st.st_size, st.st_mtime_ns))
    return items


@pytest.fixture(autouse=True)
def _nunca_gravar_nas_pastas_reais():
    before = _snapshot()
    yield
    assert _snapshot() == before, "o teste mexeu nas pastas reais do projeto"


# ------------------------------------------------------------------- F1

@pytest.mark.parametrize("order", [
    ["--sem-cadeia", "--expected-head", HEAD],
    ["--expected-head", HEAD, "--sem-cadeia"],
])
def test_f1_sem_cadeia_com_expected_head_e_erro_de_uso(tmp_path, capsys, order):
    code = cli.main(["verify", str(tmp_path / "nao_existe.json"), *order])
    out, err = capsys.readouterr()
    assert code == 2
    assert out == ""
    assert "--sem-cadeia" in err and "--expected-head" in err


def test_f1_erro_de_uso_vem_antes_de_ler_o_arquivo(tmp_path, capsys, monkeypatch):
    # Sem isto, a chave pública (real ou não) decidiria o caminho antes do arquivo.
    monkeypatch.setattr(cli, "_load_public", lambda keys_dir: b"pk")
    code = cli.main(["verify", str(tmp_path / "nao_existe.json"), "--sem-cadeia", "--expected-head", HEAD])
    assert code == 2
    assert "não encontrado" not in capsys.readouterr().err


def test_f1_cada_opcao_sozinha_continua_aceita():
    parser = cli._build_parser()
    only_flag = parser.parse_args(["verify", "x.json", "--sem-cadeia"])
    assert only_flag.sem_cadeia is True and only_flag.expected_head is None
    only_head = parser.parse_args(["verify", "x.json", "--expected-head", "a" * 64])
    assert only_head.sem_cadeia is False and only_head.expected_head == "a" * 64


def test_f1_sem_nenhuma_das_duas_continua_aceito():
    args = cli._build_parser().parse_args(["verify", "x.json"])
    assert args.sem_cadeia is False and args.expected_head is None


# ------------------------------------------------------------------- F4

def test_f4_toda_fonte_com_fabrica_e_aceita_pelo_argumento():
    for name in cli._SOURCE_FACTORIES:
        assert cli._sources_arg(name) == name


def test_f4_os_e_a_unica_fonte_desta_versao():
    # Uma fonte nova exige mudar este teste de propósito (Dia 6: IBM).
    assert set(cli._SOURCE_FACTORIES) == {"os"}


def test_f4_espacos_em_volta_continuam_aceitos():
    assert cli._sources_arg(" os ") == "os"


@pytest.mark.parametrize("value,fragment", [
    ("qpu_sim", "simulada"),
    ("faulty_bias", "simulada"),
    ("os,qpu_sim", "simulada"),
    ("ibm_kingston", "IBM"),
    ("qpu_ibm", "IBM"),
    ("xyz", "desconhecida"),
    ("os,os", "desconhecida"),
    ("", "desconhecida"),
])
def test_f4_valores_recusados_continuam_recusados_com_a_mesma_mensagem(value, fragment):
    with pytest.raises(argparse.ArgumentTypeError) as info:
        cli._sources_arg(value)
    assert fragment in str(info.value)


def _run_args(tmp_path: Path, *extra: str) -> list[str]:
    return [
        "run",
        "--keys-dir", str(tmp_path / "keys"),
        "--receipts-dir", str(tmp_path / "receipts"),
        "--public-keys-dir", str(tmp_path / "pk"),
        "--logs-dir", str(tmp_path / "logs"),
        *extra,
    ]


@pytest.fixture
def run_stubs(monkeypatch):
    """Para o run logo depois de escolher as fontes, sem pipeline real."""
    seen: dict = {"factory_calls": 0}

    def fake_keygen(sources, seed_source, n_bits, logs_dir=None):  # F12: _run_keygen recebe logs_dir
        seen["sources"] = sources
        raise cli._Fail("pipeline", "parado pelo teste")

    monkeypatch.setattr(cli, "_run_keygen", fake_keygen)
    monkeypatch.setattr(cli, "_load_issuer", lambda keys_dir: SimpleNamespace(pk=b"pk"))
    monkeypatch.setattr(cli, "_current_head", lambda receipts_dir, pk: HEAD)
    return seen


def test_f4_run_usa_a_fabrica_da_fonte_escolhida(tmp_path, monkeypatch, run_stubs):
    marker = [object()]

    def factory():
        run_stubs["factory_calls"] += 1
        return marker

    monkeypatch.setitem(cli._SOURCE_FACTORIES, "os", factory)
    assert cli.main(_run_args(tmp_path, "--sources", "os")) == 1
    assert run_stubs["sources"] is marker
    assert run_stubs["factory_calls"] == 1


def test_f4_run_sem_sources_usa_a_fabrica_padrao(tmp_path, monkeypatch, run_stubs):
    marker = [object()]
    monkeypatch.setitem(cli._SOURCE_FACTORIES, "os", lambda: marker)
    assert cli.main(_run_args(tmp_path)) == 1
    assert run_stubs["sources"] is marker


def test_f4_fontes_injetadas_pelos_testes_tem_prioridade(tmp_path, monkeypatch, run_stubs):
    monkeypatch.setitem(cli._SOURCE_FACTORIES, "os", lambda: pytest.fail("a fábrica não devia ser chamada"))
    injected = [object()]
    assert cli.main(_run_args(tmp_path), _sources=injected) == 1
    assert run_stubs["sources"] is injected


def test_f4_cadeia_ruim_para_antes_de_criar_as_fontes(tmp_path, monkeypatch, run_stubs):
    calls = {"n": 0}

    def factory():
        calls["n"] += 1
        return [object()]

    def bad_head(receipts_dir, pk):
        raise cli._Fail("chain", "cadeia ruim (teste)")

    monkeypatch.setitem(cli._SOURCE_FACTORIES, "os", factory)
    monkeypatch.setattr(cli, "_current_head", bad_head)
    assert cli.main(_run_args(tmp_path)) == 1
    assert calls["n"] == 0
    assert "sources" not in run_stubs
