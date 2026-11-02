"""E4: resiliência da mistura (XOR contra o hash do mixer real) sob falha, viés e adversário.

Pré-registro: a grade (CENARIOS, KS_FORCA, N_SEMENTES, L_BITS, REPS, REPS_FORCA) e as
definições abaixo ficam fixadas no commit deste script, antes da rodada completa.

Modelo:
- Duas fontes por semente. A honesta (`os`, local, não simulada) é uniforme e independente.
  A segunda (`qpu_remota`, remota, não simulada) muda por cenário. Cada uma contribui com
  L_BITS bits extraídos por semente. As duas entram declaradas como aprovadas: o E4 isola a
  combinação, como se um defeito tivesse passado pelos testes de saúde (a detecção é o E2).
- hash: o `mix` real (eal/mix/mixer.py), modo keygen, com toda a política e as checagens.
- xor: existe só neste script, como comparador: XOR dos primeiros 512 bits de cada fonte.
- adv_alvo: a segunda fonte vê a honesta e devolve honesta XOR alvo nos 512 primeiros bits,
  com um alvo pseudoaleatório por semente que só ela conhece.
- adv_forca (só hash): a segunda fonte vê a honesta, testa candidatos e fica com o primeiro
  que deixa os k primeiros bits da semente em zero. O caminho rápido usa hashlib com a mesma
  codificação do mixer; cada semente escolhida é conferida contra o `mix` real.
- Uma sequência = N_SEMENTES sementes de 512 bits. Aprovada = os 3 testes estatísticos do
  pipeline (run_stats_tests) passam sobre as sementes concatenadas.
- O hash e o xor de um mesmo cenário e repetição usam os mesmos bits de entrada.

Uso:
  py -3.12 scripts\\e4_mistura.py --medir-tempo   2 sequências por célula; só tempos
  py -3.12 scripts\\e4_mistura.py --rodar         grade completa; grava e4_sequencias.csv e e4_resumo.csv
  py -3.12 scripts\\e4_mistura.py --resumir       refaz e4_resumo.csv a partir de e4_sequencias.csv
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
from types import SimpleNamespace
from typing import Any, Callable

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SCHEMA = "e4_sequencias_v1"

# ---------------------------------------------------------------- pré-registro
N_SEMENTES = 2000
L_BITS = 2048
SEED_BITS = 512
P_ENVIESADA = 0.55
TRAVA_RUN, TRAVA_JANELA = 64, 1024
ID_HONESTA, ID_SEGUNDA = "os", "qpu_remota"
MODO = "keygen"
CENARIOS = ("base_boa", "enviesada", "travada", "constante", "copia", "adv_alvo", "sem_fonte_boa")
COMBINADORES = ("hash", "xor")
KS_FORCA = (1, 4, 8, 12)
REPS = 100
REPS_FORCA = 10
REPS_MEDIR_TEMPO = 2
LIMITE_TENTATIVAS = 64          # o adversário testa até 64 * 2**k candidatos por semente
Z_POSICAO = 5.0                 # posição de bit com |z| acima disto conta como enviesada
ESPERADO = {                    # resultado esperado pelo modelo, por (cenário, combinador)
    ("base_boa", "hash"): "segura", ("base_boa", "xor"): "segura",
    ("enviesada", "hash"): "segura", ("enviesada", "xor"): "segura",
    ("travada", "hash"): "segura", ("travada", "xor"): "segura",
    ("constante", "hash"): "segura", ("constante", "xor"): "segura",
    ("copia", "hash"): "sem_semente", ("copia", "xor"): "insegura",
    ("adv_alvo", "hash"): "segura", ("adv_alvo", "xor"): "insegura",
    ("sem_fonte_boa", "hash"): "insegura", ("sem_fonte_boa", "xor"): "insegura",
    ("adv_forca", "hash"): "k_bits",
}
# -----------------------------------------------------------------------------

NOME_SEQ = "e4_sequencias.csv"
NOME_RESUMO = "e4_resumo.csv"

CAMPOS_SEQ = (
    "schema", "commit", "cenario", "combinador", "k", "repeticao", "semente", "esperado",
    "n_sementes", "n_recusadas", "aprovada", "p_monobit", "p_block", "p_runs", "n_distintas",
    "n_alvo", "max_abs_z", "n_pos_z5", "n_falhas_forca", "t_s",
)
CAMPOS_RESUMO = (
    "cenario", "combinador", "k", "esperado", "n_seq", "n_seq_completas", "n_aprovadas",
    "taxa_aprovacao", "ic95_inf", "ic95_sup", "sementes_total", "recusadas_total", "frac_alvo",
    "distintas_min", "distintas_max", "max_abs_z_max", "pos_z5_min", "pos_z5_max",
    "falhas_forca_total", "t_seq_mediana_s",
)


class E4Erro(Exception):
    """Recusa: nada é gravado."""


@dataclass(frozen=True)
class Motor:
    """As peças reais do eal que o E4 usa (injetadas para os testes)."""

    mix: Callable[..., Any]
    MixInput: Any
    ExtractionResult: Any
    MixPolicyError: type
    hash_bits: Callable[[np.ndarray], str]
    run_stats_tests: Callable[[np.ndarray], Any]
    mix_domain: bytes


def motor_real() -> Motor:
    from eal.config import MIX_DOMAIN
    from eal.extract.blocks import ExtractionResult, hash_bits
    from eal.health.stats_tests import run_stats_tests
    from eal.mix.mixer import MixInput, MixPolicyError, mix

    return Motor(mix=mix, MixInput=MixInput, ExtractionResult=ExtractionResult,
                 MixPolicyError=MixPolicyError, hash_bits=hash_bits,
                 run_stats_tests=run_stats_tests, mix_domain=MIX_DOMAIN)


@dataclass(frozen=True)
class Celula:
    cenario: str
    combinador: str
    k: int | None
    reps: int

    @property
    def esperado(self) -> str:
        return ESPERADO[(self.cenario, self.combinador)]


def celulas(reps: int | None = None, reps_forca: int | None = None) -> list[Celula]:
    reps = REPS if reps is None else reps
    reps_forca = REPS_FORCA if reps_forca is None else reps_forca
    saida = [Celula(c, comb, None, reps) for c in CENARIOS for comb in COMBINADORES]
    saida += [Celula("adv_forca", "hash", k, reps_forca) for k in KS_FORCA]
    return saida


def semente(cenario: str, k: int | None, repeticao: int) -> int:
    """64 bits, determinística; não depende do combinador (hash e xor usam as mesmas entradas)."""
    chave = f"e4|v1|{cenario}|{'' if k is None else k}|{repeticao}"
    return int.from_bytes(hashlib.sha256(chave.encode("ascii")).digest()[:8], "big")


# ---------------------------------------------------------------- entradas

def gerar_entradas(cenario: str, rng: np.random.Generator, n: int
                   ) -> tuple[np.ndarray, np.ndarray | None, np.ndarray | None]:
    """(honesta, segunda, alvos). Matrizes n x L_BITS uint8; alvos n x SEED_BITS ou None."""
    H = rng.integers(0, 2, size=(n, L_BITS), dtype=np.uint8)
    alvos = None
    if cenario == "base_boa":
        S = rng.integers(0, 2, size=(n, L_BITS), dtype=np.uint8)
    elif cenario == "enviesada":
        S = (rng.random((n, L_BITS)) < P_ENVIESADA).astype(np.uint8)
    elif cenario == "travada":
        S = rng.integers(0, 2, size=(n, L_BITS), dtype=np.uint8)
        for inicio in range(0, L_BITS - TRAVA_RUN + 1, TRAVA_JANELA):
            offs = rng.integers(0, TRAVA_JANELA - TRAVA_RUN + 1, size=n)
            vals = rng.integers(0, 2, size=n, dtype=np.uint8)
            for i in range(n):
                a = inicio + int(offs[i])
                S[i, a:a + TRAVA_RUN] = vals[i]
    elif cenario == "constante":
        S = np.zeros((n, L_BITS), dtype=np.uint8)
    elif cenario == "copia":
        S = H.copy()
    elif cenario == "adv_alvo":
        alvos = rng.integers(0, 2, size=(n, SEED_BITS), dtype=np.uint8)
        S = H.copy()
        S[:, :SEED_BITS] ^= alvos
    elif cenario == "sem_fonte_boa":
        H = np.zeros((n, L_BITS), dtype=np.uint8)
        S = np.ones((n, L_BITS), dtype=np.uint8)
    elif cenario == "adv_forca":
        S = None
    else:
        raise E4Erro(f"cenário desconhecido: {cenario!r}")
    return H, S, alvos


# ---------------------------------------------------------------- combinadores

def combinar_xor(H: np.ndarray, S: np.ndarray) -> np.ndarray:
    """Sementes n x 64 bytes: XOR dos primeiros SEED_BITS bits de cada fonte."""
    return np.packbits(H[:, :SEED_BITS] ^ S[:, :SEED_BITS], axis=1)


def contribuicao(motor: Motor, sid: str, bits: np.ndarray, local: bool) -> Any:
    """MixInput consistente: relatório (aprovado), extração e hash do mesmo lote fictício."""
    bits = np.ascontiguousarray(bits, dtype=np.uint8)
    ih = motor.hash_bits(bits)
    bid = f"e4-{sid}-{ih[:16]}"
    rel = SimpleNamespace(batch_id=bid, source_id=sid, n_bits=int(bits.size), approved=True,
                          reasons=())
    ext = motor.ExtractionResult(
        extractor_type="e4_modelo", guarantee="nenhuma (modelo do E4)", n=int(bits.size),
        m=int(bits.size), h_used=1.0, epsilon_log2=-64, n_input_bits=int(bits.size), n_blocks=1,
        discarded_bits=0, bits=bits, input_hash=ih)
    return motor.MixInput(source_id=sid, batch_id=bid, input_hash=ih, is_local=local,
                          is_simulated=False, report=rel, extraction=ext)


def semente_mix(motor: Motor, h: np.ndarray, s: np.ndarray) -> bytes:
    entradas = [contribuicao(motor, ID_HONESTA, h, True), contribuicao(motor, ID_SEGUNDA, s, False)]
    return bytes(motor.mix(entradas, mode=MODO).seed)


def combinar_hash(motor: Motor, H: np.ndarray, S: np.ndarray) -> tuple[np.ndarray, int]:
    """Sementes aceitas (m x 64) e o número de recusas da política (MixPolicyError)."""
    aceitas: list[bytes] = []
    recusas = 0
    for i in range(H.shape[0]):
        try:
            aceitas.append(semente_mix(motor, H[i], S[i]))
        except motor.MixPolicyError:
            recusas += 1
    return _matriz(aceitas), recusas


def forcar(motor: Motor, H: np.ndarray, k: int) -> tuple[np.ndarray, int]:
    """Adversário que vê a honesta e força os k primeiros bits da semente em zero."""
    if not 1 <= k <= 64:
        raise E4Erro(f"k fora de 1..64: {k}")
    if not ID_HONESTA < ID_SEGUNDA:
        raise E4Erro("a segunda fonte precisa vir depois da honesta na ordem do mixer")
    sid_h, sid_s = ID_HONESTA.encode("utf-8"), ID_SEGUNDA.encode("utf-8")
    cab = len(sid_s).to_bytes(8, "big") + sid_s + L_BITS.to_bytes(8, "big")
    resto = bytes(L_BITS // 8 - 8)
    limite = max(1, int(LIMITE_TENTATIVAS * 2 ** k))
    sementes: list[bytes] = []
    falhas = 0
    for i in range(H.shape[0]):
        h0 = hashlib.sha3_512(motor.mix_domain)
        h0.update(len(sid_h).to_bytes(8, "big") + sid_h + L_BITS.to_bytes(8, "big"))
        h0.update(np.packbits(H[i]).tobytes())
        achou = False
        for j in range(limite):
            cand = j.to_bytes(8, "big") + resto
            h = h0.copy()
            h.update(cab)
            h.update(cand)
            d = h.digest()
            if int.from_bytes(d[:8], "big") >> (64 - k) == 0:
                achou = True
                break
        falhas += not achou
        real = semente_mix(motor, H[i], np.unpackbits(np.frombuffer(cand, dtype=np.uint8)))
        if real != d:
            raise E4Erro("o caminho rápido do adversário difere do mix real")
        sementes.append(real)
    return _matriz(sementes), falhas


def _matriz(sementes: list[bytes]) -> np.ndarray:
    if not sementes:
        return np.zeros((0, SEED_BITS // 8), dtype=np.uint8)
    return np.frombuffer(b"".join(sementes), dtype=np.uint8).reshape(len(sementes), -1).copy()


# ---------------------------------------------------------------- métricas

def prefixo_zero(sementes: np.ndarray, k: int) -> np.ndarray:
    bits = np.unpackbits(sementes, axis=1)[:, :k]
    return ~bits.any(axis=1)


def avaliar(motor: Motor, sementes: np.ndarray, n: int) -> dict[str, str]:
    m = int(sementes.shape[0])
    out = {"n_sementes": str(m), "aprovada": "", "p_monobit": "", "p_block": "", "p_runs": "",
           "n_distintas": str(len({row.tobytes() for row in sementes})),
           "max_abs_z": "", "n_pos_z5": ""}
    if m == 0:
        return out
    bits = np.unpackbits(sementes, axis=1)
    z = (bits.sum(axis=0) - m / 2) / math.sqrt(m / 4)
    out["max_abs_z"] = f"{float(np.abs(z).max()):.4f}"
    out["n_pos_z5"] = str(int((np.abs(z) > Z_POSICAO).sum()))
    if m == n:
        r = motor.run_stats_tests(np.ascontiguousarray(bits.reshape(-1)))
        if r.inconclusive:
            raise E4Erro("testes estatísticos inconclusivos: sequência curta demais")
        out["aprovada"] = "True" if bool(r.passed) else "False"
        out["p_monobit"] = repr(float(r.monobit.p_value))
        out["p_block"] = repr(float(r.block_frequency.p_value))
        out["p_runs"] = repr(float(r.runs.p_value))
    return out


def rodar_sequencia(motor: Motor, c: Celula, rep: int, commit: str) -> dict[str, str]:
    t0 = time.perf_counter()
    sem = semente(c.cenario, c.k, rep)
    rng = np.random.default_rng(sem)
    H, S, alvos = gerar_entradas(c.cenario, rng, N_SEMENTES)
    falhas = ""
    if c.cenario == "adv_forca":
        sementes, f = forcar(motor, H, c.k)
        recusas, falhas = 0, str(f)
        n_alvo = str(int(prefixo_zero(sementes, c.k).sum()))
    elif c.combinador == "xor":
        sementes, recusas = combinar_xor(H, S), 0
    elif c.combinador == "hash":
        sementes, recusas = combinar_hash(motor, H, S)
    else:
        raise E4Erro(f"combinador desconhecido: {c.combinador!r}")
    if c.cenario == "adv_alvo":
        if sementes.shape[0] == N_SEMENTES:
            n_alvo = str(int((sementes == np.packbits(alvos, axis=1)).all(axis=1).sum()))
        else:
            raise E4Erro("adv_alvo: sementes recusadas, comparação com o alvo impossível")
    elif c.cenario != "adv_forca":
        n_alvo = ""
    linha = {"schema": SCHEMA, "commit": commit, "cenario": c.cenario, "combinador": c.combinador,
             "k": "" if c.k is None else str(c.k), "repeticao": str(rep), "semente": str(sem),
             "esperado": c.esperado, "n_recusadas": str(recusas), "n_alvo": n_alvo,
             "n_falhas_forca": falhas}
    linha.update(avaliar(motor, sementes, N_SEMENTES))
    linha["t_s"] = f"{time.perf_counter() - t0:.4f}"
    return {k: linha[k] for k in CAMPOS_SEQ}


# ---------------------------------------------------------------- resumo

def clopper_pearson(k: int, n: int, conf: float = 0.95) -> tuple[float, float]:
    from scipy.stats import beta

    if n <= 0 or not 0 <= k <= n:
        raise E4Erro(f"contagem inválida: k={k}, n={n}")
    a = 1.0 - conf
    inf = 0.0 if k == 0 else float(beta.ppf(a / 2, k, n - k + 1))
    sup = 1.0 if k == n else float(beta.ppf(1 - a / 2, k + 1, n - k))
    return inf, sup


def validar_seq(linhas: list[dict[str, str]]) -> None:
    if not linhas:
        raise E4Erro(f"{NOME_SEQ} sem linhas")
    for i, l in enumerate(linhas, start=2):
        if l.get("schema") != SCHEMA:
            raise E4Erro(f"linha {i}: schema {l.get('schema')!r}")
        if l.get("aprovada") not in ("True", "False", ""):
            raise E4Erro(f"linha {i}: aprovada = {l.get('aprovada')!r}")


def resumir(linhas: list[dict[str, str]]) -> list[dict[str, str]]:
    validar_seq(linhas)
    grupos: dict[tuple[str, str, str], list[dict[str, str]]] = {}
    for l in linhas:
        grupos.setdefault((l["cenario"], l["combinador"], l["k"]), []).append(l)
    saida = []
    for (cen, comb, k), ls in grupos.items():
        completas = [l for l in ls if l["aprovada"] != ""]
        aprov = sum(l["aprovada"] == "True" for l in completas)
        if completas:
            inf, sup = clopper_pearson(aprov, len(completas))
            taxa, ic_i, ic_s = f"{aprov / len(completas):.4f}", f"{inf:.4f}", f"{sup:.4f}"
        else:
            taxa = ic_i = ic_s = ""
        sem_total = sum(int(l["n_sementes"]) for l in ls)
        alvos = [l for l in ls if l["n_alvo"] != ""]
        frac = (f"{sum(int(l['n_alvo']) for l in alvos) / sem_total:.4f}"
                if alvos and sem_total else "")
        dist = [int(l["n_distintas"]) for l in ls]
        zs = [float(l["max_abs_z"]) for l in ls if l["max_abs_z"] != ""]
        p5 = [int(l["n_pos_z5"]) for l in ls if l["n_pos_z5"] != ""]
        falhas = [int(l["n_falhas_forca"]) for l in ls if l["n_falhas_forca"] != ""]
        saida.append({
            "cenario": cen, "combinador": comb, "k": k, "esperado": ls[0]["esperado"],
            "n_seq": str(len(ls)), "n_seq_completas": str(len(completas)),
            "n_aprovadas": str(aprov), "taxa_aprovacao": taxa, "ic95_inf": ic_i, "ic95_sup": ic_s,
            "sementes_total": str(sem_total),
            "recusadas_total": str(sum(int(l["n_recusadas"]) for l in ls)),
            "frac_alvo": frac, "distintas_min": str(min(dist)), "distintas_max": str(max(dist)),
            "max_abs_z_max": f"{max(zs):.4f}" if zs else "",
            "pos_z5_min": str(min(p5)) if p5 else "", "pos_z5_max": str(max(p5)) if p5 else "",
            "falhas_forca_total": str(sum(falhas)) if falhas else "",
            "t_seq_mediana_s": f"{statistics.median(float(l['t_s']) for l in ls):.4f}",
        })
    return saida


# ---------------------------------------------------------------- arquivos

def csv_bytes(campos: tuple[str, ...], linhas: list[dict[str, str]]) -> bytes:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=list(campos), lineterminator="\n", extrasaction="raise")
    w.writeheader()
    w.writerows(linhas)
    return buf.getvalue().encode("utf-8")


def ler_seq(caminho: Path) -> list[dict[str, str]]:
    with caminho.open("r", encoding="utf-8", newline="") as f:
        r = csv.DictReader(f)
        if tuple(r.fieldnames or ()) != CAMPOS_SEQ:
            raise E4Erro(f"cabeçalho de {caminho.name} não é o esperado")
        return list(r)


def gravar_novo(caminho: Path, dados: bytes) -> None:
    if caminho.exists():
        raise E4Erro(f"{caminho.name} já existe; nada foi gravado")
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


def nome_celula(c: Celula) -> str:
    return f"{c.cenario}{'' if c.k is None else f'_k{c.k}'}/{c.combinador}"


# ---------------------------------------------------------------- modos

def medir_tempo(motor: Motor, saida: Callable[[str], None]) -> int:
    total = 0.0
    saida("Medição de tempo (só tempos; nenhum resultado das sequências é mostrado)")
    for c in celulas():
        tempos = [float(rodar_sequencia(motor, c, r, "medir-tempo")["t_s"])
                  for r in range(REPS_MEDIR_TEMPO)]
        media = statistics.mean(tempos)
        total += media * c.reps
        saida(f"  {nome_celula(c):<24} {media:8.3f} s/sequência  x {c.reps:>3}")
    n_seq = sum(c.reps for c in celulas())
    saida(f"Estimativa da rodada completa: {n_seq} sequências, cerca de {total / 60:.1f} min")
    return 0


def rodar(raiz: Path, motor: Motor, git, saida) -> int:
    pasta = raiz / "data" / "results"
    p_seq, p_res = pasta / NOME_SEQ, pasta / NOME_RESUMO
    for p in (p_seq, p_res):
        if p.exists():
            raise E4Erro(f"{p.name} já existe; nada foi rodado")
    commit, limpo = git(raiz)
    if not limpo:
        raise E4Erro("árvore com mudanças rastreadas; faça o commit do script antes da rodada")
    grade = celulas()
    esperado = sum(c.reps for c in grade)
    saida(f"E4 sobre o commit {commit[:7]}: {len(grade)} células, {esperado} sequências")
    linhas: list[dict[str, str]] = []
    inicio = time.perf_counter()
    for i, c in enumerate(grade, start=1):
        t0 = time.perf_counter()
        linhas += [rodar_sequencia(motor, c, r, commit) for r in range(c.reps)]
        saida(f"  [{i:>2}/{len(grade)}] {nome_celula(c)}: {c.reps} sequências em "
              f"{time.perf_counter() - t0:.1f} s (total {(time.perf_counter() - inicio) / 60:.1f} min)")
    if len(linhas) != esperado:
        raise E4Erro(f"{len(linhas)} linhas em vez de {esperado}; nada foi gravado")
    pasta.mkdir(parents=True, exist_ok=True)
    dados_seq = csv_bytes(CAMPOS_SEQ, linhas)
    gravar_novo(p_seq, dados_seq)
    dados_res = csv_bytes(CAMPOS_RESUMO, resumir(ler_seq(p_seq)))
    gravar_novo(p_res, dados_res)
    saida(f"{NOME_SEQ}: {sha256(dados_seq)}")
    saida(f"{NOME_RESUMO}: {sha256(dados_res)}")
    return 0


def refazer_resumo(raiz: Path, saida) -> int:
    pasta = raiz / "data" / "results"
    p_seq, p_res = pasta / NOME_SEQ, pasta / NOME_RESUMO
    if not p_seq.exists():
        raise E4Erro(f"{NOME_SEQ} não existe")
    dados = csv_bytes(CAMPOS_RESUMO, resumir(ler_seq(p_seq)))
    if p_res.exists():
        if p_res.read_bytes() == dados:
            saida(f"{NOME_RESUMO} já existia igual: {sha256(dados)}")
            return 0
        raise E4Erro(f"{NOME_RESUMO} existe e difere do recalculado; nada foi gravado")
    gravar_novo(p_res, dados)
    saida(f"{NOME_RESUMO}: {sha256(dados)}")
    return 0


def main(argv: list[str] | None = None, *, raiz: Path = ROOT, motor: Motor | None = None,
         git=git_estado, saida: Callable[[str], None] = print) -> int:
    ap = argparse.ArgumentParser(description="E4: resiliência da mistura")
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
    except E4Erro as exc:
        saida(f"RECUSADO: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
