"""Mutações manuais de scripts/analisar_deriva.py (DEP_SESSAO, passo 3).

Uso:  py -3.12 scripts\\mutacoes_analisar_deriva.py

Cada mutação troca um trecho único; se o trecho não aparecer exatamente uma vez, conta como
"âncora inválida". Os testes rodam sem cache e sem bytecode; o módulo é sempre restaurado.

Fora da lista, por ser equivalente: passar todos os rótulos ao ``fixed_rows`` em vez de
"referência + o lote" dá as mesmas linhas, porque o veredito de cada lote só depende da
coleta 1. Nenhum teste distingue as duas formas.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODULE = Path("scripts/analisar_deriva.py")
TESTS = ["tests/test_analisar_deriva.py"]

MUTATIONS = [
    ("retrato do envio no lugar do da execucao",
     "    values = ac.readout_of(params)\n",
     '    values = params.get("readout_error_by_position")\n'),
    ("calibracao do envio no lugar da execucao",
     "    return run if run is not None else params.get(\"calibration_date\")",
     "    return params.get(\"calibration_date\")"),
    ("retrato rotulado errado",
     'return "execucao" if params.get("readout_error_run_by_position") is not None else "envio"',
     'return "envio"'),
    ("tamanho do retrato nao conferido",
     "if values is None or len(values) != n_qubits:", "if values is None:"),
    ("backend nao conferido",
     'if p.get("backend") != first.get("backend"):', "if False:"),
    ("mapa de qubits nao conferido",
     'if int(p["qubits"]) != n_qubits or [int(q) for q in p["physical_qubits"]] != physical:',
     'if int(p["qubits"]) != n_qubits:'),
    ("job_id repetido aceito",
     'if len({b.params["job_id"] for _, b in lots}) != len(lots):', "if False:"),
    ("lote repetido aceito",
     "    ac._check_distinct([b for _, b in lots])\n", ""),
    ("comparar a coleta 1 com ela mesma",
     "    if session == REF_SESSION:\n", "    if False:\n"),
    ("sessao nao validada",
     "    session = ac.check_session(session)\n", ""),
    ("coleta 1 com varias calibracoes aceita",
     "if len(ref_cals) != 1 or None in ref_cals:", "if None in ref_cals:"),
    ("calibracao igual sempre verdadeira",
     "same_cal = {lab: calibration_in_force(b.params) == ref_cal for lab, b in lots}",
     "same_cal = {lab: True for lab, b in lots}"),
    ("retrato de outro lote no conjunto fixo",
     "rows = cal.fixed_rows(call_labels, shots, m, readouts[lab], groups, pairs)",
     "rows = cal.fixed_rows(call_labels, shots, m, readouts[labels[0]], groups, pairs)"),
    ("ordem do conjunto fixo por lote",
     "key=lambda r: (order.index((r[\"tipo\"], r[\"id\"])), labels.index(r[\"lote\"])))",
     "key=lambda r: (labels.index(r[\"lote\"]), order.index((r[\"tipo\"], r[\"id\"]))))"),
    ("lotes em disco nao conferidos",
     "    if len(names) != len(batches):\n", "    if False:\n"),
    ("inventario de outra sessao",
     "ac.load_real(raw_dir, ac.inventory_for(session), session)",
     "ac.load_real(raw_dir, ac.inventory_for(REF_SESSION), session)"),
    ("nome sem a sessao",
     'return [f"dia6_deriva_{session}_{kind}.csv" for kind in KINDS]',
     'return [f"dia6_deriva_{kind}.csv" for kind in KINDS]'),
]


def _run_tests() -> bool:
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    done = subprocess.run([sys.executable, "-m", "pytest", "-q", "-x", "-p", "no:cacheprovider",
                           *TESTS], cwd=ROOT, env=env, capture_output=True, text=True)
    return done.returncode == 0


def _drop_bytecode() -> None:
    for pyc in (ROOT / MODULE.parent / "__pycache__").glob(MODULE.stem + ".*.pyc"):
        pyc.unlink(missing_ok=True)


def main() -> int:
    path = ROOT / MODULE
    raw = path.read_bytes()
    crlf = b"\r\n" in raw
    text = raw.decode("utf-8").replace("\r\n", "\n")
    killed = survived = invalid = 0
    try:
        _drop_bytecode()
        if not _run_tests():
            print("Os testes já falham sem mutação; nada foi mutado.")
            return 2
        for name, old, new in MUTATIONS:
            if text.count(old) != 1:
                print(f"[ancora invalida] {name}")
                invalid += 1
                continue
            mutated = text.replace(old, new)
            path.write_bytes((mutated.replace("\n", "\r\n") if crlf else mutated).encode("utf-8"))
            _drop_bytecode()
            try:
                if _run_tests():
                    print(f"[SOBREVIVEU] {name}")
                    survived += 1
                else:
                    print(f"[morta] {name}")
                    killed += 1
            finally:
                path.write_bytes(raw)
                _drop_bytecode()
    finally:
        path.write_bytes(raw)
    restored = path.read_bytes() == raw
    print(f"\n{len(MUTATIONS)} mutações: {killed} mortas, {survived} sobreviveram, "
          f"{invalid} com âncora inválida.")
    print(f"módulo restaurado: {restored}")
    return 0 if survived == 0 and invalid == 0 and restored else 1


if __name__ == "__main__":
    sys.exit(main())
