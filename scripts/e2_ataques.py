"""E2: taxa de detecção das fontes defeituosas e falso positivo na fonte os.

Pré-registro: a grade (GRADE, STUCK_EVERY, TAMANHOS, REPS, REPS_OS) e as
definições abaixo ficam fixadas no commit deste script, antes da rodada completa.

- Cada lote usa uma instância nova da fonte, com semente própria derivada de
  (fonte, valor, n_bits, repetição) e gravada no CSV, e um ReplayDetector novo.
- faulty_replay: um detector por par; duas leituras da mesma instância.
- Detecção: approved == False. No replay só a 2ª leitura conta como detecção;
  a 1ª entra no resumo como referência.
- Falso positivo: lote da os com approved == False.
- A avaliação é build_health_report(batch, detector), a mesma do gate_dia3.py.
- Os bits crus não são gravados.

Uso:
  py -3.12 scripts\\e2_ataques.py --medir-tempo   2 lotes por célula; só tempos, não grava nada
  py -3.12 scripts\\e2_ataques.py --rodar         grade completa; grava e2_lotes.csv e e2_resumo.csv
  py -3.12 scripts\\e2_ataques.py --resumir       refaz e2_resumo.csv a partir de e2_lotes.csv
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import statistics
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SCHEMA = "e2_lotes_v1"

# ---------------------------------------------------------------- pré-registro
GRADE: tuple[tuple[str, str, tuple[Any, ...]], ...] = (
    ("faulty_biased", "p", (0.501, 0.502, 0.505, 0.51, 0.55)),
    ("faulty_correlated", "rho", (0.501, 0.502, 0.505, 0.51, 0.6)),
    ("faulty_stuck", "run_length", (8, 16, 24, 32, 64)),
    ("faulty_prng", "", (None,)),
    ("faulty_replay", "", (None,)),
)
STUCK_EVERY = 1024
TAMANHOS = (1_000_000, 4_000_000)
REPS = {1_000_000: 20, 4_000_000: 10}
REPS_OS = {1_000_000: 200, 4_000_000: 50}
REPS_MEDIR_TEMPO = 2
# -----------------------------------------------------------------------------

NOME_LOTES = "e2_lotes.csv"
NOME_RESUMO = "e2_resumo.csv"

CAMPOS_LOTES = (
    "schema", "commit", "fonte", "parametro", "valor", "n_bits", "repeticao",
    "leitura", "semente", "batch_hash", "approved", "rct_pass", "apt_pass",
    "apt_inconclusive", "replay_pass", "h_health_pass", "stats_pass",
    "stats_inconclusive", "h_estimated", "rct_max_run", "apt_max_count",
    "stats_json", "reasons", "t_leitura_s", "t_saude_s",
)
FLAGS = (
    "approved", "rct_pass", "apt_pass", "apt_inconclusive", "replay_pass",
    "h_health_pass", "stats_pass", "stats_inconclusive",
)
CAMPOS_RESUMO = (
    "fonte", "parametro", "valor", "n_bits", "leitura", "tipo", "n_lotes",
    "n_reprovados", "taxa", "ic95_inf", "ic95_sup", "n_rct_falhou",
    "n_apt_falhou", "n_replay_falhou", "n_h_falhou", "n_stats_falhou",
    "n_stats_inconclusivo", "h_estimada_min", "h_estimada_max",
    "t_lote_mediana_s",
)


class E2Erro(Exception):
    """Recusa: nada é gravado."""


@dataclass(frozen=True)
class Celula:
    fonte: str
    parametro: str
    valor: Any
    n_bits: int
    reps: int

    @property
    def leituras(self) -> int:
        return 2 if self.fonte == "faulty_replay" else 1

    @property
    def n_lotes(self) -> int:
        return self.reps * self.leituras


def texto_valor(valor: Any) -> str:
    if valor is None:
        return ""
    if isinstance(valor, bool):
        raise E2Erro(f"valor de grade booleano não esperado: {valor!r}")
    if isinstance(valor, int):
        return str(valor)
    if isinstance(valor, float):
        return repr(valor)
    raise E2Erro(f"valor de grade de tipo não esperado: {valor!r}")


def semente(fonte: str, valor: Any, n_bits: int, repeticao: int) -> int:
    """Semente de 64 bits, determinística e própria de cada lote."""
    chave = f"e2|v1|{fonte}|{texto_valor(valor)}|{n_bits}|{repeticao}"
    return int.from_bytes(hashlib.sha256(chave.encode("ascii")).digest()[:8], "big")


def celulas(reps: dict[int, int] | None = None, reps_os: dict[int, int] | None = None) -> list[Celula]:
    reps = REPS if reps is None else reps
    reps_os = REPS_OS if reps_os is None else reps_os
    saida: list[Celula] = []
    for n in TAMANHOS:
        for fonte, parametro, valores in GRADE:
            for valor in valores:
                saida.append(Celula(fonte, parametro, valor, n, reps[n]))
        saida.append(Celula("os", "", None, n, reps_os[n]))
    return saida


def celulas_medir_tempo() -> list[Celula]:
    r = {n: REPS_MEDIR_TEMPO for n in TAMANHOS}
    return celulas(r, r)


# ------------------------------------------------------------ fontes e saúde
def fabricas_reais() -> dict[str, Callable[[Any, int | None], Any]]:
    from eal.sources.faulty import (
        BiasedSource, CorrelatedSource, PrngSource, ReplaySource, StuckSource,
    )
    from eal.sources.os_source import OsSource

    return {
        "faulty_biased": lambda v, s: BiasedSource(p=v, seed=s),
        "faulty_correlated": lambda v, s: CorrelatedSource(rho=v, seed=s),
        "faulty_stuck": lambda v, s: StuckSource(run_length=v, every=STUCK_EVERY, seed=s),
        "faulty_prng": lambda v, s: PrngSource(seed=s),
        "faulty_replay": lambda v, s: ReplaySource(seed=s),
        "os": lambda v, s: OsSource(),
    }


def saude_real() -> tuple[Callable[[], Any], Callable[[Any, Any], Any]]:
    from eal.health.replay import ReplayDetector
    from eal.health.report import build_health_report

    return ReplayDetector, build_health_report


# ---------------------------------------------------------------- lotes
def _flag(nome: str, valor: Any) -> str:
    import numpy as np

    if isinstance(valor, (bool, np.bool_)):
        return "True" if bool(valor) else "False"
    raise E2Erro(f"campo {nome} não é booleano: {valor!r}")


def _hash_texto(h: Any) -> str:
    if isinstance(h, (bytes, bytearray)):
        return bytes(h).hex()
    if isinstance(h, str) and h:
        return h
    raise E2Erro(f"batch_hash inesperado: {h!r}")


def linha_lote(c: Celula, repeticao: int, leitura: int, sem: int | None, batch: Any,
               rel: dict[str, Any], t_leitura: float, t_saude: float, commit: str) -> dict[str, str]:
    linha = {
        "schema": SCHEMA,
        "commit": commit,
        "fonte": c.fonte,
        "parametro": c.parametro,
        "valor": texto_valor(c.valor),
        "n_bits": str(c.n_bits),
        "repeticao": str(repeticao),
        "leitura": str(leitura),
        "semente": "" if sem is None else str(sem),
        "batch_hash": _hash_texto(getattr(batch, "batch_hash", None)),
    }
    for nome in FLAGS:
        linha[nome] = _flag(nome, rel[nome])
    if int(rel["n_bits"]) != c.n_bits:
        raise E2Erro(f"relatório com n_bits {rel['n_bits']} em vez de {c.n_bits}")
    h = rel["h_estimated"]
    linha["h_estimated"] = "" if h is None else repr(float(h))
    linha["rct_max_run"] = str(int(rel["rct_max_run"]))
    linha["apt_max_count"] = str(int(rel["apt_max_count"]))
    linha["stats_json"] = json.dumps(rel["stats"], sort_keys=True)
    linha["reasons"] = json.dumps(list(rel["reasons"]), ensure_ascii=False)
    linha["t_leitura_s"] = f"{t_leitura:.4f}"
    linha["t_saude_s"] = f"{t_saude:.4f}"
    return linha


def rodar_celula(c: Celula, fabricas: dict[str, Callable[[Any, int | None], Any]],
                 novo_detector: Callable[[], Any], avaliar: Callable[[Any, Any], Any],
                 commit: str) -> list[dict[str, str]]:
    linhas: list[dict[str, str]] = []
    for rep in range(c.reps):
        sem = None if c.fonte == "os" else semente(c.fonte, c.valor, c.n_bits, rep)
        fonte = fabricas[c.fonte](c.valor, sem)
        detector = novo_detector()
        for leitura in range(1, c.leituras + 1):
            t0 = time.perf_counter()
            batch = fonte.read(c.n_bits)
            t1 = time.perf_counter()
            if getattr(batch, "source_id", None) != c.fonte:
                raise E2Erro(f"lote de {getattr(batch, 'source_id', None)!r} na célula {c.fonte}")
            params = getattr(batch, "params", None) or {}
            if sem is not None and params.get("seed") != sem:
                raise E2Erro(f"semente do lote {params.get('seed')!r} difere da derivada {sem}")
            if c.fonte == "faulty_replay" and params.get("replayed") is not (leitura == 2):
                raise E2Erro(f"replay: leitura {leitura} com replayed={params.get('replayed')!r}")
            rel = avaliar(batch, detector).to_dict()
            t2 = time.perf_counter()
            linhas.append(linha_lote(c, rep, leitura, sem, batch, rel, t1 - t0, t2 - t1, commit))
    return linhas


# ---------------------------------------------------------------- resumo
def clopper_pearson(k: int, n: int, conf: float = 0.95) -> tuple[float, float]:
    from scipy.stats import beta

    if n <= 0 or not 0 <= k <= n:
        raise E2Erro(f"contagem inválida: k={k}, n={n}")
    a = 1.0 - conf
    inf = 0.0 if k == 0 else float(beta.ppf(a / 2, k, n - k + 1))
    sup = 1.0 if k == n else float(beta.ppf(1 - a / 2, k + 1, n - k))
    return inf, sup


def tipo_grupo(fonte: str, leitura: str) -> str:
    if fonte == "os":
        return "falso_positivo"
    if fonte == "faulty_replay" and leitura == "1":
        return "referencia"
    return "deteccao"


def validar_lotes(linhas: list[dict[str, str]]) -> None:
    if not linhas:
        raise E2Erro("e2_lotes.csv sem linhas")
    for i, l in enumerate(linhas, start=2):
        if l.get("schema") != SCHEMA:
            raise E2Erro(f"linha {i}: schema {l.get('schema')!r}")
        for nome in FLAGS:
            if l.get(nome) not in ("True", "False"):
                raise E2Erro(f"linha {i}: {nome} = {l.get(nome)!r}")


def resumir(linhas: list[dict[str, str]]) -> list[dict[str, str]]:
    validar_lotes(linhas)
    grupos: dict[tuple[str, ...], list[dict[str, str]]] = {}
    for l in linhas:
        chave = (l["fonte"], l["parametro"], l["valor"], l["n_bits"], l["leitura"])
        grupos.setdefault(chave, []).append(l)
    saida: list[dict[str, str]] = []
    for (fonte, parametro, valor, n_bits, leitura), ls in grupos.items():
        n = len(ls)
        k = sum(l["approved"] == "False" for l in ls)
        inf, sup = clopper_pearson(k, n)
        hs = [float(l["h_estimated"]) for l in ls if l["h_estimated"] != ""]
        tempos = [float(l["t_leitura_s"]) + float(l["t_saude_s"]) for l in ls]
        saida.append({
            "fonte": fonte, "parametro": parametro, "valor": valor,
            "n_bits": n_bits, "leitura": leitura, "tipo": tipo_grupo(fonte, leitura),
            "n_lotes": str(n), "n_reprovados": str(k), "taxa": f"{k / n:.4f}",
            "ic95_inf": f"{inf:.4f}", "ic95_sup": f"{sup:.4f}",
            "n_rct_falhou": str(sum(l["rct_pass"] == "False" for l in ls)),
            "n_apt_falhou": str(sum(l["apt_pass"] == "False" for l in ls)),
            "n_replay_falhou": str(sum(l["replay_pass"] == "False" for l in ls)),
            "n_h_falhou": str(sum(l["h_health_pass"] == "False" for l in ls)),
            "n_stats_falhou": str(sum(l["stats_pass"] == "False" for l in ls)),
            "n_stats_inconclusivo": str(sum(l["stats_inconclusive"] == "True" for l in ls)),
            "h_estimada_min": f"{min(hs):.6f}" if hs else "",
            "h_estimada_max": f"{max(hs):.6f}" if hs else "",
            "t_lote_mediana_s": f"{statistics.median(tempos):.4f}",
        })
    return saida


# ---------------------------------------------------------------- arquivos
def csv_bytes(campos: tuple[str, ...], linhas: list[dict[str, str]]) -> bytes:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=list(campos), lineterminator="\n", extrasaction="raise")
    w.writeheader()
    w.writerows(linhas)
    return buf.getvalue().encode("utf-8")


def ler_lotes(caminho: Path) -> list[dict[str, str]]:
    with caminho.open("r", encoding="utf-8", newline="") as f:
        r = csv.DictReader(f)
        if tuple(r.fieldnames or ()) != CAMPOS_LOTES:
            raise E2Erro(f"cabeçalho de {caminho.name} não é o esperado")
        return list(r)


def gravar_novo(caminho: Path, dados: bytes) -> None:
    if caminho.exists():
        raise E2Erro(f"{caminho.name} já existe; nada foi gravado")
    tmp = caminho.with_name(caminho.name + ".tmp")
    tmp.write_bytes(dados)
    os.replace(tmp, caminho)


def sha256(dados: bytes) -> str:
    return hashlib.sha256(dados).hexdigest()


def git_estado(raiz: Path) -> tuple[str, bool]:
    def git(*args: str) -> str:
        return subprocess.run(["git", *args], cwd=raiz, capture_output=True,
                              text=True, check=True).stdout.strip()

    return git("rev-parse", "HEAD"), git("status", "--porcelain", "--untracked-files=no") == ""


# ---------------------------------------------------------------- modos
def medir_tempo(fabricas, novo_detector, avaliar, saida: Callable[[str], None]) -> int:
    lotes_completos = {(c.fonte, c.valor, c.n_bits): c.n_lotes for c in celulas()}
    total_s = 0.0
    saida("Medição de tempo (só tempos; o veredito dos lotes não é mostrado)")
    for c in celulas_medir_tempo():
        linhas = rodar_celula(c, fabricas, novo_detector, avaliar, commit="medir-tempo")
        media = statistics.mean(float(l["t_leitura_s"]) + float(l["t_saude_s"]) for l in linhas)
        n_completo = lotes_completos[(c.fonte, c.valor, c.n_bits)]
        total_s += media * n_completo
        saida(f"  {c.fonte:<18} {c.parametro or '-':<10} {texto_valor(c.valor) or '-':<6} "
              f"n={c.n_bits:>9,}  {media:7.3f} s/lote  x {n_completo:>3} lotes")
    n_total = sum(c.n_lotes for c in celulas())
    saida(f"Estimativa da rodada completa: {n_total} lotes, cerca de {total_s / 60:.1f} min")
    return 0


def rodar(raiz: Path, fabricas, novo_detector, avaliar, git, saida) -> int:
    pasta = raiz / "data" / "results"
    p_lotes, p_resumo = pasta / NOME_LOTES, pasta / NOME_RESUMO
    for p in (p_lotes, p_resumo):
        if p.exists():
            raise E2Erro(f"{p.name} já existe; nada foi rodado")
    commit, limpo = git(raiz)
    if not limpo:
        raise E2Erro("árvore com mudanças rastreadas; faça o commit do script antes da rodada")
    grade = celulas()
    esperado = sum(c.n_lotes for c in grade)
    saida(f"E2 sobre o commit {commit[:7]}: {len(grade)} células, {esperado} lotes")
    linhas: list[dict[str, str]] = []
    inicio = time.perf_counter()
    for i, c in enumerate(grade, start=1):
        t0 = time.perf_counter()
        linhas.extend(rodar_celula(c, fabricas, novo_detector, avaliar, commit))
        saida(f"  [{i:>2}/{len(grade)}] {c.fonte} {c.parametro}={texto_valor(c.valor) or '-'} "
              f"n={c.n_bits:,}: {c.n_lotes} lotes em {time.perf_counter() - t0:.1f} s "
              f"(total {(time.perf_counter() - inicio) / 60:.1f} min)")
    if len(linhas) != esperado:
        raise E2Erro(f"{len(linhas)} linhas em vez de {esperado}; nada foi gravado")
    pasta.mkdir(parents=True, exist_ok=True)
    dados_lotes = csv_bytes(CAMPOS_LOTES, linhas)
    gravar_novo(p_lotes, dados_lotes)
    dados_resumo = csv_bytes(CAMPOS_RESUMO, resumir(ler_lotes(p_lotes)))
    gravar_novo(p_resumo, dados_resumo)
    saida(f"{NOME_LOTES}: {sha256(dados_lotes)}")
    saida(f"{NOME_RESUMO}: {sha256(dados_resumo)}")
    return 0


def refazer_resumo(raiz: Path, saida) -> int:
    pasta = raiz / "data" / "results"
    p_lotes, p_resumo = pasta / NOME_LOTES, pasta / NOME_RESUMO
    if not p_lotes.exists():
        raise E2Erro(f"{NOME_LOTES} não existe")
    dados = csv_bytes(CAMPOS_RESUMO, resumir(ler_lotes(p_lotes)))
    if p_resumo.exists():
        if p_resumo.read_bytes() == dados:
            saida(f"{NOME_RESUMO} já existia igual: {sha256(dados)}")
            return 0
        raise E2Erro(f"{NOME_RESUMO} existe e difere do recalculado; nada foi gravado")
    gravar_novo(p_resumo, dados)
    saida(f"{NOME_RESUMO}: {sha256(dados)}")
    return 0


def main(argv: list[str] | None = None, *, raiz: Path = ROOT, fabricas=None,
         saude=None, git=git_estado, saida: Callable[[str], None] = print) -> int:
    ap = argparse.ArgumentParser(description="E2: detecção de fontes defeituosas")
    modo = ap.add_mutually_exclusive_group(required=True)
    modo.add_argument("--medir-tempo", action="store_true")
    modo.add_argument("--rodar", action="store_true")
    modo.add_argument("--resumir", action="store_true")
    args = ap.parse_args(argv)
    try:
        if args.resumir:
            return refazer_resumo(raiz, saida)
        fabricas = fabricas_reais() if fabricas is None else fabricas
        novo_detector, avaliar = saude_real() if saude is None else saude
        if args.medir_tempo:
            return medir_tempo(fabricas, novo_detector, avaliar, saida)
        return rodar(raiz, fabricas, novo_detector, avaliar, git, saida)
    except E2Erro as exc:
        saida(f"RECUSADO: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
