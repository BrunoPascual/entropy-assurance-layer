"""Registra o consolidado E1 a E5 no PROJECT.md (bloco dia7-consolidado).

Lê data/results/consolidado_gate.csv e consolidado_e1_e5.csv, confere que os dois
são a derivação exata dos CSVs de origem (re-executa consolidar_dia7.montar com o
commit gravado no gate) e acrescenta ao fim do PROJECT.md um bloco gerado só
desses CSVs. Nenhum número é digitado à mão; as frases de ressalva só são
gravadas se confirmadas pelos CSVs (deriva, CHSH, custo útil, arquivos do painel), e
qualquer falha recusa sem gravar.

Uso (na raiz do projeto):
    py -3.12 scripts/registrar_consolidado.py --conferir   # monta, não grava
    py -3.12 scripts/registrar_consolidado.py --gravar     # só se o hash bater
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import io
import os
import re
import sys
from pathlib import Path

TARGET = Path("PROJECT.md")
RESULTS = Path("data/results")
HASH_ANTES = "48a7143c539b599e8a6158bfefb586f0d0b7f9c755cebc16945efd589880f514"
START = "<!-- dia7-consolidado:start -->"
END = "<!-- dia7-consolidado:end -->"
ARQ_LONG = "consolidado_e1_e5.csv"
ARQ_GATE = "consolidado_gate.csv"
SCRIPT = Path(__file__).resolve().with_name("consolidar_dia7.py")

CONFIGS_E5 = ("ideal_exato", "ideal_amostrado", "ruido_fake_kingston",
              "classico_aleatorio", "classico_otimo")
DERIVAS = ("mesmo_dia", "coleta2_vs_coleta1", "coleta3_vs_coleta1")
E3_METRICAS = ("qpu_jobs", "qpu_segundos", "qpu_bits_brutos", "coleta_bits_por_s",
               "coleta_custo_por_mbit_bruto_pay_as_you_go", "coleta_lotes_aprovados",
               "coleta_bits_uteis", "coleta_custo_por_mbit_util_pay_as_you_go",
               "local_bits_por_s", "razao_s_por_mbit_qpu_sobre_os", "criterio_limiar",
               "criterio_muito_mais_caro")
ARQUIVOS_PAINEL = ("dia6_qpu_vs_sim_por_qubit.csv", "dia6_coleta2_qpu_vs_sim_por_qubit.csv",
                   "dia6_coleta3_qpu_vs_sim_por_qubit.csv", "dia6_qpu_excesso_leitura.csv",
                   "dia6_coleta2_qpu_excesso_leitura.csv",
                   "dia6_coleta3_qpu_excesso_leitura.csv")


class Recusa(Exception):
    """Algo não bateu; nada é gravado."""


def sha256(data: bytes) -> str:
    """SHA-256 em hex dos bytes."""
    return hashlib.sha256(data).hexdigest()


def carregar_consolidar(path: Path = SCRIPT):
    """Importa consolidar_dia7.py por caminho, para reaproveitar montar e csv_bytes."""
    if not path.is_file():
        raise Recusa(f"arquivo ausente: {path.name}")
    spec = importlib.util.spec_from_file_location("consolidar_dia7", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["consolidar_dia7"] = mod
    spec.loader.exec_module(mod)
    return mod


def ler(path: Path) -> tuple[list[dict[str, str]], bytes]:
    """Lê um CSV UTF-8 e devolve as linhas e os bytes em disco."""
    if not path.is_file():
        raise Recusa(f"arquivo ausente: {path.name}")
    data = path.read_bytes()
    try:
        texto = data.decode("utf-8")
    except UnicodeDecodeError:
        raise Recusa(f"não é UTF-8: {path.name}") from None
    linhas = list(csv.DictReader(io.StringIO(texto, newline="")))
    if not linhas:
        raise Recusa(f"{path.name}: sem linhas")
    return linhas, data


def load(results: Path, cd=None) -> dict:
    """Lê os dois consolidados e confere que são a derivação exata das origens."""
    cd = cd or carregar_consolidar()
    gate, b_gate = ler(results / ARQ_GATE)
    longo, b_longo = ler(results / ARQ_LONG)
    if [g.get("experimento") for g in gate] != list(cd.EXPERIMENTOS):
        raise Recusa("o gate não traz E1 a E5 nessa ordem")
    commits = {g.get("commit", "") for g in gate}
    if len(commits) != 1 or "" in commits:
        raise Recusa("o gate traz commits diferentes ou vazios")
    commit = commits.pop()
    try:
        esp_longo, esp_gate = cd.montar(results, commit)
    except cd.Recusa as exc:
        raise Recusa(f"origem não confere: {exc}") from None
    if b_longo != cd.csv_bytes(cd.CAMPOS_LONG, esp_longo):
        raise Recusa(f"{ARQ_LONG} não é a derivação exata dos CSVs de origem")
    if b_gate != cd.csv_bytes(cd.CAMPOS_GATE, esp_gate):
        raise Recusa(f"{ARQ_GATE} não é a derivação exata dos CSVs de origem")
    return {"gate": gate, "longo": longo, "commit": commit,
            "sha_gate": sha256(b_gate), "sha_longo": sha256(b_longo)}


# --- formatação ---

def num(valor: str, casas: int) -> str:
    """Número com vírgula decimal e casas fixas; texto não numérico passa direto."""
    try:
        return f"{float(valor):.{casas}f}".replace(".", ",")
    except ValueError:
        return valor


def sim_nao(valor: str) -> str:
    """True/False do CSV como sim/não."""
    return {"True": "sim", "False": "não"}.get(valor, valor)


def milhar(valor: str) -> str:
    """Inteiro com ponto de milhar; texto não inteiro passa direto."""
    return f"{int(valor):,}".replace(",", ".") if re.fullmatch(r"-?\d+", valor) else valor


def copia(valor: str) -> str:
    """Valor do E3 como está no CSV, só com vírgula decimal e sim/não."""
    if valor in ("True", "False"):
        return sim_nao(valor)
    if re.fullmatch(r"-?\d+", valor):
        return milhar(valor) if abs(int(valor)) >= 10000 else valor
    if re.fullmatch(r"-?\d+\.\d+", valor):
        inteiro, frac = valor.split(".")
        return (milhar(inteiro) if abs(int(inteiro)) >= 10000 else inteiro) + "," + frac
    return valor


def tabela(cabecalho: list[str], linhas: list[list[str]]) -> list[str]:
    """Tabela markdown."""
    def cel(t: str) -> str:
        return t.replace("|", "\\|")
    saida = ["| " + " | ".join(cabecalho) + " |", "|" + "---|" * len(cabecalho)]
    saida += ["| " + " | ".join(cel(c) for c in l) + " |" for l in linhas]
    return saida


# --- leitura do formato longo ---

def parse_chave(chave: str) -> tuple[str, dict[str, str]]:
    """Separa 'tabela=X;a=b;...' em (X, {a: b})."""
    params: dict[str, str] = {}
    for parte in chave.split(";"):
        k, sep, v = parte.partition("=")
        if not sep:
            raise Recusa(f"chave malformada: {chave}")
        params[k] = v
    tab = params.pop("tabela", None)
    if tab is None:
        raise Recusa(f"chave sem tabela: {chave}")
    return tab, params


def agrupar(longo: list[dict[str, str]], exp: str, tab: str) -> list[tuple[dict, dict]]:
    """Linhas de uma tabela de origem, em ordem: [(params da chave, {métrica: valor})]."""
    grupos: dict[str, tuple[dict, dict]] = {}
    for l in longo:
        if l["experimento"] != exp:
            continue
        t, params = parse_chave(l["chave"])
        if t != tab:
            continue
        grupos.setdefault(l["chave"], (params, {}))[1][l["metrica"]] = l["valor"]
    if not grupos:
        raise Recusa(f"{exp}: sem linhas da tabela {tab}")
    return list(grupos.values())


def obter(metricas: dict[str, str], nome: str, opcional: bool = False) -> str:
    """Valor de uma métrica; ausente recusa, ou '-' se opcional."""
    if nome in metricas:
        return metricas[nome]
    if opcional:
        return "-"
    raise Recusa(f"métrica ausente: {nome}")


def op(metricas: dict[str, str], nome: str) -> str:
    """Valor só para exibir: célula vazia na origem vira '-'."""
    return obter(metricas, nome, opcional=True)


def exigir(condicao: bool, mensagem: str) -> None:
    """Recusa se a frase não for confirmada pelos CSVs."""
    if not condicao:
        raise Recusa(mensagem)


# --- seções ---

def secao_gate(gate: list[dict[str, str]]) -> list[str]:
    """Tabela do gate do Dia 7."""
    linhas = [[g["experimento"], g["estado"], milhar(g["n_metricas"]), g["n_arquivos"],
               g["ressalva"] or "-"] for g in gate]
    return tabela(["Experimento", "Estado", "Métricas", "Arquivos de origem", "Ressalva"],
                  linhas)


def sessao(lote: str) -> str:
    """Sessão de um lote: 'coleta3_002' -> 'coleta3'; recusa nome fora do padrão."""
    m = re.fullmatch(r"([a-z]+\d*)_\d{3}", lote)
    exigir(m is not None, f"nome de lote fora do padrão: {lote}")
    return m.group(1)


def secao_e1(longo: list[dict[str, str]]) -> tuple[list[str], list[str], list[str]]:
    """Tabelas do E1 e a frase de contagem da saúde; confere a deriva só contra a coleta 1."""
    lotes = agrupar(longo, "E1", "qpu_vs_sim_lotes")
    contagem: dict[str, list[int]] = {}
    linhas_lotes = []
    for p, m in lotes:
        aprovado = obter(m, "saude_approved")
        exigir(aprovado in ("True", "False"), f"saude_approved inesperado: {aprovado}")
        c = contagem.setdefault(p["fonte"], [0, 0])
        c[0] += aprovado == "True"
        c[1] += 1
        linhas_lotes.append([p["coleta"], p["fonte"], p["lote"], sim_nao(aprovado),
                             num(op(m, "saude_h_estimated"), 4), op(m, "pipe_status"),
                             milhar(op(m, "ext_n_output_bits"))])
    t1 = tabela(["Coleta", "Fonte", "Lote", "Aprovado", "H estimada", "Pipeline",
                 "Bits extraídos"], linhas_lotes)
    linhas_res = [[p["coleta"], p["fonte"], num(op(m, "frac1_lote1"), 4),
                   num(op(m, "frac1_lote2"), 4), num(op(m, "zdiff_dp"), 3),
                   op(m, "zdiff_n_acima3"), num(op(m, "zdiff_max_abs"), 2)]
                  for p, m in agrupar(longo, "E1", "qpu_vs_sim_resumo")]
    t2 = tabela(["Coleta", "Fonte", "Fração de 1 (lote 1)", "Fração de 1 (lote 2)",
                 "DP do zdiff", "Qubits com |z| > 3", "|z| máximo"], linhas_res)
    est = agrupar(longo, "E1", "deriva_estabilidade")
    derivas = {p["deriva"] for p, _ in est}
    exigir(derivas == set(DERIVAS), f"derivas inesperadas: {sorted(derivas)}")
    for p, _ in est:
        sa, sb = sessao(p["lote_a"]), sessao(p["lote_b"])
        exigir({sa, sb} != {"coleta2", "coleta3"},
               f"há comparação entre a coleta 2 e a coleta 3: {p['lote_a']} x {p['lote_b']}")
        exigir(sa == sb or "coleta1" in (sa, sb),
               f"comparação entre sessões sem a coleta 1: {p['lote_a']} x {p['lote_b']}")
    linhas_est = [[p["deriva"], p["lote_a"], p["lote_b"], num(op(m, "zdiff_media"), 3),
                   num(op(m, "zdiff_dp"), 3), op(m, "zdiff_n_acima3"),
                   num(op(m, "zdiff_max_abs"), 2)] for p, m in est]
    t3 = tabela(["Comparação", "Lote A", "Lote B", "zdiff médio", "DP do zdiff",
                 "Qubits com |z| > 3", "|z| máximo"], linhas_est)
    partes = [f"`{f}` {a} de {t}" for f, (a, t) in contagem.items()]
    frase = ("Lotes aprovados nos testes de saúde (as 3 coletas somadas): "
             + "; ".join(partes) + ".")
    return t1 + [""] + t2 + [""] + t3, [frase], list(contagem)


def secao_e2(longo: list[dict[str, str]]) -> tuple[list[str], list[str]]:
    """Tabela do E2 e a frase dos falsos positivos da fonte os."""
    grupos = agrupar(longo, "E2", "e2_resumo")
    linhas, fp = [], []
    for p, m in grupos:
        par = f"{p['parametro']}={p['valor']}" if p["parametro"] else "-"
        linhas.append([p["fonte"], par, p["tipo"], milhar(p["n_bits"]), p["leitura"],
                       op(m, "n_lotes"), op(m, "n_reprovados"), num(op(m, "taxa"), 4)])
        if p["tipo"] == "falso_positivo":
            fp.append(f"{obter(m, 'n_reprovados')} de {obter(m, 'n_lotes')} lotes em "
                      f"{milhar(p['n_bits'])} bits ({num(obter(m, 'taxa'), 4)})")
    exigir(bool(fp), "E2 sem linhas de falso positivo")
    frase = "Falso positivo na fonte `os`: " + "; ".join(fp) + "."
    return tabela(["Fonte", "Parâmetro", "Tipo", "Bits", "Leitura", "Lotes", "Reprovados",
                   "Taxa"], linhas), [frase]


def secao_e3(longo: list[dict[str, str]]) -> tuple[list[str], list[str]]:
    """Tabela do E3 e a frase do custo útil indefinido, só se confirmada."""
    linhas_e3 = {l["metrica"]: l for l in longo if l["experimento"] == "E3"}
    for nome in E3_METRICAS:
        exigir(nome in linhas_e3, f"E3 sem a métrica {nome}")
    linhas = [[n, copia(linhas_e3[n]["valor"]), linhas_e3[n]["unidade"]]
              for n in E3_METRICAS]
    frases = []
    util = linhas_e3["coleta_custo_por_mbit_util_pay_as_you_go"]["valor"]
    aprov = linhas_e3["coleta_lotes_aprovados"]["valor"]
    exigir(util == "indefinido" and aprov == "0",
           "o custo por Mbit útil não está indefinido com 0 lotes aprovados")
    frases.append("O custo por Mbit útil da QPU real é indefinido: "
                  f"{aprov} lotes aprovados na coleta.")
    return tabela(["Métrica", "Valor", "Unidade"], linhas), frases


def secao_e4(longo: list[dict[str, str]]) -> list[str]:
    """Tabela do E4."""
    linhas = []
    for p, m in agrupar(longo, "E4", "e4_resumo"):
        linhas.append([p["cenario"], p["combinador"], p["k"] or "-", op(m, "esperado"),
                       op(m, "n_seq"), op(m, "n_seq_completas"), op(m, "n_aprovadas"),
                       num(op(m, "taxa_aprovacao"), 4), num(op(m, "frac_alvo"), 4)])
    return tabela(["Cenário", "Combinador", "k", "Esperado", "Sequências", "Completas",
                   "Aprovadas", "Taxa de aprovação", "Fração alvo"], linhas)


def secao_e5(longo: list[dict[str, str]]) -> tuple[list[str], list[str]]:
    """Tabela do E5 (etapa A), a contagem de critérios e a confirmação de que não há QPU."""
    grupos = agrupar(longo, "E5", "e5_resumo")
    nomes = tuple(p["configuracao"] for p, _ in grupos)
    exigir(nomes == CONFIGS_E5, f"configurações inesperadas no E5: {nomes}")
    ok = 0
    linhas = []
    for p, m in grupos:
        crit = obter(m, "criterio_ok")
        exigir(crit in ("True", "False"), f"criterio_ok inesperado: {crit}")
        ok += crit == "True"
        linhas.append([p["configuracao"], op(m, "esperado"), op(m, "n_reps"),
                       num(op(m, "s_media"), 6), num(op(m, "s_dp"), 6), sim_nao(crit)])
    frase = f"Critério pré-registrado cumprido em {ok} de {len(grupos)} configurações."
    return tabela(["Configuração", "Esperado", "Repetições", "S médio", "DP de S",
                   "Critério"], linhas), [frase]


def confere_painel(results: Path) -> None:
    """Os CSVs que o painel lê direto precisam existir."""
    for nome in ARQUIVOS_PAINEL:
        exigir((results / nome).is_file(), f"arquivo do painel ausente: {nome}")


def render(facts: dict, results: Path = RESULTS) -> str:
    """Bloco do PROJECT.md, com LF; os números saem só dos CSVs."""
    longo, gate = facts["longo"], facts["gate"]
    confere_painel(results)
    e1_tabelas, e1_frases, _ = secao_e1(longo)
    e2_tabela, e2_frases = secao_e2(longo)
    e3_tabela, e3_frases = secao_e3(longo)
    e5_tabela, e5_frases = secao_e5(longo)
    origens = []
    for l in longo:
        par = (l["arquivo_origem"], l["sha256_origem"])
        if par not in origens:
            origens.append(par)
    estados = ", ".join(f"{g['experimento']} ({g['estado']})" for g in gate)
    nlinhas = len(longo)
    L = [START, "### Consolidado E1 a E5 para o painel (Dia 7, registro gerado dos CSVs)", "",
         f"Gerado por `scripts/registrar_consolidado.py` a partir de `{ARQ_GATE}` e "
         f"`{ARQ_LONG}`, que o `scripts/consolidar_dia7.py` montou dos CSVs de resultados "
         f"na rodada sobre o commit `{facts['commit']}` (coluna `commit` das 5 linhas do "
         "gate). Nenhum número foi digitado à mão. O registro confere que os dois CSVs "
         "são a derivação exata dos arquivos de origem, com o SHA-256 de cada origem; as "
         "frases sobre a deriva, o CHSH, o custo útil e os arquivos do painel só são "
         "gravadas se confirmadas pelos CSVs.", "",
         f"**Gate do Dia 7 (tabela com os 5 experimentos):** {estados}; "
         f"{milhar(str(nlinhas))} linhas no formato longo "
         "(experimento, chave, métrica, valor, unidade, estado, arquivo de origem e "
         "SHA-256 da origem).", ""]
    L += secao_gate(gate)
    L += ["", "Nas tabelas abaixo, `-` marca célula vazia no CSV de origem; as métricas "
          "que sustentam as frases da Leitura são obrigatórias e, se faltarem, o "
          "registro é recusado."]
    L += ["", "**E1, QPU real contra simulador e `os` (3 coletas) e deriva:**", ""]
    L += e1_tabelas
    L += ["", "**E2, ataques (detecção e falso positivo):**", ""] + e2_tabela
    L += ["", "**E3, vazão e custo (custo teórico):**", ""] + e3_tabela
    L += ["", "**E4, resiliência da mistura:**", ""] + secao_e4(longo)
    L += ["", "**E5, CHSH etapa A (sem QPU):**", ""] + e5_tabela
    L += ["", "**Leitura (contagens calculadas dos CSVs):**", ""]
    L += [f"- {f}" for f in e1_frases + e2_frases + e3_frases + e5_frases]
    L += ["", "**Ressalvas (deriva, CHSH, custo útil e arquivos do painel conferidos contra os "
          "CSVs antes de gravar; \"sem gasto\" e T_TEMPO vêm de decisão e limitação já "
          "registradas, não dos CSVs):**", "",
          "- E1: a deriva entre dias foi medida só contra a coleta 1; a coleta 3 contra a "
          "coleta 2 não foi feita (toda comparação entre sessões diferentes envolve um lote "
          "da coleta 1, e nenhuma compara coleta 2 com coleta 3).",
          "- E5: só a etapa A, com as 5 configurações sem QPU real; o CHSH na QPU real "
          "não foi feito e a hipótese de que a QPU real fique entre 2 e 2√2 não foi "
          "testada.",
          "- E3: custo teórico no Open Plan, sem gasto; os tempos medidos dependem da "
          "velocidade da máquina (T_TEMPO).",
          "- O consolidado não traz o viés por qubit nem o excesso de leitura; o painel "
          "lê direto os `dia6_*_por_qubit.csv` e `dia6_*_excesso_leitura.csv` das 3 "
          "coletas (os 6 arquivos existem em `data/results`).", "",
          "**Origens (SHA-256 dos bytes em disco, como gravados no consolidado):**", ""]
    L += [f"- `{a}`: `{h}`" for a, h in origens]
    L += ["", "**CSVs gerados (SHA-256 dos bytes em disco):**", "",
          f"- `{ARQ_LONG}`: `{facts['sha_longo']}`",
          f"- `{ARQ_GATE}`: `{facts['sha_gate']}`", END]
    return "\n".join(L)


# --- gravação ---

def apply(path: Path, block: str, antes: str | None = None) -> str:
    """Acrescenta o bloco ao fim do arquivo, tudo ou nada; idempotente."""
    data = path.read_bytes()
    try:
        texto = data.decode("utf-8")
    except UnicodeDecodeError:
        raise Recusa("PROJECT.md não é UTF-8") from None
    bloco = block.replace("\n", "\r\n")
    if START in texto or END in texto:
        i, j = texto.find(START), texto.find(END)
        if texto.count(START) != 1 or texto.count(END) != 1 or j < i:
            raise Recusa("marcadores do bloco dia7-consolidado quebrados")
        if texto[i:j + len(END)] == bloco:
            return "já registrado"
        raise Recusa("o bloco dia7-consolidado já existe e é diferente")
    if antes is not None and sha256(data) != antes:
        raise Recusa("o SHA-256 do PROJECT.md não é o esperado")
    if not texto.endswith("\r\n"):
        raise Recusa("PROJECT.md não termina em CRLF")
    if texto.replace("\r\n", "").count("\n") or data.startswith(b"\xef\xbb\xbf"):
        raise Recusa("PROJECT.md tem LF solto ou BOM")
    novo = data + b"\r\n" + bloco.encode("utf-8") + b"\r\n"
    tmp = path.with_name(path.name + ".tmp")
    criado = False
    try:
        with open(tmp, "xb") as fh:
            criado = True
            fh.write(novo)
        os.replace(tmp, path)
    except BaseException:
        if criado:
            tmp.unlink(missing_ok=True)
        raise
    if path.read_bytes() != novo:
        raise Recusa("conferência pós-gravação falhou")
    return "registrado"


def main(argv: list[str] | None = None, path: Path = TARGET,
         results: Path = RESULTS) -> int:
    """Ponto de entrada; 0 ok, 1 recusa."""
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    modo = ap.add_mutually_exclusive_group(required=True)
    modo.add_argument("--conferir", action="store_true")
    modo.add_argument("--gravar", action="store_true")
    args = ap.parse_args(argv)
    try:
        facts = load(results)
        block = render(facts, results)
        if not path.is_file():
            raise Recusa(f"arquivo ausente: {path.name}")
        atual = sha256(path.read_bytes())
        if args.conferir:
            print(f"bloco montado: {block.count(chr(10)) + 1} linhas; "
                  f"SHA-256 do bloco {sha256(block.encode('utf-8'))}")
            print(f"PROJECT.md atual {atual} "
                  f"({'igual' if atual == HASH_ANTES else 'DIFERENTE de'} HASH_ANTES)")
            print("conferência: nada gravado")
            return 0
        resultado = apply(path, block, HASH_ANTES)
        print(f"{resultado}: bloco dia7-consolidado em {path.name}")
        print(f"SHA-256 do PROJECT.md agora: {sha256(path.read_bytes())}")
        return 0
    except Recusa as exc:
        print(f"RECUSADO: {exc}; nada gravado")
        return 1


if __name__ == "__main__":
    sys.exit(main())
