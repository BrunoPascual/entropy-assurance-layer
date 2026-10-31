"""G6, passo 2: os params do lote entram no recibo (bloco batch_params), por lista fechada.

Fontes de TESTE (SHAKE256 determinístico, não é entropia); pipeline e builder são os reais.
O rótulo da fonte "local" é o mesmo da CLI, que já passa na saúde com DEFAULT_N_BITS.
A semente do extrator vem de uma fonte SEPARADA (SeedStandin), com bits diferentes a cada
leitura: o extrator recusa semente igual ao início do lote.
"""
from __future__ import annotations

import hashlib
import json

import numpy as np
import pytest

from eal.config import DEFAULT_N_BITS, GENESIS_PREV_HASH
from eal.pipeline import run_pipeline
from eal.pqc.keygen import derive_keys_from_mix
from eal.receipt.builder import SOURCE_ENTRY_KEYS, build_receipt_body, clean_batch_params
from eal.receipt.schema import _check_batch_params, batch_param_problems, validate_body
from eal.sources.base import RawBatch, Source

OS_LABEL = b"EAL-v1|test-standin|1"
IBM_LABEL = b"EAL-v1|test-ibm|1"
SEED_LABEL = b"EAL-v1|test-seed|1"
SEGREDO = "SEGREDO-123"
PARAMS = {"backend": "ibm_teste", "job_id": "job-123", "shots": 4096, "qubits": 5}


def _bits(label: bytes, n_bits: int) -> np.ndarray:
    raw = hashlib.shake_256(label).digest((n_bits + 7) // 8)
    return np.unpackbits(np.frombuffer(raw, dtype=np.uint8))[:n_bits].copy()


class OsStandin(Source):
    """Fonte local de TESTE. Nunca usar fora dos testes."""

    source_id = "os_standin"
    source_type = "os"
    is_local = True
    is_simulated = False

    def __init__(self, params: dict | None = None) -> None:
        self.held = params or {}

    def read(self, n_bits: int) -> RawBatch:
        n_bits = self.validate_n_bits(n_bits)
        return self._build_batch(_bits(OS_LABEL, n_bits), dict(self.held))


class IbmFake(Source):
    """Fonte remota de TESTE com tipo qpu_ibm. Não é a QPU."""

    source_id = "ibm_fake"
    source_type = "qpu_ibm"
    is_local = False
    is_simulated = False

    def __init__(self, params: dict) -> None:
        self.held = params

    def read(self, n_bits: int) -> RawBatch:
        n_bits = self.validate_n_bits(n_bits)
        return self._build_batch(_bits(IBM_LABEL, n_bits), dict(self.held))


class SeedStandin(Source):
    """Fonte de TESTE para a semente do extrator: bits novos a cada leitura. Não é entropia."""

    source_id = "seed_standin"
    source_type = "os"
    is_local = True
    is_simulated = False

    def __init__(self) -> None:
        self.calls = 0

    def read(self, n_bits: int) -> RawBatch:
        n_bits = self.validate_n_bits(n_bits)
        self.calls += 1
        return self._build_batch(_bits(SEED_LABEL + bytes([self.calls]), n_bits), {})


def _body(os_params: dict | None = None, ibm_params: dict | None = None, with_ibm: bool = False) -> dict:
    srcs = [OsStandin(os_params)]
    if with_ibm:
        srcs.append(IbmFake(ibm_params or {}))
    res = run_pipeline(srcs, SeedStandin(), mode="keygen", n_bits=DEFAULT_N_BITS)
    assert res.mix is not None, "fail-closed inesperado nos testes"
    keys = derive_keys_from_mix(res.mix)
    return build_receipt_body(res, keys, srcs, prev_receipt_hash=GENESIS_PREV_HASH)


# ---------------------------------------------------------------- clean_batch_params

def test_clean_descarta_chaves_fora_da_lista():
    sujo = {**PARAMS, "token": SEGREDO, "seed": "abc", "label": "x"}
    assert clean_batch_params(sujo) == PARAMS


def test_clean_none_vira_vazio():
    assert clean_batch_params(None) == {}
    assert clean_batch_params({}) == {}


def test_clean_converte_inteiro_do_numpy():
    out = clean_batch_params({"shots": np.int64(100), "qubits": np.int32(5)})
    assert out == {"shots": 100, "qubits": 5}
    assert type(out["shots"]) is int


@pytest.mark.parametrize("key, value", [
    ("job_id", "valor ruim!"), ("job_id", ""), ("job_id", "a" * 65), ("job_id", 7),
    ("backend", "a/b"), ("backend", None),
    ("shots", True), ("shots", 0), ("shots", -1), ("shots", "10"), ("shots", 10**9 + 1),
    ("qubits", 1.5), ("qubits", False),
])
def test_clean_recusa_valor_invalido_sem_citar_o_valor(key, value):
    with pytest.raises(ValueError) as exc:
        clean_batch_params({"job_id": "j", key: value})
    assert key in str(exc.value)
    assert "valor ruim" not in str(exc.value)


def test_clean_recusa_params_que_nao_e_objeto():
    with pytest.raises(ValueError):
        clean_batch_params(["job_id"])


# ---------------------------------------------------------------- schema

def test_problemas_citam_nomes_e_nunca_valores():
    msg = " ".join(batch_param_problems({"job_id": SEGREDO + " !", "token": SEGREDO}, "w"))
    assert "job_id" in msg and "token" in msg
    assert SEGREDO not in msg.replace("token", "")


def test_params_validos_sem_problemas():
    assert batch_param_problems(dict(PARAMS), "w") == []
    assert batch_param_problems({}, "w") == []


def test_fonte_qpu_ibm_com_lote_exige_job_id_no_esquema():
    src = {"source_type": "qpu_ibm", "batch_hash": "a" * 64}
    assert any("job_id" in p for p in _check_batch_params(0, src))
    assert any("job_id" in p for p in _check_batch_params(0, {**src, "batch_params": {}}))
    assert _check_batch_params(0, {**src, "batch_params": {"job_id": "j-1"}}) == []


def test_fonte_qpu_ibm_sem_lote_nao_exige_job_id():
    assert _check_batch_params(0, {"source_type": "qpu_ibm", "batch_hash": None}) == []


# ---------------------------------------------------------------- builder + recibo

def test_job_id_e_params_aparecem_no_recibo():
    body = _body(os_params=dict(PARAMS))
    assert body["sources"][0]["batch_params"] == PARAMS
    assert validate_body(body) == []


def test_chave_fora_da_lista_nao_chega_ao_recibo():
    body = _body(os_params={**PARAMS, "token": SEGREDO, "seed": SEGREDO, "label": "x"})
    assert body["sources"][0]["batch_params"] == PARAMS
    assert SEGREDO not in json.dumps(body)


def test_fonte_sem_params_tem_batch_params_vazio():
    body = _body()
    assert body["sources"][0]["batch_params"] == {}
    assert validate_body(body) == []


def test_o_bloco_da_fonte_tem_exatamente_as_chaves_da_lista_fechada():
    body = _body(os_params=dict(PARAMS))
    assert set(body["sources"][0]) == SOURCE_ENTRY_KEYS


def test_builder_recusa_job_id_invalido_sem_citar_o_valor():
    with pytest.raises(ValueError) as exc:
        _body(os_params={"job_id": "valor ruim!"})
    assert "job_id" in str(exc.value) and "valor ruim" not in str(exc.value)


def test_recibo_antigo_sem_batch_params_continua_valido():
    body = _body(os_params=dict(PARAMS))
    for entry in body["sources"]:
        del entry["batch_params"]
    assert validate_body(body) == []


def test_qpu_ibm_com_job_id_entra_no_recibo():
    body = _body(with_ibm=True, ibm_params={"backend": "ibm_teste", "job_id": "job-9", "shots": 100})
    ibm = next(s for s in body["sources"] if s["source_id"] == "ibm_fake")
    assert ibm["batch_params"] == {"backend": "ibm_teste", "job_id": "job-9", "shots": 100}
    assert validate_body(body) == []


def test_qpu_ibm_sem_job_id_recusa_o_recibo():
    with pytest.raises(ValueError, match="job_id"):
        _body(with_ibm=True, ibm_params={"backend": "ibm_teste"})


def test_esquema_recusa_qpu_ibm_sem_job_id_mesmo_fora_do_builder():
    body = _body(os_params=dict(PARAMS))
    body["sources"][0]["source_type"] = "qpu_ibm"
    del body["sources"][0]["batch_params"]
    assert any("job_id" in p for p in validate_body(body))
