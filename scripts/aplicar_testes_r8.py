"""R8 (Dia 6): acrescenta ao fim de tests/test_qpu_ibm.py os testes de integração do _save_result.

Uso único:  py -3.12 scripts\\aplicar_testes_r8.py

Só acrescenta um bloco no fim, marcado por MARKER; não edita nada do que já existe. Tudo ou nada,
idempotente, preserva CRLF ou LF. Recusa sem gravar se o arquivo faltar, tiver fim de linha misto
ou tiver o marcador sem o bloco exato.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TARGET = ROOT / "tests" / "test_qpu_ibm.py"
MARKER = "# --- R8-INTEGRACAO: retrato da calibração em vigor na execução ---"

BLOCK = '''# --- R8-INTEGRACAO: retrato da calibração em vigor na execução ---
RUN_DATE_R8 = "2026-11-01 11:57:51-03:00"


class RunPropsR8:
    """Falso ``job.properties()``: calibração da execução, com defeitos opcionais."""

    last_update_date = RUN_DATE_R8

    def __init__(self, bad=None) -> None:
        self.bad = bad

    def readout_error(self, q: int) -> float:
        if self.bad == "raise":
            raise RuntimeError("sem leitura")
        if self.bad == "range":
            return 1.5
        return 0.02 + 0.001 * q


def _job_com_properties_r8(monkeypatch, props) -> None:
    def properties(self):
        if isinstance(props, Exception):
            raise props
        return props
    monkeypatch.setattr(FakeJob, "properties", properties, raising=False)


def test_r8_lote_grava_o_retrato_da_execucao_separado_do_envio(h, monkeypatch):
    h.rows = np.array([[1, 0, 1], [0, 1, 1]], dtype=bool)
    _job_com_properties_r8(monkeypatch, RunPropsR8())
    result, _ = h.send(shots=2, qubits=[4, 1, 3])
    out = h.collector.retrieve(result.job_id)
    batch = load_batch(h.raw_dir / out.output_file)
    assert batch.params["calibration_date_run"] == RUN_DATE_R8
    assert batch.params["readout_error_run_by_position"] == [0.02 + 0.001 * q for q in (4, 1, 3)]
    assert batch.params["readout_error_by_position"] == [0.01 + 0.001 * q for q in (4, 1, 3)]
    assert batch.params["calibration_date"] != RUN_DATE_R8


def test_r8_job_sem_properties_grava_none_e_fecha_a_conta(h):
    result, job = h.send(shots=4)
    out = h.collector.retrieve(result.job_id)
    assert out.state == "final"
    batch = load_batch(h.raw_dir / out.output_file)
    assert batch.params["calibration_date_run"] is None
    assert batch.params["readout_error_run_by_position"] is None
    assert np.array_equal(batch.bits, job.expected_bits)


@pytest.mark.parametrize("props", [RuntimeError("fora do ar"), RunPropsR8("raise"),
                                   RunPropsR8("range")],
                         ids=["properties-levanta", "leitura-levanta", "valor-fora-de-faixa"])
def test_r8_retrato_ruim_nao_custa_o_lote(h, monkeypatch, props):
    _job_com_properties_r8(monkeypatch, props)
    result, job = h.send(shots=4)
    out = h.collector.retrieve(result.job_id)
    assert out.state == "final"
    batch = load_batch(h.raw_dir / out.output_file)
    assert batch.params["calibration_date_run"] is None
    assert batch.params["readout_error_run_by_position"] is None
    assert np.array_equal(batch.bits, job.expected_bits)
'''


class Recusa(Exception):
    """Algo não bate: nada é gravado."""


def main() -> int:
    try:
        if not TARGET.is_file():
            raise Recusa(f"arquivo ausente: {TARGET}")
        raw = TARGET.read_bytes()
        crlf, lf = raw.count(b"\r\n"), raw.count(b"\n")
        if crlf and crlf != lf:
            raise Recusa("fim de linha misto (CRLF e LF)")
        text = raw.decode("utf-8").replace("\r\n", "\n")
        if text.count(MARKER) > 1:
            raise Recusa("marcador repetido")
        if text.count(MARKER) == 1:
            if text.endswith(BLOCK) and text.count(BLOCK) == 1:
                print("Testes do R8 já presentes; nada foi gravado.")
                return 0
            raise Recusa("o marcador existe, mas o bloco é diferente do esperado")
        if not text.endswith("\n"):
            text += "\n"
        new_text = text + "\n\n" + BLOCK
        compile(new_text, str(TARGET), "exec")
    except (Recusa, UnicodeDecodeError, SyntaxError) as exc:
        print(f"RECUSADO, nada foi gravado: {exc}")
        return 1
    data = (new_text.replace("\n", "\r\n") if crlf else new_text).encode("utf-8")
    tmp = TARGET.with_suffix(".py.r8tmp")
    try:
        tmp.write_bytes(data)
        os.replace(tmp, TARGET)
    except OSError as exc:
        tmp.unlink(missing_ok=True)
        print(f"RECUSADO, nada foi gravado: {exc}")
        return 1
    print("Testes de integração do R8 acrescentados a tests/test_qpu_ibm.py.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
