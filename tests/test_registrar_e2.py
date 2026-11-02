"""Testes de scripts/registrar_e2.py (registro do E2 no PROJECT.md, Dia 7)."""
from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
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


reg = _carregar("_registrar_e2", "registrar_e2.py")
e2 = _carregar("_e2_para_teste_registro", "e2_ataques.py")

T1, T4 = 1_000_000, 4_000_000
PROJECT = (b"# Projeto\r\n\r\ntexto antigo\r\n"
           b"<!-- dia6-coleta2:start -->\r\nx\r\n<!-- dia6-coleta2:end -->\r\n")


def spec_padrao() -> dict:
    """(fonte, parametro, valor, n_bits, leitura) -> (n, {teste: quantos lotes falham}, motivos)."""
    s: dict = {}

    def cel(f, p, v, n, falhas, leitura=1, lotes=10):
        s[(f, p, v, n, leitura)] = (lotes, falhas)

    for n, bias in ((T1, (3, 9, 10, 10)), (T4, (9, 10, 10, 10))):
        for f, p, forte in (("faulty_biased", "p", "0.55"), ("faulty_correlated", "rho", "0.6")):
            for v, k in zip(("0.501", "0.502", "0.505", "0.51"), bias):
                cel(f, p, v, n, {"stats": k})
            cel(f, p, forte, n, {"stats": 10, "h": 10, "apt": 10 if f == "faulty_biased" else 1})
        cel("faulty_stuck", "run_length", "8", n, {"stats": 10})
        cel("faulty_stuck", "run_length", "16", n, {"stats": 10, "h": 10, "apt": 1})
        cel("faulty_stuck", "run_length", "24", n, {"stats": 10, "h": 10, "rct": 3, "apt": 1})
        cel("faulty_stuck", "run_length", "32", n, {"stats": 10, "h": 10, "rct": 10})
        cel("faulty_stuck", "run_length", "64", n, {"stats": 10, "h": 10, "rct": 10, "apt": 5})
        cel("faulty_prng", "", "", n, {"stats": 1})
        cel("faulty_replay", "", "", n, {"stats": 1}, leitura=1)
        cel("faulty_replay", "", "", n, {"replay": 10}, leitura=2)
        cel("os", "", "", n, {"stats": 2, "apt": 1}, lotes=20)
    # na 4M a correlação 0.501 já tinha 9/10 (acima); o viés 0.502 em 1M é 9/10
    return s


MOTIVOS_OS = {
    T1: [["monobit: p = 0.001 (< 0.01)"], ["runs: p = 0.002 (< 0.01)"]],
    T4: [["block: p = 0.003 (< 0.01)"], ["APT: 1 de 3906 janelas no limite 589 ou acima"]],
}


def linhas_lotes(spec: dict, commit: str | None = None) -> list[dict[str, str]]:
    commit = commit or reg.COMMIT_PRE_REGISTRO
    saida = []
    for (f, p, v, n, leitura), (lotes, falhas) in spec.items():
        motivos_os = list(MOTIVOS_OS[n])
        for i in range(lotes):
            reprova = {t for t, k in falhas.items() if i < k}
            # os: os dois reprovados são os lotes 0 e 1, com um motivo cada
            if f == "os":
                reprova = {"stats"} if i == 0 else ({"apt"} if i == 1 and n == T4 else
                                                    ({"stats"} if i == 1 else set()))
                reprova |= {t for t in ("rct", "h") if i < falhas.get(t, 0)}
            d = {c: "x" for c in e2.CAMPOS_LOTES}
            d.update({
                "schema": e2.SCHEMA, "commit": commit, "fonte": f, "parametro": p, "valor": v,
                "n_bits": str(n), "repeticao": str(i), "leitura": str(leitura), "semente": "",
                "batch_hash": f"h{f}{v}{n}{leitura}{i}",
                "approved": "False" if reprova else "True",
                "rct_pass": str("rct" not in reprova), "apt_pass": str("apt" not in reprova),
                "apt_inconclusive": "False", "replay_pass": str("replay" not in reprova),
                "h_health_pass": str("h" not in reprova), "stats_pass": str("stats" not in reprova),
                "stats_inconclusive": "False", "h_estimated": "0.96", "rct_max_run": "20",
                "apt_max_count": "540", "stats_json": "{}",
                "reasons": json.dumps(motivos_os[i] if f == "os" and reprova else
                                      (["x"] if reprova else []), ensure_ascii=False),
                "t_leitura_s": "0.1000", "t_saude_s": "0.2000",
            })
            saida.append(d)
    return saida


def gravar_dados(raiz: Path, linhas: list[dict[str, str]]) -> None:
    pasta = raiz / "data" / "results"
    pasta.mkdir(parents=True, exist_ok=True)
    (pasta / "e2_lotes.csv").write_bytes(e2.csv_bytes(e2.CAMPOS_LOTES, linhas))
    (pasta / "e2_resumo.csv").write_bytes(e2.csv_bytes(e2.CAMPOS_RESUMO, e2.resumir(linhas)))


@pytest.fixture
def ambiente(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "PROJECT.md").write_bytes(PROJECT)
    monkeypatch.setattr(reg, "HASH_ANTES", hashlib.sha256(PROJECT).hexdigest())
    gravar_dados(tmp_path, linhas_lotes(spec_padrao()))
    return tmp_path


def rodar() -> tuple[int, list[str]]:
    saida: list[str] = []
    return reg.main(saida.append), saida


def linhas_do_bloco(tmp_path: Path) -> list[str]:
    texto = (tmp_path / "PROJECT.md").read_bytes().decode("utf-8")
    i = texto.index(reg.START)
    return texto[i:].split("\r\n")


# ---------------------------------------------------------------- formatação

def test_formatacao():
    assert reg.n_pt("1000000") == "1.000.000" and reg.n_pt(7) == "7"
    assert reg.d_pt("0.3000") == "0,3000"
    assert reg.valor_pt("") == "-" and reg.valor_pt("0.501") == "0,501"


def test_referencia_teorica():
    assert "3 testes estatísticos" in reg.referencia_teorica()
    assert "reprovariam 0,0297 dos lotes" in reg.referencia_teorica()
    assert "p mínimo 0,01" in reg.referencia_teorica()


# ---------------------------------------------------------------- aplicação

def test_aplica_e_preserva_o_resto(ambiente):
    codigo, saida = rodar()
    assert codigo == 0 and saida[0].startswith("aplicado")
    dados = (ambiente / "PROJECT.md").read_bytes()
    assert dados.startswith(PROJECT + b"\r\n" + reg.START.encode())
    assert dados.endswith(reg.END.encode() + b"\r\n")
    assert dados.count(b"\n") == dados.count(b"\r\n")
    assert dados.count(reg.START.encode()) == 1 and dados.count(reg.END.encode()) == 1
    assert not list(ambiente.glob("*.tmp"))
    assert saida[0] == f"aplicado; PROJECT.md: {hashlib.sha256(dados).hexdigest()}"


def test_idempotente(ambiente):
    assert rodar()[0] == 0
    antes = (ambiente / "PROJECT.md").read_bytes()
    codigo, saida = rodar()
    assert codigo == 0 and saida[0].startswith("já aplicado")
    assert (ambiente / "PROJECT.md").read_bytes() == antes


def test_bloco_traz_os_hashes_dos_csvs(ambiente):
    rodar()
    bloco = "\n".join(linhas_do_bloco(ambiente))
    for nome in ("e2_lotes.csv", "e2_resumo.csv"):
        h = hashlib.sha256((ambiente / "data" / "results" / nome).read_bytes()).hexdigest()
        assert f"- `{nome}`: `{h}`" in bloco
    assert reg.COMMIT_PRE_REGISTRO in bloco


def test_tabela_vem_do_csv(ambiente):
    rodar()
    with (ambiente / "data" / "results" / "e2_resumo.csv").open(encoding="utf-8", newline="") as f:
        resumo = list(csv.DictReader(f))
    linhas = linhas_do_bloco(ambiente)
    tabela = [l for l in linhas if l.startswith("| ") and "| IC" not in l and "Grupo" not in l
              and "Bits | Lotes" not in l]
    for r in resumo:
        esperado = (f"| {reg.grupo_texto(r)} | {r['fonte']} | {reg.valor_pt(r['valor'])} "
                    f"| {reg.n_pt(r['n_bits'])} | {reg.n_pt(r['n_reprovados'])} "
                    f"| {reg.n_pt(r['n_lotes'])} | {reg.d_pt(r['taxa'])} "
                    f"| {reg.d_pt(r['ic95_inf'])} a {reg.d_pt(r['ic95_sup'])} "
                    f"| {r['n_rct_falhou']} | {r['n_apt_falhou']} | {r['n_replay_falhou']} "
                    f"| {r['n_h_falhou']} | {r['n_stats_falhou']} |")
        assert esperado in tabela, esperado
    assert len([l for l in tabela if l.count("|") == 14]) == len(resumo)


def test_grupos_do_replay_e_os(ambiente):
    rodar()
    texto = "\n".join(linhas_do_bloco(ambiente))
    assert "| referência (1ª leitura) | faulty_replay |" in texto
    assert "| detecção (2ª leitura) | faulty_replay |" in texto
    assert "| falso positivo | os |" in texto
    assert "| detecção | faulty_prng |" in texto


def test_falso_positivo_por_teste(ambiente):
    rodar()
    linhas = linhas_do_bloco(ambiente)
    i = linhas.index("| Bits | Lotes `os` | Reprovados | monobit | block | runs | APT |")
    assert linhas[i + 2] == "| 1.000.000 | 20 | 2 | 1 | 0 | 1 | 0 |"
    assert linhas[i + 3] == "| 4.000.000 | 20 | 2 | 0 | 1 | 0 | 1 |"


def test_falso_positivo_motivo_multiplo_conta_cada_teste():
    lotes = [{"fonte": "os", "n_bits": "1000000", "approved": "False",
              "reasons": json.dumps(["monobit: p = 0.001 (< 0.01)", "runs: p = 0.002 (< 0.01)",
                                     "runs: p = 0.003 (< 0.01)"])},
             {"fonte": "os", "n_bits": "1000000", "approved": "True", "reasons": "[]"},
             {"fonte": "faulty_biased", "n_bits": "1000000", "approved": "False",
              "reasons": json.dumps(["block: p = 0 (< 0.01)"])}]
    tab = reg.falso_positivo_por_teste(lotes)
    assert tab[0] == "| Bits | Lotes `os` | Reprovados | monobit | runs |"
    assert tab[2] == "| 1.000.000 | 2 | 1 | 1 | 1 |"


def test_motivos_desconhecidos_vao_depois_dos_conhecidos_em_ordem_alfabetica():
    def lote(motivo):
        return {"fonte": "os", "n_bits": "1000000", "approved": "False",
                "reasons": json.dumps([motivo])}

    tab = reg.falso_positivo_por_teste([lote("zeta: x"), lote("runs: p"), lote("alfa: y"),
                                        lote("APT: z"), lote("alfa: w")])
    assert tab[0] == "| Bits | Lotes `os` | Reprovados | runs | APT | alfa | zeta |"
    assert tab[2] == "| 1.000.000 | 5 | 5 | 1 | 1 | 2 | 1 |"


def test_leitura_e_ressalvas_presentes(ambiente):
    rodar()
    texto = "\n".join(linhas_do_bloco(ambiente))
    assert "O limite inferior de detecção do travamento não foi encontrado." in texto
    assert "inclusive no menor (8)" in texto
    assert "**Ressalvas:**" in texto and "não para ataques reais" in texto
    assert texto.count("\n- ") >= 10 + 6


# ---------------------------------------------------------------- recusas

def estado(tmp_path: Path) -> dict[str, bytes]:
    return {str(p.relative_to(tmp_path)): p.read_bytes() for p in sorted(tmp_path.rglob("*"))
            if p.is_file()}


def recusa(ambiente, trecho: str):
    antes = estado(ambiente)
    codigo, saida = rodar()
    assert codigo == 1 and saida[-1].startswith("RECUSADO") and trecho in saida[-1], saida
    assert estado(ambiente) == antes
    assert not list(ambiente.glob("*.tmp"))


def test_recusa_hash_do_project_diferente(ambiente, monkeypatch):
    monkeypatch.setattr(reg, "HASH_ANTES", "0" * 64)
    recusa(ambiente, "difere de HASH_ANTES")


def test_recusa_marcador_existente(ambiente, monkeypatch):
    novo = PROJECT + reg.START.encode() + b"\r\n"
    (ambiente / "PROJECT.md").write_bytes(novo)
    monkeypatch.setattr(reg, "HASH_ANTES", hashlib.sha256(novo).hexdigest())
    recusa(ambiente, "marcador")


def test_recusa_project_nao_crlf(ambiente, monkeypatch):
    lf = PROJECT.replace(b"\r\n", b"\n")
    (ambiente / "PROJECT.md").write_bytes(lf)
    monkeypatch.setattr(reg, "HASH_ANTES", hashlib.sha256(lf).hexdigest())
    recusa(ambiente, "CRLF puro")


def test_recusa_project_sem_fim_de_linha(ambiente, monkeypatch):
    sem = PROJECT.rstrip(b"\r\n")
    (ambiente / "PROJECT.md").write_bytes(sem)
    monkeypatch.setattr(reg, "HASH_ANTES", hashlib.sha256(sem).hexdigest())
    recusa(ambiente, "CRLF puro")


def test_recusa_project_ausente(ambiente):
    (ambiente / "PROJECT.md").unlink()
    codigo, saida = rodar()
    assert codigo == 1 and "arquivo ausente" in saida[-1]


@pytest.mark.parametrize("nome", ["e2_lotes.csv", "e2_resumo.csv"])
def test_recusa_csv_ausente(ambiente, nome):
    (ambiente / "data" / "results" / nome).unlink()
    codigo, saida = rodar()
    assert codigo == 1 and "CSV ausente" in saida[-1]
    assert (ambiente / "PROJECT.md").read_bytes() == PROJECT


def test_recusa_cabecalho_do_resumo(ambiente):
    p = ambiente / "data" / "results" / "e2_resumo.csv"
    p.write_bytes(p.read_bytes().replace(b"n_rct_falhou", b"n_rct", 1))
    recusa(ambiente, "cabeçalho")


def test_recusa_cabecalho_dos_lotes(ambiente):
    p = ambiente / "data" / "results" / "e2_lotes.csv"
    p.write_bytes(p.read_bytes().replace(b"stats_json", b"stats", 1))
    recusa(ambiente, "cabeçalho")


def test_recusa_resumo_adulterado(ambiente):
    p = ambiente / "data" / "results" / "e2_resumo.csv"
    p.write_bytes(p.read_bytes().replace(b",0.3000,", b",0.9000,", 1))
    recusa(ambiente, "derivação exata")


def test_recusa_commit_diferente(ambiente):
    gravar_dados(ambiente, linhas_lotes(spec_padrao(), commit="a" * 40))
    recusa(ambiente, "difere de")


def test_recusa_lotes_vazios(ambiente):
    p = ambiente / "data" / "results" / "e2_lotes.csv"
    cab = e2.csv_bytes(e2.CAMPOS_LOTES, [])
    p.write_bytes(cab)
    recusa(ambiente, "sem linhas")


def test_recusa_os_reprovado_sem_motivo(ambiente):
    linhas = linhas_lotes(spec_padrao())
    for l in linhas:
        if l["fonte"] == "os" and l["approved"] == "False":
            l["reasons"] = "[]"
            break
    gravar_dados(ambiente, linhas)
    recusa(ambiente, "sem motivo")


def test_recusa_motivo_ilegivel(ambiente):
    linhas = linhas_lotes(spec_padrao())
    for l in linhas:
        if l["fonte"] == "os" and l["approved"] == "False":
            l["reasons"] = "nao json"
            break
    gravar_dados(ambiente, linhas)
    recusa(ambiente, "ilegível")


def mutar(spec: dict, chave: tuple, **falhas) -> dict:
    lotes, f = spec[chave]
    spec[chave] = (lotes, {**f, **falhas})
    return spec


def sem_falha(spec: dict, chave: tuple, teste: str) -> dict:
    lotes, f = spec[chave]
    spec[chave] = (lotes, {k: v for k, v in f.items() if k != teste})
    return spec


@pytest.mark.parametrize("nome,alterar,trecho", [
    ("forte não total", lambda s: mutar(s, ("faulty_biased", "p", "0.505", T1, 1), stats=9),
     "reprovados em todos os lotes"),
    ("fraco total", lambda s: mutar(s, ("faulty_biased", "p", "0.501", T1, 1), stats=10),
     "detecção é parcial"),
    ("fraco zero", lambda s: mutar(s, ("faulty_correlated", "rho", "0.501", T4, 1), stats=0),
     "detecção é parcial"),
    ("rct em viés", lambda s: mutar(s, ("faulty_biased", "p", "0.51", T1, 1), rct=1),
     "O RCT não reprovou nenhum lote de viés"),
    ("stuck 8 parcial", lambda s: mutar(s, ("faulty_stuck", "run_length", "8", T4, 1), stats=9),
     "todos os lotes foram reprovados em todos os comprimentos"),
    ("stuck 8 com rct", lambda s: mutar(s, ("faulty_stuck", "run_length", "8", T1, 1), rct=1),
     "No menor comprimento de travamento (8)"),
    ("stuck 8 com h", lambda s: mutar(s, ("faulty_stuck", "run_length", "8", T1, 1), h=1),
     "No menor comprimento de travamento (8)"),
    ("rct em 16", lambda s: mutar(s, ("faulty_stuck", "run_length", "16", T1, 1), rct=1),
     "O RCT não reprova travamentos"),
    ("rct 24 total", lambda s: mutar(s, ("faulty_stuck", "run_length", "24", T4, 1), rct=10),
     "O RCT não reprova travamentos"),
    ("rct 24 zero", lambda s: mutar(s, ("faulty_stuck", "run_length", "24", T1, 1), rct=0),
     "O RCT não reprova travamentos"),
    ("rct 32 parcial", lambda s: mutar(s, ("faulty_stuck", "run_length", "32", T1, 1), rct=9),
     "O RCT não reprova travamentos"),
    ("rct 64 zero", lambda s: mutar(s, ("faulty_stuck", "run_length", "64", T4, 1), rct=0),
     "O RCT não reprova travamentos"),
    ("h em viés fraco", lambda s: mutar(s, ("faulty_biased", "p", "0.51", T1, 1), h=1),
     "O teste de min-entropia só reprovou"),
    ("h em stuck 8", lambda s: mutar(s, ("faulty_stuck", "run_length", "8", T4, 1), h=1),
     "No menor comprimento de travamento (8)"),
    ("h no prng", lambda s: mutar(s, ("faulty_prng", "", "", T4, 1), h=1),
     "O teste de min-entropia só reprovou"),
    ("h no replay", lambda s: mutar(s, ("faulty_replay", "", "", T1, 1), h=1),
     "O teste de min-entropia só reprovou"),
    ("h na os", lambda s: mutar(s, ("os", "", "", T1, 1), h=1),
     "O teste de min-entropia só reprovou"),
    ("replay falso alarme", lambda s: mutar(s, ("faulty_prng", "", "", T1, 1), replay=1),
     "O teste de replay reprovou todas"),
    ("replay 2ª parcial", lambda s: mutar(s, ("faulty_replay", "", "", T1, 2), replay=9),
     "O teste de replay reprovou todas"),
    ("replay 1ª com replay", lambda s: mutar(s, ("faulty_replay", "", "", T4, 1), replay=1),
     "O teste de replay reprovou todas"),
    ("replay 2ª com outro teste cobrindo", lambda s: mutar(
        s, ("faulty_replay", "", "", T1, 2), replay=9, stats=10),
     "O teste de replay reprovou todas"),
    ("stuck 8 stats parcial, apt cobre", lambda s: mutar(
        s, ("faulty_stuck", "run_length", "8", T1, 1), stats=9, apt=10),
     "No menor comprimento de travamento (8)"),
    ("os com rct", lambda s: mutar(s, ("os", "", "", T4, 1), rct=1),
     "Na fonte `os`, o RCT"),
    ("prng alto", lambda s: mutar(s, ("faulty_prng", "", "", T4, 1), stats=10),
     "não se distingue da da `os`"),
])
def test_recusa_afirmacao_falsa(ambiente, nome, alterar, trecho):
    spec = alterar(spec_padrao())
    gravar_dados(ambiente, linhas_lotes(spec))
    recusa(ambiente, trecho)


def test_recusa_ic_do_os_sem_sobreposicao(ambiente):
    spec = spec_padrao()
    spec[("os", "", "", T1, 1)] = (2000, {})          # 0 de 2000: IC bem abaixo
    spec[("os", "", "", T4, 1)] = (20, {"stats": 20})
    linhas = [l for l in linhas_lotes(spec) if l["fonte"] != "os"]
    antes = [l for l in linhas_lotes(spec) if l["fonte"] == "os"]
    for l in antes:
        if l["approved"] == "False":
            l["reasons"] = json.dumps(["monobit: p = 0.001 (< 0.01)"])
    gravar_dados(ambiente, linhas + antes)
    recusa(ambiente, "Os IC 95% do falso positivo")


def _afirmacao(resumo, inicio):
    for texto, teste in reg.montar_afirmacoes(resumo):
        if texto.startswith(inicio):
            return teste
    raise AssertionError(inicio)


def test_afirmacao_h_isolada_recusa_h_em_stuck_8(ambiente):
    spec = mutar(spec_padrao(), ("faulty_stuck", "run_length", "8", T1, 1), h=1)
    gravar_dados(ambiente, linhas_lotes(spec))
    resumo = reg.ler_resumo(e2, ambiente / "data" / "results" / "e2_resumo.csv")
    assert _afirmacao(resumo, "O teste de min-entropia só reprovou")() is False
    base = e2_resumo_padrao(ambiente)
    assert _afirmacao(base, "O teste de min-entropia só reprovou")() is True


def e2_resumo_padrao(raiz):
    gravar_dados(raiz, linhas_lotes(spec_padrao()))
    return reg.ler_resumo(e2, raiz / "data" / "results" / "e2_resumo.csv")


def test_recusa_resumo_vazio(ambiente):
    p = ambiente / "data" / "results" / "e2_resumo.csv"
    p.write_bytes(e2.csv_bytes(e2.CAMPOS_RESUMO, []))
    recusa(ambiente, "sem linhas")


def test_protocolo_usa_contagens_do_csv(ambiente):
    rodar()
    texto = "\n".join(linhas_do_bloco(ambiente))
    n = len(linhas_lotes(spec_padrao()))
    assert n != 38
    assert f"conferido na coluna `commit` das {reg.n_pt(n)} linhas. 36 células, " \
           f"lotes de 1.000.000 e 4.000.000 bits." in texto


def test_recusa_estrutura_sem_celula(ambiente):
    spec = spec_padrao()
    del spec[("faulty_biased", "p", "0.505", T1, 1)]
    gravar_dados(ambiente, linhas_lotes(spec))
    recusa(ambiente, "afirmação")


def test_ja_aplicado_exige_prefixo_original():
    ins = b"\r\nBLOCO\r\n"
    reg.HASH_ANTES, antigo = hashlib.sha256(PROJECT).hexdigest(), reg.HASH_ANTES
    try:
        with pytest.raises(reg.Refused):
            reg.aplicar(PROJECT + b"extra\r\n" + ins, ins)
        with pytest.raises(reg.Refused):
            reg.aplicar(b"outro\r\n" + ins, ins)
    finally:
        reg.HASH_ANTES = antigo


def test_aplicar_direto():
    ins = b"\r\nBLOCO\r\n"
    h = hashlib.sha256(PROJECT).hexdigest()
    reg.HASH_ANTES, antigo = h, reg.HASH_ANTES
    try:
        assert reg.aplicar(PROJECT, ins) == PROJECT + ins
        assert reg.aplicar(PROJECT + ins, ins) is None
        with pytest.raises(reg.Refused):
            reg.aplicar(PROJECT + b"x\r\n", ins)
    finally:
        reg.HASH_ANTES = antigo


def test_insercao_sem_cr_solto():
    with pytest.raises(reg.Refused):
        reg.preparar_insercao("a\rb")
    assert reg.preparar_insercao("a\nb") == b"\r\na\r\nb\r\n"
