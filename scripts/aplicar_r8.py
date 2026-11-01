"""R8 (Dia 6): grava no lote da IBM o retrato da calibração em vigor na execução.

Uso único:  py -3.12 scripts\\aplicar_r8.py

Troca texto em eal/sources/qpu_ibm.py e eal/sources/ibm_bits.py. Tudo ou nada: cada trecho
original tem de aparecer exatamente uma vez, senão recusa sem gravar. Preserva CRLF ou LF.
Uma segunda execução diz que já foi aplicado e não grava nada.
"""
from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
QPU = ROOT / "eal" / "sources" / "qpu_ibm.py"
BITS = ROOT / "eal" / "sources" / "ibm_bits.py"

SNAPSHOT = '''def _snapshot(backend: Any, physical: list[int]) -> tuple[list[float] | None, str | None]:
    """Retrato da calibração (erro de leitura por posição e data); None se indisponível."""
    try:
        props = backend.properties()
        errors = [float(props.readout_error(q)) for q in physical]
        return errors, str(props.last_update_date)
    except Exception:  # noqa: BLE001
        return None, None'''

RUN_SNAPSHOT = '''

def _run_snapshot(job: Any, physical: list[int]) -> tuple[list[float] | None, str | None]:
    """Calibração em vigor quando o job rodou (``job.properties()``), R8; None se indisponível.

    Nunca levanta: um retrato ruim não pode custar o lote, que já foi pago.
    """
    try:
        props = job.properties()
        date = props.last_update_date
        errors = [float(props.readout_error(q)) for q in physical]
    except Exception:  # noqa: BLE001
        return None, None
    if date is None or not all(0.0 <= e <= 1.0 for e in errors):
        return None, None
    return errors, str(date)'''

BUILD_CALL = ('            params = build_ibm_params(\n'
              '                backend_name=manifest["backend"], job_id=job_id, '
              'shots=manifest["shots"],\n')

CAL_ARG = ('                calibration_date=manifest["calibration_date"],\n'
           '                rep_delay_seconds=manifest["rep_delay_seconds"],\n')

QPU_EDITS = [
    (SNAPSHOT, SNAPSHOT + RUN_SNAPSHOT),
    (BUILD_CALL,
     '            run_errors, run_date = _run_snapshot(job, manifest["physical_qubits"])\n'
     + BUILD_CALL),
    (CAL_ARG,
     '                calibration_date=manifest["calibration_date"],\n'
     '                readout_error_run=run_errors, calibration_date_run=run_date,\n'
     '                rep_delay_seconds=manifest["rep_delay_seconds"],\n'),
]

SIGNATURE = '                     sdk_versions: dict[str, str]) -> dict[str, Any]:\n'
DOC_LINE = ('    ``readout_error_by_position[i]`` é o erro de leitura do qubit '
            '``physical_qubits[i]``.\n')
CHECK_LINE = ('    errors, cal_date = _check_snapshot(readout_error, calibration_date, '
              'len(physical))\n')
DICT_LINE = '        "readout_error_by_position": errors,\n'

BITS_EDITS = [
    (SIGNATURE,
     '                     sdk_versions: dict[str, str],\n'
     '                     readout_error_run: Sequence[float] | None = None,\n'
     '                     calibration_date_run: str | None = None) -> dict[str, Any]:\n'),
    (DOC_LINE,
     DOC_LINE
     + '    ``calibration_date_run`` e ``readout_error_run_by_position`` são o retrato da '
       'calibração\n'
     + '    em vigor na execução (R8); ``None`` se indisponível ou em lote anterior ao R8.\n'),
    (CHECK_LINE,
     CHECK_LINE
     + '    run_errors, run_date = _check_snapshot(readout_error_run, calibration_date_run, '
       'len(physical))\n'),
    (DICT_LINE,
     DICT_LINE
     + '        "calibration_date_run": run_date,\n'
     + '        "readout_error_run_by_position": run_errors,\n'),
]


class Recusa(Exception):
    """Algo não bate: nada é gravado."""


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load(path: Path) -> tuple[bytes, str, bool]:
    if not path.is_file():
        raise Recusa(f"arquivo ausente: {path}")
    raw = path.read_bytes()
    crlf = raw.count(b"\r\n")
    lf = raw.count(b"\n")
    if crlf and crlf != lf:
        raise Recusa(f"fim de linha misto (CRLF e LF) em {path.name}")
    text = raw.decode("utf-8").replace("\r\n", "\n")
    return raw, text, bool(crlf)


def plan(name: str, text: str, edits: list[tuple[str, str]]) -> tuple[str, bool]:
    """Devolve (texto novo, já_aplicado). Recusa estado parcial ou trecho ausente/repetido."""
    done = 0
    for i, (old, new) in enumerate(edits, 1):
        if text.count(new) == 1:
            done += 1
        elif text.count(old) == 1:
            text = text.replace(old, new)
        else:
            raise Recusa(f"{name}: trecho {i} não aparece exatamente uma vez")
    if 0 < done < len(edits):
        raise Recusa(f"{name}: estado parcial ({done} de {len(edits)} trechos já aplicados)")
    return text, done == len(edits)


def encode(text: str, crlf: bool) -> bytes:
    return (text.replace("\n", "\r\n") if crlf else text).encode("utf-8")


def main() -> int:
    try:
        work = []
        for path, edits in ((QPU, QPU_EDITS), (BITS, BITS_EDITS)):
            raw, text, crlf = load(path)
            new_text, applied = plan(path.name, text, edits)
            if not applied:
                compile(new_text, str(path), "exec")
            work.append((path, raw, encode(new_text, crlf), applied))
    except (Recusa, UnicodeDecodeError, SyntaxError) as exc:
        print(f"RECUSADO, nada foi gravado: {exc}")
        return 1
    flags = [w[3] for w in work]
    if all(flags):
        print("R8 já aplicado; nada foi gravado.")
        for path, raw, _, _ in work:
            print(f"  {path.name}: {sha(raw)}")
        return 0
    if any(flags):
        print("RECUSADO, nada foi gravado: um arquivo já tem o R8 e o outro não")
        return 1
    written: list[tuple[Path, bytes]] = []
    try:
        for path, raw, new, _ in work:
            tmp = path.with_suffix(path.suffix + ".r8tmp")
            tmp.write_bytes(new)
            os.replace(tmp, path)
            written.append((path, raw))
    except OSError as exc:
        for path, raw in written:
            path.write_bytes(raw)
        for path, _, _, _ in work:
            path.with_suffix(path.suffix + ".r8tmp").unlink(missing_ok=True)
        print(f"RECUSADO, arquivos restaurados: {exc}")
        return 1
    for path, raw, new, _ in work:
        print(f"{path.name}: {sha(raw)} -> {sha(new)}")
    print("R8 aplicado.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
