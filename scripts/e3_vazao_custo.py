"""E3: vazão e custo por megabit da QPU real, comparados com a fonte `os`.

Não envia nenhum job e não gasta nada: usa os jobs já executados no Open Plan (log de uso,
JSONs dos crus e CSVs de saúde das coletas). O custo é TEÓRICO: segundos de QPU informados
pela API vezes o preço por minuto dos planos pagos da IBM (PRECOS, com a fonte e a data da
consulta). O lado local mede o `run_pipeline` real com a `os`.

Pré-registro (fixado no commit deste script, antes da rodada):
- 1 Mbit = 1.000.000 bits. Bits brutos = shots x qubits. Bits úteis = bits extraídos de lotes
  aprovados pela saúde. Bits úteis hipotéticos = o que o extrator do projeto daria com o H
  estimado do lote, se ele tivesse sido aprovado (a fórmula é conferida contra os lotes da os).
- Ajuste por mínimos quadrados: segundos = fixo + por_shot * shots, sobre todos os jobs.
- Local: N_BITS_LOCAL bits por execução (o tamanho de um job de coleta), 1 aquecimento
  descartado e REPS_LOCAL medidas; mediana, mínimo e máximo do tempo de parede.
- Critério da hipótese "muito mais caro que a os": a razão entre os segundos de QPU por Mbit
  bruto (jobs de coleta) e os segundos de CPU por Mbit bruto da os (mediana) é >= RAZAO_MUITO.

Uso:
  py -3.12 scripts\\e3_vazao_custo.py --medir-tempo   2 execuções locais; só tempos, não grava nada
  py -3.12 scripts\\e3_vazao_custo.py --rodar         grava e3_qpu.csv, e3_local.csv e e3_resumo.csv
  py -3.12 scripts\\e3_vazao_custo.py --resumir       refaz e3_resumo.csv a partir dos outros dois
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import platform
import statistics
import subprocess
import sys
import time
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_EVEN
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SCHEMA_QPU = "e3_qpu_v1"
SCHEMA_LOCAL = "e3_local_v1"

# ---------------------------------------------------------------- pré-registro
PRECOS = (("pay_as_you_go", Decimal("96")), ("flex", Decimal("72")), ("premium", Decimal("48")))
FONTE_PRECO = "https://www.ibm.com/quantum/pricing"
DATA_CONSULTA_PRECO = "2026-11-03"
N_BITS_LOCAL = 1_500_096
REPS_LOCAL = 20
REPS_MEDIR_TEMPO = 2
RAZAO_MUITO = Decimal("10")
CIRCUITO = "hadamard_all_measure"
REP_DELAY_S = 0.00025
SAUDE = {
    "coleta1": "dia6_qpu_vs_sim_lotes.csv",
    "coleta2": "dia6_coleta2_qpu_vs_sim_lotes.csv",
    "coleta3": "dia6_coleta3_qpu_vs_sim_lotes.csv",
}
MBIT = Decimal(1_000_000)
# -----------------------------------------------------------------------------

LOG_USO = Path("data") / "logs" / "qpu_usage.csv"
PASTA_RAW = Path("data") / "raw"
PASTA_RES = Path("data") / "results"
NOME_QPU, NOME_LOCAL, NOME_RESUMO = "e3_qpu.csv", "e3_local.csv", "e3_resumo.csv"

CAMPOS_QPU = (
    "schema", "sessao", "job_id", "arquivo", "shots", "qubits", "n_bits", "quantum_seconds",
    "bits_por_s", "custo_usd_payg", "custo_usd_por_mbit_payg", "circuito", "rep_delay_s",
    "json_sha256", "saude_aprovada", "h_estimada", "bits_uteis", "bits_uteis_hipoteticos",
)
CAMPOS_LOCAL = (
    "schema", "commit", "repeticao", "n_bits", "t_s", "semente_gerada", "bits_extraidos",
    "status_os", "python", "plataforma", "cpus",
)
CAMPOS_RESUMO = ("metrica", "valor", "unidade")


class E3Erro(Exception):
    """Recusa: nada é gravado."""


@dataclass(frozen=True)
class Motor:
    """Peças do eal usadas pelo E3 (injetadas para os testes)."""

    block_output_bits: Callable[..., int]
    extractor_entropy: Callable[[float, float], float]
    n_extrator: int
    epsilon_log2: int
    h_declarada: float
    executar_local: Callable[[int], dict[str, Any]]


def _executar_os(n_bits: int) -> dict[str, Any]:
    from eal.health.replay import ReplayDetector
    from eal.pipeline import run_pipeline
    from eal.sources.os_source import OsSource

    t0 = time.perf_counter()
    r = run_pipeline([OsSource()], OsSource(), mode="keygen", n_bits=n_bits, detector=ReplayDetector())
    t = time.perf_counter() - t0
    return {"t_s": t, "semente_gerada": bool(r.seed_generated),
            "bits_extraidos": sum(int(mi.extraction.n_output_bits) for mi in r.inputs),
            "status_os": r.outcomes[0].status if r.outcomes else ""}


def motor_real() -> Motor:
    from eal.config import H_DECLARED_DEFAULT
    from eal.extract.blocks import EXTRACTOR_EPSILON_LOG2, EXTRACTOR_INPUT_BITS, block_output_bits
    from eal.health.min_entropy import extractor_entropy

    return Motor(block_output_bits=block_output_bits, extractor_entropy=extractor_entropy,
                 n_extrator=int(EXTRACTOR_INPUT_BITS), epsilon_log2=int(EXTRACTOR_EPSILON_LOG2),
                 h_declarada=float(H_DECLARED_DEFAULT), executar_local=_executar_os)


# ---------------------------------------------------------------- formatação

def dec(valor: Any, casas: int = 4) -> str:
    q = Decimal(1).scaleb(-casas)
    return str(Decimal(str(valor)).quantize(q, rounding=ROUND_HALF_EVEN))


def sha256(dados: bytes) -> str:
    return hashlib.sha256(dados).hexdigest()


# ---------------------------------------------------------------- lado da QPU

def ler_log(raiz: Path) -> list[dict[str, Any]]:
    """Um registro por job: pares submitted/final do log de uso."""
    caminho = raiz / LOG_USO
    if not caminho.is_file():
        raise E3Erro(f"log de uso ausente: {caminho}")
    with caminho.open(encoding="utf-8", newline="") as f:
        linhas = list(csv.DictReader(f))
    env: dict[str, dict[str, str]] = {}
    fim: dict[str, dict[str, str]] = {}
    for l in linhas:
        alvo = {"submitted": env, "final": fim}.get(l.get("event", ""))
        if alvo is None:
            raise E3Erro(f"evento desconhecido no log: {l.get('event')!r}")
        if l["job_id"] in alvo:
            raise E3Erro(f"job {l['job_id']} com dois eventos {l['event']}")
        alvo[l["job_id"]] = l
    if set(env) != set(fim):
        raise E3Erro(f"jobs sem par submitted/final: {sorted(set(env) ^ set(fim))}")
    jobs = []
    for jid, s in env.items():
        f = fim[jid]
        if f.get("note") != "status=DONE":
            raise E3Erro(f"job {jid} não terminou: {f.get('note')!r}")
        nota = s.get("note", "")
        if not nota.startswith("session="):
            raise E3Erro(f"job {jid} sem sessão na nota: {nota!r}")
        try:
            seg = Decimal(f["quantum_seconds"])
            shots, qubits = int(s["shots"]), int(s["qubits"])
        except Exception as exc:  # noqa: BLE001
            raise E3Erro(f"job {jid}: número inválido no log") from exc
        if seg <= 0 or shots <= 0 or qubits <= 0:
            raise E3Erro(f"job {jid}: valores não positivos no log")
        jobs.append({"job_id": jid, "sessao": nota[len("session="):], "shots": shots,
                     "qubits": qubits, "quantum_seconds": seg, "arquivo": f["output_file"]})
    if not jobs:
        raise E3Erro("log de uso sem jobs")
    return sorted(jobs, key=lambda j: j["arquivo"])


def conferir_cru(raiz: Path, job: dict[str, Any]) -> tuple[int, str]:
    """Confere o JSON do cru contra o log; devolve (n_bits, sha256 do JSON)."""
    arq = job["arquivo"]
    if not arq.endswith(".npy"):
        raise E3Erro(f"arquivo de saída inesperado: {arq!r}")
    p = raiz / PASTA_RAW / (arq[:-4] + ".json")
    if not p.is_file():
        raise E3Erro(f"JSON do cru ausente: {p}")
    dados = p.read_bytes()
    m = json.loads(dados.decode("utf-8"))
    par = m.get("params", {})
    n_bits = int(m.get("n_bits", -1))
    if par.get("job_id") != job["job_id"]:
        raise E3Erro(f"{p.name}: job_id {par.get('job_id')!r} difere do log")
    if int(par.get("shots", -1)) != job["shots"]:
        raise E3Erro(f"{p.name}: shots difere do log")
    if n_bits != job["shots"] * job["qubits"]:
        raise E3Erro(f"{p.name}: n_bits {n_bits} difere de shots x qubits")
    if par.get("circuit") != CIRCUITO:
        raise E3Erro(f"{p.name}: circuito {par.get('circuit')!r}")
    if float(par.get("rep_delay_seconds", -1)) != REP_DELAY_S:
        raise E3Erro(f"{p.name}: rep_delay {par.get('rep_delay_seconds')!r}")
    return n_bits, sha256(dados)


def bits_hipoteticos(motor: Motor, n_input: int, h_estimada: float) -> int:
    h_usada = motor.extractor_entropy(motor.h_declarada, h_estimada)
    m = motor.block_output_bits(h_usada, motor.n_extrator, motor.epsilon_log2)
    return (n_input // motor.n_extrator) * int(m)


def ler_saude(raiz: Path, motor: Motor, sessao: str, n_input: int) -> list[dict[str, str]]:
    """Linhas qpu_real da sessão (por lote); confere a fórmula do extrator nos lotes da os."""
    p = raiz / PASTA_RES / SAUDE[sessao]
    if not p.is_file():
        raise E3Erro(f"CSV de saúde ausente: {p}")
    with p.open(encoding="utf-8", newline="") as f:
        linhas = list(csv.DictReader(f))
    for l in linhas:
        if l.get("fonte") == "os" and l.get("saude_approved") == "True":
            esperado = bits_hipoteticos(motor, n_input, float(l["saude_h_estimated"]))
            if esperado != int(l["ext_n_output_bits"]):
                raise E3Erro(f"{p.name}: a fórmula do extrator dá {esperado} bits para a os, "
                             f"o CSV registra {l['ext_n_output_bits']}")
    qpu = sorted((l for l in linhas if l.get("fonte") == "qpu_real"), key=lambda l: int(l["lote"]))
    if not qpu:
        raise E3Erro(f"{p.name}: sem linhas qpu_real")
    if not any(l.get("fonte") == "os" and l.get("saude_approved") == "True" for l in linhas):
        raise E3Erro(f"{p.name}: sem lote aprovado da os para conferir a fórmula do extrator")
    return qpu


def linhas_qpu(raiz: Path, motor: Motor) -> list[dict[str, str]]:
    jobs = ler_log(raiz)
    for j in jobs:
        j["n_bits"], j["json_sha256"] = conferir_cru(raiz, j)
    por_sessao: dict[str, list[dict[str, Any]]] = {}
    for j in jobs:
        por_sessao.setdefault(j["sessao"], []).append(j)
    for sessao, js in por_sessao.items():
        if sessao not in SAUDE:
            continue
        sizes = {j["n_bits"] for j in js}
        if len(sizes) != 1:
            raise E3Erro(f"{sessao}: lotes de tamanhos diferentes")
        saude = ler_saude(raiz, motor, sessao, sizes.pop())
        if len(saude) != len(js):
            raise E3Erro(f"{sessao}: {len(saude)} lotes qpu_real na saúde para {len(js)} jobs")
        for j, s in zip(js, saude):           # lote k da saúde = k-ésimo arquivo da sessão
            j["saude"] = s
    preco_s = PRECOS[0][1] / 60
    saida = []
    for j in jobs:
        seg = j["quantum_seconds"]
        custo = seg * preco_s
        s = j.get("saude")
        aprovada = "" if s is None else s["saude_approved"]
        if aprovada not in ("", "True", "False"):
            raise E3Erro(f"{j['job_id']}: saude_approved = {aprovada!r}")
        h = "" if s is None else s["saude_h_estimated"]
        uteis = "" if s is None else str(int(s["ext_n_output_bits"]) if aprovada == "True" else 0)
        hip = "" if s is None else str(bits_hipoteticos(motor, j["n_bits"], float(h)))
        saida.append({
            "schema": SCHEMA_QPU, "sessao": j["sessao"], "job_id": j["job_id"],
            "arquivo": j["arquivo"], "shots": str(j["shots"]), "qubits": str(j["qubits"]),
            "n_bits": str(j["n_bits"]), "quantum_seconds": str(seg),
            "bits_por_s": dec(Decimal(j["n_bits"]) / seg),
            "custo_usd_payg": dec(custo), "custo_usd_por_mbit_payg": dec(custo / (j["n_bits"] / MBIT)),
            "circuito": CIRCUITO, "rep_delay_s": repr(REP_DELAY_S), "json_sha256": j["json_sha256"],
            "saude_aprovada": aprovada, "h_estimada": h, "bits_uteis": uteis,
            "bits_uteis_hipoteticos": hip,
        })
    return saida


# ---------------------------------------------------------------- lado local

def linhas_local(motor: Motor, reps: int, commit: str) -> list[dict[str, str]]:
    motor.executar_local(N_BITS_LOCAL)                        # aquecimento, descartado
    saida = []
    for r in range(reps):
        m = motor.executar_local(N_BITS_LOCAL)
        if not m["semente_gerada"] or int(m["bits_extraidos"]) <= 0:
            raise E3Erro(f"execução local {r} sem semente ou sem bits extraídos ({m['status_os']})")
        saida.append({
            "schema": SCHEMA_LOCAL, "commit": commit, "repeticao": str(r),
            "n_bits": str(N_BITS_LOCAL), "t_s": f"{float(m['t_s']):.6f}",
            "semente_gerada": "True", "bits_extraidos": str(int(m["bits_extraidos"])),
            "status_os": str(m["status_os"]), "python": platform.python_version(),
            "plataforma": platform.platform(), "cpus": str(os.cpu_count()),
        })
    return saida


# ---------------------------------------------------------------- resumo

def ajuste(xs: list[Decimal], ys: list[Decimal]) -> tuple[Decimal, Decimal]:
    n = Decimal(len(xs))
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx == 0:
        raise E3Erro("ajuste impossível: todos os jobs têm o mesmo número de shots")
    b = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
    return my - b * mx, b


def resumir(qpu: list[dict[str, str]], local: list[dict[str, str]]) -> list[dict[str, str]]:
    if not qpu or not local:
        raise E3Erro("resumo sem linhas da QPU ou locais")
    for l in qpu:
        if l.get("schema") != SCHEMA_QPU:
            raise E3Erro(f"schema da QPU {l.get('schema')!r}")
    for l in local:
        if l.get("schema") != SCHEMA_LOCAL:
            raise E3Erro(f"schema local {l.get('schema')!r}")
    out: list[dict[str, str]] = []

    def put(metrica: str, valor: str, unidade: str) -> None:
        out.append({"metrica": metrica, "valor": valor, "unidade": unidade})

    seg = [Decimal(l["quantum_seconds"]) for l in qpu]
    bits = [Decimal(l["n_bits"]) for l in qpu]
    put("preco_fonte", FONTE_PRECO, "url")
    put("preco_data_consulta", DATA_CONSULTA_PRECO, "data")
    put("qpu_jobs", str(len(qpu)), "jobs")
    put("qpu_segundos", str(sum(seg)), "s")
    put("qpu_bits_brutos", str(int(sum(bits))), "bits")
    for plano, por_min in PRECOS:
        put(f"qpu_custo_{plano}", dec(sum(seg) * por_min / 60, 2), "USD")
    col = [l for l in qpu if l["sessao"].startswith("coleta")]
    if not col:
        raise E3Erro("nenhum job de coleta no log")
    c_seg = sum(Decimal(l["quantum_seconds"]) for l in col)
    c_bits = sum(Decimal(l["n_bits"]) for l in col)
    c_mbit = c_bits / MBIT
    put("coleta_jobs", str(len(col)), "jobs")
    put("coleta_segundos", str(c_seg), "s")
    put("coleta_bits_brutos", str(int(c_bits)), "bits")
    put("coleta_bits_por_s", dec(c_bits / c_seg), "bits/s")
    put("coleta_s_por_mbit_bruto", dec(c_seg / c_mbit), "s/Mbit")
    for plano, por_min in PRECOS:
        put(f"coleta_custo_por_mbit_bruto_{plano}", dec(c_seg * por_min / 60 / c_mbit), "USD/Mbit")
    a, b = ajuste([Decimal(l["shots"]) for l in qpu], seg)
    qubits = {int(l["qubits"]) for l in qpu}
    if len(qubits) != 1:
        raise E3Erro("jobs com números de qubits diferentes")
    q = Decimal(qubits.pop())
    put("ajuste_fixo_s", dec(a), "s/job")
    put("ajuste_por_shot_s", dec(b, 8), "s/shot")
    put("ajuste_custo_marginal_por_mbit_pay_as_you_go", dec(b / q * MBIT * PRECOS[0][1] / 60), "USD/Mbit")
    uteis = [l for l in col if l["bits_uteis"] != ""]
    if len(uteis) != len(col):
        raise E3Erro("job de coleta sem dado de saúde")
    u_bits = sum(int(l["bits_uteis"]) for l in uteis)
    put("coleta_lotes_aprovados", str(sum(l["saude_aprovada"] == "True" for l in col)), "lotes")
    put("coleta_bits_uteis", str(u_bits), "bits")
    custo_payg = c_seg * PRECOS[0][1] / 60
    put("coleta_custo_por_mbit_util_pay_as_you_go",
        dec(custo_payg / (Decimal(u_bits) / MBIT)) if u_bits else "indefinido", "USD/Mbit")
    h_bits = sum(int(l["bits_uteis_hipoteticos"]) for l in col)
    put("coleta_bits_uteis_hipoteticos", str(h_bits), "bits")
    put("coleta_custo_por_mbit_util_hipotetico_pay_as_you_go",
        dec(custo_payg / (Decimal(h_bits) / MBIT)) if h_bits else "indefinido", "USD/Mbit")
    tempos = [Decimal(l["t_s"]) for l in local]
    med = Decimal(str(statistics.median(tempos)))
    n_local = {int(l["n_bits"]) for l in local}
    if len(n_local) != 1:
        raise E3Erro("execuções locais com tamanhos diferentes")
    l_mbit = Decimal(n_local.pop()) / MBIT
    put("local_execucoes", str(len(local)), "execuções")
    put("local_t_mediana_s", dec(med, 6), "s")
    put("local_t_min_s", dec(min(tempos), 6), "s")
    put("local_t_max_s", dec(max(tempos), 6), "s")
    put("local_s_por_mbit_bruto", dec(med / l_mbit, 6), "s/Mbit")
    put("local_bits_por_s", dec(l_mbit * MBIT / med), "bits/s")
    put("local_bits_extraidos_mediana",
        str(int(statistics.median(int(l["bits_extraidos"]) for l in local))), "bits")
    razao = (c_seg / c_mbit) / (med / l_mbit)
    put("razao_s_por_mbit_qpu_sobre_os", dec(razao, 2), "vezes")
    put("criterio_limiar", str(RAZAO_MUITO), "vezes")
    put("criterio_muito_mais_caro", "True" if razao >= RAZAO_MUITO else "False", "booleano")
    return out


# ---------------------------------------------------------------- arquivos

def csv_bytes(campos: tuple[str, ...], linhas: list[dict[str, str]]) -> bytes:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=list(campos), lineterminator="\n", extrasaction="raise")
    w.writeheader()
    w.writerows(linhas)
    return buf.getvalue().encode("utf-8")


def ler_csv(caminho: Path, campos: tuple[str, ...]) -> list[dict[str, str]]:
    if not caminho.is_file():
        raise E3Erro(f"{caminho.name} não existe")
    with caminho.open(encoding="utf-8", newline="") as f:
        r = csv.DictReader(f)
        if tuple(r.fieldnames or ()) != campos:
            raise E3Erro(f"cabeçalho de {caminho.name} não é o esperado")
        return list(r)


def gravar_novo(caminho: Path, dados: bytes) -> None:
    if caminho.exists():
        raise E3Erro(f"{caminho.name} já existe; nada foi gravado")
    tmp = caminho.with_name(caminho.name + ".tmp")
    tmp.write_bytes(dados)
    os.replace(tmp, caminho)


def git_estado(raiz: Path) -> tuple[str, bool]:
    def git(*args: str) -> str:
        return subprocess.run(["git", *args], cwd=raiz, capture_output=True,
                              text=True, check=True).stdout.strip()

    return git("rev-parse", "HEAD"), git("status", "--porcelain", "--untracked-files=no") == ""


# ---------------------------------------------------------------- modos

def medir_tempo(motor: Motor, saida: Callable[[str], None]) -> int:
    saida("Medição de tempo local (só tempos; nada é gravado e nenhuma razão é calculada)")
    motor.executar_local(N_BITS_LOCAL)
    tempos = [float(motor.executar_local(N_BITS_LOCAL)["t_s"]) for _ in range(REPS_MEDIR_TEMPO)]
    media = statistics.mean(tempos)
    saida(f"  execução de {N_BITS_LOCAL:,} bits: {media:.3f} s em média ({REPS_MEDIR_TEMPO} execuções)")
    saida(f"Estimativa da rodada: {REPS_LOCAL + 1} execuções, cerca de "
          f"{media * (REPS_LOCAL + 1) / 60:.1f} min")
    return 0


def rodar(raiz: Path, motor: Motor, git, saida) -> int:
    pasta = raiz / PASTA_RES
    caminhos = [pasta / n for n in (NOME_QPU, NOME_LOCAL, NOME_RESUMO)]
    for p in caminhos:
        if p.exists():
            raise E3Erro(f"{p.name} já existe; nada foi rodado")
    commit, limpo = git(raiz)
    if not limpo:
        raise E3Erro("árvore com mudanças rastreadas; faça o commit do script antes da rodada")
    qpu = linhas_qpu(raiz, motor)
    saida(f"E3 sobre o commit {commit[:7]}: {len(qpu)} jobs da QPU lidos; "
          f"{REPS_LOCAL} execuções locais (+1 aquecimento)")
    t0 = time.perf_counter()
    local = linhas_local(motor, REPS_LOCAL, commit)
    saida(f"  execuções locais em {time.perf_counter() - t0:.1f} s")
    d_qpu, d_local = csv_bytes(CAMPOS_QPU, qpu), csv_bytes(CAMPOS_LOCAL, local)
    d_res = csv_bytes(CAMPOS_RESUMO, resumir(qpu, local))
    pasta.mkdir(parents=True, exist_ok=True)
    for p, d in zip(caminhos, (d_qpu, d_local, d_res)):
        gravar_novo(p, d)
        saida(f"{p.name}: {sha256(d)}")
    return 0


def refazer_resumo(raiz: Path, saida) -> int:
    pasta = raiz / PASTA_RES
    qpu = ler_csv(pasta / NOME_QPU, CAMPOS_QPU)
    local = ler_csv(pasta / NOME_LOCAL, CAMPOS_LOCAL)
    dados = csv_bytes(CAMPOS_RESUMO, resumir(qpu, local))
    p = pasta / NOME_RESUMO
    if p.exists():
        if p.read_bytes() == dados:
            saida(f"{NOME_RESUMO} já existia igual: {sha256(dados)}")
            return 0
        raise E3Erro(f"{NOME_RESUMO} existe e difere do recalculado; nada foi gravado")
    gravar_novo(p, dados)
    saida(f"{NOME_RESUMO}: {sha256(dados)}")
    return 0


def main(argv: list[str] | None = None, *, raiz: Path = ROOT, motor: Motor | None = None,
         git=git_estado, saida: Callable[[str], None] = print) -> int:
    ap = argparse.ArgumentParser(description="E3: vazão e custo teórico por megabit")
    modo = ap.add_mutually_exclusive_group(required=True)
    modo.add_argument("--medir-tempo", action="store_true")
    modo.add_argument("--rodar", action="store_true")
    modo.add_argument("--resumir", action="store_true")
    args = ap.parse_args(argv)
    try:
        if args.resumir:
            return refazer_resumo(raiz, saida)
        motor = motor_real() if motor is None else motor
        if args.medir_tempo:
            return medir_tempo(motor, saida)
        return rodar(raiz, motor, git, saida)
    except E3Erro as exc:
        saida(f"RECUSADO: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
