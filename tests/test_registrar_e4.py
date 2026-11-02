"""Testes de scripts/registrar_e4.py (registro do E4 no PROJECT.md, Dia 7)."""
from __future__ import annotations

import csv
import hashlib
import importlib.util
import re
import sys
from pathlib import Path

import pytest

_RAIZ = Path(__file__).resolve().parent.parent / "scripts"


def _carregar(nome: str, arquivo: str):
    spec = importlib.util.spec_from_file_location(nome, _RAIZ / arquivo)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[nome] = mod
    spec.loader.exec_module(mod)
    return mod


reg = _carregar("_registrar_e4", "registrar_e4.py")
e4 = _carregar("_e4_para_teste_registro", "e4_mistura.py")

COMMIT = reg.COMMIT_CURTO + "0" * 33
N = 20
R = 10
PROJECT = (b"# Projeto\r\n\r\ntexto antigo\r\n"
           b"<!-- dia7-coleta3:start -->\r\nx\r\n<!-- dia7-coleta3:end -->\r\n")


def linha(cen, comb, k, rep, *, aprovada="True", n_sem=N, rec=0, distintas=N, alvo="",
          z="3.1", pos="0", falhas="", p=None, commit=COMMIT):
    p = f"0.{rep + 10:02d}" if p is None else p
    d = dict.fromkeys(e4.CAMPOS_SEQ, "")
    d.update(schema=e4.SCHEMA, commit=commit, cenario=cen, combinador=comb, k=k,
             repeticao=str(rep), semente=str(rep), esperado=e4.ESPERADO[(cen, comb)],
             n_sementes=str(n_sem), n_recusadas=str(rec), aprovada=aprovada,
             p_monobit="" if aprovada == "" else p, p_block="" if aprovada == "" else p,
             p_runs="" if aprovada == "" else p, n_distintas=str(distintas), n_alvo=alvo,
             max_abs_z=z, n_pos_z5=pos, n_falhas_forca=falhas, t_s="0.1000")
    return d


def celula(cen, comb, k="", reps=R, **kw):
    """Uma célula; `aprov` dá o padrão de aprovação por repetição (padrão: 9 de 10)."""
    aprov = kw.pop("aprov", None)
    out = []
    for r in range(reps):
        a = ("False" if r == 0 else "True") if aprov is None else aprov[r]
        out.append(linha(cen, comb, k, r, aprovada=a, **kw))
    return out


def spec_padrao() -> dict:
    s = {}
    for cen in reg.SEGURAS:
        for comb in ("hash", "xor"):
            s[(cen, comb, "")] = dict()
    s[("copia", "hash", "")] = dict(aprov=[""] * R, n_sem=0, rec=N, distintas=0, z="", pos="")
    s[("copia", "xor", "")] = dict(aprov=["False"] * R, p="0.0", distintas=1, z="4.4721", pos="512")
    s[("adv_alvo", "hash", "")] = dict(alvo="0")
    s[("adv_alvo", "xor", "")] = dict(alvo=str(N))
    for comb in ("hash", "xor"):
        s[("sem_fonte_boa", comb, "")] = dict(aprov=["False"] * R, p="0.0", distintas=1,
                                              z="4.4721", pos="512")
    s[("adv_forca", "hash", "1")] = dict(reps=4, aprov=["True", "True", "False", "False"],
                                         alvo=str(N), pos="1", falhas="0", z="4.4721")
    s[("adv_forca", "hash", "4")] = dict(reps=4, aprov=["False"] * 4, alvo=str(N), pos="4",
                                         falhas="0", z="4.4721")
    return s


def linhas_de(spec: dict) -> list[dict]:
    out = []
    for (cen, comb, k), kw in spec.items():
        out += celula(cen, comb, k, **dict(kw))
    return out


def gravar_dados(raiz: Path, linhas: list[dict]) -> None:
    pasta = raiz / "data" / "results"
    pasta.mkdir(parents=True, exist_ok=True)
    (pasta / "e4_sequencias.csv").write_bytes(e4.csv_bytes(e4.CAMPOS_SEQ, linhas))
    (pasta / "e4_resumo.csv").write_bytes(e4.csv_bytes(e4.CAMPOS_RESUMO, e4.resumir(linhas)))


@pytest.fixture
def ambiente(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "PROJECT.md").write_bytes(PROJECT)
    monkeypatch.setattr(reg, "HASH_ANTES", hashlib.sha256(PROJECT).hexdigest())
    gravar_dados(tmp_path, linhas_de(spec_padrao()))
    return tmp_path


def rodar():
    saida: list[str] = []
    return reg.main(saida.append), saida


def bloco(tmp_path: Path) -> list[str]:
    t = (tmp_path / "PROJECT.md").read_bytes().decode("utf-8")
    return t[t.index(reg.START):].split("\r\n")


# ---------------------------------------------------------------- formatação e dados
def test_formatacao():
    assert reg.n_pt("200000") == "200.000" and reg.d_pt("0.9700") == "0,9700"
    assert reg.d_pt("") == "-" and reg.faixa("1", "1") == "1" and reg.faixa("0", "7") == "0 a 7"
    assert reg.faixa("", "") == "-"


def test_identicas():
    ls = linhas_de(spec_padrao())
    assert reg.identicas(ls) == [("copia", "xor", ""), ("sem_fonte_boa", "hash", ""),
                                 ("sem_fonte_boa", "xor", "")]
    assert reg.identicas(celula("base_boa", "hash", reps=1, p="0.5")) == []
    so_p = celula("base_boa", "hash", reps=3, p="0.5")
    so_p[1]["max_abs_z"] = "3.9"                        # mesmo p, |z| diferente: não é idêntica
    assert reg.identicas(so_p) == []
    so_d = celula("base_boa", "hash", reps=3, p="0.5")
    so_d[2]["n_distintas"] = "19"
    assert reg.identicas(so_d) == []
    assert reg.nome(("adv_forca", "hash", "4")) == "`adv_forca k=4/hash`"
    assert reg.nome(("copia", "xor", "")) == "`copia/xor`"


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


def test_protocolo_hashes_e_identicas(ambiente):
    rodar()
    texto = "\n".join(bloco(ambiente))
    for nome in ("e4_sequencias.csv", "e4_resumo.csv"):
        h = hashlib.sha256((ambiente / "data" / "results" / nome).read_bytes()).hexdigest()
        assert f"- `{nome}`: `{h}`" in texto
    n_linhas = len(linhas_de(spec_padrao()))
    assert (f"rodada sobre o commit `{COMMIT}`, conferido na coluna `commit` das {n_linhas} "
            f"linhas; 16 células; 20 sementes de 512 bits por sequência.") in texto
    assert ("Nas células `copia/xor`, `sem_fonte_boa/hash`, `sem_fonte_boa/xor`, todas as "
            "sequências são idênticas") in texto
    assert "(`adv_forca`, k = 1, 4)" in texto
    assert "reprovaram só parte das sequências com k = 1 e todas com k = 4." in texto


def test_tabela_vem_do_resumo(ambiente):
    rodar()
    linhas = bloco(ambiente)
    with (ambiente / "data" / "results" / "e4_resumo.csv").open(encoding="utf-8", newline="") as f:
        res = list(csv.DictReader(f))
    tab = [l for l in linhas if l.startswith("| ") and not l.startswith("| Cenário")]
    assert len(tab) == len(res) == 16  # 14 + 2 valores de k
    for r, l in zip(res, tab):
        assert l == reg.tabela([r])[2]
        assert len(re.findall(r"(?<!\\)\|", l)) == 15
    alvo = next(l for l in tab if l.startswith("| adv_alvo | xor |"))
    assert "| insegura | 10 de 10 | 9 | 0,9000 |" in alvo and "| 1,0000 |" in alvo
    copia = next(l for l in tab if l.startswith("| copia | hash |"))
    assert "| sem_semente | 0 de 10 | 0 | - | - | 200 | - |" in copia
    forca = next(l for l in tab if l.startswith("| adv_forca | hash | 4 |"))
    assert forca.endswith("| 4 | 0 |")
    cab = next(l for l in linhas if l.startswith("| Cenário"))
    assert "Máx. \\|z\\|" in cab and len(re.findall(r"(?<!\\)\|", cab)) == 15


def test_leitura_e_ressalvas(ambiente):
    rodar()
    texto = "\n".join(bloco(ambiente))
    assert "os testes estatísticos não veem o controle" in texto
    assert "**Ressalvas:**" in texto and "O modelo é o pior caso." in texto
    assert texto.count("\n- ") == 7 + 6 + 2


# ---------------------------------------------------------------- recusas
def estado(tmp_path: Path) -> dict[str, bytes]:
    return {str(p.relative_to(tmp_path)): p.read_bytes() for p in sorted(tmp_path.rglob("*"))
            if p.is_file()}


def recusa(tmp_path: Path, trecho: str):
    antes = estado(tmp_path)
    codigo, saida = rodar()
    assert codigo == 1 and saida[-1].startswith("RECUSADO") and re.search(trecho, saida[-1]), saida
    assert estado(tmp_path) == antes


def test_recusa_hash_do_project(ambiente, monkeypatch):
    monkeypatch.setattr(reg, "HASH_ANTES", "0" * 64)
    recusa(ambiente, "difere de HASH_ANTES")


def test_recusa_marcador(ambiente, monkeypatch):
    novo = PROJECT + reg.START.encode() + b"\r\n"
    (ambiente / "PROJECT.md").write_bytes(novo)
    monkeypatch.setattr(reg, "HASH_ANTES", hashlib.sha256(novo).hexdigest())
    recusa(ambiente, "marcador")


@pytest.mark.parametrize("dados", [PROJECT.replace(b"\r\n", b"\n"), PROJECT.rstrip(b"\r\n")])
def test_recusa_nao_crlf_ou_sem_fim(ambiente, monkeypatch, dados):
    (ambiente / "PROJECT.md").write_bytes(dados)
    monkeypatch.setattr(reg, "HASH_ANTES", hashlib.sha256(dados).hexdigest())
    recusa(ambiente, "CRLF puro")


def test_recusa_project_ausente(ambiente):
    (ambiente / "PROJECT.md").unlink()
    codigo, saida = rodar()
    assert codigo == 1 and "arquivo ausente" in saida[-1]


@pytest.mark.parametrize("nome", ["e4_sequencias.csv", "e4_resumo.csv"])
def test_recusa_csv_ausente(ambiente, nome):
    (ambiente / "data" / "results" / nome).unlink()
    codigo, saida = rodar()
    assert codigo == 1 and "CSV ausente" in saida[-1]


def test_recusa_cabecalhos(ambiente):
    p = ambiente / "data" / "results" / "e4_resumo.csv"
    original = p.read_bytes()
    p.write_bytes(original.replace(b"frac_alvo", b"fracao", 1))
    recusa(ambiente, "cabeçalho")
    p.write_bytes(original)
    q = ambiente / "data" / "results" / "e4_sequencias.csv"
    q.write_bytes(q.read_bytes().replace(b"n_pos_z5", b"pos5", 1))
    recusa(ambiente, "cabeçalho")


def test_recusa_resumo_adulterado(ambiente):
    p = ambiente / "data" / "results" / "e4_resumo.csv"
    p.write_bytes(p.read_bytes().replace(b",0.9000,", b",0.9100,", 1))
    recusa(ambiente, "derivação exata")


@pytest.mark.parametrize("commit,trecho", [("a" * 40, "pré-registrada"),
                                           (reg.COMMIT_CURTO + "X" * 33, "pré-registrada"),
                                           (reg.COMMIT_CURTO, "pré-registrada")])
def test_recusa_commit(ambiente, commit, trecho):
    ls = linhas_de(spec_padrao())
    for l in ls:
        l["commit"] = commit
    gravar_dados(ambiente, ls)
    recusa(ambiente, trecho)


def test_recusa_dois_commits(ambiente):
    ls = linhas_de(spec_padrao())
    ls[0]["commit"] = reg.COMMIT_CURTO + "1" * 33
    gravar_dados(ambiente, ls)
    recusa(ambiente, "mais de um commit")


def mudar(spec, chave, **kw):
    spec[chave] = {**spec[chave], **kw}
    return spec


def mudar_linha(ls, cen, comb, k, rep, **kw):
    for l in ls:
        if (l["cenario"], l["combinador"], l["k"], l["repeticao"]) == (cen, comb, k, str(rep)):
            l.update(kw)
    return ls


@pytest.mark.parametrize("alterar,trecho", [
    (lambda: mudar_linha(linhas_de(spec_padrao()), "travada", "xor", "", 3, n_pos_z5="1"),
     "Com uma fonte boa"),
    (lambda: mudar_linha(linhas_de(spec_padrao()), "constante", "hash", "", 2, n_distintas="19"),
     "Com uma fonte boa"),
    (lambda: linhas_de(mudar(spec_padrao(), ("enviesada", "xor", ""), aprov=["False"] * R)),
     "Com uma fonte boa"),
    (lambda: linhas_de(mudar(spec_padrao(), ("copia", "hash", ""), aprov=["True"] * R, n_sem=N,
                             rec=0, distintas=N, z="3.0", pos="0")),
     "Cópia exata"),
    (lambda: linhas_de(mudar(spec_padrao(), ("copia", "xor", ""), distintas=2)), "Cópia exata"),
    (lambda: linhas_de(mudar(spec_padrao(), ("copia", "hash", ""), rec=N - 1)), "Cópia exata"),
    (lambda: mudar_linha(linhas_de(spec_padrao()), "adv_alvo", "xor", "", 4, n_alvo=str(N - 1)),
     "Fonte adversária"),
    (lambda: mudar_linha(linhas_de(spec_padrao()), "adv_alvo", "hash", "", 4, n_alvo="1"),
     "Fonte adversária"),
    (lambda: linhas_de(mudar(spec_padrao(), ("adv_alvo", "xor", ""), aprov=["False"] * R)),
     "Fonte adversária"),
    (lambda: mudar_linha(linhas_de(spec_padrao()), "adv_alvo", "hash", "", 1, n_distintas="19"),
     "Fonte adversária"),
    (lambda: linhas_de(mudar(spec_padrao(), ("sem_fonte_boa", "hash", ""), distintas=2)),
     "Sem fonte boa"),
    (lambda: linhas_de(mudar(spec_padrao(), ("sem_fonte_boa", "xor", ""), distintas=2)),
     "Sem fonte boa"),
    (lambda: linhas_de(mudar(spec_padrao(), ("adv_forca", "hash", "4"), pos="3")),
     "testa candidatos"),
    (lambda: mudar_linha(linhas_de(spec_padrao()), "adv_forca", "hash", "1", 0, n_falhas_forca="1"),
     "testa candidatos"),
    (lambda: mudar_linha(linhas_de(spec_padrao()), "adv_forca", "hash", "1", 0, n_alvo=str(N - 1)),
     "testa candidatos"),
    (lambda: mudar_linha(linhas_de(spec_padrao()), "adv_forca", "hash", "4", 0, n_distintas="19"),
     "testa candidatos"),
    (lambda: linhas_de(mudar(spec_padrao(), ("adv_forca", "hash", "1"), aprov=["True"] * 4)),
     "reprovaram só parte"),
    (lambda: linhas_de(mudar(spec_padrao(), ("adv_forca", "hash", "1"), aprov=["False"] * 4)),
     "reprovaram só parte"),
    (lambda: linhas_de(mudar(spec_padrao(), ("adv_forca", "hash", "4"),
                             aprov=["True", "False", "False", "False"])),
     "reprovaram só parte"),
    (lambda: linhas_de(mudar(spec_padrao(), ("base_boa", "hash", ""), p="0.5")),
     "todas as sequências são idênticas"),
    (lambda: linhas_de(mudar(mudar(mudar(spec_padrao(), ("copia", "xor", ""), p=None),
                                   ("sem_fonte_boa", "hash", ""), p=None),
                             ("sem_fonte_boa", "xor", ""), p=None)),
     "todas as sequências são idênticas"),
])
def test_recusa_afirmacao_falsa(ambiente, alterar, trecho):
    gravar_dados(ambiente, alterar())
    recusa(ambiente, trecho)


def test_recusa_sem_nenhum_k(ambiente):
    s = spec_padrao()
    del s[("adv_forca", "hash", "1")], s[("adv_forca", "hash", "4")]
    gravar_dados(ambiente, linhas_de(s))
    recusa(ambiente, "testa candidatos")


def test_recusa_resumo_vazio(ambiente):
    p = ambiente / "data" / "results" / "e4_resumo.csv"
    p.write_bytes(e4.csv_bytes(e4.CAMPOS_RESUMO, []))
    recusa(ambiente, "sem linhas")


def test_recusa_so_um_k(ambiente):
    s = spec_padrao()
    del s[("adv_forca", "hash", "4")]
    gravar_dados(ambiente, linhas_de(s))
    recusa(ambiente, "reprovaram só parte")


def test_recusa_estrutura_sem_celula(ambiente):
    s = spec_padrao()
    del s[("adv_alvo", "xor", "")]
    gravar_dados(ambiente, linhas_de(s))
    recusa(ambiente, "afirmação|estrutura")


def test_recusa_sem_base(ambiente):
    s = spec_padrao()
    del s[("base_boa", "hash", "")]
    gravar_dados(ambiente, linhas_de(s))
    recusa(ambiente, "estrutura")


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
    fonte = (_RAIZ / "registrar_e4.py").read_text(encoding="utf-8")
    assert 'HASH_ANTES = "82619b4b737e298a5bd443e7c4d4eec2a79eb31e6cb0f5ed8c91f522cce945e8"' in fonte
    assert 'COMMIT_CURTO = "ed4ae20"' in fonte
    assert reg.START == "<!-- dia7-e4:start -->" and reg.END == "<!-- dia7-e4:end -->"
