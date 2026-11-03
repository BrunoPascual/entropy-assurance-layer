"""Dia 7: registra no fim do PROJECT.md o E5 (etapa A, CHSH sem QPU), gerado dos CSVs.

Nenhum número é digitado: tabelas e contagens saem de data/results/e5_rodadas.csv e
e5_resumo.csv. Os critérios por configuração e o efeito do ruído são CALCULADOS dos CSVs; as
frases estruturais (S exato, par único, erro-padrão teórico, razão entre desvio-padrão e
erro-padrão, estratégia clássica determinística) só são gravadas se confirmadas; se alguma falhar,
o script recusa e não grava nada. Acrescenta um bloco ao FIM do PROJECT.md, entre marcadores, sem
editar nenhuma linha existente. Tudo ou nada:

- só grava se o SHA-256 atual do PROJECT.md for HASH_ANTES (o do commit fcb3ec3);
- "já aplicado" quando o arquivo termina exatamente com o bloco gerado agora e, sem ele,
  volta a HASH_ANTES;
- recusa sem gravar se faltar CSV, se o cabeçalho for outro, se o e5_resumo.csv não for a
  derivação exata do e5_rodadas.csv, se o commit das linhas não for o da rodada pré-registrada
  (COMMIT_CURTO), se o número de repetições ou de shots for outro, se os ângulos do script
  diferirem dos do PROJECT.md, se uma frase estrutural não bater, se o marcador já existir, se o
  hash do PROJECT.md for outro ou se ele não for CRLF puro terminando em fim de linha.

Uso (na raiz do projeto):
    py -3.12 scripts\\registrar_e5.py
Código de saída: 0 aplicado ou já aplicado; 1 recusado (nada foi gravado).
"""
from __future__ import annotations

import csv
import hashlib
import importlib.util
import math
import os
import re
import statistics
import sys
from pathlib import Path
from typing import Any, Callable

TARGET = Path("PROJECT.md")
RESULTS = Path("data/results")
SCRIPTS = Path(__file__).resolve().parent
HASH_ANTES = "d97b0abdae12aa17c03ec1eb313d3c0e22effd7dcfb68e2c3091447fe65e4c57"
START = "<!-- dia7-e5a:start -->"
END = "<!-- dia7-e5a:end -->"
COMMIT_CURTO = "a467431"
TOL_SE_TEORICO = 0.05          # erro-padrão medido dentro de 5% do teórico
FAIXA_RAZAO_DP = (0.75, 1.25)  # desvio-padrão entre repetições / erro-padrão calculado
NOME_ROD, NOME_RES = "e5_rodadas.csv", "e5_resumo.csv"
AMOSTRADAS = ("ideal_amostrado", "ruido_fake_kingston", "classico_aleatorio")
CAMPOS_PAR = ("par_fisico", "erro_cz", "erro_leitura_q0", "erro_leitura_q1", "calibracao_backend",
              "n_2q_por_circuito")


class Refused(Exception):
    """Recusa: nada foi gravado."""


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ---------------------------------------------------------------- formatação

def d_pt(texto: str) -> str:
    return "-" if texto == "" else texto.replace(".", ",")


def f6(x: float) -> str:
    return f"{x:.6f}".replace(".", ",")


# ---------------------------------------------------------------- leitura

def carregar_e5() -> Any:
    caminho = SCRIPTS / "e5_chsh.py"
    if not caminho.is_file():
        raise Refused(f"script ausente: {caminho}")
    spec = importlib.util.spec_from_file_location("e5_chsh_registro", caminho)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def ler_rodadas(e5: Any, caminho: Path) -> list[dict[str, str]]:
    try:
        linhas = e5.ler_rodadas(caminho)
    except e5.E5Erro as exc:
        raise Refused(str(exc)) from exc
    if not linhas:
        raise Refused(f"{caminho.name}: sem linhas")
    return linhas


def ler_resumo(e5: Any, caminho: Path) -> list[dict[str, str]]:
    if not caminho.is_file():
        raise Refused(f"CSV ausente: {caminho}")
    with open(caminho, encoding="utf-8", newline="") as fh:
        leitor = csv.DictReader(fh)
        if tuple(leitor.fieldnames or ()) != tuple(e5.CAMPOS_RESUMO):
            raise Refused(f"{caminho.name}: cabeçalho diferente do esperado")
        linhas = list(leitor)
    if not linhas:
        raise Refused(f"{caminho.name}: sem linhas")
    return linhas


def conferir_integridade(e5: Any, rod: list[dict[str, str]], p_resumo: Path) -> str:
    if tuple(e5.ANGULOS_A) != (0.0, math.pi / 2) or tuple(e5.ANGULOS_B) != (math.pi / 4, -math.pi / 4):
        raise Refused("os ângulos do script diferem dos do PROJECT.md")
    try:
        derivado = e5.csv_bytes(e5.CAMPOS_RESUMO, e5.resumir(rod))
    except e5.E5Erro as exc:
        raise Refused(str(exc)) from exc
    if derivado != p_resumo.read_bytes():
        raise Refused(f"{NOME_RES} não é a derivação exata de {NOME_ROD}")
    commits = {l["commit"] for l in rod}
    if len(commits) != 1:
        raise Refused(f"mais de um commit nas linhas: {sorted(commits)}")
    commit = commits.pop()
    if not re.fullmatch(r"[0-9a-f]{40}", commit) or not commit.startswith(COMMIT_CURTO):
        raise Refused(f"commit das linhas ({commit}) não é o da rodada pré-registrada ({COMMIT_CURTO})")
    for cfg in e5.CONFIGS:
        n = sum(1 for l in rod if l["configuracao"] == cfg)
        esperado = 1 if cfg == "ideal_exato" else e5.REPS
        if n != esperado:
            raise Refused(f"{cfg}: {n} repetições em vez de {esperado}")
    for l in rod:
        if l["configuracao"] != "ideal_exato" and l["n_shots"] != str(e5.N_SHOTS):
            raise Refused(f"{l['configuracao']}: n_shots {l['n_shots']} em vez de {e5.N_SHOTS}")
    return commit


# ---------------------------------------------------------------- contas

def por_config(rod: list[dict[str, str]]) -> dict[str, list[dict[str, str]]]:
    saida: dict[str, list[dict[str, str]]] = {}
    for l in rod:
        saida.setdefault(l["configuracao"], []).append(l)
    return saida


def ss(linhas: list[dict[str, str]]) -> list[float]:
    return [float(l["s"]) for l in linhas]


# ---------------------------------------------------------------- frases

def estruturais(e5: Any, rod: list[dict[str, str]], res: dict[str, dict[str, str]]
                ) -> list[tuple[str, Callable[[], bool]]]:
    g = por_config(rod)
    n = e5.N_SHOTS
    lo, hi = FAIXA_RAZAO_DP

    def exato() -> bool:
        s = float(g["ideal_exato"][0]["s"])
        return len(g["ideal_exato"]) == 1 and abs(s - e5.TSIRELSON) <= e5.TOL_EXATO

    def par_unico() -> bool:
        l = g["ruido_fake_kingston"]
        return (all(len({x[c] for x in l}) == 1 for c in CAMPOS_PAR)
                and l[0]["n_2q_por_circuito"] == "1" and l[0]["par_fisico"] != "")

    def otimo() -> bool:
        l = g["classico_otimo"]
        return all(x["s"] == "2.0" and x["se_s"] == "0.0" for x in l)

    def se_teorico() -> bool:
        a = float(res["ideal_amostrado"]["se_media"])
        b = float(res["classico_aleatorio"]["se_media"])
        ta, tb = math.sqrt(2 / n), math.sqrt(4 / n)
        return abs(a - ta) <= TOL_SE_TEORICO * ta and abs(b - tb) <= TOL_SE_TEORICO * tb

    def razao_dp() -> bool:
        for cfg in AMOSTRADAS:
            r = float(res[cfg]["s_dp"]) / float(res[cfg]["se_media"])
            if not lo <= r <= hi:
                return False
        return True

    n_reps = len(g["ideal_amostrado"])
    erro_rel = 1 / math.sqrt(2 * (n_reps - 1))
    return [
        ("O S exato do circuito (probabilidades do estado, sem amostragem) é 2√2, com tolerância "
         "de 1e-12.", exato),
        ("O ruído foi simulado em um único par físico, com os mesmos erros de CZ e de leitura, a "
         "mesma data de calibração e uma porta de dois qubits por circuito em todas as repetições.",
         par_unico),
        ("A estratégia clássica determinística deu S = 2 e erro-padrão 0 em todas as repetições: "
         "as repetições são idênticas por construção.", otimo),
        (f"O erro-padrão médio calculado bate com o teórico dentro de {TOL_SE_TEORICO:.0%}: "
         f"√(2/N) = {f6(math.sqrt(2 / n))} para o estado de Bell e √(4/N) = "
         f"{f6(math.sqrt(4 / n))} para saídas independentes, com N = {n} shots por ajuste.",
         se_teorico),
        (f"O desvio-padrão de S entre repetições fica entre {str(lo).replace('.', ',')} e "
         f"{str(hi).replace('.', ',')} vezes o erro-padrão calculado nas três configurações "
         f"amostradas (com {n_reps} repetições, o desvio-padrão amostral tem erro relativo de "
         f"cerca de {erro_rel:.0%}).", razao_dp),
    ]


def verificar(e5: Any, rod: list[dict[str, str]], res: dict[str, dict[str, str]]) -> list[str]:
    try:
        lista = estruturais(e5, rod, res)
    except (KeyError, ValueError, ZeroDivisionError) as exc:
        raise Refused(f"estrutura inesperada nas frases estruturais: {exc!r}") from exc
    textos = []
    for texto, teste in lista:
        try:
            ok = teste()
        except (KeyError, ValueError, IndexError, ArithmeticError):
            ok = False
        if not ok:
            raise Refused(f"afirmação não confirmada pelos CSVs: {texto}")
        textos.append(texto)
    return textos


def calculadas(e5: Any, rod: list[dict[str, str]], res: dict[str, dict[str, str]]) -> list[str]:
    g = por_config(rod)
    cumpriram = [c for c in e5.CONFIGS if res[c]["criterio_ok"] == "True"]
    falharam = [c for c in e5.CONFIGS if res[c]["criterio_ok"] != "True"]
    frases = ["Critérios pré-registrados cumpridos em: " + ", ".join(f"`{c}`" for c in cumpriram)
              + (". Não cumpridos em: " + ", ".join(f"`{c}`" for c in falharam) + "." if falharam
                 else ". Nenhuma configuração deixou de cumprir o critério.")]
    a, b = ss(g["ideal_amostrado"]), ss(g["ruido_fake_kingston"])
    ma, mb = statistics.fmean(a), statistics.fmean(b)
    se_dif = math.sqrt(statistics.variance(a) / len(a) + statistics.variance(b) / len(b))
    dif = ma - mb
    frases.append(
        f"Efeito do ruído simulado: o S médio passou de {f6(ma)} (ideal amostrado) para {f6(mb)} "
        f"(`ruido_fake_kingston`), uma {'queda' if dif > 0 else 'mudança'} de {f6(abs(dif))}, "
        f"{f6(abs(dif) / se_dif)} erros-padrão da diferença entre as médias.")
    c = ss(g["classico_aleatorio"])
    mc, mg = statistics.fmean(c), float(res["classico_aleatorio"]["margem"])
    frases.append(
        f"Saídas clássicas independentes: S médio {f6(mc)}; "
        f"{'compatível com 0' if abs(mc) <= mg else 'diferente de 0'} dentro da margem de "
        f"{f6(mg)}. O limite clássico é 2 e o máximo quântico é 2√2.")
    return frases


# ---------------------------------------------------------------- tabelas

def tabela(res: list[dict[str, str]]) -> list[str]:
    linhas = ["| Configuração | Esperado | Repetições | S médio | Desvio-padrão | Erro-padrão médio "
              "| S mínimo | S máximo | Fração S > 2 | Margem | Critério |",
              "|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in res:
        linhas.append(
            f"| `{r['configuracao']}` | {r['esperado']} | {r['n_reps']} | {d_pt(r['s_media'])} "
            f"| {d_pt(r['s_dp'])} | {d_pt(r['se_media'])} | {d_pt(r['s_min'])} | {d_pt(r['s_max'])} "
            f"| {d_pt(r['frac_s_maior_2'])} | {d_pt(r['margem'])} "
            f"| {'cumprido' if r['criterio_ok'] == 'True' else 'não cumprido'} |")
    return linhas


RESSALVAS = (
    "O simulador é um gerador clássico (limitação 6): o S de 2√2 sai do cálculo das "
    "probabilidades do estado de Bell, e não de um experimento quântico.",
    "O CHSH numa QPU em nuvem não é um teste de Bell sem brechas (limitação 5): os ajustes de "
    "medição são escolhidos pelo experimentador e os dois qubits ficam no mesmo chip, sem "
    "separação. Isto é só uma verificação de sanidade do código e da análise.",
    "O ruído é o modelo do `FakeKingston` (eal.sources.noise, leitura assimétrica) com a "
    "calibração gravada no backend simulado, na data registrada acima; não inclui crosstalk. Uma "
    "QPU real em outra data pode dar um S diferente.",
    "O par de qubits veio da regra pré-registrada (menor soma do erro de CZ e do erro médio de "
    "leitura), e não foi escolhido pelo S.",
    "Os dois geradores clássicos são referências por construção: a estratégia determinística "
    "atinge o limite clássico 2 e as saídas independentes dão S perto de 0. Não são medidas de "
    "nenhum dispositivo.",
    "A hipótese de que a QPU real fique entre 2 e 2√2 não foi testada: esta é a etapa A, sem QPU.",
    "A faixa 2 < S < 2√2 para o simulador com ruído é uma hipótese do assistente; o PROJECT.md só "
    "fixa essa faixa para a QPU real.",
    "O tempo da rodada variou em relação à medição prévia (ver T_TEMPO); isso não afeta os "
    "resultados, que são determinísticos pela semente de cada repetição.",
)


def montar_bloco(e5: Any, rod: list[dict[str, str]], resumo: list[dict[str, str]], commit: str,
                 hashes: dict[str, str]) -> str:
    res = {r["configuracao"]: r for r in resumo}
    leitura_e = verificar(e5, rod, res)
    leitura_c = calculadas(e5, rod, res)
    par = por_config(rod)["ruido_fake_kingston"][0]
    out = [
        START,
        "### E5 (etapa A), teste CHSH sem QPU (Dia 7, registro gerado dos CSVs)",
        "",
        "Gerado por `scripts/registrar_e5.py` a partir de `e5_rodadas.csv` e `e5_resumo.csv`. "
        "Nenhum número foi digitado à mão. As frases estruturais só são gravadas se confirmadas "
        "pelos CSVs; os critérios por configuração e o efeito do ruído são calculados dos CSVs.",
        "",
        f"**Protocolo (pré-registrado):** rodada sobre o commit `{commit}`, conferido na coluna "
        f"`commit` das {len(rod)} linhas. Estado de Bell Φ⁺ (H e CX) com rotação Ry(−θ) antes da "
        "medição em cada lado; Alice mede em 0 e π/2 e Bob em π/4 e −π/4; "
        "E = P(iguais) − P(diferentes); S = E(a0,b0) + E(a0,b1) + E(a1,b0) − E(a1,b1). "
        f"{e5.N_SHOTS} shots por ajuste ({4 * e5.N_SHOTS} por estimativa de S) e {e5.REPS} "
        "repetições por configuração amostrada, cada uma com semente própria gravada. Nenhuma "
        "chamada à QPU. Margem dos critérios: "
        f"{e5.K_SIGMA} erros-padrão da média das repetições.",
        "",
        "**Resultados por configuração:**",
        "",
        *tabela(resumo),
        "",
        f"**Par físico do ruído simulado:** qubits {par['par_fisico']} do `{e5.BACKEND_RUIDO}`; "
        f"erro de CZ {d_pt(par['erro_cz'])}; erro médio de leitura {d_pt(par['erro_leitura_q0'])} "
        f"e {d_pt(par['erro_leitura_q1'])}; calibração {par['calibracao_backend']}.",
        "",
        "**Leitura:**",
        "",
        *[f"- {t}" for t in leitura_c],
        *[f"- {t}" for t in leitura_e],
        "",
        "**Ressalvas:**",
        "",
        *[f"- {t}" for t in RESSALVAS],
        "",
        "**CSVs (SHA-256 dos bytes em disco):**",
        "",
        *[f"- `{n}`: `{hashes[n]}`" for n in (NOME_ROD, NOME_RES)],
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
        e5 = carregar_e5()
        p_rod, p_res = RESULTS / NOME_ROD, RESULTS / NOME_RES
        rod = ler_rodadas(e5, p_rod)
        resumo = ler_resumo(e5, p_res)
        commit = conferir_integridade(e5, rod, p_res)
        hashes = {NOME_ROD: sha256(p_rod.read_bytes()), NOME_RES: sha256(p_res.read_bytes())}
        insercao = preparar_insercao(montar_bloco(e5, rod, resumo, commit, hashes))
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
