"""Dia 6: deriva no mesmo dia, uma sessão (padrão coleta2) contra a coleta 1, por qubit.

Só lê os dados; não gasta QPU, não toca em data/logs, data/receipts nem keys. Tudo é
determinístico: saída igual à existente não é regravada e saída diferente recusa sem gravar
nenhum arquivo.

Critérios: os do plano congelado da coleta 2 no PROJECT.md, que são os do E1 parcial. O conjunto
fixo, os limiares e o veredito vêm de ``analisar_cal.py`` (QUBIT_GROUPS, PAIRS,
fixed_rows, _verdict); nada é redefinido aqui.

Diferenças em relação a ``analisar_cal.py``:
  - os lotes das duas sessões são conferidos contra o inventário de cada uma (SHA-256 do
    ``.npy`` e do ``.json``) e o ``batch_hash``;
  - o erro de leitura não precisa ser igual ao da coleta 1: cada lote usa o retrato em vigor quando
    rodou (o da execução, R8, se o lote tiver; senão, o do envio);
  - cada linha registra a calibração usada e se ela é a mesma da coleta 1.
O veredito (z, testável, réplica, magnitude) depende só das frações e correlações; o retrato de
leitura entra só nas colunas ``erro_leitura`` e ``excesso``.

Limite: cada coleta rodou sob uma calibração só. Quando a calibração difere, a deriva medida mistura
o tempo decorrido e a troca de calibração, e estes dados não separam os dois.

Saídas em data/results (com a sessão no nome):
    dia6_deriva_<sessao>_lotes.csv          um por lote
    dia6_deriva_<sessao>_por_qubit.csv      um por lote e posição
    dia6_deriva_<sessao>_conjunto_fixo.csv  um por lote e item do conjunto fixo
    dia6_deriva_<sessao>_estabilidade.csv   um por par de lotes (zdiff dos qubits)

Uso (na raiz do projeto):
    py -3.12 scripts\\analisar_deriva.py
    py -3.12 scripts\\analisar_deriva.py --sessao coleta2
Código de saída: 0 gravado ou já igual; 1 recusado ou erro; 2 erro de uso.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_HERE.parent))
import analisar_cal as cal  # noqa: E402
import analisar_coleta1 as ac  # noqa: E402
import resumo_coleta1 as rc  # noqa: E402

RAW_DIR = Path("data/raw")
OUT_DIR = Path("data/results")
REF_SESSION = "coleta1"
DEFAULT_SESSION = "coleta2"
KINDS = ("lotes", "por_qubit", "conjunto_fixo", "estabilidade")


class DerivaError(Exception):
    """Recusa: nada foi gravado."""


def out_names(session: str) -> list[str]:
    return [f"dia6_deriva_{session}_{kind}.csv" for kind in KINDS]


def calibration_in_force(params: dict[str, Any]) -> Any:
    """Data da calibração em vigor na execução: a do R8 se houver; senão, a do envio."""
    run = params.get("calibration_date_run")
    return run if run is not None else params.get("calibration_date")


def readout_source(params: dict[str, Any]) -> str:
    return "execucao" if params.get("readout_error_run_by_position") is not None else "envio"


# ---------------------------------------------------------------- carga

def load_session(raw_dir: Path, session: str) -> list[tuple[str, Any]]:
    """(rótulo, lote) de uma sessão, conferidos contra o inventário dela."""
    batches = ac.load_real(raw_dir, ac.inventory_for(session), session)
    names = sorted(raw_dir.glob(f"*_{session}_*.json"))
    if len(names) != len(batches):
        raise DerivaError(f"lotes da sessão {session} em disco diferem dos carregados")
    return [(cal._label(path), b) for path, b in zip(names, batches)]


def _readout(label: str, params: dict[str, Any], n_qubits: int) -> list[float]:
    values = ac.readout_of(params)
    if values is None or len(values) != n_qubits:
        raise DerivaError(f"{label}: erro de leitura ausente ou com tamanho diferente de qubits")
    return [float(x) for x in values]


def _check_coherent(lots: list[tuple[str, Any]]) -> tuple[int, list[int]]:
    first = lots[0][1].params
    n_qubits = int(first["qubits"])
    physical = [int(q) for q in first["physical_qubits"]]
    for label, b in lots:
        p = b.params
        if p.get("backend") != first.get("backend"):
            raise DerivaError(f"{label}: backend diferente da coleta 1")
        if int(p["qubits"]) != n_qubits or [int(q) for q in p["physical_qubits"]] != physical:
            raise DerivaError(f"{label}: qubits ou mapa de qubits diferem da coleta 1")
    if len({b.params["job_id"] for _, b in lots}) != len(lots):
        raise DerivaError("job_id repetido entre os lotes")
    ac._check_distinct([b for _, b in lots])
    return n_qubits, physical


# ---------------------------------------------------------------- execução

def _item_order(groups, pairs) -> list[tuple[str, str]]:
    return ([("qubit", str(pos)) for _, positions in groups for pos in positions]
            + [("par", f"{a}-{b}") for a, b in pairs])


def run(raw_dir: Path, out_dir: Path, session: str = DEFAULT_SESSION, *,
        groups=cal.QUBIT_GROUPS, pairs=cal.PAIRS):
    session = ac.check_session(session)
    if session == REF_SESSION:
        raise DerivaError("a sessão comparada não pode ser a própria coleta 1")
    if cal.REF_PREFIX != REF_SESSION + "_":
        raise DerivaError("o prefixo de referência do analisar_cal não é o da coleta 1")
    ref = load_session(raw_dir, REF_SESSION)
    comp = load_session(raw_dir, session)
    lots = ref + comp
    labels = [lab for lab, _ in lots]
    ref_labels = [lab for lab, _ in ref]
    n_qubits, physical = _check_coherent(lots)
    readouts = {lab: _readout(lab, b.params, n_qubits) for lab, b in lots}
    ref_cals = {calibration_in_force(b.params) for _, b in ref}
    if len(ref_cals) != 1 or None in ref_cals:
        raise DerivaError("a coleta 1 não tem uma calibração única registrada")
    ref_cal = ref_cals.pop()
    same_cal = {lab: calibration_in_force(b.params) == ref_cal for lab, b in lots}
    shots = {lab: int(b.params["shots"]) for lab, b in lots}
    m = {lab: ac.qubit_metrics(b.bits, n_qubits) for lab, b in lots}

    lotes_rows = [{"lote": lab, "sessao": REF_SESSION if lab in ref_labels else session,
                   "job_id": b.params["job_id"], "n_shots": shots[lab], "n_bits": b.n_bits,
                   "criado_em": b.created_at,
                   "calibracao_no_envio": b.params.get("calibration_date"),
                   "calibracao_execucao": b.params.get("calibration_date_run"),
                   "retrato_leitura": readout_source(b.params),
                   "calibracao_igual_coleta1": same_cal[lab],
                   "frac1": float(m[lab]["p1"].mean()), "batch_hash": b.batch_hash,
                   "conferencia": "inventario+batch_hash"} for lab, b in lots]
    qrows = [r for lab in labels
             for r in cal.qubit_rows(lab, shots[lab], m[lab], physical, readouts[lab])]

    by_lot: dict[str, list[dict[str, Any]]] = {}
    for lab in labels:
        call_labels = ref_labels if lab in ref_labels else ref_labels + [lab]
        rows = cal.fixed_rows(call_labels, shots, m, readouts[lab], groups, pairs)
        by_lot[lab] = [dict(r, calibracao_igual_coleta1=same_cal[lab])
                       for r in rows if r["lote"] == lab]
    order = _item_order(groups, pairs)
    frows = sorted((r for lab in labels for r in by_lot[lab]),
                   key=lambda r: (order.index((r["tipo"], r["id"])), labels.index(r["lote"])))
    srows = cal.stability_rows(labels, shots, m)

    texts = [rc.csv_text(lotes_rows), rc.csv_text(qrows), rc.csv_text(frows), rc.csv_text(srows)]
    targets = [(out_dir / name, text) for name, text in zip(out_names(session), texts)]
    states = rc.write_deterministic(targets)
    return states, [p for p, _ in targets], lotes_rows, frows, srows


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Dia 6: deriva de uma sessão contra a coleta 1")
    ap.add_argument("--sessao", default=DEFAULT_SESSION)
    ap.add_argument("--raw-dir", type=Path, default=RAW_DIR)
    ap.add_argument("--out-dir", type=Path, default=OUT_DIR)
    args = ap.parse_args(argv)
    try:
        states, paths, lotes, frows, srows = run(args.raw_dir, args.out_dir, args.sessao)
    except (DerivaError, cal.CalError, ac.AnalysisError, rc.SummaryError) as exc:
        print(f"RECUSADO: {exc}")
        return 1
    except Exception as exc:  # texto de exceção não é impresso, só a classe
        print(f"erro inesperado: {type(exc).__name__}")
        return 1
    for state, path in zip(states, paths):
        print(f"{state}: {path}")
    for r in lotes:
        cal_used = r["calibracao_execucao"] or r["calibracao_no_envio"]
        print(f"lote {r['lote']}: calibracao={cal_used} "
              f"retrato={r['retrato_leitura']} igual_coleta1={r['calibracao_igual_coleta1']} "
              f"frac1={rc._cell(r['frac1'])}")
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
