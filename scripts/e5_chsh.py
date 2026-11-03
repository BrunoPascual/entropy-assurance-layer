"""E5 (etapa A, sem QPU): teste CHSH como verificação de sanidade.

Não usa a QPU. Pré-registro (fixado no commit deste script, antes da rodada):
- Circuito: |Phi+> = CX(H x I)|00>; em cada lado, Ry(-theta) e medição em Z, o que mede ao
  longo do ângulo theta no plano X-Z. Ângulos do PROJECT.md: Alice em 0 e pi/2; Bob em pi/4 e
  -pi/4. E = P(iguais) - P(diferentes). S = E(a0,b0) + E(a0,b1) + E(a1,b0) - E(a1,b1).
- Configurações:
    ideal_exato          probabilidades exatas do circuito (Statevector), sem amostragem;
    ideal_amostrado      N_SHOTS amostras multinomiais das probabilidades exatas, por ajuste;
    ruido_fake_kingston  Aer em matriz densidade com o ruído do FakeKingston (eal.sources.noise,
                         leitura assimétrica), no par acoplado escolhido por REGRA_PAR;
    classico_aleatorio   saídas independentes e uniformes, que ignoram os ajustes;
    classico_otimo       a estratégia clássica determinística A(a0)=A(a1)=0, B(b0)=0, B(b1)=1.
- REGRA_PAR: o par acoplado por CZ com a menor soma de erro de CZ e erro médio de leitura dos dois
  qubits; empate desfeito pelo menor par. Cada circuito transpilado tem de ter uma porta de dois
  qubits só (sem SWAP), senão o script recusa.
- Erro-padrão de S numa repetição: raiz da soma de (1 - E^2) / N nos quatro ajustes.
- Critérios (K_SIGMA erros-padrão da média das repetições):
    ideal_exato          |S - 2*raiz(2)| <= 1e-12;
    ideal_amostrado      |S_media - 2*raiz(2)| <= K_SIGMA * dp / raiz(R);
    clássicos            S_media <= 2 + K_SIGMA * dp / raiz(R);
    ruido_fake_kingston  2 < S_media - K * dp/raiz(R) e S_media + K * dp/raiz(R) < 2*raiz(2)
                         (hipótese do assistente; o PROJECT.md só fixa essa faixa para a QPU real).

Uso:
  py -3.12 scripts\\e5_chsh.py --medir-tempo   2 repetições por configuração; só tempos
  py -3.12 scripts\\e5_chsh.py --rodar         grava e5_rodadas.csv e e5_resumo.csv
  py -3.12 scripts\\e5_chsh.py --resumir       refaz e5_resumo.csv a partir de e5_rodadas.csv
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import math
import os
import statistics
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SCHEMA = "e5_rodadas_v1"

# ---------------------------------------------------------------- pré-registro
ANGULOS_A = (0.0, math.pi / 2)
ANGULOS_B = (math.pi / 4, -math.pi / 4)
AJUSTES = ((0, 0), (0, 1), (1, 0), (1, 1))
SINAIS = (1, 1, 1, -1)
N_SHOTS = 4000
REPS = 100
REPS_MEDIR_TEMPO = 2
CONFIGS = ("ideal_exato", "ideal_amostrado", "ruido_fake_kingston", "classico_aleatorio",
           "classico_otimo")
BACKEND_RUIDO = "FakeKingston"
OPT_LEVEL = 1
SEED_TRANSPILER = 2026
K_SIGMA = 3
TOL_EXATO = 1e-12
LIMITE_CLASSICO = 2.0
TSIRELSON = 2 * math.sqrt(2)
CHAVES = ("00", "01", "10", "11")      # cadeias do Qiskit: bit clássico 1 à esquerda
ESPERADO = {
    "ideal_exato": "S = 2*raiz(2) (exato)",
    "ideal_amostrado": "compatível com 2*raiz(2)",
    "ruido_fake_kingston": "entre 2 e 2*raiz(2) (hipótese do assistente)",
    "classico_aleatorio": "S <= 2",
    "classico_otimo": "S <= 2",
}
# -----------------------------------------------------------------------------

NOME_RODADAS, NOME_RESUMO = "e5_rodadas.csv", "e5_resumo.csv"
CAMPOS = (
    "schema", "commit", "configuracao", "repeticao", "semente", "n_shots", "e_a0b0", "e_a0b1",
    "e_a1b0", "e_a1b1", "s", "se_s", "par_fisico", "erro_cz", "erro_leitura_q0",
    "erro_leitura_q1", "calibracao_backend", "n_2q_por_circuito", "t_s",
)
CAMPOS_RESUMO = (
    "configuracao", "esperado", "n_reps", "s_media", "s_dp", "se_media", "s_min", "s_max",
    "frac_s_maior_2", "margem", "criterio_ok",
)


class E5Erro(Exception):
    """Recusa: nada é gravado."""


def circuito(theta_a: float, theta_b: float, medir: bool = True) -> Any:
    from qiskit import QuantumCircuit

    qc = QuantumCircuit(2, 2)
    qc.h(0)
    qc.cx(0, 1)
    qc.ry(-theta_a, 0)
    qc.ry(-theta_b, 1)
    if medir:
        qc.measure([0, 1], [0, 1])
    return qc


def probs_exatas(theta_a: float, theta_b: float) -> np.ndarray:
    from qiskit.quantum_info import Statevector

    p = Statevector(circuito(theta_a, theta_b, medir=False)).probabilities_dict()
    return np.array([float(p.get(k, 0.0)) for k in CHAVES])


def escolher_par(target: Any, leitura: Callable[[int], tuple[float, float]]) -> dict[str, Any]:
    """REGRA_PAR sobre o Target do backend: menor erro de CZ + erro médio de leitura dos dois."""
    if "cz" not in target.operation_names:
        raise E5Erro("o backend não tem a porta cz")
    erros: dict[tuple[int, int], float] = {}
    for qs, props in target["cz"].items():
        if props is None or props.error is None:
            continue
        par = tuple(sorted(qs))
        erros[par] = min(erros.get(par, math.inf), float(props.error))
    if not erros:
        raise E5Erro("nenhum par com erro de cz conhecido")
    melhor = None
    for (a, b), e in sorted(erros.items()):
        ra, rb = (sum(leitura(a)) / 2), (sum(leitura(b)) / 2)
        custo = e + ra + rb
        if melhor is None or custo < melhor["custo"]:
            melhor = {"q0": a, "q1": b, "erro_cz": e, "ro0": ra, "ro1": rb, "custo": custo}
    return melhor


def exigir_uma_porta_2q(circuitos: list[Any]) -> None:
    """Recusa se algum circuito transpilado não tiver exatamente uma porta de dois qubits."""
    n2 = [sum(1 for ins in c.data if ins.operation.num_qubits == 2) for c in circuitos]
    if n2 != [1] * len(circuitos):
        raise E5Erro(f"circuitos transpilados com portas de 2 qubits {n2}; esperado uma cada")


class RuidoReal:
    """Aer com o ruído do FakeKingston (eal.sources.noise) no par escolhido por REGRA_PAR."""

    def __init__(self) -> None:
        from qiskit import transpile
        from qiskit_aer import AerSimulator

        from eal.sources import noise

        bk = noise.load_fake_backend(BACKEND_RUIDO)
        par = escolher_par(bk.target, lambda q: noise.readout_probs(bk, q))
        q0, q1 = par["q0"], par["q1"]
        self.sim = AerSimulator(noise_model=noise.build_noise_model(bk, [q0, q1]),
                                method="density_matrix")
        self.circuitos = [transpile(circuito(ANGULOS_A[i], ANGULOS_B[j]), bk,
                                    initial_layout=[q0, q1], optimization_level=OPT_LEVEL,
                                    seed_transpiler=SEED_TRANSPILER) for i, j in AJUSTES]
        exigir_uma_porta_2q(self.circuitos)
        self.info = {"par_fisico": f"{q0}-{q1}", "erro_cz": repr(par["erro_cz"]),
                     "erro_leitura_q0": repr(par["ro0"]), "erro_leitura_q1": repr(par["ro1"]),
                     "calibracao_backend": noise.calibration_date(bk), "n_2q_por_circuito": "1"}

    def contagens(self, seed: int) -> list[dict[str, int]]:
        r = self.sim.run(self.circuitos, shots=N_SHOTS, seed_simulator=seed).result()
        return [dict(r.get_counts(i)) for i in range(len(AJUSTES))]


@dataclass(frozen=True)
class Motor:
    probs_exatas: Callable[[float, float], np.ndarray]
    preparar_ruido: Callable[[], Any]


def motor_real() -> Motor:
    return Motor(probs_exatas=probs_exatas, preparar_ruido=RuidoReal)


def semente(config: str, rep: int) -> int:
    chave = f"e5|v1|{config}|{rep}".encode("ascii")
    return int.from_bytes(hashlib.sha256(chave).digest()[:4], "big")      # 32 bits (Aer e numpy)


# ---------------------------------------------------------------- correlações e S

def correlacao(cont: dict[str, int], n: int) -> float:
    if set(cont) - set(CHAVES):
        raise E5Erro(f"chaves inesperadas nas contagens: {sorted(cont)}")
    if sum(cont.values()) != n:
        raise E5Erro(f"contagens somam {sum(cont.values())}, esperado {n}")
    iguais = cont.get("00", 0) + cont.get("11", 0)
    return (2 * iguais - n) / n


def correlacao_exata(p: np.ndarray) -> float:
    return float(p[0] + p[3] - p[1] - p[2])


def s_de(es: list[float]) -> float:
    return sum(s * e for s, e in zip(SINAIS, es))


def se_de(es: list[float], n: int) -> float:
    return math.sqrt(sum((1 - e * e) / n for e in es))


def amostrar(rng: np.random.Generator, p: np.ndarray, n: int) -> dict[str, int]:
    return {k: int(c) for k, c in zip(CHAVES, rng.multinomial(n, p))}


def contagens_otimo(n: int) -> list[dict[str, int]]:
    """A(a0)=A(a1)=0, B(b0)=0, B(b1)=1. Chave do Qiskit: 'bitB bitA'."""
    saida = []
    for _, j in AJUSTES:
        b = 0 if j == 0 else 1
        saida.append({f"{b}0": n})
    return saida


# ---------------------------------------------------------------- rodadas

def linha(config: str, rep: int, sem: int | str, n: int | str, es: list[float], se: float,
          info: dict[str, str] | None, t: float, commit: str) -> dict[str, str]:
    info = info or {}
    return {
        "schema": SCHEMA, "commit": commit, "configuracao": config, "repeticao": str(rep),
        "semente": str(sem), "n_shots": str(n),
        **{f"e_a{i}b{j}": repr(float(e)) for (i, j), e in zip(AJUSTES, es)},
        "s": repr(float(s_de(es))), "se_s": repr(float(se)),
        "par_fisico": info.get("par_fisico", ""), "erro_cz": info.get("erro_cz", ""),
        "erro_leitura_q0": info.get("erro_leitura_q0", ""),
        "erro_leitura_q1": info.get("erro_leitura_q1", ""),
        "calibracao_backend": info.get("calibracao_backend", ""),
        "n_2q_por_circuito": info.get("n_2q_por_circuito", ""), "t_s": f"{t:.4f}",
    }


def rodar_config(motor: Motor, config: str, reps: int, commit: str,
                 ruido: Any = None) -> list[dict[str, str]]:
    probs = [motor.probs_exatas(ANGULOS_A[i], ANGULOS_B[j]) for i, j in AJUSTES]
    if config == "ideal_exato":
        t0 = time.perf_counter()
        es = [correlacao_exata(p) for p in probs]
        if abs(s_de(es) - TSIRELSON) > TOL_EXATO:
            raise E5Erro(f"S exato {s_de(es)!r} difere de 2*raiz(2): circuito ou ângulos errados")
        return [linha(config, 0, "", "", es, 0.0, None, time.perf_counter() - t0, commit)]
    saida = []
    for rep in range(reps):
        t0 = time.perf_counter()
        sem = semente(config, rep)
        if config == "ideal_amostrado":
            rng = np.random.default_rng(sem)
            conts = [amostrar(rng, p, N_SHOTS) for p in probs]
        elif config == "classico_aleatorio":
            rng = np.random.default_rng(sem)
            conts = [amostrar(rng, np.full(4, 0.25), N_SHOTS) for _ in AJUSTES]
        elif config == "classico_otimo":
            conts = contagens_otimo(N_SHOTS)
        elif config == "ruido_fake_kingston":
            if ruido is None:
                raise E5Erro("ruído não preparado")
            conts = ruido.contagens(sem)
        else:
            raise E5Erro(f"configuração desconhecida: {config!r}")
        es = [correlacao(c, N_SHOTS) for c in conts]
        info = ruido.info if config == "ruido_fake_kingston" else None
        saida.append(linha(config, rep, sem, N_SHOTS, es, se_de(es, N_SHOTS), info,
                           time.perf_counter() - t0, commit))
    return saida


# ---------------------------------------------------------------- resumo

def avaliar(config: str, media: float, margem: float) -> bool:
    if config == "ideal_exato":
        return abs(media - TSIRELSON) <= TOL_EXATO
    if config == "ideal_amostrado":
        return abs(media - TSIRELSON) <= margem
    if config == "ruido_fake_kingston":
        return media - margem > LIMITE_CLASSICO and media + margem < TSIRELSON
    if config in ("classico_aleatorio", "classico_otimo"):
        return media <= LIMITE_CLASSICO + margem
    raise E5Erro(f"configuração desconhecida: {config!r}")


def resumir(linhas: list[dict[str, str]]) -> list[dict[str, str]]:
    if not linhas:
        raise E5Erro(f"{NOME_RODADAS} sem linhas")
    grupos: dict[str, list[dict[str, str]]] = {}
    for i, l in enumerate(linhas, start=2):
        if l.get("schema") != SCHEMA:
            raise E5Erro(f"linha {i}: schema {l.get('schema')!r}")
        if l.get("configuracao") not in CONFIGS:
            raise E5Erro(f"linha {i}: configuração {l.get('configuracao')!r}")
        grupos.setdefault(l["configuracao"], []).append(l)
    if set(grupos) != set(CONFIGS):
        raise E5Erro(f"faltam configurações: {sorted(set(CONFIGS) - set(grupos))}")
    saida = []
    for config in CONFIGS:
        ls = grupos[config]
        ss = [float(l["s"]) for l in ls]
        media = statistics.fmean(ss)
        dp = statistics.stdev(ss) if len(ss) > 1 else 0.0
        margem = K_SIGMA * dp / math.sqrt(len(ss))
        saida.append({
            "configuracao": config, "esperado": ESPERADO[config], "n_reps": str(len(ss)),
            "s_media": f"{media:.6f}", "s_dp": f"{dp:.6f}",
            "se_media": f"{statistics.fmean(float(l['se_s']) for l in ls):.6f}",
            "s_min": f"{min(ss):.6f}", "s_max": f"{max(ss):.6f}",
            "frac_s_maior_2": f"{sum(s > LIMITE_CLASSICO for s in ss) / len(ss):.4f}",
            "margem": f"{margem:.6f}",
            "criterio_ok": "True" if avaliar(config, media, margem) else "False",
        })
    return saida


# ---------------------------------------------------------------- arquivos

def csv_bytes(campos: tuple[str, ...], linhas: list[dict[str, str]]) -> bytes:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=list(campos), lineterminator="\n", extrasaction="raise")
    w.writeheader()
    w.writerows(linhas)
    return buf.getvalue().encode("utf-8")


def ler_rodadas(caminho: Path) -> list[dict[str, str]]:
    if not caminho.is_file():
        raise E5Erro(f"{caminho.name} não existe")
    with caminho.open(encoding="utf-8", newline="") as f:
        r = csv.DictReader(f)
        if tuple(r.fieldnames or ()) != CAMPOS:
            raise E5Erro(f"cabeçalho de {caminho.name} não é o esperado")
        return list(r)


def gravar_novo(caminho: Path, dados: bytes) -> None:
    if caminho.exists():
        raise E5Erro(f"{caminho.name} já existe; nada foi gravado")
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

def medir_tempo(motor: Motor, saida: Callable[[str], None]) -> int:
    saida("Medição de tempo (só tempos; nenhum S é mostrado)")
    t0 = time.perf_counter()
    ruido = motor.preparar_ruido()
    preparo = time.perf_counter() - t0
    saida(f"  preparo do ruído ({BACKEND_RUIDO}): {preparo:.2f} s")
    total = preparo
    for config in CONFIGS:
        reps = 1 if config == "ideal_exato" else REPS_MEDIR_TEMPO
        ls = rodar_config(motor, config, reps, "medir-tempo", ruido)
        media = statistics.fmean(float(l["t_s"]) for l in ls)
        n = 1 if config == "ideal_exato" else REPS
        total += media * n
        saida(f"  {config:<22} {media:8.3f} s/repetição  x {n:>3}")
    saida(f"Estimativa da rodada completa: cerca de {total / 60:.1f} min")
    return 0


def rodar(raiz: Path, motor: Motor, git, saida) -> int:
    pasta = raiz / "data" / "results"
    p_rod, p_res = pasta / NOME_RODADAS, pasta / NOME_RESUMO
    for p in (p_rod, p_res):
        if p.exists():
            raise E5Erro(f"{p.name} já existe; nada foi rodado")
    commit, limpo = git(raiz)
    if not limpo:
        raise E5Erro("árvore com mudanças rastreadas; faça o commit do script antes da rodada")
    saida(f"E5 (etapa A) sobre o commit {commit[:7]}: {len(CONFIGS)} configurações")
    ruido = motor.preparar_ruido()
    linhas: list[dict[str, str]] = []
    for config in CONFIGS:
        t0 = time.perf_counter()
        linhas += rodar_config(motor, config, REPS, commit, ruido)
        saida(f"  {config}: em {time.perf_counter() - t0:.1f} s")
    esperado = 1 + (len(CONFIGS) - 1) * REPS
    if len(linhas) != esperado:
        raise E5Erro(f"{len(linhas)} linhas em vez de {esperado}; nada foi gravado")
    pasta.mkdir(parents=True, exist_ok=True)
    d_rod = csv_bytes(CAMPOS, linhas)
    gravar_novo(p_rod, d_rod)
    d_res = csv_bytes(CAMPOS_RESUMO, resumir(ler_rodadas(p_rod)))
    gravar_novo(p_res, d_res)
    saida(f"{NOME_RODADAS}: {sha256(d_rod)}")
    saida(f"{NOME_RESUMO}: {sha256(d_res)}")
    return 0


def refazer_resumo(raiz: Path, saida) -> int:
    pasta = raiz / "data" / "results"
    p_res = pasta / NOME_RESUMO
    dados = csv_bytes(CAMPOS_RESUMO, resumir(ler_rodadas(pasta / NOME_RODADAS)))
    if p_res.exists():
        if p_res.read_bytes() == dados:
            saida(f"{NOME_RESUMO} já existia igual: {sha256(dados)}")
            return 0
        raise E5Erro(f"{NOME_RESUMO} existe e difere do recalculado; nada foi gravado")
    gravar_novo(p_res, dados)
    saida(f"{NOME_RESUMO}: {sha256(dados)}")
    return 0


def main(argv: list[str] | None = None, *, raiz: Path = ROOT, motor: Motor | None = None,
         git=git_estado, saida: Callable[[str], None] = print) -> int:
    ap = argparse.ArgumentParser(description="E5 (etapa A): CHSH sem QPU")
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
    except E5Erro as exc:
        saida(f"RECUSADO: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
