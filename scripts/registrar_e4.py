"""Dia 7: registra no fim do PROJECT.md o E4 (resiliência da mistura), gerado dos CSVs.

Nenhum número é digitado: tabelas e contagens saem de data/results/e4_sequencias.csv e
e4_resumo.csv. As frases de leitura só são gravadas se cada uma passar numa verificação
contra os CSVs; se alguma falhar, o script recusa e não grava nada. Acrescenta um bloco ao
FIM do PROJECT.md, entre marcadores, sem editar nenhuma linha existente. Tudo ou nada:

- só grava se o SHA-256 atual do PROJECT.md for HASH_ANTES (o do commit 0db017a);
- "já aplicado" quando o arquivo termina exatamente com o bloco gerado agora e, sem ele,
  volta a HASH_ANTES;
- recusa sem gravar se faltar CSV, se o cabeçalho for outro, se o e4_resumo.csv não for a
  derivação exata do e4_sequencias.csv, se o commit das linhas não for o da grade
  pré-registrada (COMMIT_CURTO), se uma frase de leitura não bater com os dados, se o marcador
  já existir, se o hash do PROJECT.md for outro ou se ele não for CRLF puro terminando em fim
  de linha.

Uso (na raiz do projeto):
    py -3.12 scripts\\registrar_e4.py
Código de saída: 0 aplicado ou já aplicado; 1 recusado (nada foi gravado).
"""
from __future__ import annotations

import csv
import hashlib
import importlib.util
import os
import re
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable

TARGET = Path("PROJECT.md")
RESULTS = Path("data/results")
SCRIPTS = Path(__file__).resolve().parent
HASH_ANTES = "82619b4b737e298a5bd443e7c4d4eec2a79eb31e6cb0f5ed8c91f522cce945e8"
START = "<!-- dia7-e4:start -->"
END = "<!-- dia7-e4:end -->"
COMMIT_CURTO = "ed4ae20"
NOME_SEQ = "e4_sequencias.csv"
NOME_RESUMO = "e4_resumo.csv"
SEGURAS = ("base_boa", "enviesada", "travada", "constante")


class Refused(Exception):
    """Recusa: nada foi gravado."""


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ---------------------------------------------------------------- formatação

def n_pt(valor: Any) -> str:
    return f"{int(valor):,}".replace(",", ".")


def d_pt(texto: str) -> str:
    return "-" if texto == "" else texto.replace(".", ",")


def faixa(a: str, b: str) -> str:
    if a == "" and b == "":
        return "-"
    return a if a == b else f"{a} a {b}"


# ---------------------------------------------------------------- leitura

def carregar_e4() -> Any:
    caminho = SCRIPTS / "e4_mistura.py"
    if not caminho.is_file():
        raise Refused(f"script ausente: {caminho}")
    spec = importlib.util.spec_from_file_location("e4_mistura_registro", caminho)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def ler_seq(e4: Any, caminho: Path) -> list[dict[str, str]]:
    if not caminho.is_file():
        raise Refused(f"CSV ausente: {caminho}")
    try:
        linhas = e4.ler_seq(caminho)
    except e4.E4Erro as exc:
        raise Refused(str(exc)) from exc
    if not linhas:
        raise Refused(f"{caminho.name}: sem linhas")
    return linhas


def ler_resumo(e4: Any, caminho: Path) -> list[dict[str, str]]:
    if not caminho.is_file():
        raise Refused(f"CSV ausente: {caminho}")
    with open(caminho, encoding="utf-8", newline="") as fh:
        leitor = csv.DictReader(fh)
        if tuple(leitor.fieldnames or ()) != tuple(e4.CAMPOS_RESUMO):
            raise Refused(f"{caminho.name}: cabeçalho diferente do esperado")
        linhas = list(leitor)
    if not linhas:
        raise Refused(f"{caminho.name}: sem linhas")
    return linhas


def conferir_integridade(e4: Any, seq: list[dict[str, str]], p_resumo: Path) -> str:
    try:
        derivado = e4.csv_bytes(e4.CAMPOS_RESUMO, e4.resumir(seq))
    except e4.E4Erro as exc:
        raise Refused(str(exc)) from exc
    if derivado != p_resumo.read_bytes():
        raise Refused(f"{NOME_RESUMO} não é a derivação exata de {NOME_SEQ}")
    commits = {l["commit"] for l in seq}
    if len(commits) != 1:
        raise Refused(f"mais de um commit nas linhas: {sorted(commits)}")
    commit = commits.pop()
    if not re.fullmatch(r"[0-9a-f]{40}", commit) or not commit.startswith(COMMIT_CURTO):
        raise Refused(f"commit das linhas ({commit}) não é o da grade pré-registrada ({COMMIT_CURTO})")
    return commit


# ---------------------------------------------------------------- dados derivados

def chave(r: dict[str, str]) -> tuple[str, str, str]:
    return (r["cenario"], r["combinador"], r["k"])


def identicas(seq: list[dict[str, str]]) -> list[tuple[str, str, str]]:
    """Células com mais de uma sequência completa e todas iguais (p-valores, |z| e distintas)."""
    grupos: dict[tuple[str, str, str], list[dict[str, str]]] = {}
    for l in seq:
        grupos.setdefault(chave(l), []).append(l)
    saida = []
    for k, ls in grupos.items():
        if len(ls) < 2 or any(l["aprovada"] == "" for l in ls):
            continue
        assinaturas = {(l["p_monobit"], l["p_block"], l["p_runs"], l["max_abs_z"], l["n_distintas"])
                       for l in ls}
        if len(assinaturas) == 1:
            saida.append(k)
    return saida


def nome(k: tuple[str, str, str]) -> str:
    cen, comb, kk = k
    return f"`{cen}{'' if kk == '' else f' k={kk}'}/{comb}`"


# ---------------------------------------------------------------- afirmações verificadas

def _i(r: dict[str, str], campo: str) -> int:
    return int(r[campo])


def _sobrepoe(a: dict[str, str], b: dict[str, str]) -> bool:
    return (Decimal(a["ic95_inf"]) <= Decimal(b["ic95_sup"])
            and Decimal(b["ic95_inf"]) <= Decimal(a["ic95_sup"]))


def montar_afirmacoes(res: list[dict[str, str]], ident: list[tuple[str, str, str]]
                      ) -> list[tuple[str, Callable[[], bool]]]:
    ix = {chave(r): r for r in res}

    def c(cen: str, comb: str, k: str = "") -> dict[str, str]:
        return ix[(cen, comb, k)]

    base = c("base_boa", "hash")
    n = _i(base, "sementes_total") // _i(base, "n_seq")
    forca = sorted((r for r in res if r["cenario"] == "adv_forca"), key=lambda r: int(r["k"]))
    ks = [r["k"] for r in forca]
    seguras = [(cen, comb) for cen in SEGURAS for comb in ("hash", "xor")]

    def uma_boa() -> bool:
        for cen, comb in seguras:
            r, b = c(cen, comb), c("base_boa", comb)
            if _i(r, "distintas_min") != n or r["pos_z5_max"] != "0" or not _sobrepoe(r, b):
                return False
        return True

    def copia() -> bool:
        h, x = c("copia", "hash"), c("copia", "xor")
        return (h["n_seq_completas"] == "0" and h["sementes_total"] == "0"
                and _i(h, "recusadas_total") == _i(h, "n_seq") * n and x["distintas_max"] == "1")

    def adv_alvo() -> bool:
        h, x = c("adv_alvo", "hash"), c("adv_alvo", "xor")
        return (x["frac_alvo"] == "1.0000" and _sobrepoe(x, c("base_boa", "xor"))
                and h["frac_alvo"] == "0.0000" and _i(h, "distintas_min") == n)

    def sem_boa() -> bool:
        return all(c("sem_fonte_boa", comb)["distintas_max"] == "1" for comb in ("hash", "xor"))

    def forca_bits() -> bool:
        return bool(forca) and all(
            r["frac_alvo"] == "1.0000" and r["pos_z5_min"] == r["pos_z5_max"] == r["k"]
            and r["falhas_forca_total"] == "0" and _i(r, "distintas_min") == n for r in forca)

    def forca_aprovacao() -> bool:
        if len(forca) < 2:
            return False
        primeiro, resto = forca[0], forca[1:]
        return (0 < _i(primeiro, "n_aprovadas") < _i(primeiro, "n_seq_completas")
                and all(r["n_aprovadas"] == "0" for r in resto))

    def identicas_ok() -> bool:
        return bool(ident) and not any((cen, comb, "") in ident for cen, comb in seguras)

    lista_ks = ", ".join(ks)
    return [
        ("Com uma fonte boa e independente (`base_boa`, `enviesada`, `travada`, `constante`), os "
         "dois combinadores deram sementes todas distintas, nenhuma posição de bit com |z| > 5 e "
         "taxa de aprovação com IC 95% sobreposto ao do `base_boa` do mesmo combinador.",
         uma_boa),
        ("Cópia exata da honesta: o `mix` real recusou todas as sementes (`input_hash` repetido, "
         "fail-closed); o XOR produziu uma única semente, repetida em toda a sequência.",
         copia),
        ("Fonte adversária que vê a honesta (`adv_alvo`): no XOR, todas as sementes foram as "
         "escolhidas pelo adversário (fração no alvo 1) e a taxa de aprovação tem IC 95% "
         "sobreposto ao do `base_boa`, ou seja, os testes estatísticos não veem o controle. No "
         "hash, nenhuma semente coincidiu com o alvo e as sementes ficaram todas distintas.",
         adv_alvo),
        ("Sem fonte boa (as duas constantes), os dois combinadores repetiram uma única semente "
         "em cada sequência.",
         sem_boa),
        (f"Adversário que testa candidatos contra o hash (`adv_forca`, k = {lista_ks}): em cada "
         "k, todas as sementes tiveram os k primeiros bits em zero, exatamente k posições de bit "
         "com |z| > 5, sementes todas distintas e nenhuma falha dentro do limite de tentativas. "
         "Cada semente escolhida foi conferida contra o `mix` real durante a rodada (o script "
         "recusaria se alguma divergisse).",
         forca_bits),
        (f"Sobre as sementes concatenadas, os testes estatísticos reprovaram só parte das "
         f"sequências com k = {ks[0] if ks else '-'} e todas com k = "
         f"{', '.join(ks[1:]) if len(ks) > 1 else '-'}.",
         forca_aprovacao),
        ("Nas células " + ", ".join(nome(k) for k in ident) + ", todas as sequências são "
         "idênticas (mesmos p-valores, mesmo |z| máximo e mesmas sementes distintas): as "
         "repetições não são observações independentes e o IC 95% da taxa de aprovação não se "
         "aplica a elas. Nenhuma célula com uma fonte boa está nessa lista.",
         identicas_ok),
    ]


def verificar_afirmacoes(res: list[dict[str, str]], ident: list[tuple[str, str, str]]) -> list[str]:
    try:
        afirmacoes = montar_afirmacoes(res, ident)
    except (KeyError, ValueError, ZeroDivisionError) as exc:
        raise Refused(f"o resumo não tem a estrutura esperada pelas afirmações: {exc!r}") from exc
    textos = []
    for texto, teste in afirmacoes:
        try:
            ok = teste()
        except (KeyError, ValueError, ArithmeticError):
            ok = False
        if not ok:
            raise Refused(f"afirmação não confirmada pelos CSVs: {texto}")
        textos.append(texto)
    return textos


# ---------------------------------------------------------------- bloco

def tabela(res: list[dict[str, str]]) -> list[str]:
    linhas = [
        "| Cenário | Combinador | k | Esperado | Sequências completas | Aprovadas | Taxa | IC 95% "
        "| Recusadas | Fração no alvo | Sementes distintas | Máx. \\|z\\| | Posições \\|z\\| > 5 "
        "| Falhas do adversário |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in res:
        ic = "-" if r["ic95_inf"] == "" else f"{d_pt(r['ic95_inf'])} a {d_pt(r['ic95_sup'])}"
        linhas.append(
            f"| {r['cenario']} | {r['combinador']} | {r['k'] or '-'} | {r['esperado']} "
            f"| {n_pt(r['n_seq_completas'])} de {n_pt(r['n_seq'])} | {n_pt(r['n_aprovadas'])} "
            f"| {d_pt(r['taxa_aprovacao'])} | {ic} | {n_pt(r['recusadas_total'])} "
            f"| {d_pt(r['frac_alvo'])} | {faixa(r['distintas_min'], r['distintas_max'])} "
            f"| {d_pt(r['max_abs_z_max'])} | {faixa(r['pos_z5_min'], r['pos_z5_max'])} "
            f"| {r['falhas_forca_total'] or '-'} |")
    return linhas


RESSALVAS = (
    "O modelo é o pior caso. No pipeline, nenhuma fonte recebe a saída das outras; a fonte que "
    "vê a honesta é hipotética (por exemplo, um provedor remoto que tivesse acesso à saída da "
    "`os`).",
    "Todas as fontes entram declaradas como aprovadas: o E4 isola a combinação e não reavalia "
    "a saúde, que é medida no E2.",
    "A aprovação é medida sobre milhares de sementes concatenadas. O pipeline gera uma semente "
    "por execução, e numa semente isolada não se vê repetição nem bits forçados. O controle do "
    "adversário sobre o XOR não aparece nos testes nem com as sementes concatenadas.",
    "O XOR existe só no script do E4, como comparador; o `eal` usa só o hash.",
    "Forçar k bits custa cerca de 2^k avaliações do hash por semente, e com mais computação k "
    "cresce. O que o hash limita é o controle a esses k bits dos 512 da semente; no XOR, o "
    "controle do adversário é total e sem custo.",
    "O tempo de execução variou muito em relação à medição prévia, sobretudo no maior k. Isso "
    "não afeta os resultados, que são determinísticos pela semente de cada sequência.",
)


def montar_bloco(seq: list[dict[str, str]], res: list[dict[str, str]], commit: str,
                 hashes: dict[str, str]) -> str:
    ident = identicas(seq)
    leitura = verificar_afirmacoes(res, ident)
    base = next(r for r in res if chave(r) == ("base_boa", "hash", ""))
    n = int(base["sementes_total"]) // int(base["n_seq"])
    out = [
        START,
        "### E4, resiliência da mistura: XOR contra o hash do mixer (Dia 7, registro gerado dos "
        "CSVs)",
        "",
        "Gerado por `scripts/registrar_e4.py` a partir de `e4_sequencias.csv` e `e4_resumo.csv`. "
        "Nenhum número foi digitado à mão. As frases da seção de leitura só são gravadas se cada "
        "uma for confirmada pelos CSVs; o script recusa se alguma falhar.",
        "",
        f"**Protocolo (pré-registrado):** rodada sobre o commit `{commit}`, conferido na coluna "
        f"`commit` das {n_pt(len(seq))} linhas; {n_pt(len(res))} células; {n_pt(n)} sementes de "
        "512 bits por sequência. Duas fontes por semente: a honesta (`os`, local) e a segunda "
        "(`qpu_remota`, remota), que muda por cenário; as duas entram declaradas como aprovadas. "
        "`hash` é o `mix` real em modo `keygen`; `xor` é um comparador do script (XOR dos "
        "primeiros 512 bits de cada fonte). O hash e o XOR de um mesmo cenário e repetição usam "
        "as mesmas entradas. Aprovada: os 3 testes estatísticos do pipeline passam sobre as "
        "sementes concatenadas. IC 95% de Clopper-Pearson.",
        "",
        "**Resultados por célula:**",
        "",
        *tabela(res),
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
        f"- `{NOME_SEQ}`: `{hashes[NOME_SEQ]}`",
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
        e4 = carregar_e4()
        p_seq, p_res = RESULTS / NOME_SEQ, RESULTS / NOME_RESUMO
        seq = ler_seq(e4, p_seq)
        res = ler_resumo(e4, p_res)
        commit = conferir_integridade(e4, seq, p_res)
        hashes = {NOME_SEQ: sha256(p_seq.read_bytes()), NOME_RESUMO: sha256(p_res.read_bytes())}
        insercao = preparar_insercao(montar_bloco(seq, res, commit, hashes))
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
