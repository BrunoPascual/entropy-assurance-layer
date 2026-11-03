"""Dia 7: registra no fim do PROJECT.md o E3 (vazão e custo por megabit), gerado dos CSVs.

Nenhum número é digitado: tabelas e contagens saem de data/results/e3_qpu.csv, e3_local.csv e
e3_resumo.csv. O veredito da hipótese, a razão nos extremos e a divisão dos tempos locais em
grupos são CALCULADOS dos CSVs. As frases estruturais (nenhum lote da QPU aprovado, forma do
ajuste, relação entre custo hipotético e bruto) só são gravadas se confirmadas; se alguma falhar,
o script recusa e não grava nada. Acrescenta um bloco ao FIM do PROJECT.md, entre marcadores,
sem editar nenhuma linha existente. Tudo ou nada:

- só grava se o SHA-256 atual do PROJECT.md for HASH_ANTES (o do commit 3d89508);
- "já aplicado" quando o arquivo termina exatamente com o bloco gerado agora e, sem ele,
  volta a HASH_ANTES;
- recusa sem gravar se faltar CSV, se o cabeçalho for outro, se o e3_resumo.csv não for a
  derivação exata de e3_qpu.csv e e3_local.csv, se o commit das linhas locais não for o da
  rodada pré-registrada (COMMIT_CURTO), se o tamanho do lote local for outro, se uma frase
  estrutural não bater, se o marcador já existir, se o hash do PROJECT.md for outro ou se ele
  não for CRLF puro terminando em fim de linha.

Uso (na raiz do projeto):
    py -3.12 scripts\\registrar_e3.py
Código de saída: 0 aplicado ou já aplicado; 1 recusado (nada foi gravado).
"""
from __future__ import annotations

import hashlib
import importlib.util
import os
import re
import statistics
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable

TARGET = Path("PROJECT.md")
RESULTS = Path("data/results")
SCRIPTS = Path(__file__).resolve().parent
HASH_ANTES = "93266df50f08941f3a5ff6714b022343e890d1a2be696776dd10ec3722511033"
START = "<!-- dia7-e3:start -->"
END = "<!-- dia7-e3:end -->"
COMMIT_CURTO = "af1f1c4"
LIMIAR_SEPARACAO = Decimal(2)       # só descritivo: o grupo lento tem pelo menos 2x o tempo do rápido
NOME_QPU, NOME_LOCAL, NOME_RESUMO = "e3_qpu.csv", "e3_local.csv", "e3_resumo.csv"


class Refused(Exception):
    """Recusa: nada foi gravado."""


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ---------------------------------------------------------------- formatação

def n_pt(valor: Any) -> str:
    return f"{int(valor):,}".replace(",", ".")


def d_pt(texto: str) -> str:
    return "-" if texto == "" else texto.replace(".", ",")


def valor_pt(valor: str, unidade: str) -> str:
    if unidade == "bits":
        return n_pt(valor)
    if re.fullmatch(r"-?\d+\.\d+", valor):
        return valor.replace(".", ",")
    return valor


def dec4(x: Decimal) -> str:
    return f"{x:.4f}".replace(".", ",")


# ---------------------------------------------------------------- leitura

def carregar_e3() -> Any:
    caminho = SCRIPTS / "e3_vazao_custo.py"
    if not caminho.is_file():
        raise Refused(f"script ausente: {caminho}")
    spec = importlib.util.spec_from_file_location("e3_vazao_custo_registro", caminho)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def ler(e3: Any, caminho: Path, campos: tuple[str, ...]) -> list[dict[str, str]]:
    try:
        linhas = e3.ler_csv(caminho, campos)
    except e3.E3Erro as exc:
        raise Refused(str(exc)) from exc
    if not linhas:
        raise Refused(f"{caminho.name}: sem linhas")
    return linhas


def conferir_integridade(e3: Any, qpu: list[dict[str, str]], local: list[dict[str, str]],
                         p_resumo: Path) -> str:
    try:
        derivado = e3.csv_bytes(e3.CAMPOS_RESUMO, e3.resumir(qpu, local))
    except e3.E3Erro as exc:
        raise Refused(str(exc)) from exc
    if derivado != p_resumo.read_bytes():
        raise Refused(f"{NOME_RESUMO} não é a derivação exata de {NOME_QPU} e {NOME_LOCAL}")
    commits = {l["commit"] for l in local}
    if len(commits) != 1:
        raise Refused(f"mais de um commit nas linhas locais: {sorted(commits)}")
    commit = commits.pop()
    if not re.fullmatch(r"[0-9a-f]{40}", commit) or not commit.startswith(COMMIT_CURTO):
        raise Refused(f"commit das linhas locais ({commit}) não é o da rodada pré-registrada "
                      f"({COMMIT_CURTO})")
    if {int(l["n_bits"]) for l in local} != {e3.N_BITS_LOCAL}:
        raise Refused(f"tamanho do lote local diferente de {e3.N_BITS_LOCAL}")
    return commit


# ---------------------------------------------------------------- contas a partir dos CSVs

def metricas(e3: Any, qpu: list[dict[str, str]], local: list[dict[str, str]]) -> dict[str, str]:
    return {r["metrica"]: r["valor"] for r in e3.resumir(qpu, local)}


def razao(c_seg: Decimal, c_mbit: Decimal, t: Decimal, l_mbit: Decimal) -> Decimal:
    return (c_seg / c_mbit) / (t / l_mbit)


def base_coleta(e3: Any, qpu: list[dict[str, str]], local: list[dict[str, str]]
                ) -> tuple[Decimal, Decimal, Decimal]:
    col = [l for l in qpu if l["sessao"].startswith("coleta")]
    c_seg = sum(Decimal(l["quantum_seconds"]) for l in col)
    c_mbit = sum(Decimal(l["n_bits"]) for l in col) / e3.MBIT
    l_mbit = Decimal(local[0]["n_bits"]) / e3.MBIT
    return c_seg, c_mbit, l_mbit


def separacao(tempos: list[Decimal]) -> tuple[int, Decimal] | None:
    """Melhor ponto k tal que max(t[:k]) < min(t[k:]) (em ordem de execução), com a razão
    min(t[k:]) / max(t[:k]) >= LIMIAR_SEPARACAO; None se não houver."""
    melhor: tuple[int, Decimal] | None = None
    for k in range(1, len(tempos)):
        a, b = max(tempos[:k]), min(tempos[k:])
        if a < b:
            r = b / a
            if melhor is None or r > melhor[1]:
                melhor = (k, r)
    return melhor if melhor is not None and melhor[1] >= LIMIAR_SEPARACAO else None


# ---------------------------------------------------------------- frases

def afirmacoes_estruturais(qpu: list[dict[str, str]], r: dict[str, str]
                           ) -> list[tuple[str, Callable[[], bool]]]:
    col = [l for l in qpu if l["sessao"].startswith("coleta")]

    def nenhum_aprovado() -> bool:
        return (len(col) > 0 and all(l["saude_aprovada"] == "False" for l in col)
                and r["coleta_lotes_aprovados"] == "0" and r["coleta_bits_uteis"] == "0"
                and r["coleta_custo_por_mbit_util_pay_as_you_go"] == "indefinido")

    def ajuste() -> bool:
        return (Decimal(r["ajuste_fixo_s"]) > 0
                and Decimal(r["ajuste_custo_marginal_por_mbit_pay_as_you_go"])
                < Decimal(r["coleta_custo_por_mbit_bruto_pay_as_you_go"]))

    def hipotetico() -> bool:
        return (Decimal(r["coleta_custo_por_mbit_util_hipotetico_pay_as_you_go"])
                > Decimal(r["coleta_custo_por_mbit_bruto_pay_as_you_go"]))

    return [
        ("Nenhum dos jobs de coleta teve lote aprovado pela saúde: bits úteis = 0 e o custo por "
         "megabit útil é indefinido. O custo por megabit útil observado não existe; só o custo "
         "por megabit bruto.", nenhum_aprovado),
        ("O ajuste de segundos por shot dá um custo fixo por job positivo e um custo marginal por "
         "megabit menor que o custo médio por megabit dos jobs de coleta: jobs maiores saem mais "
         "baratos por bit.", ajuste),
        ("Se os lotes tivessem sido aprovados, o custo por megabit útil hipotético seria maior que "
         "o custo por megabit bruto, porque o extrator aproveita só parte dos bits.", hipotetico),
    ]


def verificar_estruturais(qpu: list[dict[str, str]], r: dict[str, str]) -> list[str]:
    try:
        lista = afirmacoes_estruturais(qpu, r)
    except (KeyError, ValueError) as exc:
        raise Refused(f"estrutura inesperada nas frases estruturais: {exc!r}") from exc
    textos = []
    for texto, teste in lista:
        try:
            ok = teste()
        except (KeyError, ValueError, ArithmeticError):
            ok = False
        if not ok:
            raise Refused(f"afirmação não confirmada pelos CSVs: {texto}")
        textos.append(texto)
    return textos


def frases_calculadas(e3: Any, qpu: list[dict[str, str]], local: list[dict[str, str]],
                      r: dict[str, str]) -> list[str]:
    c_seg, c_mbit, l_mbit = base_coleta(e3, qpu, local)
    tempos = [Decimal(l["t_s"]) for l in local]
    limiar = e3.RAZAO_MUITO
    med = Decimal(r["local_t_mediana_s"])
    ra = razao(c_seg, c_mbit, med, l_mbit)
    if ra.quantize(Decimal("0.01")) != Decimal(r["razao_s_por_mbit_qpu_sobre_os"]):
        raise Refused("a razão recalculada difere da razão do resumo")
    confirmado = r["criterio_muito_mais_caro"] == "True"
    if confirmado != (ra >= limiar):
        raise Refused("o veredito do resumo contradiz a razão e o limiar")
    mais_rapida, mais_lenta = min(tempos), max(tempos)
    rr, rl = razao(c_seg, c_mbit, mais_rapida, l_mbit), razao(c_seg, c_mbit, mais_lenta, l_mbit)
    frases = [
        (f"Critério pré-registrado (razão entre os segundos de QPU por megabit bruto e os segundos "
         f"de CPU por megabit bruto da `os`, pela mediana local, igual ou maior que "
         f"{limiar}): razão {d_pt(r['razao_s_por_mbit_qpu_sobre_os'])}; hipótese \"muito mais caro "
         f"que a `os`\" {'confirmada' if confirmado else 'não confirmada'} sob esta definição."),
        (f"A razão nos extremos dos tempos locais: {dec4(rr)} com a execução mais rápida e "
         f"{dec4(rl)} com a mais lenta, {'igual ou acima' if rl >= limiar else 'abaixo'} do "
         f"limiar na execução mais lenta."),
    ]
    sep = separacao(tempos)
    if sep is None:
        frases.append(f"Os tempos locais variaram de {d_pt(str(mais_rapida))} a "
                      f"{d_pt(str(mais_lenta))} s, sem separação em dois grupos.")
    else:
        k, gap = sep
        g1, g2 = tempos[:k], tempos[k:]
        m1, m2 = Decimal(str(statistics.median(g1))), Decimal(str(statistics.median(g2)))
        grupo_med = "lento" if med >= min(g2) else "rápido"
        frases.append(
            f"Os tempos locais formam dois grupos sem sobreposição, em ordem de execução: as "
            f"execuções 0 a {k - 1} ({len(g1)} execuções, de {d_pt(str(min(g1)))} a "
            f"{d_pt(str(max(g1)))} s) e {k} a {len(tempos) - 1} ({len(g2)} execuções, de "
            f"{d_pt(str(min(g2)))} a {d_pt(str(max(g2)))} s); o menor tempo do segundo grupo é "
            f"{dec4(gap).rstrip('0').rstrip(',')} vezes o maior do primeiro. A mediana "
            f"pré-registrada cai no grupo {grupo_med}. Razão com a mediana do grupo rápido: "
            f"{dec4(razao(c_seg, c_mbit, m1, l_mbit))}; do grupo lento: "
            f"{dec4(razao(c_seg, c_mbit, m2, l_mbit))}. A causa da diferença não foi investigada.")
    return frases


# ---------------------------------------------------------------- tabelas

def tabela_jobs(qpu: list[dict[str, str]]) -> list[str]:
    linhas = [
        "| Sessão | Job | Shots | Bits | Segundos de QPU | Bits/s | Custo teórico (US$) "
        "| US$/Mbit | Saúde | Bits úteis | Bits úteis hipotéticos |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    nomes = {"": "-", "True": "aprovada", "False": "reprovada"}
    for l in qpu:
        linhas.append(
            f"| {l['sessao']} | {l['job_id']} | {n_pt(l['shots'])} | {n_pt(l['n_bits'])} "
            f"| {d_pt(l['quantum_seconds'])} | {d_pt(l['bits_por_s'])} | {d_pt(l['custo_usd_payg'])} "
            f"| {d_pt(l['custo_usd_por_mbit_payg'])} | {nomes[l['saude_aprovada']]} "
            f"| {n_pt(l['bits_uteis']) if l['bits_uteis'] != '' else '-'} "
            f"| {n_pt(l['bits_uteis_hipoteticos']) if l['bits_uteis_hipoteticos'] != '' else '-'} |")
    return linhas


def tabela_resumo(resumo: list[dict[str, str]]) -> list[str]:
    linhas = ["| Métrica | Valor | Unidade |", "|---|---|---|"]
    for r in resumo:
        linhas.append(f"| `{r['metrica']}` | {valor_pt(r['valor'], r['unidade'])} | {r['unidade']} |")
    return linhas


RESSALVAS = (
    "O custo é teórico. O Open Plan não cobra nada; o preço do plano pago foi lido na página da "
    "IBM na data de consulta registrada acima e pode mudar. Nenhum job foi enviado para o E3: "
    "ele usa só os 8 jobs já executados.",
    "Os segundos de QPU vêm da API em valores inteiros (2,0; 3,0; 5,0) e há só 3 tamanhos de job; "
    "o ajuste de custo fixo e marginal é grosseiro e a incerteza dele não foi quantificada.",
    "O tempo de QPU é tempo cobrado de execução; o tempo local é o tempo de parede do pipeline "
    "completo (leitura, saúde, extração e mistura) da `os`. São recursos diferentes e não foram "
    "valorados na mesma moeda: o custo em dólares da `os` não foi valorado (CPU e energia ficam "
    "de fora). Os bits da QPU ainda passariam pelo mesmo processamento local.",
    "Não há medida de latência de fila nem de tempo de parede da QPU: o log registra a hora da "
    "recuperação, e não a do fim do job.",
    "Todos os jobs usaram `rep_delay` de 0,00025 s. A documentação da IBM registra um aumento "
    "temporário do padrão para 4 ms; não foi verificado se isso afeta jobs que definem o valor, "
    "e o custo vale para a configuração usada.",
    "As RUs do painel da IBM não foram usadas; a conversão entre RUs e segundos continua "
    "pendente (IBM_RU).",
    "O benchmark local é de uma única máquina e a velocidade oscilou (ver os tempos por "
    "execução); o critério foi avaliado pela mediana, como pré-registrado.",
    "Os bits úteis hipotéticos usam o extrator do projeto com o H estimado de cada lote. Esses "
    "lotes foram reprovados pela saúde, então não são bits utilizáveis.",
)


def montar_bloco(e3: Any, qpu: list[dict[str, str]], local: list[dict[str, str]],
                 resumo: list[dict[str, str]], commit: str, hashes: dict[str, str]) -> str:
    r = {x["metrica"]: x["valor"] for x in resumo}
    estruturais = verificar_estruturais(qpu, r)
    calculadas = frases_calculadas(e3, qpu, local, r)
    precos = ", ".join(f"{nome.replace('_', '-')} US$ {n_pt(valor)}/min" for nome, valor in e3.PRECOS)
    tempos = "; ".join(d_pt(l["t_s"]) for l in local)
    out = [
        START,
        "### E3, vazão e custo por megabit (Dia 7, registro gerado dos CSVs)",
        "",
        "Gerado por `scripts/registrar_e3.py` a partir de `e3_qpu.csv`, `e3_local.csv` e "
        "`e3_resumo.csv`. Nenhum número foi digitado à mão. As frases estruturais só são gravadas "
        "se confirmadas pelos CSVs; o veredito, a razão nos extremos e os grupos de tempo são "
        "calculados dos CSVs.",
        "",
        f"**Protocolo (pré-registrado):** nenhum job foi enviado; foram usados os {n_pt(len(qpu))} "
        f"jobs já executados no Open Plan (log de uso, JSONs dos crus e CSVs de saúde, conferidos "
        f"entre si). Custo teórico: segundos de QPU da API vezes o preço por minuto ({precos}); "
        f"fonte {r['preco_fonte']}, consultada em {r['preco_data_consulta']}. 1 Mbit = 1.000.000 "
        f"bits. Benchmark local: o `run_pipeline` real com a `os`, lotes de {n_pt(e3.N_BITS_LOCAL)} "
        f"bits, 1 execução de aquecimento descartada e {n_pt(len(local))} medidas, sobre o commit "
        f"`{commit}`. Critério: razão de pelo menos {e3.RAZAO_MUITO}.",
        "",
        "**Jobs da QPU:**",
        "",
        *tabela_jobs(qpu),
        "",
        "**Resumo (`e3_resumo.csv`):**",
        "",
        *tabela_resumo(resumo),
        "",
        f"**Tempos locais por execução, em ordem (s):** {tempos}.",
        "",
        "**Leitura:**",
        "",
        *[f"- {t}" for t in calculadas],
        *[f"- {t}" for t in estruturais],
        "",
        "**Ressalvas:**",
        "",
        *[f"- {t}" for t in RESSALVAS],
        "",
        "**CSVs (SHA-256 dos bytes em disco):**",
        "",
        *[f"- `{n}`: `{hashes[n]}`" for n in (NOME_QPU, NOME_LOCAL, NOME_RESUMO)],
        END,
    ]
    return "\n".join(out)


# ---------------------------------------------------------------- aplicação

def preparar_insercao(bloco: str) -> bytes:
    if "\r" in bloco:
        raise Refused("o bloco gerado contém CR")
    return ("\r\n" + bloco.replace("\n", "\r\n") + "\r\n").encode("utf-8")


def aplicar(atual: bytes, insercao: bytes) -> bytes | None:
    """Devolve os novos bytes, ou None se já estiver aplicado."""
    if atual.endswith(insercao) and sha256(atual[:-len(insercao)]) == HASH_ANTES:
        return None
    if START.encode() in atual or END.encode() in atual:
        raise Refused("o marcador do bloco já existe no PROJECT.md com outro conteúdo")
    if sha256(atual) != HASH_ANTES:
        raise Refused(f"SHA-256 do PROJECT.md ({sha256(atual)}) difere de HASH_ANTES")
    if atual.count(b"\n") != atual.count(b"\r\n") or not atual.endswith(b"\r\n"):
        raise Refused("o PROJECT.md não é CRLF puro terminando em fim de linha")
    return atual + insercao


def gravar(caminho: Path, dados: bytes) -> None:
    tmp = caminho.with_name(caminho.name + ".tmp")
    tmp.write_bytes(dados)
    os.replace(tmp, caminho)


def main(saida: Callable[[str], None] = print) -> int:
    try:
        if not TARGET.is_file():
            raise Refused(f"arquivo ausente: {TARGET}")
        e3 = carregar_e3()
        p_qpu, p_local, p_res = RESULTS / NOME_QPU, RESULTS / NOME_LOCAL, RESULTS / NOME_RESUMO
        qpu = ler(e3, p_qpu, e3.CAMPOS_QPU)
        local = ler(e3, p_local, e3.CAMPOS_LOCAL)
        resumo = ler(e3, p_res, e3.CAMPOS_RESUMO)
        commit = conferir_integridade(e3, qpu, local, p_res)
        hashes = {n: sha256((RESULTS / n).read_bytes()) for n in (NOME_QPU, NOME_LOCAL, NOME_RESUMO)}
        insercao = preparar_insercao(montar_bloco(e3, qpu, local, resumo, commit, hashes))
        novo = aplicar(TARGET.read_bytes(), insercao)
        if novo is None:
            saida(f"já aplicado; PROJECT.md: {sha256(TARGET.read_bytes())}")
            return 0
        gravar(TARGET, novo)
        saida(f"aplicado; PROJECT.md: {sha256(novo)}")
        return 0
    except Refused as exc:
        saida(f"RECUSADO: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
