"""Dia 7: registra no fim do PROJECT.md o E2 (ataques), gerado dos CSVs.

Nenhum número é digitado: tabelas e contagens saem de data/results/e2_lotes.csv e
e2_resumo.csv. As frases de leitura só são gravadas se cada uma passar numa verificação
contra os CSVs; se alguma falhar, o script recusa e não grava nada. Acrescenta um bloco ao
FIM do PROJECT.md, entre marcadores, sem editar nenhuma linha existente. Tudo ou nada:

- só grava se o SHA-256 atual do PROJECT.md for HASH_ANTES (o do commit d8605e1);
- "já aplicado" quando o arquivo termina exatamente com o bloco gerado agora e, sem ele,
  volta a HASH_ANTES;
- recusa sem gravar se faltar CSV, se o cabeçalho for outro, se o e2_resumo.csv não for a
  derivação exata do e2_lotes.csv, se o commit das linhas não for COMMIT_PRE_REGISTRO, se uma
  frase de leitura não bater com os dados, se o marcador já existir, se o hash do PROJECT.md for
  outro ou se ele não for CRLF puro terminando em fim de linha.

Uso (na raiz do projeto):
    py -3.12 scripts\\registrar_e2.py
Código de saída: 0 aplicado ou já aplicado; 1 recusado (nada foi gravado).
"""
from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import os
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable

TARGET = Path("PROJECT.md")
RESULTS = Path("data/results")
SCRIPTS = Path(__file__).resolve().parent
HASH_ANTES = "c8f405ef1cf87964ddb4ffd629ad67b0d1d3d2e3dcc4736a20b222535d5d85ae"
START = "<!-- dia7-e2:start -->"
END = "<!-- dia7-e2:end -->"
COMMIT_PRE_REGISTRO = "f5b35166ff9550357d0dc30cc14c4ed7fd975130"
NOME_LOTES = "e2_lotes.csv"
NOME_RESUMO = "e2_resumo.csv"

# Conta de referência (não é medição): config.STATS_P_MIN e os 3 testes estatísticos do pipeline.
P_MIN = Decimal("0.01")
STATS_KEYS = ("monobit", "block", "runs")
ORDEM_MOTIVOS = ("monobit", "block", "runs", "APT", "RCT")

T1, T4 = 1_000_000, 4_000_000


class Refused(Exception):
    """Recusa: nada foi gravado."""


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ---------------------------------------------------------------- formatação

def n_pt(valor: Any) -> str:
    return f"{int(valor):,}".replace(",", ".")


def d_pt(texto: str) -> str:
    return texto.replace(".", ",")


def valor_pt(texto: str) -> str:
    return "-" if texto == "" else d_pt(texto)


# ---------------------------------------------------------------- leitura

def carregar_e2() -> Any:
    caminho = SCRIPTS / "e2_ataques.py"
    if not caminho.is_file():
        raise Refused(f"script ausente: {caminho}")
    spec = importlib.util.spec_from_file_location("e2_ataques_registro", caminho)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def ler_resumo(e2: Any, caminho: Path) -> list[dict[str, str]]:
    if not caminho.is_file():
        raise Refused(f"CSV ausente: {caminho}")
    with open(caminho, encoding="utf-8", newline="") as fh:
        leitor = csv.DictReader(fh)
        if tuple(leitor.fieldnames or ()) != tuple(e2.CAMPOS_RESUMO):
            raise Refused(f"{caminho.name}: cabeçalho diferente do esperado")
        linhas = list(leitor)
    if not linhas:
        raise Refused(f"{caminho.name}: sem linhas")
    return linhas


def ler_lotes(e2: Any, caminho: Path) -> list[dict[str, str]]:
    if not caminho.is_file():
        raise Refused(f"CSV ausente: {caminho}")
    try:
        linhas = e2.ler_lotes(caminho)
    except e2.E2Erro as exc:
        raise Refused(str(exc)) from exc
    if not linhas:
        raise Refused(f"{caminho.name}: sem linhas")
    return linhas


def conferir_integridade(e2: Any, lotes: list[dict[str, str]], p_resumo: Path) -> None:
    try:
        derivado = e2.csv_bytes(e2.CAMPOS_RESUMO, e2.resumir(lotes))
    except e2.E2Erro as exc:
        raise Refused(str(exc)) from exc
    if derivado != p_resumo.read_bytes():
        raise Refused(f"{NOME_RESUMO} não é a derivação exata de {NOME_LOTES}")
    commits = {l["commit"] for l in lotes}
    if commits != {COMMIT_PRE_REGISTRO}:
        raise Refused(f"commit das linhas {sorted(commits)} difere de {COMMIT_PRE_REGISTRO}")


# ---------------------------------------------------------------- afirmações verificadas

def _i(linha: dict[str, str], campo: str) -> int:
    return int(linha[campo])


def _d(linha: dict[str, str], campo: str) -> Decimal:
    return Decimal(linha[campo])


def _todos(l: dict[str, str]) -> bool:
    return _i(l, "n_reprovados") == _i(l, "n_lotes")


def _parcial(l: dict[str, str]) -> bool:
    return 0 < _i(l, "n_reprovados") < _i(l, "n_lotes")


def _sobrepoe(a: dict[str, str], b: dict[str, str]) -> bool:
    return _d(a, "ic95_inf") <= _d(b, "ic95_sup") and _d(b, "ic95_inf") <= _d(a, "ic95_sup")


def montar_afirmacoes(resumo: list[dict[str, str]]) -> list[tuple[str, Callable[[], bool]]]:
    ix = {(r["fonte"], r["valor"], int(r["n_bits"]), r["leitura"]): r for r in resumo}
    sem_valor = ""

    def c(fonte: str, valor: str, n: int, leitura: str = "1") -> dict[str, str]:
        return ix[(fonte, valor, n, leitura)]

    linhas_de = lambda fonte: [r for r in resumo if r["fonte"] == fonte]  # noqa: E731
    stuck = linhas_de("faulty_stuck")
    menor = min(int(r["valor"]) for r in stuck)
    forte = ([("faulty_biased", v, T1) for v in ("0.505", "0.51", "0.55")]
             + [("faulty_correlated", v, T1) for v in ("0.505", "0.51", "0.6")]
             + [("faulty_biased", v, T4) for v in ("0.502", "0.505", "0.51", "0.55")]
             + [("faulty_correlated", v, T4) for v in ("0.502", "0.505", "0.51", "0.6")])
    fraco = [(f, "0.501", n) for f in ("faulty_biased", "faulty_correlated") for n in (T1, T4)]
    fraco += [(f, "0.502", T1) for f in ("faulty_biased", "faulty_correlated")]
    h_permitido = {("faulty_biased", "0.55"), ("faulty_correlated", "0.6")}

    def rct_travamento() -> bool:
        for n in (T1, T4):
            if _i(c("faulty_stuck", "8", n), "n_rct_falhou") != 0:
                return False
            if _i(c("faulty_stuck", "16", n), "n_rct_falhou") != 0:
                return False
            if not _parcial_campo(c("faulty_stuck", "24", n), "n_rct_falhou"):
                return False
            for v in ("32", "64"):
                l = c("faulty_stuck", v, n)
                if _i(l, "n_rct_falhou") != _i(l, "n_lotes"):
                    return False
        return True

    def _parcial_campo(l: dict[str, str], campo: str) -> bool:
        return 0 < _i(l, campo) < _i(l, "n_lotes")

    def menor_so_estatistico() -> bool:
        for n in (T1, T4):
            l = c("faulty_stuck", str(menor), n)
            if (_i(l, "n_rct_falhou"), _i(l, "n_h_falhou")) != (0, 0):
                return False
            if _i(l, "n_stats_falhou") != _i(l, "n_lotes"):
                return False
        return True

    def h_restrito() -> bool:
        for r in resumo:
            if _i(r, "n_h_falhou") == 0:
                continue
            if (r["fonte"], r["valor"]) in h_permitido:
                continue
            if r["fonte"] == "faulty_stuck" and int(r["valor"]) >= 16:
                continue
            return False
        return True

    def replay() -> bool:
        for n in (T1, T4):
            l2 = c("faulty_replay", sem_valor, n, "2")
            if _i(l2, "n_replay_falhou") != _i(l2, "n_lotes") or not _todos(l2):
                return False
        return all(_i(r, "n_replay_falhou") == 0
                   for r in resumo if not (r["fonte"] == "faulty_replay" and r["leitura"] == "2"))

    t = f"{n_pt(T1)}", f"{n_pt(T4)}"
    return [
        (f"Viés e correlação (`faulty_biased`, `faulty_correlated`) com intensidade igual ou "
         f"maior que 0,505 em lotes de {t[0]} bits, ou 0,502 em lotes de {t[1]} bits, foram "
         f"reprovados em todos os lotes.",
         lambda: all(_todos(c(f, v, n)) for f, v, n in forte)),
        (f"Nos valores mais fracos da grade (0,501 nos dois tamanhos e 0,502 em {t[0]} bits) a "
         f"detecção é parcial: parte dos lotes passa.",
         lambda: all(_parcial(c(f, v, n)) for f, v, n in fraco)),
        ("O RCT não reprovou nenhum lote de viés nem de correlação.",
         lambda: all(_i(r, "n_rct_falhou") == 0
                     for f in ("faulty_biased", "faulty_correlated") for r in linhas_de(f))),
        (f"Travamento (`faulty_stuck`): todos os lotes foram reprovados em todos os comprimentos "
         f"da grade, inclusive no menor ({menor}). O limite inferior de detecção do travamento "
         f"não foi encontrado.",
         lambda: all(_todos(r) for r in stuck)),
        (f"No menor comprimento de travamento ({menor}), o RCT e o teste de min-entropia não "
         f"reprovaram nenhum lote e os testes estatísticos reprovaram todos.",
         menor_so_estatistico),
        ("O RCT não reprova travamentos de 8 e 16 bits, reprova só parte dos lotes com 24 bits "
         "e reprova todos os lotes com 32 e 64 bits.",
         rct_travamento),
        ("O teste de min-entropia só reprovou lotes com viés de 0,55, correlação de 0,6 ou "
         "travamento de 16 bits ou mais; não reprovou nenhum lote das demais células, "
         "incluindo `os`, `faulty_prng` e `faulty_replay`.",
         h_restrito),
        ("O teste de replay reprovou todas as 2ª leituras de `faulty_replay` e nenhum lote de "
         "qualquer outra célula (sem alarme falso de replay).",
         replay),
        ("Na fonte `os`, o RCT e o teste de min-entropia não reprovaram nenhum lote.",
         lambda: all(_i(r, "n_rct_falhou") == 0 and _i(r, "n_h_falhou") == 0
                     for r in linhas_de("os"))),
        ("Os IC 95% do falso positivo da `os` nos dois tamanhos se sobrepõem; estes dados não "
         "distinguem os dois tamanhos.",
         lambda: _sobrepoe(c("os", sem_valor, T1), c("os", sem_valor, T4))),
        ("A taxa de reprovação de `faulty_prng` não se distingue da da `os`: os IC 95% se "
         "sobrepõem nos dois tamanhos. O teste de saída não separa um PRNG de uma fonte boa "
         "(limitação T4 do modelo de ameaça).",
         lambda: all(_sobrepoe(c("faulty_prng", sem_valor, n), c("os", sem_valor, n))
                     for n in (T1, T4))),
    ]


def verificar_afirmacoes(resumo: list[dict[str, str]]) -> list[str]:
    try:
        afirmacoes = montar_afirmacoes(resumo)
    except (KeyError, ValueError) as exc:
        raise Refused(f"o resumo não tem a estrutura esperada pelas afirmações: {exc!r}") from exc
    textos: list[str] = []
    for texto, teste in afirmacoes:
        try:
            ok = teste()
        except (KeyError, ValueError, ArithmeticError):
            ok = False
        if not ok:
            raise Refused(f"afirmação não confirmada pelos CSVs: {texto}")
        textos.append(texto)
    return textos


# ---------------------------------------------------------------- tabelas

def grupo_texto(r: dict[str, str]) -> str:
    if r["tipo"] == "falso_positivo":
        return "falso positivo"
    if r["tipo"] == "referencia":
        return "referência (1ª leitura)"
    if r["fonte"] == "faulty_replay":
        return "detecção (2ª leitura)"
    return "detecção"


def tabela_resultados(resumo: list[dict[str, str]]) -> list[str]:
    linhas = [
        "| Grupo | Fonte | Valor | Bits | Reprovados | Lotes | Taxa | IC 95% | RCT | APT | "
        "Replay | H | Estat. |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in resumo:
        linhas.append(
            f"| {grupo_texto(r)} | {r['fonte']} | {valor_pt(r['valor'])} | {n_pt(r['n_bits'])} "
            f"| {n_pt(r['n_reprovados'])} | {n_pt(r['n_lotes'])} | {d_pt(r['taxa'])} "
            f"| {d_pt(r['ic95_inf'])} a {d_pt(r['ic95_sup'])} | {n_pt(r['n_rct_falhou'])} "
            f"| {n_pt(r['n_apt_falhou'])} | {n_pt(r['n_replay_falhou'])} "
            f"| {n_pt(r['n_h_falhou'])} | {n_pt(r['n_stats_falhou'])} |")
    return linhas


def falso_positivo_por_teste(lotes: list[dict[str, str]]) -> list[str]:
    por_n: dict[int, dict[str, Any]] = {}
    chaves: set[str] = set()
    for l in lotes:
        if l["fonte"] != "os":
            continue
        d = por_n.setdefault(int(l["n_bits"]), {"lotes": 0, "reprov": 0, "chaves": {}})
        d["lotes"] += 1
        if l["approved"] != "False":
            continue
        d["reprov"] += 1
        try:
            motivos = json.loads(l["reasons"])
        except json.JSONDecodeError as exc:
            raise Refused(f"os: motivo ilegível: {l['reasons']!r}") from exc
        if (not isinstance(motivos, list) or not motivos
                or not all(isinstance(m, str) and m for m in motivos)):
            raise Refused(f"os: lote reprovado sem motivo legível: {l['reasons']!r}")
        for k in {m.split(":", 1)[0].strip() for m in motivos}:
            d["chaves"][k] = d["chaves"].get(k, 0) + 1
            chaves.add(k)
    if not por_n:
        raise Refused("sem lotes da fonte os")
    ordem = [k for k in ORDEM_MOTIVOS if k in chaves] + sorted(chaves - set(ORDEM_MOTIVOS))
    saida = ["| Bits | Lotes `os` | Reprovados | " + " | ".join(ordem) + " |",
             "|---|---|---|" + "---|" * len(ordem)]
    for n in sorted(por_n):
        d = por_n[n]
        cont = " | ".join(n_pt(d["chaves"].get(k, 0)) for k in ordem)
        saida.append(f"| {n_pt(n)} | {n_pt(d['lotes'])} | {n_pt(d['reprov'])} | {cont} |")
    return saida


def referencia_teorica() -> str:
    ref = (1 - (1 - P_MIN) ** len(STATS_KEYS)).quantize(Decimal("0.0001"))
    return (f"Referência (conta, não medição): {len(STATS_KEYS)} testes estatísticos "
            f"independentes com p mínimo {d_pt(str(P_MIN))} reprovariam {d_pt(str(ref))} dos "
            f"lotes de uma fonte perfeita.")


RESSALVAS = (
    "As fontes defeituosas são simuladas (`eal.sources.faulty`, geradas por numpy). As taxas "
    "valem para esses modelos de defeito, não para ataques reais. O E2 não usou QPU.",
    "As taxas das intensidades fracas incluem o ruído de fundo do falso positivo, que tem a "
    "ordem de grandeza da `os`; nada foi subtraído.",
    "Os testes estatísticos só concluem a partir de um tamanho mínimo de lote "
    "(`STATS_MIN_BITS`). O E2 mediu apenas lotes acima desse mínimo e não mediu lotes menores.",
    "Os testes estatísticos reprovam, por construção, uma fração das fontes perfeitas ligada ao "
    "p mínimo (referência acima). Mudar esse limiar mudaria também a sensibilidade nas "
    "intensidades fracas; isso só pode ser avaliado em um experimento novo, pré-registrado, e "
    "não foi feito aqui.",
    "Os lotes da `os` não têm semente e não são reproduzíveis. Os das fontes defeituosas são "
    "reproduzíveis pela semente gravada em `e2_lotes.csv`. Os bits crus não foram guardados.",
    "A grade, os tamanhos e as repetições foram fixados no commit indicado acima, antes da "
    "rodada. O aumento das repetições (10 vezes) foi decidido depois de medir o tempo e antes "
    "de ver qualquer taxa.",
)


def montar_bloco(e2: Any, lotes: list[dict[str, str]], resumo: list[dict[str, str]],
                 hashes: dict[str, str]) -> str:
    leitura = verificar_afirmacoes(resumo)
    celulas = {(r["fonte"], r["valor"], r["n_bits"]) for r in resumo}
    tamanhos = sorted({int(r["n_bits"]) for r in resumo})
    out = [
        START,
        "### E2, ataques: taxa de detecção e falsos positivos (Dia 7, registro gerado dos CSVs)",
        "",
        "Gerado por `scripts/registrar_e2.py` a partir de `e2_lotes.csv` e `e2_resumo.csv`. "
        "Nenhum número foi digitado à mão. As frases da seção de leitura só são gravadas se cada "
        "uma for confirmada pelos CSVs; o script recusa se alguma falhar.",
        "",
        f"**Protocolo (pré-registrado):** rodada sobre o commit `{COMMIT_PRE_REGISTRO}`, "
        f"conferido na coluna `commit` das {n_pt(len(lotes))} linhas. {n_pt(len(celulas))} "
        f"células, lotes de {' e '.join(n_pt(n) for n in tamanhos)} bits. Cada lote usa uma "
        "instância nova da fonte, semente própria gravada e um detector de replay novo; no "
        "replay, as duas leituras de cada par vêm da mesma instância. Detecção é o lote com "
        "`approved` falso; no replay só a 2ª leitura conta, e a 1ª entra como referência. Falso "
        "positivo é um lote da `os` reprovado. IC 95% de Clopper-Pearson.",
        "",
        "**Resultados por célula** (RCT, APT, Replay, H e Estat. contam os lotes em que o "
        "respectivo teste falhou; um lote pode falhar em mais de um):",
        "",
        *tabela_resultados(resumo),
        "",
        "**Falso positivo da `os`, por teste que reprovou o lote:**",
        "",
        *falso_positivo_por_teste(lotes),
        "",
        referencia_teorica(),
        "",
        "**Leitura (cada frase foi verificada contra os CSVs antes de ser gravada):**",
        "",
        *[f"- {t}" for t in leitura],
        "",
        "**Ressalvas:**",
        "",
        *[f"- {t}" for t in RESSALVAS],
        "",
        "**CSVs (SHA-256 dos bytes em disco):**",
        "",
        f"- `{NOME_LOTES}`: `{hashes[NOME_LOTES]}`",
        f"- `{NOME_RESUMO}`: `{hashes[NOME_RESUMO]}`",
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
        e2 = carregar_e2()
        p_lotes, p_resumo = RESULTS / NOME_LOTES, RESULTS / NOME_RESUMO
        lotes = ler_lotes(e2, p_lotes)
        resumo = ler_resumo(e2, p_resumo)
        conferir_integridade(e2, lotes, p_resumo)
        hashes = {NOME_LOTES: sha256(p_lotes.read_bytes()),
                  NOME_RESUMO: sha256(p_resumo.read_bytes())}
        insercao = preparar_insercao(montar_bloco(e2, lotes, resumo, hashes))
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
