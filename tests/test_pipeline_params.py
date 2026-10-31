"""G6, passo 1: o SourceOutcome carrega os params do lote (cópia rasa), fora do to_dict().

Fontes de TESTE (SHAKE256 determinístico, não é entropia). O pipeline é o real.
"""
from __future__ import annotations

import hashlib
from types import SimpleNamespace

import numpy as np

from eal.config import DEFAULT_N_BITS
from eal.pipeline import SourceOutcome, run_pipeline
from eal.sources.base import RawBatch, Source

LABEL = b"EAL-v1|test-g6|1"


class ParamSource(Source):
    """Fonte de TESTE com params à escolha. Nunca usar fora dos testes."""

    source_id = "param_source"
    source_type = "os"
    is_local = True
    is_simulated = False

    def __init__(self, params: dict) -> None:
        self.held = params

    def read(self, n_bits: int) -> RawBatch:
        n_bits = self.validate_n_bits(n_bits)
        raw = hashlib.shake_256(LABEL).digest((n_bits + 7) // 8)
        bits = np.unpackbits(np.frombuffer(raw, dtype=np.uint8))[:n_bits].copy()
        return self._build_batch(bits, self.held)


class ReadFails(Source):
    source_id = "read_fails"
    source_type = "os"
    is_local = True
    is_simulated = False

    def read(self, n_bits: int) -> RawBatch:
        raise RuntimeError("segredo-do-provedor")


PARAMS = {"backend": "ibm_teste", "job_id": "job-123"}


def _run(sources, seed=None, **kwargs):
    return run_pipeline(sources, seed or ParamSource({}), mode="keygen", n_bits=DEFAULT_N_BITS, **kwargs)


def test_params_do_lote_chegam_ao_outcome():
    res = _run([ParamSource(dict(PARAMS))])
    assert res.outcomes[0].params == PARAMS


def test_params_chegam_tambem_quando_a_saude_falha():
    def boom(batch, detector, h_declared):
        raise RuntimeError("x")

    res = _run([ParamSource(dict(PARAMS))], health_fn=boom)
    assert res.outcomes[0].status == "health_failed"
    assert res.outcomes[0].params == PARAMS


def test_params_chegam_tambem_quando_a_extracao_falha():
    def sem_h(batch, detector, h_declared):
        return SimpleNamespace(approved=True, h_estimated=None, h_declared=h_declared, reasons=())

    res = _run([ParamSource(dict(PARAMS))], health_fn=sem_h)
    assert res.outcomes[0].status == "extraction_failed"
    assert res.outcomes[0].params == PARAMS


def test_leitura_que_falha_nao_tem_params():
    res = _run([ReadFails()])
    assert res.outcomes[0].status == "read_failed"
    assert res.outcomes[0].params is None


def test_params_ficam_fora_do_to_dict():
    res = _run([ParamSource(dict(PARAMS))])
    assert all("params" not in o for o in res.to_dict()["outcomes"])
    assert "job-123" not in str(res.to_dict())


def test_outcome_guarda_copia_e_nao_o_dict_da_fonte():
    src = ParamSource(dict(PARAMS))
    res = _run([src])
    src.held["job_id"] = "alterado-depois"
    assert res.outcomes[0].params == PARAMS


def test_params_nao_entram_na_comparacao_nem_no_repr():
    a = SourceOutcome("a", "mixed")
    b = SourceOutcome("a", "mixed", params={"job_id": "j"})
    assert a == b
    assert "job_id" not in repr(b)
