"""R8 (Dia 6): retrato da calibração em vigor na execução, gravado no lote da IBM."""
from __future__ import annotations

import importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from eal.sources.ibm_bits import build_ibm_params
from eal.sources.qpu_ibm import _run_snapshot

_spec = importlib.util.spec_from_file_location(
    "_r8_base_test_ibm_bits", Path(__file__).with_name("test_ibm_bits.py"))
_base = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_base)
good_params = _base.good_params

RUN = [0.02, 0.03, 0.4]
RUN_DATE = "2026-11-01 11:57:51-03:00"
WHEN = datetime(2026, 11, 1, 11, 57, 51, tzinfo=timezone(timedelta(hours=-3)))


class Props:
    def __init__(self, errors: dict[int, float], date: object) -> None:
        self._errors = errors
        self.last_update_date = date

    def readout_error(self, q: int) -> float:
        return self._errors[q]


def job_with(props: object) -> SimpleNamespace:
    return SimpleNamespace(properties=lambda: props)


def physical() -> list[int]:
    return build_ibm_params(**good_params())["physical_qubits"]


# ---------------------------------------------------------------- build_ibm_params

def test_sem_retrato_da_execucao_os_campos_ficam_none():
    p = build_ibm_params(**good_params())
    assert p["calibration_date_run"] is None
    assert p["readout_error_run_by_position"] is None


def test_retrato_do_envio_nao_muda():
    p = build_ibm_params(**good_params(readout_error_run=RUN, calibration_date_run=RUN_DATE))
    assert p["readout_error_by_position"] == [0.01, 0.02, 0.5]
    assert p["calibration_date"] == build_ibm_params(**good_params())["calibration_date"]


def test_retrato_da_execucao_gravado():
    p = build_ibm_params(**good_params(readout_error_run=RUN, calibration_date_run=RUN_DATE))
    assert p["readout_error_run_by_position"] == RUN
    assert p["calibration_date_run"] == RUN_DATE


def test_retrato_da_execucao_sem_o_do_envio():
    p = build_ibm_params(**good_params(readout_error=None, calibration_date=None,
                                       readout_error_run=RUN, calibration_date_run=RUN_DATE))
    assert p["readout_error_by_position"] is None
    assert p["readout_error_run_by_position"] == RUN


@pytest.mark.parametrize("changes", [
    {"readout_error_run": RUN},
    {"calibration_date_run": RUN_DATE},
])
def test_retrato_da_execucao_pela_metade_recusado(changes):
    with pytest.raises(ValueError):
        build_ibm_params(**good_params(**changes))


def test_retrato_da_execucao_com_tamanho_errado_recusado():
    with pytest.raises(ValueError):
        build_ibm_params(**good_params(readout_error_run=RUN[:2], calibration_date_run=RUN_DATE))


def test_retrato_da_execucao_fora_de_faixa_recusado():
    with pytest.raises(ValueError):
        build_ibm_params(**good_params(readout_error_run=[0.1, 0.2, 1.5],
                                       calibration_date_run=RUN_DATE))


# ---------------------------------------------------------------- _run_snapshot

def test_run_snapshot_le_por_posicao_e_data():
    phys = physical()
    errors = {q: 0.001 * (i + 1) for i, q in enumerate(phys)}
    got_errors, got_date = _run_snapshot(job_with(Props(errors, WHEN)), phys)
    assert got_errors == [errors[q] for q in phys]
    assert got_date == RUN_DATE


def test_run_snapshot_aceito_pelo_build():
    phys = physical()
    errors, date = _run_snapshot(job_with(Props({q: 0.05 for q in phys}, WHEN)), phys)
    p = build_ibm_params(**good_params(readout_error_run=errors, calibration_date_run=date))
    assert p["readout_error_run_by_position"] == [0.05] * len(phys)
    assert p["calibration_date_run"] == RUN_DATE


def test_run_snapshot_job_sem_properties():
    assert _run_snapshot(SimpleNamespace(), physical()) == (None, None)


def test_run_snapshot_properties_levanta():
    def boom():
        raise RuntimeError("indisponível")
    assert _run_snapshot(SimpleNamespace(properties=boom), physical()) == (None, None)


def test_run_snapshot_qubit_ausente():
    assert _run_snapshot(job_with(Props({}, WHEN)), physical()) == (None, None)


def test_run_snapshot_sem_data():
    phys = physical()
    assert _run_snapshot(job_with(Props({q: 0.05 for q in phys}, None)), phys) == (None, None)


@pytest.mark.parametrize("bad", [float("nan"), -0.01, 1.01])
def test_run_snapshot_valor_invalido(bad):
    phys = physical()
    errors = {q: 0.05 for q in phys}
    errors[phys[0]] = bad
    assert _run_snapshot(job_with(Props(errors, WHEN)), phys) == (None, None)
