"""Mutações manuais das linhas novas do R8 (eal/sources/qpu_ibm.py e eal/sources/ibm_bits.py).

Uso:  py -3.12 scripts\\mutacoes_r8.py

Cada mutação troca um trecho único; se o trecho não aparecer exatamente uma vez, conta como
"âncora inválida". Os testes rodam sem cache e sem bytecode; o módulo é sempre restaurado.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
QPU = Path("eal/sources/qpu_ibm.py")
BITS = Path("eal/sources/ibm_bits.py")
TESTS = ["tests/test_r8_retrato_execucao.py", "tests/test_ibm_bits.py", "tests/test_qpu_ibm.py"]

MUTATIONS = [
    (QPU, "retrato da execucao nao lido",
     'run_errors, run_date = _run_snapshot(job, manifest["physical_qubits"])',
     'run_errors, run_date = None, None'),
    (QPU, "retrato da execucao nao passado ao lote",
     'readout_error_run=run_errors, calibration_date_run=run_date,',
     'readout_error_run=None, calibration_date_run=None,'),
    (QPU, "retrato da execucao no lugar do retrato do envio",
     'calibration_date=manifest["calibration_date"],\n                readout_error_run',
     'calibration_date=run_date,\n                readout_error_run'),
    (QPU, "falha de properties() vaza",
     'except Exception:  # noqa: BLE001\n        return None, None\n    if date is None',
     'except KeyError:\n        return None, None\n    if date is None'),
    (QPU, "data ausente aceita",
     'if date is None or not all(', 'if not all('),
    (QPU, "erro de leitura fora de faixa aceito",
     'if date is None or not all(0.0 <= e <= 1.0 for e in errors):',
     'if date is None:'),
    (QPU, "data convertida para texto errado",
     'return errors, str(date)', 'return errors, repr(date)'),
    (BITS, "data da execucao nao gravada",
     '"calibration_date_run": run_date,', '"calibration_date_run": None,'),
    (BITS, "erro de leitura da execucao nao gravado",
     '"readout_error_run_by_position": run_errors,',
     '"readout_error_run_by_position": None,'),
    (BITS, "retrato da execucao pela metade aceito",
     'run_errors, run_date = _check_snapshot(readout_error_run, calibration_date_run, '
     'len(physical))',
     'run_errors, run_date = readout_error_run, calibration_date_run'),
    (BITS, "tamanho do retrato da execucao nao conferido",
     'run_errors, run_date = _check_snapshot(readout_error_run, calibration_date_run, '
     'len(physical))',
     'run_errors, run_date = _check_snapshot(readout_error_run, calibration_date_run, '
     'len(readout_error_run or physical))'),
]


def _run_tests() -> bool:
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    done = subprocess.run([sys.executable, "-m", "pytest", "-q", "-x", "-p", "no:cacheprovider",
                           *TESTS], cwd=ROOT, env=env, capture_output=True, text=True)
    return done.returncode == 0


def _drop_bytecode(module: Path) -> None:
    cache = ROOT / module.parent / "__pycache__"
    for pyc in cache.glob(module.stem + ".*.pyc"):
        pyc.unlink(missing_ok=True)


def main() -> int:
    originals = {m: (ROOT / m).read_bytes() for m in {QPU, BITS}}
    killed = survived = invalid = 0
    try:
        for m in originals:
            _drop_bytecode(m)
        if not _run_tests():
            print("Os testes já falham sem mutação; nada foi mutado.")
            return 2
        for module, name, old, new in MUTATIONS:
            raw = originals[module]
            crlf = b"\r\n" in raw
            text = raw.decode("utf-8").replace("\r\n", "\n")
            if text.count(old) != 1:
                print(f"[ancora invalida] {name}")
                invalid += 1
                continue
            mutated = text.replace(old, new)
            (ROOT / module).write_bytes(
                (mutated.replace("\n", "\r\n") if crlf else mutated).encode("utf-8"))
            _drop_bytecode(module)
            try:
                if _run_tests():
                    print(f"[SOBREVIVEU] {name}")
                    survived += 1
                else:
                    print(f"[morta] {name}")
                    killed += 1
            finally:
                (ROOT / module).write_bytes(raw)
                _drop_bytecode(module)
    finally:
        for m, raw in originals.items():
            (ROOT / m).write_bytes(raw)
    restored = all((ROOT / m).read_bytes() == raw for m, raw in originals.items())
    print(f"\n{len(MUTATIONS)} mutações: {killed} mortas, {survived} sobreviveram, "
          f"{invalid} com âncora inválida.")
    print(f"módulos restaurados: {restored}")
    return 0 if survived == 0 and invalid == 0 and restored else 1


if __name__ == "__main__":
    sys.exit(main())
