"""Dia 6: os jobs de calibração (sessão cal) replicam o que a coleta 1 mostrou por qubit?

Só lê os dados; não gasta QPU, não toca em data/logs, data/receipts nem keys. Tudo é
determinístico (sem simulação nem aleatoriedade): saída igual à existente não é regravada e
saída diferente recusa sem gravar nenhum arquivo.

Entrada: os 2 lotes ``coleta1`` (conferidos contra o inventário e o ``batch_hash``) e os 2 lotes
``cal`` (conferidos pelo ``batch_hash`` e pela coerência com a coleta 1). Os ``cal`` não estão no
inventário: a integridade deles é só o ``batch_hash``.

Conjunto fixo, definido ANTES de olhar os dados ``cal`` e só com base na coleta 1:
  - qubits 14, 21, 138: excesso sobre o erro de leitura nos dois lotes da coleta 1;
  - controles de leitura 121 e 131: viés compatível com o erro de leitura do retrato;
  - pares 112-113 e 130-131: correlação com a posição vizinha repetida nos dois lotes.
(O qubit 112 já tinha aparecido entre as 3 colunas mais afastadas de 0,5 do cal_001, no registro
do PROJECT.md; a correlação do par não tinha sido vista nos ``cal``.)

Critérios, fixados antes da leitura:
  - testável: efeito esperado (média da coleta 1) >= 2,8 erros-padrão do lote;
  - replica: testável, mesmo sinal e |z| > 2 (z em relação a 0,5 para p1; a 0 para r);
  - magnitude compatível: testável e |estimativa - referência| <= 3 erros-padrão da diferença.
Erro-padrão de p1: 0,5 / sqrt(shots). De r: 1 / sqrt(shots) (aproximação).

Limites: os ``cal`` são do mesmo dia e foram salvos antes da coleta 1 (persistência dentro do dia, não
entre dias); o retrato de calibração gravado é o do envio, não o da execução (R8); "vizinho" é a
posição i+1, não necessariamente um par acoplado no chip.

Saídas em data/results:
    dia6_deriva_dia_lotes.csv         um por lote (job, shots, datas, fração de 1, hash)
    dia6_deriva_dia_por_qubit.csv     um por lote e posição
    dia6_deriva_dia_conjunto_fixo.csv um por lote e item do conjunto fixo
    dia6_deriva_dia_estabilidade.csv  um por par de lotes (zdiff dos 156 qubits)

Uso (na raiz do projeto):
    py -3.12 scripts\\analisar_cal.py
Código de saída: 0 gravado ou já igual; 1 recusado ou erro; 2 erro de uso.
"""
from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path
from typing import Any

import numpy as np

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_HERE.parent))
import analisar_coleta1 as ac  # noqa: E402
import resumo_coleta1 as rc  # noqa: E402
from eal.sources.ibm_bits import BIT_ORDER  # noqa: E402
from eal.storage import load_batch  # noqa: E402

RAW_DIR = Path("data/raw")
INVENTORY_PATH = Path("data/results/dia6_coleta1_inventario.csv")
OUT_DIR = Path("data/results")
CAL_SESSION = "cal"
N_CAL = 2
REF_PREFIX = "coleta1_"
LOTES_NAME = "dia6_deriva_dia_lotes.csv"
QUBIT_NAME = "dia6_deriva_dia_por_qubit.csv"
FIXO_NAME = "dia6_deriva_dia_conjunto_fixo.csv"
EST_NAME = "dia6_deriva_dia_estabilidade.csv"

QUBIT_GROUPS: tuple[tuple[str, tuple[int, ...]], ...] = (
    ("vies_alem_da_leitura", (14, 21, 138)),
    ("controle_leitura", (121, 131)),
)
PAIRS: tuple[tuple[int, int], ...] = ((112, 113), (130, 131))
TESTABLE_Z = 2.8
REPLICA_Z = 2.0
MAGNITUDE_Z = 3.0

FIXED_COLUMNS = ("tipo", "grupo", "id", "lote", "n_shots", "estimativa", "se", "z",
                 "referencia_coleta1", "z_esperado", "testavel", "sinal_igual", "replica",
                 "zdiff_vs_coleta1", "magnitude_compativel", "erro_leitura", "excesso")


class CalError(Exception):
    """Recusa: nada foi gravado."""


def _f(x: Any) -> float | None:
    if x is None:
        return None
    x = float(x)
    return None if math.isnan(x) else x


# ---------------------------------------------------------------- carga

def _label(meta: Path) -> str:
    return "_".join(meta.stem.split("_")[-2:])


def load_cal(raw_dir: Path, ref: Any, session: str = CAL_SESSION) -> list[tuple[str, Any]]:
    """Carrega e confere os lotes cal contra um lote da coleta 1 (``ref``)."""
    metas = sorted(raw_dir.glob(f"*_{session}_*.json"))
    if len(metas) != N_CAL:
        raise CalError(f"esperava {N_CAL} lotes {session} em {raw_dir}, achei {len(metas)}")
    rp = ref.params
    out = []
    for meta in metas:
        npy = meta.with_suffix(".npy")
        if not npy.exists():
            raise CalError(f"{meta.name}: falta o .npy")
        try:
            b = load_batch(npy)
        except (ValueError, KeyError, OSError) as exc:
            raise CalError(f"{npy.name}: {type(exc).__name__}: {exc}") from exc
        p, name = b.params, meta.name
        if b.is_local is not False or b.is_simulated is not False:
            raise CalError(f"{name}: lote não é real (is_local/is_simulated)")
        if p.get("backend") != rp.get("backend"):
            raise CalError(f"{name}: backend diferente da coleta 1")
        if not (isinstance(p.get("shots"), int) and isinstance(p.get("qubits"), int)
                and b.n_bits == p["shots"] * p["qubits"]):
            raise CalError(f"{name}: n_bits diferente de shots x qubits")
        if p["qubits"] != rp["qubits"] or p.get("physical_qubits") != rp["physical_qubits"]:
            raise CalError(f"{name}: qubits ou mapa de qubits diferem da coleta 1")
        if p.get("bit_order") != BIT_ORDER or p.get("discarded_bits") != 0:
            raise CalError(f"{name}: bit_order inesperado ou bits descartados")
        if p.get("readout_error_by_position") != rp.get("readout_error_by_position"):
            raise CalError(f"{name}: retrato de erro de leitura diferente da coleta 1")
        out.append((_label(meta), b))
    return out


# ---------------------------------------------------------------- contas

def _verdict(est: float, null: float, se: float, ref: float, se_diff: float) -> dict[str, Any]:
    z = (est - null) / se
    z_exp = abs(ref - null) / se
    testavel = bool(z_exp >= TESTABLE_Z)
    same = bool((est - null) * (ref - null) > 0)
    zd = (est - ref) / se_diff if se_diff > 0 else None
    replica = bool(same and abs(z) > REPLICA_Z) if testavel else None
    mag = bool(abs(zd) <= MAGNITUDE_Z) if (testavel and zd is not None) else None
    return {"z": z, "z_esperado": z_exp, "testavel": testavel, "sinal_igual": same,
            "replica": replica, "zdiff_vs_coleta1": zd, "magnitude_compativel": mag}


def _row(**kw: Any) -> dict[str, Any]:
    extra = set(kw) - set(FIXED_COLUMNS)
    if extra:
        raise CalError(f"colunas desconhecidas: {sorted(extra)}")
    return {c: kw.get(c) for c in FIXED_COLUMNS}


def fixed_rows(labels: list[str], shots: dict[str, int], m: dict[str, dict[str, Any]],
               readout: list[float], groups=QUBIT_GROUPS, pairs=PAIRS) -> list[dict[str, Any]]:
    """Linhas do conjunto fixo. ``m[lote]`` traz ``p1`` e ``corr_vizinho`` por posição."""
    refs = [lab for lab in labels if lab.startswith(REF_PREFIX)]
    if not refs:
        raise CalError("sem lotes da coleta 1")
    n_ref = sum(shots[lab] for lab in refs)
    n_pos = len(readout)
    rows: list[dict[str, Any]] = []
    for grupo, positions in groups:
        for pos in positions:
            if not 0 <= pos < n_pos:
                raise CalError(f"posição {pos} fora de 0..{n_pos - 1}")
            ref = sum(float(m[lab]["p1"][pos]) * shots[lab] for lab in refs) / n_ref
            for lab in labels:
                n, p1 = shots[lab], float(m[lab]["p1"][pos])
                se = 0.5 / math.sqrt(n)
                err = float(readout[pos])
                base = dict(tipo="qubit", grupo=grupo, id=str(pos), lote=lab, n_shots=n,
                            estimativa=p1, se=se, z=(p1 - 0.5) / se, referencia_coleta1=ref,
                            erro_leitura=err, excesso=abs(p1 - 0.5) - err)
                if lab not in refs:
                    se_diff = math.sqrt(p1 * (1 - p1) / n + ref * (1 - ref) / n_ref)
                    base.update(_verdict(p1, 0.5, se, ref, se_diff))
                rows.append(_row(**base))
    for a, b in pairs:
        if b != a + 1:
            raise CalError(f"par {a}-{b} não é de posições vizinhas")
        if not 0 <= a < n_pos - 1:
            raise CalError(f"par {a}-{b} fora de 0..{n_pos - 1}")
        ref = sum(float(m[lab]["corr_vizinho"][a]) * shots[lab] for lab in refs) / n_ref
        for lab in labels:
            n, r = shots[lab], float(m[lab]["corr_vizinho"][a])
            if math.isnan(r) or math.isnan(ref):
                raise CalError(f"correlação indefinida no par {a}-{b}")
            se = 1 / math.sqrt(n)
            base = dict(tipo="par", grupo="par_replicado_coleta1", id=f"{a}-{b}", lote=lab,
                        n_shots=n, estimativa=r, se=se, z=r / se, referencia_coleta1=ref)
            if lab not in refs:
                base.update(_verdict(r, 0.0, se, ref, math.sqrt(se ** 2 + 1 / n_ref)))
            rows.append(_row(**base))
    return rows


def stability_rows(labels: list[str], shots: dict[str, int],
                   m: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """zdiff dos qubits para cada par de lotes (shots podem diferir)."""
    rows = []
    for i, a in enumerate(labels):
        for b in labels[i + 1:]:
            na, nb = shots[a], shots[b]
            zs = []
            for pos in range(len(m[a]["p1"])):
                pa, pb = float(m[a]["p1"][pos]), float(m[b]["p1"][pos])
                pm = (na * pa + nb * pb) / (na + nb)
                if 0.0 < pm < 1.0:
                    zs.append((pos, (pa - pb) / math.sqrt(pm * (1 - pm) * (1 / na + 1 / nb))))
            vals = [z for _, z in zs]
            top = max(zs, key=lambda t: abs(t[1]), default=None)
            rows.append({"lote_a": a, "lote_b": b, "n_qubits": len(vals),
                         "zdiff_media": sum(vals) / len(vals) if vals else None,
                         "zdiff_dp": rc.sample_sd(vals),
                         "zdiff_n_acima3": rc._count_above(vals),
                         "zdiff_max_abs": None if top is None else abs(top[1]),
                         "zdiff_max_pos": None if top is None else top[0]})
    return rows


def qubit_rows(label: str, n_shots: int, met: dict[str, Any], physical: list[int],
               readout: list[float]) -> list[dict[str, Any]]:
    limit = 3 * 0.5 / math.sqrt(n_shots)
    rows = []
    for pos in range(len(physical)):
        p1 = float(met["p1"][pos])
        desvio = abs(p1 - 0.5)
        rows.append({"lote": label, "posicao": pos, "qubit_fisico": physical[pos],
                     "n_shots": n_shots, "p1": p1, "z_p1": _f(met["z_p1"][pos]),
                     "corr_vizinho": _f(met["corr_vizinho"][pos]),
                     "corr_prox_shot": _f(met["corr_prox_shot"][pos]),
                     "erro_leitura": readout[pos], "desvio": desvio,
                     "excesso": desvio - readout[pos], "limite_3ep": limit,
                     "acima_do_limite": desvio - readout[pos] > limit})
    return rows


# ---------------------------------------------------------------- execução

def run(raw_dir: Path, inventory: Path, out_dir: Path, *, groups=QUBIT_GROUPS, pairs=PAIRS):
    real = ac.load_real(raw_dir, inventory)
    cal = load_cal(raw_dir, real[0])
    lots = [(lab, b, "batch_hash") for lab, b in cal]
    # rótulos da coleta 1 vêm do nome do arquivo, na mesma ordem (por nome) de load_real
    ref_names = sorted(raw_dir.glob(f"*_{ac.SESSION}_*.json"))
    if len(ref_names) != len(real):
        raise CalError("lotes da coleta 1 em disco diferem dos carregados")
    lots += [(_label(path), b, "inventario+batch_hash") for path, b in zip(ref_names, real)]
    labels = [lab for lab, _, _ in lots]
    batches = [b for _, b, _ in lots]
    ac._check_distinct(batches)
    if len({b.params["job_id"] for b in batches}) != len(batches):
        raise CalError("job_id repetido entre os lotes")
    n_qubits = int(real[0].params["qubits"])
    physical = [int(q) for q in real[0].params["physical_qubits"]]
    readout = [float(x) for x in real[0].params["readout_error_by_position"]]
    if len(readout) != n_qubits:
        raise CalError("erro de leitura com tamanho diferente de qubits")
    shots = {lab: int(b.params["shots"]) for lab, b in zip(labels, batches)}
    m = {lab: ac.qubit_metrics(b.bits, n_qubits) for lab, b in zip(labels, batches)}
    lotes_rows = [{"lote": lab, "job_id": b.params["job_id"], "n_shots": shots[lab],
                   "n_bits": b.n_bits, "criado_em": b.created_at,
                   "calibracao_no_envio": b.params.get("calibration_date"),
                   "frac1": float(m[lab]["p1"].mean()), "batch_hash": b.batch_hash,
                   "conferencia": how} for (lab, b, how) in lots]
    qrows = [r for lab in labels for r in qubit_rows(lab, shots[lab], m[lab], physical, readout)]
    frows = fixed_rows(labels, shots, m, readout, groups, pairs)
    srows = stability_rows(labels, shots, m)
    targets = [(out_dir / LOTES_NAME, rc.csv_text(lotes_rows)),
               (out_dir / QUBIT_NAME, rc.csv_text(qrows)),
               (out_dir / FIXO_NAME, rc.csv_text(frows)),
               (out_dir / EST_NAME, rc.csv_text(srows))]
    states = rc.write_deterministic(targets)
    return states, [p for p, _ in targets], frows, srows


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Dia 6: jobs cal vs coleta 1 por qubit")
    ap.add_argument("--raw-dir", type=Path, default=RAW_DIR)
    ap.add_argument("--inventario", type=Path, default=INVENTORY_PATH)
    ap.add_argument("--out-dir", type=Path, default=OUT_DIR)
    args = ap.parse_args(argv)
    try:
        states, paths, frows, srows = run(args.raw_dir, args.inventario, args.out_dir)
    except (CalError, ac.AnalysisError, rc.SummaryError) as exc:
        print(f"RECUSADO: {exc}")
        return 1
    except Exception as exc:  # texto de exceção não é impresso, só a classe
        print(f"erro inesperado: {type(exc).__name__}")
        return 1
    for state, path in zip(states, paths):
        print(f"{state}: {path}")
    for r in frows:
        if r["testavel"] is None:
            continue
        print(f"{r['tipo']} {r['id']} ({r['grupo']}) {r['lote']}: est={rc._cell(r['estimativa'])} "
              f"z={rc._cell(r['z'])} z_esp={rc._cell(r['z_esperado'])} testavel={r['testavel']} "
              f"replica={r['replica']} magnitude_ok={r['magnitude_compativel']}")
    for r in srows:
        print(f"estabilidade {r['lote_a']} x {r['lote_b']}: media={rc._cell(r['zdiff_media'])} "
              f"dp={rc._cell(r['zdiff_dp'])} |z|>3={r['zdiff_n_acima3']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
