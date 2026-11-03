"""Testes de scripts/registrar_consolidado.py (pastas temporárias; um teste lê o data/results real se existir)."""
from __future__ import annotations

import csv
import hashlib
import importlib.util
import io
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _carregar(nome: str):
    spec = importlib.util.spec_from_file_location(nome, ROOT / "scripts" / f"{nome}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[nome] = mod
    spec.loader.exec_module(mod)
    return mod


cd = _carregar("consolidar_dia7")
rc = _carregar("registrar_consolidado")

COMMIT = "b" * 40
LIMPA = lambda: (True, COMMIT)  # noqa: E731

E3 = """metrica,valor,unidade
preco_fonte,https://www.ibm.com/quantum/pricing,url
preco_data_consulta,2026-11-03,data
qpu_jobs,8,jobs
qpu_segundos,35.0,s
qpu_bits_brutos,9780576,bits
qpu_custo_pay_as_you_go,56.00,USD
qpu_custo_flex,42.00,USD
qpu_custo_premium,28.00,USD
coleta_jobs,6,jobs
coleta_segundos,30.0,s
coleta_bits_brutos,9000576,bits
coleta_bits_por_s,300019.2000,bits/s
coleta_s_por_mbit_bruto,3.3331,s/Mbit
coleta_custo_por_mbit_bruto_pay_as_you_go,5.3330,USD/Mbit
coleta_custo_por_mbit_bruto_flex,3.9997,USD/Mbit
coleta_custo_por_mbit_bruto_premium,2.6665,USD/Mbit
ajuste_fixo_s,1.6296,s/job
ajuste_por_shot_s,0.00035031,s/shot
ajuste_custo_marginal_por_mbit_pay_as_you_go,3.5930,USD/Mbit
coleta_lotes_aprovados,0,lotes
coleta_bits_uteis,0,bits
coleta_custo_por_mbit_util_pay_as_you_go,indefinido,USD/Mbit
coleta_bits_uteis_hipoteticos,8054196,bits
coleta_custo_por_mbit_util_hipotetico_pay_as_you_go,5.9596,USD/Mbit
local_execucoes,20,execuções
local_t_mediana_s,0.324724,s
local_t_min_s,0.074158,s
local_t_max_s,0.384965,s
local_s_por_mbit_bruto,0.216468,s/Mbit
local_bits_por_s,4619610.2222,bits/s
local_bits_extraidos_mediana,1354932,bits
razao_s_por_mbit_qpu_sobre_os,15.40,vezes
criterio_limiar,10,vezes
criterio_muito_mais_caro,True,booleano
"""

E5 = """configuracao,esperado,n_reps,s_media,s_dp,se_media,s_min,s_max,frac_s_maior_2,margem,criterio_ok
ideal_exato,S = 2*raiz(2) (exato),1,2.828427,0.000000,0.000000,2.828427,2.828427,1.0000,0.000000,True
ideal_amostrado,compatível com 2*raiz(2),100,2.828795,0.024325,0.022354,2.770000,2.884500,1.0000,0.007297,True
ruido_fake_kingston,entre 2 e 2*raiz(2) (hipótese do assistente),100,2.759055,0.024498,0.022892,2.700000,2.821000,1.0000,0.007349,True
classico_aleatorio,S <= 2,100,-0.000685,0.030991,0.031619,-0.077500,0.093000,0.0000,0.009297,True
classico_otimo,S <= 2,100,2.000000,0.000000,0.000000,2.000000,2.000000,0.0000,0.000000,True
"""

_CAB = "lote_a,lote_b,n_qubits,zdiff_media,zdiff_dp,zdiff_n_acima3,zdiff_max_abs,zdiff_max_pos\n"
ESTAB_REAL = {  # conteúdo real dos 3 arquivos, colado pelo usuário no Dia 7
    "mesmo_dia": _CAB + """cal_001,cal_002,156,-0.010678650321,1.44718479773,6,6.0531511473,138
cal_001,coleta1_001,156,0.0455323239457,1.61543216345,5,10.3304385845,14
cal_001,coleta1_002,156,-0.0475213313929,1.56718149478,6,8.90055950472,14
cal_002,coleta1_001,156,0.0970644627442,1.26427195311,2,6.75841562982,14
cal_002,coleta1_002,156,-0.0659883954121,1.12921975319,2,4.37249890667,14
coleta1_001,coleta1_002,156,-0.212376798164,1.14453833441,3,4.35572873365,35
""",
    "coleta2_vs_coleta1": _CAB + """coleta1_001,coleta1_002,156,-0.212376798164,1.14453833441,3,4.35572873365,35
coleta1_001,coleta2_001,156,-0.844945367072,3.27429322893,12,22.601465368,87
coleta1_001,coleta2_002,156,-0.649045982388,3.37719466768,9,25.8900429665,87
coleta1_002,coleta2_001,156,-0.63285249278,3.11121447163,10,23.8044977984,87
coleta1_002,coleta2_002,156,-0.436908874436,3.31292312159,11,27.0879220016,87
coleta2_001,coleta2_002,156,0.195616094695,1.13325804101,2,7.35592383431,12
""",
    "coleta3_vs_coleta1": _CAB + """coleta1_001,coleta1_002,156,-0.212376798164,1.14453833441,3,4.35572873365,35
coleta1_001,coleta3_001,156,-0.882294511815,3.0634951651,12,21.9092966222,138
coleta1_001,coleta3_002,156,-1.17067129253,3.06697484855,14,22.2106538056,14
coleta1_002,coleta3_001,156,-0.670161792237,2.96523738244,11,19.7298085243,138
coleta1_002,coleta3_002,156,-0.95856395808,2.98325828064,11,19.1707964242,14
coleta3_001,coleta3_002,156,-0.288445358533,1.08886888903,1,3.20172708204,57
"""}

E2_COLS = ("n_lotes", "n_reprovados", "taxa", "ic95_inf", "ic95_sup", "n_rct_falhou",
           "n_apt_falhou", "n_replay_falhou", "n_h_falhou", "n_stats_falhou",
           "n_stats_inconclusivo", "h_estimada_min", "h_estimada_max", "t_lote_mediana_s")
E4_COLS = ("esperado", "n_seq", "n_seq_completas", "n_aprovadas", "taxa_aprovacao",
           "ic95_inf", "ic95_sup", "sementes_total", "recusadas_total", "frac_alvo",
           "distintas_min", "distintas_max", "max_abs_z_max", "pos_z5_min", "pos_z5_max",
           "falhas_forca_total", "t_seq_mediana_s")


def escrever(path: Path, campos: list[str], linhas: list[dict]) -> None:
    buf = io.StringIO(newline="")
    w = csv.DictWriter(buf, fieldnames=campos, lineterminator="\r\n")
    w.writeheader()
    w.writerows(linhas)
    path.write_bytes(buf.getvalue().encode("utf-8"))


def ler(path: Path) -> list[dict]:
    return list(csv.DictReader(io.StringIO(path.read_bytes().decode("utf-8"), newline="")))


def preencher(cols, i: int) -> dict:
    return {c: f"{j + 1}.{i}25" for j, c in enumerate(cols)}


def fabricar(pasta: Path) -> Path:
    """Os 16 CSVs de origem (estrutura real, números sintéticos) mais os 6 do painel."""
    for c, p in cd.COLETAS:
        escrever(pasta / f"{p}qpu_vs_sim_resumo.csv", ["fonte", *cd.RESUMO],
                 [{"fonte": f, **preencher(cd.RESUMO, i)}
                  for i, f in enumerate(("qpu_real", "simulador"))])
        linhas = []
        for f, aprov, status in (("qpu_real", "False", "excluded"),
                                 ("simulador", "False", "excluded"), ("os", "True", "mixed")):
            for lote in ("1", "2"):
                l = {"fonte": f, "lote": lote, **preencher(cd.LOTES, 1)}
                l.update(saude_approved=aprov, pipe_status=status, saude_h_estimated="0.96",
                         ext_n_output_bits="1349076" if aprov == "True" else "0")
                linhas.append(l)
        escrever(pasta / f"{p}qpu_vs_sim_lotes.csv", ["fonte", "lote", *cd.LOTES], linhas)
    for d, p in cd.DERIVAS:
        (pasta / f"{p}estabilidade.csv").write_bytes(ESTAB_REAL[d].encode("utf-8"))
        escrever(pasta / f"{p}conjunto_fixo.csv", ["tipo", "grupo", "id", "lote", *cd.FIXO],
                 [{"tipo": "qubit", "grupo": "g", "id": str(i), "lote": "coleta1_001",
                   **preencher(cd.FIXO, i)} for i in range(2)])
    e2 = [("faulty_biased", "p", "0.501", "1000000", "1", "deteccao", "200", "60", "0.3000"),
          ("faulty_biased", "p", "0.502", "1000000", "1", "deteccao", "200", "185", "0.9250"),
          ("faulty_replay", "", "", "1000000", "1", "referencia", "100", "0", "0.0000"),
          ("os", "", "", "1000000", "1", "falso_positivo", "2000", "52", "0.0260"),
          ("os", "", "", "4000000", "1", "falso_positivo", "500", "18", "0.0360")]
    linhas = []
    for i, (f, par, v, nb, lei, tipo, nl, nr, taxa) in enumerate(e2):
        l = {"fonte": f, "parametro": par, "valor": v, "n_bits": nb, "leitura": lei,
             "tipo": tipo, **preencher(E2_COLS, i)}
        l.update(n_lotes=nl, n_reprovados=nr, taxa=taxa)
        linhas.append(l)
    escrever(pasta / "e2_resumo.csv", ["fonte", "parametro", "valor", "n_bits", "leitura",
                                       "tipo", *E2_COLS], linhas)
    (pasta / "e3_resumo.csv").write_bytes(E3.encode("utf-8"))
    linhas = []
    for i, (cen, comb, k, alvo) in enumerate((("base_boa", "hash", "", ""),
                                              ("base_boa", "xor", "", ""),
                                              ("adv_forca", "hash", "8", "1.0000"),
                                              ("sem_semente", "hash", "", ""))):
        l = {"cenario": cen, "combinador": comb, "k": k, **preencher(E4_COLS, i)}
        l.update(esperado="segura", n_seq="100", n_seq_completas="100", n_aprovadas="97",
                 taxa_aprovacao="0.9700", frac_alvo=alvo)
        if cen == "sem_semente":  # caso real: nenhuma sequência completa, taxa vazia
            l.update(esperado="sem_semente", n_seq_completas="0", n_aprovadas="0",
                     taxa_aprovacao="", ic95_inf="", ic95_sup="")
        linhas.append(l)
    escrever(pasta / "e4_resumo.csv", ["cenario", "combinador", "k", *E4_COLS], linhas)
    (pasta / "e5_resumo.csv").write_bytes(E5.encode("utf-8"))
    for nome in rc.ARQUIVOS_PAINEL:
        (pasta / nome).write_bytes(b"x\n")
    return pasta


def gravar_consolidado(pasta: Path) -> Path:
    assert cd.main(["--gravar"], results=pasta, git=LIMPA) == 0
    return pasta


def montar_pasta(tmp: Path, alterar=None) -> Path:
    pasta = tmp / "res"
    pasta.mkdir()
    fabricar(pasta)
    if alterar:
        alterar(pasta)
    return gravar_consolidado(pasta)


@pytest.fixture
def pasta(tmp_path: Path) -> Path:
    return montar_pasta(tmp_path)


def projeto(tmp_path: Path, final: bytes = b"fim\r\n<!-- x:end -->\r\n") -> Path:
    p = tmp_path / "PROJECT.md"
    p.write_bytes(b"# Titulo\r\n\r\ntexto\r\n" + final)
    return p


def h(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def editar(pasta: Path, arquivo: str, f) -> None:
    p = pasta / arquivo
    linhas = ler(p)
    f(linhas)
    escrever(p, list(linhas[0]), linhas)


# --- especificação fixa ---

def test_constantes():
    assert rc.START == "<!-- dia7-consolidado:start -->" and rc.END == "<!-- dia7-consolidado:end -->"
    assert rc.HASH_ANTES == "48a7143c539b599e8a6158bfefb586f0d0b7f9c755cebc16945efd589880f514"
    assert rc.CONFIGS_E5 == ("ideal_exato", "ideal_amostrado", "ruido_fake_kingston",
                             "classico_aleatorio", "classico_otimo")
    assert rc.DERIVAS == ("mesmo_dia", "coleta2_vs_coleta1", "coleta3_vs_coleta1")
    assert len(rc.ARQUIVOS_PAINEL) == 6 and len(set(rc.ARQUIVOS_PAINEL)) == 6


def test_derivas_alinhadas_com_o_consolidar():
    assert tuple(d for d, _ in cd.DERIVAS) == rc.DERIVAS


def test_metricas_do_e3_existem_na_saida_real():
    nomes = {l.split(",")[0] for l in E3.splitlines()[1:]}
    assert set(rc.E3_METRICAS) <= nomes


# --- formatação ---

def test_num_e_derivados():
    assert rc.num("0.96", 4) == "0,9600"
    assert rc.num("2.828427", 6) == "2,828427"
    assert rc.num("texto", 4) == "texto" and rc.num("-", 2) == "-"
    assert rc.sim_nao("True") == "sim" and rc.sim_nao("False") == "não" and rc.sim_nao("x") == "x"
    assert rc.milhar("1000000") == "1.000.000" and rc.milhar("200") == "200"
    assert rc.milhar("-12345") == "-12.345" and rc.milhar("abc") == "abc" and rc.milhar("1.5") == "1.5"


def test_copia():
    assert rc.copia("15.40") == "15,40" and rc.copia("0.00035031") == "0,00035031"
    assert rc.copia("300019.2000") == "300.019,2000" and rc.copia("4619610.2222") == "4.619.610,2222"
    assert rc.copia("9999.5") == "9999,5" and rc.copia("-12345.5") == "-12.345,5"
    assert rc.copia("9780576") == "9.780.576" and rc.copia("8") == "8" and rc.copia("10000") == "10.000"
    assert rc.copia("9999") == "9999"
    assert rc.copia("True") == "sim" and rc.copia("indefinido") == "indefinido"
    assert rc.copia("2026-11-03") == "2026-11-03"
    assert rc.copia("https://www.ibm.com/quantum/pricing") == "https://www.ibm.com/quantum/pricing"


def test_tabela_escapa_barra():
    t = rc.tabela(["a", "b"], [["x|y", "z"]])
    assert t[0] == "| a | b |" and t[1] == "|---|---|" and t[2] == "| x\\|y | z |"


def test_parse_chave():
    assert rc.parse_chave("tabela=t;a=1;k=") == ("t", {"a": "1", "k": ""})
    with pytest.raises(rc.Recusa):
        rc.parse_chave("tabela=t;semigual")
    with pytest.raises(rc.Recusa):
        rc.parse_chave("a=1")


def test_obter_e_exigir():
    assert rc.obter({"a": "1"}, "a") == "1" and rc.obter({}, "a", opcional=True) == "-"
    with pytest.raises(rc.Recusa):
        rc.obter({}, "a")
    rc.exigir(True, "x")
    with pytest.raises(rc.Recusa, match="x"):
        rc.exigir(False, "x")


# --- load ---

def test_load_ok(pasta: Path):
    f = rc.load(pasta)
    assert f["commit"] == COMMIT and len(f["gate"]) == 5
    assert f["sha_longo"] == h(pasta / rc.ARQ_LONG) and f["sha_gate"] == h(pasta / rc.ARQ_GATE)
    assert len(f["longo"]) == sum(int(g["n_metricas"]) for g in f["gate"])


@pytest.mark.parametrize("arquivo", [rc.ARQ_LONG, rc.ARQ_GATE])
def test_load_recusa_consolidado_ausente(pasta: Path, arquivo: str):
    (pasta / arquivo).unlink()
    with pytest.raises(rc.Recusa, match="ausente"):
        rc.load(pasta)


def test_load_recusa_consolidado_alterado(pasta: Path):
    p = pasta / rc.ARQ_LONG
    p.write_bytes(p.read_bytes().replace(b"0.3000", b"0.3001", 1) if b"0.3000" in p.read_bytes()
                  else p.read_bytes() + b"x")
    with pytest.raises(rc.Recusa, match="derivação exata"):
        rc.load(pasta)


def test_load_recusa_gate_alterado(pasta: Path):
    p = pasta / rc.ARQ_GATE
    p.write_bytes(p.read_bytes().replace(b"parcial", b"completo", 1))
    with pytest.raises(rc.Recusa, match="derivação exata"):
        rc.load(pasta)


def test_load_recusa_origem_mudou_depois(pasta: Path):
    p = pasta / "e5_resumo.csv"
    p.write_bytes(p.read_bytes().replace(b"2.828795", b"2.828796"))
    with pytest.raises(rc.Recusa, match="derivação exata"):
        rc.load(pasta)


def test_load_recusa_origem_ausente(pasta: Path):
    (pasta / "e4_resumo.csv").unlink()
    with pytest.raises(rc.Recusa, match="origem não confere"):
        rc.load(pasta)


def test_load_recusa_commit_diferente_no_gate(pasta: Path):
    p = pasta / rc.ARQ_GATE
    linhas = ler(p)
    linhas[2]["commit"] = "c" * 40
    escrever(p, list(linhas[0]), linhas)
    with pytest.raises(rc.Recusa, match="commits diferentes"):
        rc.load(pasta)


def test_load_recusa_commit_vazio(pasta: Path):
    p = pasta / rc.ARQ_GATE
    linhas = ler(p)
    for l in linhas:
        l["commit"] = ""
    escrever(p, list(linhas[0]), linhas)
    with pytest.raises(rc.Recusa, match="commits"):
        rc.load(pasta)


def test_load_recusa_experimento_faltando(pasta: Path):
    p = pasta / rc.ARQ_GATE
    linhas = ler(p)[:4]
    escrever(p, list(linhas[0]), linhas)
    with pytest.raises(rc.Recusa, match="E1 a E5"):
        rc.load(pasta)


def test_load_recusa_ordem_trocada(pasta: Path):
    p = pasta / rc.ARQ_GATE
    linhas = ler(p)
    linhas[0], linhas[1] = linhas[1], linhas[0]
    escrever(p, list(linhas[0]), linhas)
    with pytest.raises(rc.Recusa, match="E1 a E5"):
        rc.load(pasta)


def test_load_recusa_nao_utf8(pasta: Path):
    (pasta / rc.ARQ_GATE).write_bytes("é".encode("cp1252") + b"\n")
    with pytest.raises(rc.Recusa, match="UTF-8"):
        rc.load(pasta)


def test_load_recusa_sem_linhas(pasta: Path):
    (pasta / rc.ARQ_LONG).write_bytes(",".join(cd.CAMPOS_LONG).encode() + b"\n")
    with pytest.raises(rc.Recusa, match="sem linhas"):
        rc.load(pasta)


# --- render ---

def bloco(pasta: Path) -> str:
    return rc.render(rc.load(pasta), pasta)


def test_render_estrutura(pasta: Path):
    b = bloco(pasta)
    linhas = b.split("\n")
    assert linhas[0] == rc.START and linhas[-1] == rc.END
    assert linhas[1].startswith("### Consolidado E1 a E5 para o painel (Dia 7")
    assert "\r" not in b
    assert b.count(rc.START) == 1 and b.count(rc.END) == 1
    assert "Nenhum número foi digitado à mão" in b
    assert f"commit `{COMMIT}`" in b


def test_render_tabela_do_gate(pasta: Path):
    b = bloco(pasta)
    gate = ler(pasta / rc.ARQ_GATE)
    assert "| Experimento | Estado | Métricas | Arquivos de origem | Ressalva |" in b
    for g in gate:
        assert f"| {g['experimento']} | {g['estado']} | {rc.milhar(g['n_metricas'])} | {g['n_arquivos']} |" in b
    assert "E1 (parcial), E2 (completo), E3 (completo), E4 (completo), E5 (parcial)" in b
    assert f"{rc.milhar(str(len(ler(pasta / rc.ARQ_LONG))))} linhas no formato longo" in b


def test_render_e1(pasta: Path):
    b = bloco(pasta)
    assert "| Coleta | Fonte | Lote | Aprovado | H estimada | Pipeline | Bits extraídos |" in b
    assert "| 3 | qpu_real | 1 | não | 0,9600 | excluded | 0 |" in b
    assert "| 2 | os | 2 | sim | 0,9600 | mixed | 1.349.076 |" in b
    assert b.count("| qpu_real | ") >= 0
    assert "| mesmo_dia | cal_001 | cal_002 |" in b
    assert "| coleta3_vs_coleta1 | coleta1_001 | coleta3_001 |" in b
    assert ("Lotes aprovados nos testes de saúde (as 3 coletas somadas): "
            "`qpu_real` 0 de 6; `simulador` 0 de 6; `os` 6 de 6.") in b


def test_render_e1_resumo(pasta: Path):
    b = bloco(pasta)
    r = ler(pasta / "dia6_coleta2_qpu_vs_sim_resumo.csv")[0]
    esperado = (f"| 2 | qpu_real | {rc.num(r['frac1_lote1'], 4)} | {rc.num(r['frac1_lote2'], 4)} | "
                f"{rc.num(r['zdiff_dp'], 3)} | {r['zdiff_n_acima3']} | {rc.num(r['zdiff_max_abs'], 2)} |")
    assert esperado in b


def test_render_e2(pasta: Path):
    b = bloco(pasta)
    assert "| faulty_biased | p=0.501 | deteccao | 1.000.000 | 1 | 200 | 60 | 0,3000 |" in b
    assert "| faulty_replay | - | referencia | 1.000.000 | 1 | 100 | 0 | 0,0000 |" in b
    assert ("Falso positivo na fonte `os`: 52 de 2000 lotes em 1.000.000 bits (0,0260); "
            "18 de 500 lotes em 4.000.000 bits (0,0360).") in b


def test_render_e3(pasta: Path):
    b = bloco(pasta)
    assert "| coleta_bits_por_s | 300.019,2000 | bits/s |" in b
    assert "| razao_s_por_mbit_qpu_sobre_os | 15,40 | vezes |" in b
    assert "| criterio_muito_mais_caro | sim | booleano |" in b
    assert "| coleta_custo_por_mbit_util_pay_as_you_go | indefinido | USD/Mbit |" in b
    assert "O custo por Mbit útil da QPU real é indefinido: 0 lotes aprovados na coleta." in b
    assert "| preco_fonte |" not in b


def test_render_e4(pasta: Path):
    b = bloco(pasta)
    assert "| base_boa | hash | - | segura | 100 | 100 | 97 | 0,9700 | - |" in b
    assert "| adv_forca | hash | 8 | segura | 100 | 100 | 97 | 0,9700 | 1,0000 |" in b
    assert "| sem_semente | hash | - | sem_semente | 100 | 0 | 0 | - | - |" in b
    assert "`-` marca célula vazia no CSV de origem" in b


def test_render_e5(pasta: Path):
    b = bloco(pasta)
    assert "| ideal_amostrado | compatível com 2*raiz(2) | 100 | 2,828795 | 0,024325 | sim |" in b
    assert "| classico_aleatorio | S <= 2 | 100 | -0,000685 | 0,030991 | sim |" in b
    assert "Critério pré-registrado cumprido em 5 de 5 configurações." in b


def test_render_e5_contagem_com_falha(tmp_path: Path):
    def alterar(p: Path):
        t = (p / "e5_resumo.csv").read_text(encoding="utf-8")
        (p / "e5_resumo.csv").write_bytes(t.replace("0.007349,True", "0.007349,False").encode("utf-8"))
    b = bloco(montar_pasta(tmp_path, alterar))
    assert "Critério pré-registrado cumprido em 4 de 5 configurações." in b
    assert "| ruido_fake_kingston |" in b and "| não |" in b


def test_render_ressalvas_e_origens(pasta: Path):
    b = bloco(pasta)
    assert "a deriva entre dias foi medida só contra a coleta 1" in b
    assert "nenhuma compara coleta 2 com coleta 3" in b
    assert "o CHSH na QPU real não foi feito" in b
    assert "T_TEMPO" in b and "dia6_*_por_qubit.csv" in b
    assert "não dos CSVs" in b and "cada uma conferida" not in b
    longo = ler(pasta / rc.ARQ_LONG)
    for l in longo:
        assert f"- `{l['arquivo_origem']}`: `{l['sha256_origem']}`" in b
    assert b.count("- `e5_resumo.csv`: `") == 1
    assert f"- `{rc.ARQ_LONG}`: `{h(pasta / rc.ARQ_LONG)}`" in b
    assert f"- `{rc.ARQ_GATE}`: `{h(pasta / rc.ARQ_GATE)}`" in b


def test_render_deterministico(pasta: Path):
    assert bloco(pasta) == bloco(pasta)


# --- frases verificadas: cada falha recusa ---

def test_recusa_deriva_contra_coleta_2(tmp_path: Path):
    def alterar(p: Path):
        editar(p, "dia6_deriva_coleta3_estabilidade.csv",
               lambda ls: ls[1].update(lote_a="coleta2_001"))
    pasta = montar_pasta(tmp_path, alterar)
    with pytest.raises(rc.Recusa, match="entre a coleta 2 e a coleta 3: coleta2_001 x coleta3_001"):
        bloco(pasta)


def _trocar_linha(p: Path, arquivo: str, velha: str, nova: str) -> None:
    t = (p / arquivo).read_text(encoding="utf-8")
    assert velha in t
    (p / arquivo).write_bytes(t.replace(velha, nova, 1).encode("utf-8"))


def test_recusa_coleta3_contra_coleta2_invertida(tmp_path: Path):
    pasta = montar_pasta(tmp_path, lambda p: _trocar_linha(
        p, "dia6_deriva_coleta2_estabilidade.csv", "coleta1_002,coleta2_002,", "coleta3_002,coleta2_002,"))
    with pytest.raises(rc.Recusa, match="entre a coleta 2 e a coleta 3"):
        bloco(pasta)


def test_recusa_entre_sessoes_sem_coleta1(tmp_path: Path):
    pasta = montar_pasta(tmp_path, lambda p: _trocar_linha(
        p, "dia6_deriva_dia_estabilidade.csv", "cal_001,coleta1_001,", "cal_001,coleta2_001,"))
    with pytest.raises(rc.Recusa, match="sem a coleta 1: cal_001 x coleta2_001"):
        bloco(pasta)


def test_mesma_sessao_permitida_em_qualquer_coleta(pasta: Path):
    b = bloco(pasta)
    assert "| coleta2_vs_coleta1 | coleta2_001 | coleta2_002 |" in b
    assert "| coleta3_vs_coleta1 | coleta3_001 | coleta3_002 | -0,288 | 1,089 | 1 | 3,20 |" in b
    assert "| mesmo_dia | cal_001 | cal_002 |" in b


def test_recusa_lote_fora_do_padrao(tmp_path: Path):
    pasta = montar_pasta(tmp_path, lambda p: _trocar_linha(
        p, "dia6_deriva_coleta3_estabilidade.csv", "coleta3_001,coleta3_002,", "coleta3_001,coleta3-002,"))
    with pytest.raises(rc.Recusa, match="fora do padrão: coleta3-002"):
        bloco(pasta)


def test_sessao():
    assert rc.sessao("coleta3_002") == "coleta3" and rc.sessao("cal_001") == "cal"
    for ruim in ("coleta3_02", "coleta3_0021", "Coleta3_002", "coleta3002", "_001", "coleta3_00a"):
        with pytest.raises(rc.Recusa):
            rc.sessao(ruim)


def test_recusa_conjunto_de_derivas_diferente(tmp_path: Path):
    def alterar(p: Path):
        (p / "dia6_deriva_coleta3_estabilidade.csv").rename(p / "x.csv")
        (p / "x.csv").rename(p / "dia6_deriva_coleta3_estabilidade.csv")
    pasta = montar_pasta(tmp_path, alterar)
    facts = rc.load(pasta)
    facts["longo"] = [l for l in facts["longo"]
                      if not (l["experimento"] == "E1" and "deriva=coleta3_vs_coleta1" in l["chave"]
                              and "deriva_estabilidade" in l["chave"])]
    with pytest.raises(rc.Recusa, match="derivas inesperadas"):
        rc.render(facts, pasta)


def test_recusa_config_e5_com_qpu(tmp_path: Path):
    def alterar(p: Path):
        t = (p / "e5_resumo.csv").read_text(encoding="utf-8")
        (p / "e5_resumo.csv").write_bytes(t.replace("classico_otimo", "qpu_real").encode("utf-8"))
    with pytest.raises(rc.Recusa, match="configurações inesperadas"):
        bloco(montar_pasta(tmp_path, alterar))


def test_recusa_config_e5_extra(tmp_path: Path):
    def alterar(p: Path):
        t = (p / "e5_resumo.csv").read_text(encoding="utf-8")
        (p / "e5_resumo.csv").write_bytes((t + t.splitlines()[1] .replace("ideal_exato", "qpu_real") + "\n").encode("utf-8"))
    with pytest.raises(rc.Recusa, match="configurações inesperadas"):
        bloco(montar_pasta(tmp_path, alterar))


def test_recusa_custo_util_definido(tmp_path: Path):
    def alterar(p: Path):
        t = (p / "e3_resumo.csv").read_text(encoding="utf-8")
        (p / "e3_resumo.csv").write_bytes(
            t.replace("pay_as_you_go,indefinido", "pay_as_you_go,5.0").encode("utf-8"))
    with pytest.raises(rc.Recusa, match="não está indefinido"):
        bloco(montar_pasta(tmp_path, alterar))


def test_recusa_lotes_aprovados_diferente_de_zero(tmp_path: Path):
    def alterar(p: Path):
        t = (p / "e3_resumo.csv").read_text(encoding="utf-8")
        (p / "e3_resumo.csv").write_bytes(
            t.replace("coleta_lotes_aprovados,0", "coleta_lotes_aprovados,2").encode("utf-8"))
    with pytest.raises(rc.Recusa, match="não está indefinido"):
        bloco(montar_pasta(tmp_path, alterar))


def test_recusa_metrica_e3_ausente(tmp_path: Path):
    def alterar(p: Path):
        t = (p / "e3_resumo.csv").read_text(encoding="utf-8")
        (p / "e3_resumo.csv").write_bytes(
            "\n".join(l for l in t.splitlines() if not l.startswith("local_bits_por_s")).encode("utf-8") + b"\n")
    with pytest.raises(rc.Recusa, match="E3 sem a métrica local_bits_por_s"):
        bloco(montar_pasta(tmp_path, alterar))


@pytest.mark.parametrize("nome", list(rc.ARQUIVOS_PAINEL))
def test_recusa_arquivo_do_painel_ausente(pasta: Path, nome: str):
    (pasta / nome).unlink()
    with pytest.raises(rc.Recusa, match=nome):
        bloco(pasta)


def test_recusa_saude_approved_estranho(tmp_path: Path):
    def alterar(p: Path):
        editar(p, "dia6_qpu_vs_sim_lotes.csv", lambda ls: ls[0].update(saude_approved="talvez"))
    with pytest.raises(rc.Recusa, match="saude_approved inesperado"):
        bloco(montar_pasta(tmp_path, alterar))


def test_recusa_criterio_estranho(tmp_path: Path):
    def alterar(p: Path):
        t = (p / "e5_resumo.csv").read_text(encoding="utf-8")
        (p / "e5_resumo.csv").write_bytes(t.replace("0.007297,True", "0.007297,talvez").encode("utf-8"))
    with pytest.raises(rc.Recusa, match="criterio_ok inesperado"):
        bloco(montar_pasta(tmp_path, alterar))


def test_recusa_e2_sem_falso_positivo(tmp_path: Path):
    def alterar(p: Path):
        def f(ls):
            for l in ls:
                if l["tipo"] == "falso_positivo":
                    l["tipo"] = "deteccao"
        editar(p, "e2_resumo.csv", f)
    with pytest.raises(rc.Recusa, match="falso positivo"):
        bloco(montar_pasta(tmp_path, alterar))


def test_agrupar_tabela_ausente(pasta: Path):
    with pytest.raises(rc.Recusa, match="sem linhas da tabela"):
        rc.agrupar(ler(pasta / rc.ARQ_LONG), "E2", "nao_existe")


def test_agrupar_ordem_e_metricas(pasta: Path):
    g = rc.agrupar(ler(pasta / rc.ARQ_LONG), "E5", "e5_resumo")
    assert [p["configuracao"] for p, _ in g] == list(rc.CONFIGS_E5)
    assert g[1][1]["s_media"] == "2.828795" and "esperado" in g[1][1]


# --- apply ---

def test_apply_acrescenta_no_fim(tmp_path: Path):
    p = projeto(tmp_path)
    antes = p.read_bytes()
    r = rc.apply(p, "A\nB", antes=h(p))
    assert r == "registrado"
    assert p.read_bytes() == antes + b"\r\nA\r\nB\r\n"
    assert not (tmp_path / "PROJECT.md.tmp").exists()


def test_apply_preserva_crlf_e_utf8(tmp_path: Path):
    p = projeto(tmp_path)
    rc.apply(p, "ação\nx", antes=h(p))
    d = p.read_bytes()
    assert d.count(b"\n") == d.count(b"\r\n") and "ação".encode() in d


def test_apply_recusa_hash_diferente(tmp_path: Path):
    p = projeto(tmp_path)
    antes = p.read_bytes()
    with pytest.raises(rc.Recusa, match="SHA-256"):
        rc.apply(p, "A", antes="0" * 64)
    assert p.read_bytes() == antes


def test_apply_idempotente(tmp_path: Path):
    p = projeto(tmp_path)
    blk = f"{rc.START}\nx\n{rc.END}"
    assert rc.apply(p, blk, antes=h(p)) == "registrado"
    depois = p.read_bytes()
    assert rc.apply(p, blk, antes=h(p)) == "já registrado"
    assert p.read_bytes() == depois


def test_apply_recusa_bloco_diferente_existente(tmp_path: Path):
    p = projeto(tmp_path)
    rc.apply(p, f"{rc.START}\nx\n{rc.END}", antes=h(p))
    depois = p.read_bytes()
    with pytest.raises(rc.Recusa, match="já existe e é diferente"):
        rc.apply(p, f"{rc.START}\ny\n{rc.END}", antes=h(p))
    assert p.read_bytes() == depois


@pytest.mark.parametrize("final", [
    b"a\r\n<!-- dia7-consolidado:start -->\r\n",
    b"a\r\n<!-- dia7-consolidado:end -->\r\n",
    b"<!-- dia7-consolidado:end -->\r\n<!-- dia7-consolidado:start -->\r\n",
    b"<!-- dia7-consolidado:start -->\r\n<!-- dia7-consolidado:start -->\r\n<!-- dia7-consolidado:end -->\r\n"])
def test_apply_recusa_marcadores_quebrados(tmp_path: Path, final: bytes):
    p = projeto(tmp_path, final)
    antes = p.read_bytes()
    with pytest.raises(rc.Recusa, match="marcadores"):
        rc.apply(p, "A", antes=h(p))
    assert p.read_bytes() == antes


def test_apply_recusa_sem_crlf_final(tmp_path: Path):
    p = projeto(tmp_path, b"fim")
    with pytest.raises(rc.Recusa, match="CRLF"):
        rc.apply(p, "A", antes=h(p))


def test_apply_recusa_lf_solto(tmp_path: Path):
    p = projeto(tmp_path, b"a\nb\r\n")
    antes = p.read_bytes()
    with pytest.raises(rc.Recusa, match="LF solto"):
        rc.apply(p, "A", antes=h(p))
    assert p.read_bytes() == antes


def test_apply_recusa_bom(tmp_path: Path):
    p = tmp_path / "PROJECT.md"
    p.write_bytes(b"\xef\xbb\xbfa\r\n")
    with pytest.raises(rc.Recusa, match="BOM"):
        rc.apply(p, "A", antes=h(p))


def test_apply_recusa_nao_utf8(tmp_path: Path):
    p = tmp_path / "PROJECT.md"
    p.write_bytes("é\r\n".encode("cp1252"))
    with pytest.raises(rc.Recusa, match="UTF-8"):
        rc.apply(p, "A", antes=h(p))


def test_apply_sem_antes_nao_confere_hash(tmp_path: Path):
    p = projeto(tmp_path)
    assert rc.apply(p, "A") == "registrado"


def test_apply_falha_na_escrita_nao_deixa_rastro(tmp_path: Path, monkeypatch):
    p = projeto(tmp_path)
    antes = p.read_bytes()
    def quebrado(src, dst):
        raise OSError("disco")
    monkeypatch.setattr(rc.os, "replace", quebrado)
    with pytest.raises(OSError):
        rc.apply(p, "A", antes=h(p))
    assert p.read_bytes() == antes and not (tmp_path / "PROJECT.md.tmp").exists()


def test_apply_tmp_existente_nao_sobrescreve(tmp_path: Path):
    p = projeto(tmp_path)
    (tmp_path / "PROJECT.md.tmp").write_bytes(b"outro")
    antes = p.read_bytes()
    with pytest.raises(FileExistsError):
        rc.apply(p, "A", antes=h(p))
    assert p.read_bytes() == antes and (tmp_path / "PROJECT.md.tmp").read_bytes() == b"outro"


# --- main ---

@pytest.fixture
def ambiente(pasta: Path, tmp_path: Path, monkeypatch):
    p = projeto(tmp_path)
    monkeypatch.setattr(rc, "HASH_ANTES", h(p))
    return pasta, p


def test_main_conferir_nao_grava(ambiente, capsys):
    pasta, p = ambiente
    antes = p.read_bytes()
    assert rc.main(["--conferir"], path=p, results=pasta) == 0
    assert p.read_bytes() == antes
    out = capsys.readouterr().out
    assert "nada gravado" in out and "igual" in out and "bloco montado" in out


def test_main_conferir_avisa_hash_diferente(ambiente, capsys):
    pasta, p = ambiente
    p.write_bytes(p.read_bytes() + b"mais\r\n")
    assert rc.main(["--conferir"], path=p, results=pasta) == 0
    assert "DIFERENTE de" in capsys.readouterr().out


def test_main_gravar_e_idempotente(ambiente, capsys):
    pasta, p = ambiente
    assert rc.main(["--gravar"], path=p, results=pasta) == 0
    gravado = p.read_bytes()
    blk = bloco(pasta).replace("\n", "\r\n").encode("utf-8")
    assert gravado.endswith(b"\r\n" + blk + b"\r\n")
    out = capsys.readouterr().out
    assert "registrado: bloco dia7-consolidado" in out and h(p) in out
    assert rc.main(["--gravar"], path=p, results=pasta) == 0
    assert p.read_bytes() == gravado
    assert "já registrado" in capsys.readouterr().out


def test_main_gravar_recusa_hash(ambiente, capsys):
    pasta, p = ambiente
    p.write_bytes(p.read_bytes() + b"mudou\r\n")
    antes = p.read_bytes()
    assert rc.main(["--gravar"], path=p, results=pasta) == 1
    assert p.read_bytes() == antes and "RECUSADO" in capsys.readouterr().out


def test_main_recusa_consolidado_adulterado(ambiente, capsys):
    pasta, p = ambiente
    antes = p.read_bytes()
    (pasta / rc.ARQ_LONG).write_bytes((pasta / rc.ARQ_LONG).read_bytes() + b"x")
    assert rc.main(["--gravar"], path=p, results=pasta) == 1
    assert p.read_bytes() == antes and "derivação exata" in capsys.readouterr().out


def test_main_recusa_project_ausente(ambiente, tmp_path: Path, capsys):
    pasta, _ = ambiente
    assert rc.main(["--gravar"], path=tmp_path / "nao.md", results=pasta) == 1
    assert "arquivo ausente" in capsys.readouterr().out


def test_main_modo_obrigatorio(ambiente):
    pasta, p = ambiente
    with pytest.raises(SystemExit):
        rc.main([], path=p, results=pasta)


def test_carregar_consolidar_ausente(tmp_path: Path):
    with pytest.raises(rc.Recusa, match="ausente"):
        rc.carregar_consolidar(tmp_path / "nao.py")


# --- dados reais (só leitura; pulado se o consolidado real não existir) ---

def test_dados_reais_renderizam():
    real = ROOT / "data" / "results"
    if not (real / rc.ARQ_LONG).is_file():
        pytest.skip("consolidado real ausente")
    b = rc.render(rc.load(real), real)
    assert b.startswith(rc.START) and b.endswith(rc.END)
    assert "Critério pré-registrado cumprido em 5 de 5 configurações." in b


# --- testes vindos de mutantes sobreviventes ---

def test_render_e3_traz_todas_as_metricas_listadas(pasta: Path):
    b = bloco(pasta)
    for nome in rc.E3_METRICAS:
        assert f"| {nome} | " in b, nome
    assert "| coleta_lotes_aprovados | 0 | lotes |" in b


def test_agrupar_filtra_por_experimento():
    longo = [{"experimento": "E2", "chave": "tabela=t;a=1", "metrica": "m", "valor": "x"},
             {"experimento": "E4", "chave": "tabela=t;a=2", "metrica": "m", "valor": "y"}]
    g = rc.agrupar(longo, "E4", "t")
    assert g == [({"a": "2"}, {"m": "y"})]
    with pytest.raises(rc.Recusa):
        rc.agrupar(longo, "E1", "t")


def test_recusa_e5_com_configuracao_faltando(tmp_path: Path):
    def alterar(p: Path):
        t = (p / "e5_resumo.csv").read_text(encoding="utf-8").splitlines()
        (p / "e5_resumo.csv").write_bytes(("\n".join(t[:-1]) + "\n").encode("utf-8"))
    with pytest.raises(rc.Recusa, match="configurações inesperadas"):
        bloco(montar_pasta(tmp_path, alterar))


def test_apply_recusa_end_duplicado(tmp_path: Path):
    p = projeto(tmp_path, b"<!-- dia7-consolidado:start -->\r\nx\r\n"
                          b"<!-- dia7-consolidado:end -->\r\n<!-- dia7-consolidado:end -->\r\n")
    antes = p.read_bytes()
    with pytest.raises(rc.Recusa, match="marcadores"):
        rc.apply(p, "A", antes=h(p))
    assert p.read_bytes() == antes


def test_apply_confere_o_que_gravou(tmp_path: Path, monkeypatch):
    p = projeto(tmp_path)
    real = rc.os.replace
    def adultera(src, dst):
        Path(src).write_bytes(b"corrompido")
        real(src, dst)
    monkeypatch.setattr(rc.os, "replace", adultera)
    with pytest.raises(rc.Recusa, match="pós-gravação"):
        rc.apply(p, "A", antes=h(p))


# --- célula vazia vira '-' só para exibir; métricas das frases seguem obrigatórias ---

def test_metricas_lidas_existem_no_consolidar(pasta: Path, monkeypatch):
    """Todo nome pedido a obter() precisa ser coluna copiada pelo consolidar (pega erro de digitação)."""
    pedidos: list[str] = []
    real = rc.obter
    def gravador(m, nome, opcional=False):
        pedidos.append(nome)
        return real(m, nome, opcional)
    monkeypatch.setattr(rc, "obter", gravador)
    bloco(pasta)
    copiadas = {c for f in cd.FONTES for c in f.valores}
    assert pedidos and set(pedidos) <= copiadas, sorted(set(pedidos) - copiadas)


def test_fixture_completa_nao_gera_traco_inesperado(pasta: Path, monkeypatch):
    vazios: list[str] = []
    real = rc.obter
    def gravador(m, nome, opcional=False):
        if nome not in m:
            vazios.append(nome)
        return real(m, nome, opcional)
    monkeypatch.setattr(rc, "obter", gravador)
    bloco(pasta)
    assert set(vazios) == {"frac_alvo", "taxa_aprovacao"}


def test_op():
    assert rc.op({"a": "1"}, "a") == "1" and rc.op({}, "a") == "-"


@pytest.mark.parametrize("arquivo,velho,novo,msg", [
    ("dia6_qpu_vs_sim_lotes.csv", "saude_approved", "saude_aprovado", "métrica ausente: saude_approved"),
])
def test_coluna_obrigatoria_ausente_no_consolidado(pasta: Path, arquivo, velho, novo, msg):
    facts = rc.load(pasta)
    facts["longo"] = [l for l in facts["longo"] if l["metrica"] != velho]
    with pytest.raises(rc.Recusa, match=msg):
        rc.render(facts, pasta)


@pytest.mark.parametrize("metrica", ["criterio_ok", "n_lotes", "n_reprovados", "taxa"])
def test_metricas_das_frases_continuam_obrigatorias(pasta: Path, metrica: str):
    facts = rc.load(pasta)
    exp = "E5" if metrica == "criterio_ok" else "E2"
    facts["longo"] = [l for l in facts["longo"]
                      if not (l["experimento"] == exp and l["metrica"] == metrica
                              and ("falso_positivo" in l["chave"] or exp == "E5"))]
    with pytest.raises(rc.Recusa, match=f"métrica ausente: {metrica}"):
        rc.render(facts, pasta)


def test_tabelas_mostram_traco_para_celula_vazia(tmp_path: Path):
    def alterar(p: Path):
        editar(p, "dia6_coleta2_qpu_vs_sim_resumo.csv", lambda ls: ls[0].update(zdiff_dp=""))
        editar(p, "dia6_qpu_vs_sim_lotes.csv", lambda ls: ls[0].update(saude_h_estimated=""))
        t = (p / "e5_resumo.csv").read_text(encoding="utf-8")
        (p / "e5_resumo.csv").write_bytes(t.replace(",100,2.828795,", ",,2.828795,").encode("utf-8"))
    b = bloco(montar_pasta(tmp_path, alterar))
    assert "| 1 | qpu_real | 1 | não | - | excluded | 0 |" in b
    assert "| ideal_amostrado | compatível com 2*raiz(2) | - | 2,828795 |" in b
    assert any(l.startswith("| 2 | qpu_real | ") and " | - | " in l for l in b.split("\n"))
