"""Testes do núcleo do recibo (Dia 5, etapa 2A): formato, emissor, assinatura, verificação.

Não depende do pipeline: o corpo do recibo é montado aqui à mão. O construtor
a partir do PipelineResult (etapa 2B) terá testes próprios.
"""
from __future__ import annotations

import base64
import copy
import hashlib
import json
import math

import numpy as np
import pytest
from dilithium_py.ml_dsa import ML_DSA_65

from eal.config import GENESIS_PREV_HASH, RECEIPT_CTX, RECEIPT_REQUIRED_LIMITATIONS
from eal.receipt.schema import (
    canonical_bytes,
    receipt_body,
    receipt_hash,
    validate_body,
)
from eal.receipt.sign import (
    IssuerKey,
    issuer_key_from_seed,
    load_issuer_key,
    load_issuer_public_key,
    save_issuer_key,
    sign_receipt,
)
from eal.receipt.verify import parse_receipt_json, verify_receipt, verify_receipt_text

ISSUER_XI = bytes(range(100, 132))
OTHER_XI = bytes(range(200, 232))
H = "ab" * 32  # um SHA3-256 qualquer em hex


def _frag(data: bytes, n: int = 40) -> str:
    return repr(data)[2:-1][:n]


def _source(sid, *, status="mixed", local=True, sim=False, approved=True):
    return {"source_id": sid, "status": status, "is_local": local,
            "is_simulated": sim, "approved": approved}


def _body() -> dict:
    """Corpo válido mínimo, no formato da seção 6.11."""
    return {
        "eal_version": "0.1.0",
        "receipt_id": "3f2b1c9e-1111-4222-8333-444455556666",
        "created_at": "2026-10-30T18:00:00+00:00",
        "mode": "keygen",
        "prev_receipt_hash": GENESIS_PREV_HASH,
        "software": {"python": "3.12.10", "kyber-py": "1.2.0", "dilithium-py": "1.5.1"},
        "sources": [
            _source("ibm_kingston", local=False, status="mixed"),
            _source("os"),
            {**_source("faulty_x", status="excluded", approved=False), "reasons": ["APT"]},
        ],
        "extractor": {"type": "toeplitz", "n": 2048, "epsilon_log2": -64, "seed_hash": H},
        "mixer": {"type": "sha3-512", "inputs": ["ibm_kingston", "os"]},
        "seed_hash": H,
        "keys": {"ml_kem_768_pk_hash": H, "ml_dsa_65_pk_hash": H},
        "limitations": list(RECEIPT_REQUIRED_LIMITATIONS),
    }


@pytest.fixture(scope="module")
def issuer() -> IssuerKey:
    return issuer_key_from_seed(ISSUER_XI)


@pytest.fixture(scope="module")
def other_issuer() -> IssuerKey:
    return issuer_key_from_seed(OTHER_XI)


@pytest.fixture(scope="module")
def signed(issuer) -> dict:
    return sign_receipt(_body(), issuer)


# --- 1. JSON canônico ------------------------------------------------------

def test_canonico_independe_da_ordem_das_chaves():
    a = {"b": 1, "a": {"y": 2, "x": [3, 1]}}
    b = {"a": {"x": [3, 1], "y": 2}, "b": 1}
    assert canonical_bytes(a) == canonical_bytes(b) == b'{"a":{"x":[3,1],"y":2},"b":1}'


def test_canonico_preserva_utf8():
    assert canonical_bytes({"m": "não"}) == '{"m":"não"}'.encode("utf-8")


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf], ids=["nan", "inf", "-inf"])
def test_canonico_recusa_nan_e_infinito(bad):
    with pytest.raises(ValueError):
        canonical_bytes({"x": bad})


@pytest.mark.parametrize("bad", [np.bool_(True), np.int64(3), b"bytes"], ids=["np.bool_", "np.int64", "bytes"])
def test_canonico_recusa_tipos_fora_do_json(bad):
    with pytest.raises(TypeError):
        canonical_bytes({"x": bad})


# --- 2. Validação do corpo -------------------------------------------------

def test_corpo_valido_nao_tem_problemas():
    assert validate_body(_body()) == []


def _mut(fn):
    body = _body()
    fn(body)
    return body


INVALID_BODIES = {
    "não é dict": lambda: [],
    "campo ausente": lambda: _mut(lambda b: b.pop("seed_hash")),
    "campo desconhecido": lambda: _mut(lambda b: b.update(extra=1)),
    "assinatura dentro do corpo": lambda: _mut(lambda b: b.update(signature={})),
    "modo experiment": lambda: _mut(lambda b: b.update(mode="experiment")),
    "eal_version vazio": lambda: _mut(lambda b: b.update(eal_version="")),
    "uuid maiúsculo": lambda: _mut(lambda b: b.update(receipt_id=b["receipt_id"].upper())),
    "uuid inválido": lambda: _mut(lambda b: b.update(receipt_id="abc")),
    "data sem fuso": lambda: _mut(lambda b: b.update(created_at="2026-10-30T18:00:00")),
    "data fora de UTC": lambda: _mut(lambda b: b.update(created_at="2026-10-30T18:00:00-03:00")),
    "seed_hash maiúsculo": lambda: _mut(lambda b: b.update(seed_hash=H.upper())),
    "prev curto": lambda: _mut(lambda b: b.update(prev_receipt_hash="0" * 63)),
    "keys com campo a mais": lambda: _mut(lambda b: b["keys"].update(x=H)),
    "keys com hash inválido": lambda: _mut(lambda b: b["keys"].update(ml_dsa_65_pk_hash="x")),
    "limitação obrigatória ausente": lambda: _mut(lambda b: b["limitations"].remove("prototype")),
    "sources vazio": lambda: _mut(lambda b: b.update(sources=[])),
    "fonte sem campo": lambda: _mut(lambda b: b["sources"][1].pop("approved")),
    "flag inteira no lugar de bool": lambda: _mut(lambda b: b["sources"][1].update(is_local=1)),
    "source_id repetido": lambda: _mut(lambda b: b["sources"].append(_source("os"))),
    "fonte simulada mesmo excluída": lambda: _mut(
        lambda b: b["sources"].append(_source("qpu_sim", status="excluded", sim=True, approved=False))),
    "misturada sem aprovação": lambda: _mut(lambda b: b["sources"][0].update(approved=False)),
    "sem fonte local na mistura": lambda: _mut(lambda b: b["sources"][1].update(status="excluded")),
    "mixer não é objeto": lambda: _mut(lambda b: b.update(mixer=[])),
}


@pytest.mark.parametrize("make", INVALID_BODIES.values(), ids=INVALID_BODIES.keys())
def test_corpo_invalido_tem_problemas(make):
    assert validate_body(make()) != []


def test_mensagens_de_validacao_nao_ecoam_valores():
    segredo = "segredo-que-nao-pode-aparecer"
    body = _mut(lambda b: b.update(seed_hash=segredo, receipt_id=segredo, eal_version=7))
    assert segredo not in " ".join(validate_body(body))


# --- 3. Chave do emissor ----------------------------------------------------

@pytest.mark.parametrize("bad", [ISSUER_XI[:31], ISSUER_XI + b"\x00"], ids=["31", "33"])
def test_semente_do_emissor_com_tamanho_errado(bad):
    with pytest.raises(ValueError):
        issuer_key_from_seed(bad)


@pytest.mark.parametrize("bad", [bytearray(ISSUER_XI), ISSUER_XI.hex(), None], ids=["bytearray", "str", "None"])
def test_semente_do_emissor_com_tipo_errado(bad):
    with pytest.raises(TypeError):
        issuer_key_from_seed(bad)


def test_chave_do_emissor_deterministica_e_sem_vazamento(issuer):
    again = issuer_key_from_seed(ISSUER_XI)
    assert again.pk == issuer.pk and again.sk == issuer.sk
    assert issuer.pk_hash == hashlib.sha3_256(issuer.pk).hexdigest()
    texto = repr(issuer)
    assert _frag(issuer.pk) in texto  # controle
    assert _frag(issuer.sk[32:64]) not in texto  # K, trecho secreto (rho é público)


def test_salvar_e_carregar_a_chave(issuer, tmp_path):
    sk_path, pk_path = save_issuer_key(issuer, tmp_path)
    assert sk_path.read_text(encoding="ascii").strip() == issuer.sk.hex()
    loaded = load_issuer_key(sk_path, pk_path)
    assert loaded.pk == issuer.pk and loaded.sk == issuer.sk
    assert load_issuer_public_key(pk_path) == issuer.pk


def test_salvar_nao_sobrescreve(issuer, other_issuer, tmp_path):
    sk_path, _ = save_issuer_key(issuer, tmp_path)
    with pytest.raises(FileExistsError):
        save_issuer_key(other_issuer, tmp_path)
    assert sk_path.read_text(encoding="ascii").strip() == issuer.sk.hex()


def test_carregar_par_trocado_e_recusado(issuer, other_issuer, tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    sk_a, _ = save_issuer_key(issuer, a)
    _, pk_b = save_issuer_key(other_issuer, b)
    with pytest.raises(ValueError):
        load_issuer_key(sk_a, pk_b)


@pytest.mark.parametrize("content", ["zz", "00" * 10, ""], ids=["não hex", "curto", "vazio"])
def test_carregar_chave_publica_corrompida(tmp_path, content):
    p = tmp_path / "x.pk"
    p.write_text(content, encoding="ascii")
    with pytest.raises(ValueError):
        load_issuer_public_key(p)


# --- 4. Assinatura ----------------------------------------------------------

def test_assinatura_tem_o_formato_esperado(signed, issuer):
    sig = signed["signature"]
    assert set(sig) == {"alg", "issuer_pk_hash", "value"}
    assert sig["alg"] == "ML-DSA-65"
    assert sig["issuer_pk_hash"] == issuer.pk_hash
    assert len(base64.b64decode(sig["value"], validate=True)) == 3309
    assert receipt_body(signed) == _body()


def test_assinatura_usa_o_contexto_e_o_json_canonico(signed, issuer):
    sig = base64.b64decode(signed["signature"]["value"])
    msg = canonical_bytes(_body())
    assert ML_DSA_65.verify(issuer.pk, msg, sig, ctx=RECEIPT_CTX)
    assert not ML_DSA_65.verify(issuer.pk, msg, sig, ctx=b"")


def test_assinatura_deterministica(issuer, signed):
    assert sign_receipt(_body(), issuer)["signature"] == signed["signature"]


def test_assinar_nao_altera_o_corpo_original(issuer):
    body = _body()
    before = copy.deepcopy(body)
    sign_receipt(body, issuer)
    assert body == before


@pytest.mark.parametrize("make", [INVALID_BODIES["modo experiment"],
                                  INVALID_BODIES["assinatura dentro do corpo"],
                                  INVALID_BODIES["sem fonte local na mistura"]],
                         ids=["experiment", "já assinado", "sem fonte local"])
def test_nao_assina_corpo_invalido(issuer, make):
    with pytest.raises(ValueError):
        sign_receipt(make(), issuer)


def test_assinar_exige_issuer_key():
    with pytest.raises(TypeError):
        sign_receipt(_body(), object())


def test_recibo_assinado_nao_contem_a_chave_privada(signed, issuer):
    texto = json.dumps(signed)
    for parte in (issuer.sk[32:64], issuer.sk[-32:]):
        assert parte.hex()[:32] not in texto
        assert base64.b64encode(parte).decode()[:24] not in texto


# --- 5. Verificação ---------------------------------------------------------

def test_recibo_valido_e_aceito(signed, issuer):
    result = verify_receipt(signed, issuer.pk)
    assert result.ok and result.reasons == ()


def _tampered(signed: dict, fn) -> dict:
    r = copy.deepcopy(signed)
    fn(r)
    return r


def _flip_sig(r):
    raw = bytearray(base64.b64decode(r["signature"]["value"]))
    raw[100] ^= 0x01
    r["signature"]["value"] = base64.b64encode(bytes(raw)).decode()


TAMPERS = {
    # (alteração, trecho esperado em algum motivo)
    "seed_hash": (lambda r: r.update(seed_hash="cd" * 32), "assinatura não confere"),
    "hash da chave KEM": (lambda r: r["keys"].update(ml_kem_768_pk_hash="cd" * 32), "assinatura não confere"),
    "prev_receipt_hash": (lambda r: r.update(prev_receipt_hash="cd" * 32), "assinatura não confere"),
    "fonte excluída vira aprovada": (lambda r: r["sources"][2].update(approved=True), "assinatura não confere"),
    "motivo de exclusão apagado": (lambda r: r["sources"][2].pop("reasons"), "assinatura não confere"),
    "extractor": (lambda r: r["extractor"].update(n=1024), "assinatura não confere"),
    "modo": (lambda r: r.update(mode="experiment"), "mode diferente de keygen"),
    "limitação removida": (lambda r: r["limitations"].remove("prototype"), "limitations"),
    "campo extra": (lambda r: r.update(nota="ok"), "campos desconhecidos"),
    "bit da assinatura": (_flip_sig, "assinatura não confere"),
    "assinatura removida": (lambda r: r.pop("signature"), "signature ausente"),
    "algoritmo trocado": (lambda r: r["signature"].update(alg="ML-DSA-44"), "algoritmo"),
    "emissor trocado": (lambda r: r["signature"].update(issuer_pk_hash="cd" * 32), "outro emissor"),
    "base64 inválido": (lambda r: r["signature"].update(value="***"), "base64"),
    "assinatura curta": (lambda r: r["signature"].update(value=base64.b64encode(b"x" * 10).decode()), "base64"),
    "campo extra na assinatura": (lambda r: r["signature"].update(nota=1), "signature ausente"),
}


def _sig_with_newline(r):
    v = r["signature"]["value"]
    r["signature"]["value"] = v[:100] + "\n" + v[100:]


TAMPERS["base64 com quebra de linha"] = (_sig_with_newline, "base64")
TAMPERS["base64 com caractere estranho"] = (
    lambda r: r["signature"].update(value=r["signature"]["value"][:100] + "!" + r["signature"]["value"][100:]),
    "base64",
)


@pytest.mark.parametrize("fn, motivo", TAMPERS.values(), ids=TAMPERS.keys())
def test_recibo_adulterado_e_recusado_com_motivo(signed, issuer, fn, motivo):
    result = verify_receipt(_tampered(signed, fn), issuer.pk)
    assert not result.ok
    assert any(motivo in r for r in result.reasons), result.reasons


def test_recibo_de_outro_emissor_e_recusado(issuer, other_issuer):
    receipt = sign_receipt(_body(), other_issuer)
    assert verify_receipt(receipt, other_issuer.pk).ok
    result = verify_receipt(receipt, issuer.pk)
    assert not result.ok and any("outro emissor" in r for r in result.reasons)


def test_emissor_falso_com_hash_da_chave_certa_e_recusado(issuer, other_issuer):
    """Assina com outra chave mas declara o issuer_pk_hash do emissor verdadeiro."""
    receipt = sign_receipt(_body(), other_issuer)
    receipt["signature"]["issuer_pk_hash"] = issuer.pk_hash
    result = verify_receipt(receipt, issuer.pk)
    assert not result.ok and "assinatura não confere" in result.reasons


def test_assinatura_com_outro_contexto_e_recusada(issuer):
    body = _body()
    sig = ML_DSA_65.sign(issuer.sk, canonical_bytes(body), ctx=b"outro", deterministic=True)
    receipt = {**body, "signature": {"alg": "ML-DSA-65", "issuer_pk_hash": issuer.pk_hash,
                                     "value": base64.b64encode(sig).decode()}}
    result = verify_receipt(receipt, issuer.pk)
    assert not result.ok and "assinatura não confere" in result.reasons


@pytest.mark.parametrize("bad", [None, [], "x", 5, {"signature": 5}, {}], ids=["None", "lista", "str", "int", "sig int", "vazio"])
def test_entrada_estranha_nao_levanta_excecao(issuer, bad):
    result = verify_receipt(bad, issuer.pk)
    assert not result.ok and result.reasons


@pytest.mark.parametrize("pk", [b"", b"x" * 1951, None, "ab"], ids=["vazia", "curta", "None", "str"])
def test_chave_publica_invalida_reprova_sem_excecao(signed, pk):
    result = verify_receipt(signed, pk)
    assert not result.ok and result.reasons


def test_recibo_com_objeto_fora_do_json_reprova_sem_excecao(signed, issuer):
    r = _tampered(signed, lambda r: r["extractor"].update(n=np.int64(2048)))
    result = verify_receipt(r, issuer.pk)
    assert not result.ok and "recibo não serializa em JSON canônico" in result.reasons


# --- 6. Texto JSON ----------------------------------------------------------

def test_texto_formatado_com_indentacao_verifica(signed, issuer):
    texto = json.dumps(signed, indent=2, ensure_ascii=False)
    assert verify_receipt_text(texto, issuer.pk).ok


def test_texto_com_chave_repetida_e_recusado(signed, issuer):
    texto = json.dumps(signed)
    texto = '{"seed_hash":"' + "cd" * 32 + '",' + texto[1:]
    with pytest.raises(ValueError):
        parse_receipt_json(texto)
    assert not verify_receipt_text(texto, issuer.pk).ok


@pytest.mark.parametrize("texto", ['{"x": NaN}', '{"x": Infinity}', '{"x": -Infinity}'],
                         ids=["NaN", "Infinity", "-Infinity"])
def test_parse_recusa_constantes_fora_do_json(texto):
    with pytest.raises(ValueError):
        parse_receipt_json(texto)


def test_parse_aceita_objeto_valido():
    assert parse_receipt_json('{"a": 1, "b": [1, 2]}') == {"a": 1, "b": [1, 2]}


@pytest.mark.parametrize("texto", ['{"x": NaN}', '{"x": Infinity}', "{", "[]", "", None],
                         ids=["NaN", "Infinity", "truncado", "lista", "vazio", "None"])
def test_texto_invalido_reprova_sem_excecao(issuer, texto):
    result = verify_receipt_text(texto, issuer.pk)
    assert not result.ok and result.reasons


# --- 7. Hash do recibo (base do encadeamento) ------------------------------

def test_hash_do_recibo_cobre_a_assinatura(signed):
    h = receipt_hash(signed)
    assert h == hashlib.sha3_256(canonical_bytes(signed)).hexdigest()
    other = _tampered(signed, _flip_sig)
    assert receipt_hash(other) != h
