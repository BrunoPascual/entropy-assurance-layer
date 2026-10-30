"""Vetores oficiais (NIST ACVP) para o key_derive das bibliotecas PQC (Dia 5, etapa 1).

O que isto cobre: kyber-py e dilithium-py, dado o material interno (d||z para
ML-KEM-768; xi para ML-DSA-65), produzem exatamente as chaves dos vetores
oficiais do CAVP (FIPS 203 e FIPS 204).

O que NÃO cobre: a derivação da EAL (SHAKE256 com prefixo de domínio sobre a
semente de 64 bytes). Ela é do projeto e não tem vetor oficial; fica presa à
especificação em tests/test_pqc_keygen.py::test_derivacao_segue_a_especificacao.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from dilithium_py.ml_dsa import ML_DSA_65
from kyber_py.ml_kem import ML_KEM_768

KAT_DIR = Path(__file__).parent / "data" / "kat"
SOURCE = json.loads((KAT_DIR / "SOURCE.json").read_text(encoding="utf-8"))


def _load(name: str) -> dict:
    return json.loads((KAT_DIR / name).read_text(encoding="utf-8"))


def _canonical_hash(data: object) -> str:
    text = json.dumps(data, sort_keys=True, separators=(",", ":"))
    return hashlib.sha3_256(text.encode("utf-8")).hexdigest()


KEM = _load("ml_kem_768_keygen.json")
DSA = _load("ml_dsa_65_keygen.json")
KEM_TESTS = KEM["testGroups"][0]["tests"]
DSA_TESTS = DSA["testGroups"][0]["tests"]


# --- Integridade e estrutura dos arquivos ---------------------------------

@pytest.mark.parametrize(
    "name, data", [("ml_kem_768_keygen.json", KEM), ("ml_dsa_65_keygen.json", DSA)]
)
def test_arquivo_de_vetores_confere_com_o_hash_registrado(name, data):
    assert _canonical_hash(data) == SOURCE["arquivos"][name]["subconjunto_sha3_256_canonico"]


def test_estrutura_dos_vetores():
    assert len(KEM["testGroups"]) == 1 and len(DSA["testGroups"]) == 1
    assert KEM["testGroups"][0]["parameterSet"] == "ML-KEM-768"
    assert DSA["testGroups"][0]["parameterSet"] == "ML-DSA-65"
    assert (KEM["revision"], DSA["revision"]) == ("FIPS203", "FIPS204")
    assert KEM["isSample"] is False and DSA["isSample"] is False
    assert len(KEM_TESTS) == 25 and len(DSA_TESTS) == 25
    assert not any(t["deferred"] for t in KEM_TESTS + DSA_TESTS)


def test_tamanhos_dos_vetores_batem_com_os_padroes():
    t = KEM_TESTS[0]
    assert (len(t["d"]), len(t["z"])) == (64, 64)  # hex: 32 bytes cada
    assert (len(t["ek"]) // 2, len(t["dk"]) // 2) == (1184, 2400)
    s = DSA_TESTS[0]
    assert len(s["seed"]) // 2 == 32
    assert (len(s["pk"]) // 2, len(s["sk"]) // 2) == (1952, 4032)


# --- ML-KEM-768 (FIPS 203) ------------------------------------------------

@pytest.mark.parametrize("t", KEM_TESTS, ids=lambda t: f"tcId{t['tcId']}")
def test_ml_kem_768_key_derive_reproduz_o_vetor(t):
    ek, dk = ML_KEM_768.key_derive(bytes.fromhex(t["d"] + t["z"]))
    assert ek.hex().upper() == t["ek"].upper()
    assert dk.hex().upper() == t["dk"].upper()


def test_ml_kem_768_vetor_encapsula_e_decapsula():
    t = KEM_TESTS[0]
    ek, dk = bytes.fromhex(t["ek"]), bytes.fromhex(t["dk"])
    ss, ct = ML_KEM_768.encaps(ek)
    assert ML_KEM_768.decaps(dk, ct) == ss


# --- ML-DSA-65 (FIPS 204) -------------------------------------------------

@pytest.mark.parametrize("t", DSA_TESTS, ids=lambda t: f"tcId{t['tcId']}")
def test_ml_dsa_65_key_derive_reproduz_o_vetor(t):
    pk, sk = ML_DSA_65.key_derive(bytes.fromhex(t["seed"]))
    assert pk.hex().upper() == t["pk"].upper()
    assert sk.hex().upper() == t["sk"].upper()


def test_ml_dsa_65_vetor_assina_e_verifica():
    t = DSA_TESTS[0]
    pk, sk = bytes.fromhex(t["pk"]), bytes.fromhex(t["sk"])
    sig = ML_DSA_65.sign(sk, b"EAL KAT", deterministic=True)
    assert ML_DSA_65.verify(pk, b"EAL KAT", sig)


# --- Controle: o teste não passa por acaso --------------------------------

def test_um_bit_de_diferenca_na_semente_nao_reproduz_o_vetor():
    t = KEM_TESTS[0]
    seed = bytearray.fromhex(t["d"] + t["z"])
    seed[0] ^= 0x01
    ek, _ = ML_KEM_768.key_derive(bytes(seed))
    assert ek.hex().upper() != t["ek"].upper()
    s = DSA_TESTS[0]
    xi = bytearray.fromhex(s["seed"])
    xi[0] ^= 0x01
    pk, _ = ML_DSA_65.key_derive(bytes(xi))
    assert pk.hex().upper() != s["pk"].upper()
