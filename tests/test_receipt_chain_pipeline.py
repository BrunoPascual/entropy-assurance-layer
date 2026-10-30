"""Integração do log encadeado (Dia 5, etapa 3) com recibos vindos do pipeline REAL.

Cada recibo sai de run_pipeline -> derive_keys_from_mix -> build_receipt_body ->
sign_receipt, e entra no log por append_receipt. Os testes de comportamento da
cadeia (adulteração, fail-closed etc.) estão em tests/test_receipt_chain.py.

A ShakeStandin é uma fonte de TESTE (SHAKE256 determinístico, não é entropia):
evita que o teste falhe por acaso nos testes estatísticos. É a mesma de
tests/test_receipt_pipeline.py; fica copiada aqui porque tests/ não é pacote.
"""
from __future__ import annotations

import base64
import hashlib

import numpy as np
import pytest

from eal.config import DEFAULT_N_BITS, GENESIS_PREV_HASH, RECEIPT_CHAIN_NAME
from eal.pipeline import run_pipeline
from eal.pqc.keygen import derive_keys_from_mix
from eal.receipt.builder import build_receipt_body, issuer_seed_from_mix, receipt_id_for
from eal.receipt.chain import ChainError, append_receipt, verify_chain
from eal.receipt.schema import receipt_hash
from eal.receipt.sign import issuer_key_from_seed, sign_receipt
from eal.receipt.verify import verify_receipt_text
from eal.sources.base import RawBatch, Source
from eal.sources.os_source import OsSource

STANDIN_LABEL = b"EAL-v1|test-standin|1"


class ShakeStandin(Source):
    """Fonte de TESTE: bits determinísticos do SHAKE256. Nunca usar fora dos testes."""

    source_id = "shake_standin"
    source_type = "os"
    is_local = True
    is_simulated = False

    def read(self, n_bits: int) -> RawBatch:
        n_bits = self.validate_n_bits(n_bits)
        raw = hashlib.shake_256(STANDIN_LABEL).digest((n_bits + 7) // 8)
        bits = np.unpackbits(np.frombuffer(raw, dtype=np.uint8))[:n_bits].copy()
        return self._build_batch(bits, {"label": STANDIN_LABEL.decode()})


def _one_run():
    sources = [ShakeStandin()]
    result = run_pipeline(sources, OsSource(), mode="keygen", n_bits=DEFAULT_N_BITS)
    assert result.mix is not None, result.to_dict()
    return sources, result, derive_keys_from_mix(result.mix)


@pytest.fixture(scope="module")
def real():
    """Duas execuções reais do pipeline. Devolve recibos assinados e os segredos para o teste de sigilo."""
    sources1, result1, keys1 = _one_run()
    issuer = issuer_key_from_seed(issuer_seed_from_mix(result1.mix))
    r0 = sign_receipt(build_receipt_body(result1, keys1, sources1), issuer)
    sources2, result2, keys2 = _one_run()
    r1 = sign_receipt(
        build_receipt_body(result2, keys2, sources2, prev_receipt_hash=receipt_hash(r0)), issuer
    )
    orphan = sign_receipt(  # a 2ª execução, mas dizendo que é a primeira da cadeia
        build_receipt_body(result2, keys2, sources2, prev_receipt_hash=GENESIS_PREV_HASH), issuer
    )
    secrets = {
        "semente 1": result1.mix.seed,
        "semente 2": result2.mix.seed,
        "ML-KEM dk 1 (início)": keys1.kem_dk[:32],
        "ML-KEM z 1": keys1.kem_dk[-32:],
        "ML-DSA K 1": keys1.dsa_sk[32:64],
        "ML-DSA K 2": keys2.dsa_sk[32:64],
        "emissor K": issuer.sk[32:64],
    }
    public = {"seed_hash 1": result1.mix.seed_hash, "seed_hash 2": result2.mix.seed_hash}
    return issuer, [r0, r1], orphan, secrets, public


def test_dois_recibos_reais_encadeiam_e_verificam(tmp_path, real):
    # Prova: recibos do pipeline real entram no log em sequência e a cadeia verifica.
    issuer, (r0, r1), _, _, _ = real
    assert r0["receipt_id"] != r1["receipt_id"]
    assert r0["receipt_id"] == receipt_id_for(r0["seed_hash"])
    append_receipt(r0, issuer.pk, tmp_path)
    append_receipt(r1, issuer.pk, tmp_path)
    res = verify_chain(tmp_path, issuer.pk)
    assert res.ok, res.reasons
    assert res.length == 2 and res.head == receipt_hash(r1)


def test_arquivo_individual_real_verifica_como_recibo_solto(tmp_path, real):
    # Prova: o <id>.json gravado é o que o 'eal verify' vai receber, e ele verifica sozinho.
    issuer, receipts, _, _, _ = real
    for r in receipts:
        path = append_receipt(r, issuer.pk, tmp_path)
        verdict = verify_receipt_text(path.read_text(encoding="utf-8"), issuer.pk)
        assert verdict.ok, verdict.reasons


def test_recibo_real_que_se_diz_primeiro_e_recusado_depois_do_primeiro(tmp_path, real):
    # Prova: um recibo real e bem assinado, mas com prev = gênese, não entra no meio da cadeia.
    issuer, (r0, _), orphan, _, _ = real
    append_receipt(r0, issuer.pk, tmp_path)
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    with pytest.raises(ChainError, match="prev_receipt_hash"):
        append_receipt(orphan, issuer.pk, tmp_path)
    assert {p.name: p.read_bytes() for p in tmp_path.iterdir()} == before


def test_cadeia_real_nao_contem_semente_nem_chaves_privadas(tmp_path, real):
    # Prova: nada secreto vai ao disco (G5). Procura hex e base64; a linha de controle exige que um dado
    # público (seed_hash) apareça, para o teste não passar vazio.
    issuer, receipts, _, secrets, public = real
    for r in receipts:
        append_receipt(r, issuer.pk, tmp_path)
    blob = b"".join(p.read_bytes() for p in sorted(tmp_path.iterdir()))
    assert (tmp_path / RECEIPT_CHAIN_NAME).exists()
    for name, value in public.items():
        assert value.encode() in blob, f"controle: {name} deveria aparecer no log"
    for name, value in secrets.items():
        assert value.hex().encode() not in blob, name
        assert base64.b64encode(value) not in blob, name
