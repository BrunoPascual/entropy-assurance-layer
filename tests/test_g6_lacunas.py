"""Lacunas do G6 apontadas pelas mutações (pendência P2 do Dia 6).

1. O construtor do recibo exige ``job_id`` de uma fonte ``qpu_ibm`` com lote lido
   (``_require_job_id``). Nenhum teste conferia ESSA recusa com a mensagem dela: a remoção da
   checagem sobrevivia, provavelmente porque outra camada também recusa o recibo e os testes só
   olhavam se houve recusa, não qual. Aqui a mensagem do construtor é conferida diretamente.
2. O validador do recibo precisa ACUSAR ``batch_params`` que não é objeto (devolver o problema),
   e não quebrar com exceção: um validador fail-closed lista problemas, não estoura.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from eal.receipt.builder import _require_job_id
from eal.receipt.schema import _check_batch_params, batch_param_problems

JOB_MESSAGE = "fonte do tipo qpu_ibm sem job_id nos params do lote"


def outcome(batch_id="lote-1"):
    return SimpleNamespace(batch_id=batch_id)


def source(source_type="qpu_ibm"):
    return SimpleNamespace(source_type=source_type)


# ------------------------------------------------------------------ construtor: _require_job_id

def test_construtor_recusa_qpu_ibm_com_lote_sem_job_id():
    with pytest.raises(ValueError, match=JOB_MESSAGE):
        _require_job_id(outcome(), source(), {"batch_params": {"backend": "ibm_kingston"}})


def test_construtor_recusa_qpu_ibm_com_params_vazios():
    with pytest.raises(ValueError, match=JOB_MESSAGE):
        _require_job_id(outcome(), source(), {"batch_params": {}})


def test_mensagem_do_construtor_nao_cita_valores_dos_params():
    with pytest.raises(ValueError) as info:
        _require_job_id(outcome(), source(),
                        {"batch_params": {"backend": "ibm_kingston", "shots": 4096}})
    assert "ibm_kingston" not in str(info.value) and "4096" not in str(info.value)


def test_construtor_aceita_qpu_ibm_com_job_id():
    assert _require_job_id(outcome(), source(),
                           {"batch_params": {"job_id": "dbji1pgnceqs73ak2c8g"}}) is None


def test_construtor_nao_exige_job_id_sem_lote_lido():
    assert _require_job_id(outcome(batch_id=None), source(), {"batch_params": {}}) is None


@pytest.mark.parametrize("source_type", ["os", "qpu_sim", "faulty"])
def test_construtor_nao_exige_job_id_de_outros_tipos(source_type):
    assert _require_job_id(outcome(), source(source_type), {"batch_params": {}}) is None


# ------------------------------------------------------------------ validador: não-objeto

@pytest.mark.parametrize("bad", [None, [], ["job_id"], "job_id", 5, ("job_id",), True])
def test_params_que_nao_sao_objeto_viram_problema_sem_excecao(bad):
    assert batch_param_problems(bad, "w") == ["w não é objeto"]


@pytest.mark.parametrize("bad", [None, [], "x", 0])
def test_validador_acusa_batch_params_que_nao_e_objeto(bad):
    problems = _check_batch_params(0, {"source_type": "os", "batch_hash": "h", "batch_params": bad})
    assert problems == ["sources[0].batch_params não é objeto"]


def test_validador_acusa_os_dois_problemas_em_fonte_que_exige_job_id():
    problems = _check_batch_params(
        2, {"source_type": "qpu_ibm", "batch_hash": "h", "batch_params": None})
    assert problems == ["sources[2].batch_params não é objeto",
                        "sources[2].batch_params.job_id ausente em fonte que exige job_id"]
