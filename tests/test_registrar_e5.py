"""Testes de scripts/registrar_e5.py (registro do E5, etapa A, no PROJECT.md, Dia 7)."""
from __future__ import annotations

import hashlib
import importlib.util
import math
import re
import sys
from pathlib import Path

import numpy as np
import pytest

_RAIZ = Path(__file__).resolve().parent.parent / "scripts"


def _carregar(nome: str, arquivo: str):
    spec = importlib.util.spec_from_file_location(nome, _RAIZ / arquivo)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[nome] = mod
    spec.loader.exec_module(mod)
    return mod


reg = _carregar("_registrar_e5", "registrar_e5.py")
e5 = _carregar("_e5_para_teste_registro", "e5_chsh.py")

COMMIT = reg.COMMIT_CURTO + "0" * 33
PROJECT = (b"# Projeto\r\n\r\ntexto antigo\r\n"
           b"<!-- dia7-e3:start -->\r\nx\r\n<!-- dia7-e3:end -->\r\n")


def probs_analiticas(ta, tb):
    c = math.cos(ta - tb)
    return np.array([(1 + c) / 4, (1 - c) / 4, (1 - c) / 4, (1 + c) / 4])


class RuidoFalso:
    info = {"par_fisico": "147-148", "erro_cz": "0.0024336098672234907",
            "erro_leitura_q0": "0.005859375", "erro_leitura_q1": "0.002197265625",
            "calibracao_backend": "2026-04-15T09:15:15+02:00", "n_2q_por_circuito": "1"}

    def __init__(self):
        self.probs = [0.97 * probs_analiticas(e5.ANGULOS_A[i], e5.ANGULOS_B[j]) + 0.0075
                      for i, j in e5.AJUSTES]

    def contagens(self, seed):
        rng = np.random.default_rng(seed)
        return [e5.amostrar(rng, p, e5.N_SHOTS) for p in self.probs]


MOTOR = e5.Motor(probs_exatas=probs_analiticas, preparar_ruido=RuidoFalso)


def todas_as_linhas(commit=COMMIT):
    ruido = RuidoFalso()
    return [l for c in e5.CONFIGS for l in e5.rodar_config(MOTOR, c, e5.REPS, commit, ruido)]


@pytest.fixture(scope="module")
def linhas_base():
    return todas_as_linhas()


def gravar_dados(raiz: Path, linhas, resumo=None):
    pasta = raiz / "data" / "results"
    pasta.mkdir(parents=True, exist_ok=True)
    (pasta / "e5_rodadas.csv").write_bytes(e5.csv_bytes(e5.CAMPOS, linhas))
    res = e5.resumir(linhas) if resumo is None else resumo
    (pasta / "e5_resumo.csv").write_bytes(e5.csv_bytes(e5.CAMPOS_RESUMO, res))


@pytest.fixture
def ambiente(tmp_path, monkeypatch, linhas_base):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "PROJECT.md").write_bytes(PROJECT)
    monkeypatch.setattr(reg, "HASH_ANTES", hashlib.sha256(PROJECT).hexdigest())
    gravar_dados(tmp_path, [dict(l) for l in linhas_base])
    return tmp_path


def rodar():
    saida: list[str] = []
    return reg.main(saida.append), saida


def bloco(raiz: Path) -> list[str]:
    t = (raiz / "PROJECT.md").read_bytes().decode("utf-8")
    return t[t.index(reg.START):].split("\r\n")


def refazer(raiz: Path, linhas):
    for n in ("e5_rodadas.csv", "e5_resumo.csv"):
        (raiz / "data" / "results" / n).unlink()
    gravar_dados(raiz, linhas)


def com(linhas_base, cfg, **campos):
    return [dict(l, **campos) if l["configuracao"] == cfg else dict(l) for l in linhas_base]


# ---------------------------------------------------------------- dados de teste
def test_dados_de_teste_cumprem_os_criterios(linhas_base):
    res = {r["configuracao"]: r for r in e5.resumir(linhas_base)}
    assert all(res[c]["criterio_ok"] == "True" for c in e5.CONFIGS)
    assert len(linhas_base) == 1 + 4 * e5.REPS


# ---------------------------------------------------------------- formatação
def test_formatacao():
    assert reg.d_pt("2.828427") == "2,828427" and reg.d_pt("") == "-"
    assert reg.f6(0.0693) == "0,069300"


# ---------------------------------------------------------------- aplicação
def test_aplica_e_preserva_o_resto(ambiente):
    codigo, saida = rodar()
    assert codigo == 0 and saida[0].startswith("aplicado")
    dados = (ambiente / "PROJECT.md").read_bytes()
    assert dados.startswith(PROJECT + b"\r\n" + reg.START.encode())
    assert dados.endswith(reg.END.encode() + b"\r\n")
    assert dados.count(b"\n") == dados.count(b"\r\n")
    assert saida[0] == f"aplicado; PROJECT.md: {hashlib.sha256(dados).hexdigest()}"
    assert not list(ambiente.glob("*.tmp"))


def test_idempotente(ambiente):
    assert rodar()[0] == 0
    antes = (ambiente / "PROJECT.md").read_bytes()
    codigo, saida = rodar()
    assert codigo == 0 and saida[0].startswith("já aplicado")
    assert (ambiente / "PROJECT.md").read_bytes() == antes


def test_protocolo_hashes_e_par(ambiente, linhas_base):
    rodar()
    b = bloco(ambiente)
    t = "\n".join(b)
    assert f"rodada sobre o commit `{COMMIT}`, conferido na coluna `commit` das {len(linhas_base)} linhas." in t
    assert "Alice mede em 0 e π/2 e Bob em π/4 e −π/4" in t
    assert "4000 shots por ajuste (16000 por estimativa de S) e 100 repetições" in t
    assert "Margem dos critérios: 3 erros-padrão" in t
    assert ("**Par físico do ruído simulado:** qubits 147-148 do `FakeKingston`; erro de CZ 0,0024336098672234907; "
            "erro médio de leitura 0,005859375 e 0,002197265625; calibração 2026-04-15T09:15:15+02:00.") in b
    for nome in ("e5_rodadas.csv", "e5_resumo.csv"):
        h = hashlib.sha256((ambiente / "data" / "results" / nome).read_bytes()).hexdigest()
        assert f"- `{nome}`: `{h}`" in b


def test_tabela_vem_do_resumo(ambiente):
    rodar()
    b = bloco(ambiente)
    res = e5.resumir(todas_as_linhas())
    tab = [l for l in b if l.startswith("| `")]
    assert len(tab) == 5
    for r, l in zip(res, tab):
        assert l == reg.tabela([r])[2]
        assert l.count("|") == 12
    assert tab[0].startswith("| `ideal_exato` | S = 2*raiz(2) (exato) | 1 | 2,828427 | 0,000000 |")
    assert tab[4].endswith("| 0,000000 | cumprido |") and "| 2,000000 | 0,000000 |" in tab[4]
    assert "| Fração S > 2 | Margem | Critério |" in "\n".join(b)


def test_frases_calculadas(ambiente, linhas_base):
    rodar()
    t = "\n".join(bloco(ambiente))
    assert ("Critérios pré-registrados cumpridos em: `ideal_exato`, `ideal_amostrado`, `ruido_fake_kingston`, "
            "`classico_aleatorio`, `classico_otimo`. Nenhuma configuração deixou de cumprir o critério.") in t
    g = reg.por_config(linhas_base)
    a, b = reg.ss(g["ideal_amostrado"]), reg.ss(g["ruido_fake_kingston"])
    import statistics
    dif = statistics.fmean(a) - statistics.fmean(b)
    assert dif > 0.05
    assert f"uma queda de {reg.f6(dif)}," in t
    se = math.sqrt(statistics.variance(a) / 100 + statistics.variance(b) / 100)
    assert f"{reg.f6(dif / se)} erros-padrão da diferença entre as médias." in t
    assert "S médio" in t and "compatível com 0 dentro da margem de" in t


def test_frases_estruturais(ambiente):
    rodar()
    t = "\n".join(bloco(ambiente))
    assert "O S exato do circuito" in t and "é 2√2, com tolerância de 1e-12." in t
    assert "em um único par físico" in t and "idênticas por construção" in t
    assert "dentro de 5%: √(2/N) = 0,022361 para o estado de Bell e √(4/N) = 0,031623" in t
    assert "entre 0,75 e 1,25 vezes o erro-padrão calculado" in t and "erro relativo de cerca de 7%" in t
    assert "**Ressalvas:**" in t and "limitação 6" in t and "limitação 5" in t
    assert t.count("\n- ") == 3 + 5 + 8 + 2


def test_criterio_nao_cumprido_vira_texto(ambiente, linhas_base):
    # o clássico ótimo deixa de ser clássico: S = 2,5 em todas as repetições (mantém se_s = 0)
    ruim = [dict(l, s="2.5") if l["configuracao"] == "classico_otimo" else dict(l) for l in linhas_base]
    refazer(ambiente, ruim)
    codigo, saida = rodar()
    assert codigo == 1 and "idênticas por construção" in saida[-1]        # a frase estrutural recusa
    # já o ideal amostrado fora do critério gera texto, sem recusa
    deslocado = [dict(l, s=repr(float(l["s"]) - 0.2)) if l["configuracao"] == "ideal_amostrado" else dict(l)
                 for l in linhas_base]
    refazer(ambiente, deslocado)
    codigo, saida = rodar()
    t = "\n".join(bloco(ambiente))
    assert codigo == 0, saida
    assert "Não cumpridos em: `ideal_amostrado`." in t and "Nenhuma configuração deixou" not in t


# ---------------------------------------------------------------- recusas
def estado(raiz: Path) -> dict[str, bytes]:
    return {str(p.relative_to(raiz)): p.read_bytes() for p in sorted(raiz.rglob("*")) if p.is_file()}


def recusa(raiz: Path, trecho: str):
    antes = estado(raiz)
    codigo, saida = rodar()
    assert codigo == 1 and saida[-1].startswith("RECUSADO") and re.search(trecho, saida[-1]), saida
    assert estado(raiz) == antes


def test_recusa_hash_marcador_crlf(ambiente, monkeypatch):
    monkeypatch.setattr(reg, "HASH_ANTES", "0" * 64)
    recusa(ambiente, "difere de HASH_ANTES")
    novo = PROJECT + reg.START.encode() + b"\r\n"
    (ambiente / "PROJECT.md").write_bytes(novo)
    monkeypatch.setattr(reg, "HASH_ANTES", hashlib.sha256(novo).hexdigest())
    recusa(ambiente, "marcador")
    for dados in (PROJECT.replace(b"\r\n", b"\n"), PROJECT.rstrip(b"\r\n")):
        (ambiente / "PROJECT.md").write_bytes(dados)
        monkeypatch.setattr(reg, "HASH_ANTES", hashlib.sha256(dados).hexdigest())
        recusa(ambiente, "CRLF puro")


def test_recusa_project_ausente(ambiente):
    (ambiente / "PROJECT.md").unlink()
    codigo, saida = rodar()
    assert codigo == 1 and "arquivo ausente" in saida[-1]


@pytest.mark.parametrize("nome", ["e5_rodadas.csv", "e5_resumo.csv"])
def test_recusa_csv_ausente(ambiente, nome):
    (ambiente / "data" / "results" / nome).unlink()
    codigo, saida = rodar()
    assert codigo == 1 and ("não existe" in saida[-1] or "ausente" in saida[-1])


@pytest.mark.parametrize("nome,campo", [("e5_rodadas.csv", b"erro_cz"), ("e5_resumo.csv", b"margem")])
def test_recusa_cabecalho(ambiente, nome, campo):
    p = ambiente / "data" / "results" / nome
    p.write_bytes(p.read_bytes().replace(campo, b"outro", 1))
    recusa(ambiente, "cabeçalho")


@pytest.mark.parametrize("nome,campos", [("e5_rodadas.csv", e5.CAMPOS), ("e5_resumo.csv", e5.CAMPOS_RESUMO)])
def test_recusa_csv_sem_linhas(ambiente, nome, campos):
    (ambiente / "data" / "results" / nome).write_bytes(e5.csv_bytes(campos, []))
    recusa(ambiente, f"{re.escape(nome)}: sem linhas")


def test_recusa_resumo_adulterado(ambiente):
    p = ambiente / "data" / "results" / "e5_resumo.csv"
    p.write_bytes(p.read_bytes().replace(b"True", b"False", 1))
    recusa(ambiente, "derivação exata")


@pytest.mark.parametrize("commit", ["a" * 40, reg.COMMIT_CURTO + "X" * 33, reg.COMMIT_CURTO])
def test_recusa_commit(ambiente, linhas_base, commit):
    refazer(ambiente, [dict(l, commit=commit) for l in linhas_base])
    recusa(ambiente, "pré-registrada")


def test_recusa_dois_commits(ambiente, linhas_base):
    ls = [dict(l) for l in linhas_base]
    ls[0]["commit"] = reg.COMMIT_CURTO + "1" * 33
    refazer(ambiente, ls)
    recusa(ambiente, "mais de um commit")


def test_recusa_numero_de_repeticoes(ambiente, linhas_base):
    refazer(ambiente, [l for l in linhas_base if not (l["configuracao"] == "classico_aleatorio" and l["repeticao"] == "99")])
    recusa(ambiente, "classico_aleatorio: 99 repetições em vez de 100")


def test_recusa_n_shots(ambiente, linhas_base):
    refazer(ambiente, com(linhas_base, "ideal_amostrado", n_shots="1000"))
    recusa(ambiente, "ideal_amostrado: n_shots 1000 em vez de 4000")


def test_recusa_angulos_diferentes(ambiente, monkeypatch):
    real = reg.carregar_e5

    def alterado():
        m = real()
        m.ANGULOS_B = (math.pi / 4, math.pi / 4)
        return m

    monkeypatch.setattr(reg, "carregar_e5", alterado)
    recusa(ambiente, "ângulos do script")


@pytest.mark.parametrize("cfg,campos,trecho", [
    ("ideal_exato", {"s": "2.8"}, "S exato"),
    ("ruido_fake_kingston", {"par_fisico": "1-2"}, "único par físico"),
    ("ruido_fake_kingston", {"n_2q_por_circuito": "2"}, "único par físico"),
    ("classico_otimo", {"se_s": "0.01"}, "idênticas por construção"),
    ("ideal_amostrado", {"se_s": "0.04"}, "bate com o teórico"),
    ("classico_aleatorio", {"se_s": "0.05"}, "bate com o teórico"),
])
def test_recusa_afirmacao_estrutural(ambiente, linhas_base, cfg, campos, trecho):
    ls = com(linhas_base, cfg, **campos)
    if cfg == "ruido_fake_kingston" and "par_fisico" in campos:
        ls[[i for i, l in enumerate(ls) if l["configuracao"] == cfg][0]]["par_fisico"] = "147-148"
    refazer(ambiente, ls)
    recusa(ambiente, trecho)


def test_recusa_um_so_valor_diferente_no_par(ambiente, linhas_base):
    ls = [dict(l) for l in linhas_base]
    i = [k for k, l in enumerate(ls) if l["configuracao"] == "ruido_fake_kingston"][5]
    ls[i]["calibracao_backend"] = "2026-05-01T00:00:00+00:00"
    refazer(ambiente, ls)
    recusa(ambiente, "único par físico")


def test_recusa_dispersao_incompativel(ambiente, linhas_base):
    # desloca metade das repetições: dp entre repetições muito acima do erro-padrão calculado
    ls, k = [], 0
    for l in linhas_base:
        if l["configuracao"] == "ruido_fake_kingston":
            k += 1
            if k % 2:
                l = dict(l, s=repr(float(l["s"]) + 0.1))
        ls.append(dict(l))
    refazer(ambiente, ls)
    recusa(ambiente, "desvio-padrão de S entre repetições")


def test_recusa_dispersao_pequena_demais(ambiente, linhas_base):
    ls = [dict(l, s="0.0") if l["configuracao"] == "classico_aleatorio" else dict(l) for l in linhas_base]
    refazer(ambiente, ls)
    recusa(ambiente, "desvio-padrão de S entre repetições")


def test_exato_com_mais_de_uma_linha_recusa(linhas_base):
    res = {r["configuracao"]: r for r in e5.resumir(linhas_base)}
    exato = [l for l in linhas_base if l["configuracao"] == "ideal_exato"][0]
    com_duas = [dict(l) for l in linhas_base] + [dict(exato, repeticao="1")]
    with pytest.raises(reg.Refused, match="S exato"):
        reg.verificar(e5, com_duas, res)
    assert len(reg.verificar(e5, [dict(l) for l in linhas_base], res)) == 5


def test_par_fisico_vazio_recusa(ambiente, linhas_base):
    refazer(ambiente, com(linhas_base, "ruido_fake_kingston", par_fisico=""))
    recusa(ambiente, "único par físico")


def test_excecao_dentro_da_checagem_recusa(linhas_base):
    res = {r["configuracao"]: r for r in e5.resumir(linhas_base)}
    sem_ruido = [l for l in linhas_base if l["configuracao"] != "ruido_fake_kingston"]
    with pytest.raises(reg.Refused, match="afirmação não confirmada"):
        reg.verificar(e5, sem_ruido, res)
    # ruído presente mas com a coluna do par ausente: KeyError dentro da checagem
    quebradas = [{k: v for k, v in l.items() if k != "par_fisico"} if l["configuracao"] == "ruido_fake_kingston"
                 else dict(l) for l in linhas_base]
    with pytest.raises(reg.Refused):
        reg.verificar(e5, quebradas, res)


def test_margem_citada_e_a_do_aleatorio(ambiente):
    rodar()
    res = {r["configuracao"]: r for r in e5.resumir(todas_as_linhas())}
    t = "\n".join(bloco(ambiente))
    assert f"dentro da margem de {reg.f6(float(res['classico_aleatorio']['margem']))}." in t
    assert res["classico_aleatorio"]["margem"] != res["ruido_fake_kingston"]["margem"]


def test_hashes_na_ordem(ambiente):
    rodar()
    nomes = [re.match(r"- `(e5_\w+\.csv)`", l).group(1) for l in bloco(ambiente) if re.match(r"- `e5_\w+\.csv`", l)]
    assert nomes == ["e5_rodadas.csv", "e5_resumo.csv"]


def test_verificar_estrutura_inesperada():
    with pytest.raises(reg.Refused, match="estrutura inesperada"):
        reg.verificar(e5, [{"configuracao": "ideal_exato"}], {})


def test_ja_aplicado_exige_prefixo_original():
    ins = b"\r\nBLOCO\r\n"
    antigo, reg.HASH_ANTES = reg.HASH_ANTES, hashlib.sha256(PROJECT).hexdigest()
    try:
        assert reg.aplicar(PROJECT, ins) == PROJECT + ins
        assert reg.aplicar(PROJECT + ins, ins) is None
        with pytest.raises(reg.Refused):
            reg.aplicar(PROJECT + b"extra\r\n" + ins, ins)
    finally:
        reg.HASH_ANTES = antigo


def test_insercao_sem_cr():
    with pytest.raises(reg.Refused):
        reg.preparar_insercao("a\rb")
    assert reg.preparar_insercao("a\nb") == b"\r\na\r\nb\r\n"


def test_hash_antes_e_commit_fixos():
    fonte = (_RAIZ / "registrar_e5.py").read_text(encoding="utf-8")
    assert 'HASH_ANTES = "d97b0abdae12aa17c03ec1eb313d3c0e22effd7dcfb68e2c3091447fe65e4c57"' in fonte
    assert 'COMMIT_CURTO = "a467431"' in fonte
    assert reg.START == "<!-- dia7-e5a:start -->" and reg.END == "<!-- dia7-e5a:end -->"
