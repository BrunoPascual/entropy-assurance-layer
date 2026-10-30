"""Testes do construtor do recibo com objetos falsos (Dia 5, etapa 2B).

Os falsos seguem os nomes reais de PipelineResult, SourceOutcome, MixInput,
MixResult, HealthReport, ExtractionResult e Source. A integração com o
pipeline real fica em tests/test_receipt_pipeline.py.
"""
from __future__ import annotations

import base64
import hashlib
import json
import uuid
from types import SimpleNamespace

import numpy as np
import pytest

from eal.config import (
    DSA_DOMAIN,
    EAL_VERSION,
    ISSUER_DOMAIN,
    RECEIPT_ID_NAMESPACE,
    RECEIPT_REQUIRED_LIMITATIONS,
)
from eal.pqc.keygen import derive_keys, derive_keys_from_mix
from eal.receipt.builder import (
    build_receipt_body,
    issuer_seed_from_mix,
    receipt_id_for,
    software_versions,
    to_native,
)
from eal.receipt.schema import validate_body
from eal.receipt.sign import issuer_key_from_seed, sign_receipt
from eal.receipt.verify import verify_receipt

SEED = bytes(range(64))
OTHER_SEED = bytes(range(1, 65))
SEED_HASH = hashlib.sha3_256(SEED).hexdigest()
H1, H2, H3 = "11" * 32, "22" * 32, "33" * 32
CREATED = "2026-10-30T19:00:00+00:00"
SOFTWARE = {"python": "3.12.10", "kyber-py": "1.2.0", "dilithium-py": "1.5.1"}


def _frag(data: bytes, n: int = 40) -> str:
    return repr(data)[2:-1][:n]


def _src(sid, stype, local, sim):
    return SimpleNamespace(source_id=sid, source_type=stype, source_version="0.1.0",
                           is_local=local, is_simulated=sim)


def _report(approved, **extra):
    d = {"approved": bool(approved), "stats": {"monobit": np.float64(0.41)},
         "rct_pass": np.True_, "reasons": [], **extra}
    return SimpleNamespace(approved=np.bool_(approved), to_dict=lambda: d)


def _extraction(kind="toeplitz", m=1825):
    d = {"extractor_type": kind, "m": np.int64(m), "seed_hash": H3}
    return SimpleNamespace(extractor_type=kind, to_dict=lambda: d)


def _input(sid, batch_id, input_hash, local, sim, approved=True, kind="toeplitz"):
    return SimpleNamespace(source_id=sid, batch_id=batch_id, input_hash=input_hash,
                           is_local=np.bool_(local), is_simulated=np.bool_(sim),
                           report=_report(approved), extraction=_extraction(kind))


def _outcome(sid, status, batch_id=None, reasons=()):
    return SimpleNamespace(source_id=sid, status=status, batch_id=batch_id, reasons=reasons)


def _mix(seed=SEED, mode="keygen", usable=True, meta=None):
    seed_hash = hashlib.sha3_256(seed).hexdigest()
    d = meta if meta is not None else {"mode": mode, "usable_for_key": np.bool_(usable),
                                       "seed_hash": seed_hash, "included": ["ibm_x", "os"]}
    return SimpleNamespace(mode=mode, usable_for_key=usable, seed=seed,
                           seed_hash=seed_hash, to_dict=lambda: d)


def _scenario(**over):
    """Execução keygen: os e ibm_x misturadas, ibm_ruim reprovada, ibm_fora sem leitura."""
    sources = [_src("os", "os", True, False), _src("ibm_x", "qpu_ibm", False, False),
               _src("ibm_ruim", "qpu_ibm", False, False), _src("ibm_fora", "qpu_ibm", False, False)]
    inputs = [_input("os", "b-os", H1, True, False),
              _input("ibm_x", "b-x", H2, False, False),
              _input("ibm_ruim", "b-r", H3, False, False, approved=False, kind="none")]
    outcomes = [_outcome("os", "mixed", "b-os"), _outcome("ibm_x", "mixed", "b-x"),
                _outcome("ibm_ruim", "excluded", "b-r", ("APT: viés",)),
                _outcome("ibm_fora", "read_failed", None, ("leitura falhou: TimeoutError",))]
    result = SimpleNamespace(mode="keygen", outcomes=tuple(outcomes), mix=_mix(),
                             error=None, inputs=tuple(inputs))
    for k, v in over.items():
        setattr(result, k, v)
    return result, sources


@pytest.fixture(scope="module")
def keys():
    return derive_keys(SEED)


@pytest.fixture(scope="module")
def body(keys):
    result, sources = _scenario()
    return build_receipt_body(result, keys, sources, created_at=CREATED, software=SOFTWARE)


def _build(keys, result, sources, **kw):
    return build_receipt_body(result, keys, sources, created_at=CREATED, software=SOFTWARE, **kw)


# --- 1. Corpo montado -------------------------------------------------------

def test_corpo_valido(body):
    assert validate_body(body) == []


def test_campos_de_topo(body, keys):
    assert body["eal_version"] == EAL_VERSION
    assert body["mode"] == "keygen"
    assert body["created_at"] == CREATED
    assert body["software"] == SOFTWARE
    assert body["seed_hash"] == SEED_HASH
    assert body["keys"] == keys.public_summary()
    assert body["receipt_id"] == str(uuid.uuid5(uuid.UUID(RECEIPT_ID_NAMESPACE), SEED_HASH))
    assert body["limitations"] == list(RECEIPT_REQUIRED_LIMITATIONS)
    assert body["extractor"] == {"type": "toeplitz", "n": 2048, "epsilon_log2": -64}
    assert body["mixer"]["seed_hash"] == SEED_HASH


def test_fontes_na_ordem_da_execucao(body):
    assert [s["source_id"] for s in body["sources"]] == ["os", "ibm_x", "ibm_ruim", "ibm_fora"]
    assert [s["status"] for s in body["sources"]] == ["mixed", "mixed", "excluded", "read_failed"]


def test_fonte_misturada_traz_hash_saude_e_extracao(body):
    os_entry = body["sources"][0]
    assert os_entry["batch_hash"] == H1 and os_entry["batch_id"] == "b-os"
    assert os_entry["approved"] is True
    assert os_entry["source_type"] == "os" and os_entry["source_version"] == "0.1.0"
    assert os_entry["health"]["stats"]["monobit"] == 0.41
    assert type(os_entry["health"]["stats"]["monobit"]) is float
    assert type(os_entry["health"]["rct_pass"]) is bool
    assert type(os_entry["extraction"]["m"]) is int


def test_fonte_reprovada_fica_registrada_com_motivo(body):
    ruim = body["sources"][2]
    assert ruim["approved"] is False and ruim["reasons"] == ["APT: viés"]
    assert ruim["batch_hash"] == H3


def test_fonte_sem_leitura_usa_flags_do_objeto(body):
    fora = body["sources"][3]
    assert fora["is_local"] is False and fora["is_simulated"] is False
    assert fora["approved"] is False
    assert fora["batch_hash"] is None and fora["health"] is None and fora["extraction"] is None
    assert fora["reasons"] == ["leitura falhou: TimeoutError"]


def test_assinado_e_verificado(body):
    issuer = issuer_key_from_seed(bytes(range(100, 132)))
    assert verify_receipt(sign_receipt(body, issuer), issuer.pk).ok


def test_prev_receipt_hash_e_repassado(keys):
    result, sources = _scenario()
    assert _build(keys, result, sources, prev_receipt_hash=H1)["prev_receipt_hash"] == H1


def test_created_at_padrao_e_utc(keys):
    result, sources = _scenario()
    b = build_receipt_body(result, keys, sources, software=SOFTWARE)
    assert b["created_at"].endswith("+00:00")


# --- 2. Sigilo --------------------------------------------------------------

def test_recibo_nao_contem_semente_nem_chave_privada(body, keys):
    texto = json.dumps(body, ensure_ascii=False)
    for parte in (SEED, keys.kem_dk[:32], keys.kem_dk[-32:], keys.dsa_sk[32:64]):
        assert parte.hex()[:32] not in texto
        assert _frag(parte) not in texto
        assert base64.b64encode(parte).decode()[:24] not in texto


# --- 3. Recusas -------------------------------------------------------------

def _mut_result(**over):
    return _scenario(**over)


REFUSALS = {
    "modo experiment": lambda: _mut_result(mode="experiment"),
    "sem semente": lambda: _mut_result(mix=None),
    "com erro de política": lambda: _mut_result(error="política"),
    "mix experiment": lambda: _mut_result(mix=_mix(mode="experiment", usable=False)),
}


@pytest.mark.parametrize("make", REFUSALS.values(), ids=REFUSALS.keys())
def test_execucao_sem_recibo(keys, make):
    result, sources = make()
    with pytest.raises(ValueError):
        _build(keys, result, sources)


def test_chaves_de_outra_semente_sao_recusadas():
    result, sources = _scenario()
    with pytest.raises(ValueError):
        _build(derive_keys(OTHER_SEED), result, sources)


def test_keys_precisa_ser_derivedkeys(keys):
    result, sources = _scenario()
    with pytest.raises(TypeError):
        _build(SimpleNamespace(public_summary=keys.public_summary), result, sources)


def test_fonte_sem_objeto_e_recusada(keys):
    result, sources = _scenario()
    with pytest.raises(ValueError):
        _build(keys, result, sources[:3])


def test_objeto_de_fonte_repetido_e_recusado(keys):
    result, sources = _scenario()
    with pytest.raises(ValueError):
        _build(keys, result, sources + [_src("os", "os", True, False)])


def test_resultado_repetido_e_recusado(keys):
    result, sources = _scenario()
    result.outcomes = result.outcomes + (_outcome("os", "mixed", "b-os"),)
    with pytest.raises(ValueError):
        _build(keys, result, sources)


def test_flags_do_lote_diferentes_da_fonte(keys):
    result, sources = _scenario()
    sources[1].is_local = True  # o lote diz remoto, o objeto diz local
    with pytest.raises(ValueError):
        _build(keys, result, sources)


@pytest.mark.parametrize("flag", [1, None, "True"], ids=["int", "None", "str"])
def test_flag_da_fonte_nao_booleana(keys, flag):
    result, sources = _scenario()
    sources[3].is_local = flag
    with pytest.raises(ValueError):
        _build(keys, result, sources)


def test_batch_id_inconsistente(keys):
    result, sources = _scenario()
    result.outcomes = (_outcome("os", "mixed", "outro"),) + result.outcomes[1:]
    with pytest.raises(ValueError):
        _build(keys, result, sources)


def test_fonte_misturada_sem_toeplitz(keys):
    result, sources = _scenario()
    inputs = list(result.inputs)
    inputs[0] = _input("os", "b-os", H1, True, False, kind="sha3")
    result.inputs = tuple(inputs)
    with pytest.raises(ValueError):
        _build(keys, result, sources)


def test_fonte_simulada_na_execucao(keys):
    result, sources = _scenario()
    sources[3].is_simulated = True
    with pytest.raises(ValueError):
        _build(keys, result, sources)


def test_bytes_nos_metadados_sao_recusados(keys):
    result, sources = _scenario(mix=_mix(meta={"seed_hash": SEED_HASH, "x": b"\x00"}))
    with pytest.raises(TypeError):
        _build(keys, result, sources)


def test_nan_nos_metadados_e_recusado(keys):
    result, sources = _scenario()
    inputs = list(result.inputs)
    inputs[0].report = _report(True, h_estimated=float("nan"))
    result.inputs = tuple(inputs)
    with pytest.raises(ValueError):
        _build(keys, result, sources)


def test_seed_hash_do_mixer_inconsistente(keys):
    result, sources = _scenario(mix=_mix(meta={"seed_hash": H1}))
    with pytest.raises(ValueError):
        _build(keys, result, sources)


# --- 4. Auxiliares ----------------------------------------------------------

def test_to_native_converte_numpy_e_tuplas():
    out = to_native({"a": (np.int64(1), np.float32(0.5)), "b": np.bool_(False), "c": None})
    assert out == {"a": [1, 0.5], "b": False, "c": None}
    assert type(out["a"][0]) is int and type(out["b"]) is bool


@pytest.mark.parametrize("bad", [b"x", {1: "a"}, object(), float("inf")], ids=["bytes", "chave int", "objeto", "inf"])
def test_to_native_recusa(bad):
    with pytest.raises((TypeError, ValueError)):
        to_native({"x": bad})


def test_receipt_id_deterministico_e_distinto():
    assert receipt_id_for(H1) == receipt_id_for(H1)
    assert receipt_id_for(H1) != receipt_id_for(H2)
    assert str(uuid.UUID(receipt_id_for(H1))) == receipt_id_for(H1)


def test_software_versions():
    v = software_versions()
    assert {"python", "kyber-py", "dilithium-py"} <= v.keys()
    assert v["kyber-py"] == "1.2.0" and v["dilithium-py"] == "1.5.1"


# --- 5. Semente do emissor --------------------------------------------------

def test_semente_do_emissor_segue_a_especificacao():
    xi = issuer_seed_from_mix(_mix())
    assert xi == hashlib.shake_256(ISSUER_DOMAIN + SEED).digest(32)
    assert xi == issuer_seed_from_mix(_mix())


def test_semente_do_emissor_separada_das_chaves_do_usuario():
    xi = issuer_seed_from_mix(_mix())
    assert xi != hashlib.shake_256(DSA_DOMAIN + SEED).digest(32)
    assert issuer_key_from_seed(xi).pk != derive_keys_from_mix(_mix()).dsa_pk


@pytest.mark.parametrize("mix", [None, _mix(mode="experiment", usable=False)], ids=["None", "experiment"])
def test_semente_do_emissor_recusa_mix_invalido(mix):
    with pytest.raises(ValueError):
        issuer_seed_from_mix(mix)
