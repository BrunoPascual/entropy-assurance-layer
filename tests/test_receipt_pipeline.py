"""Integração: pipeline real -> chaves -> recibo -> assinatura -> verificação (Dia 5, etapa 2B).

Usa os testes de saúde reais. A fonte principal é determinística (SHAKE256 com
rótulo fixo, local e não simulada) para o teste não falhar por acaso: a `os`
é reprovada em cerca de 3% dos lotes de 1.000.000 bits (seção 16.1). Esse
fluxo foi conferido à parte contra os critérios do teste de saúde (monobit,
bloco, runs, RCT, APT e H estimada). Não é fonte de entropia: só existe aqui.

As sementes do extrator vêm da `os` real (não passam por teste de saúde).
"""
from __future__ import annotations

import hashlib
import json

import numpy as np
import pytest

from eal.config import DEFAULT_N_BITS
from eal.pipeline import run_pipeline
from eal.pqc.keygen import derive_keys_from_mix
from eal.receipt.builder import build_receipt_body, issuer_seed_from_mix
from eal.receipt.schema import canonical_bytes, validate_body
from eal.receipt.sign import issuer_key_from_seed, sign_receipt
from eal.receipt.verify import verify_receipt, verify_receipt_text
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


class RemoteDown(Source):
    """Fonte remota que falha na leitura (fila ou queda do provedor, T16)."""

    source_id = "remote_down"
    source_type = "qpu_ibm"
    is_local = False
    is_simulated = False

    def read(self, n_bits: int) -> RawBatch:
        raise TimeoutError("provedor fora do ar: detalhe que não pode ir ao recibo")


@pytest.fixture(scope="module")
def run():
    sources = [ShakeStandin(), RemoteDown()]
    result = run_pipeline(sources, OsSource(), mode="keygen", n_bits=DEFAULT_N_BITS)
    assert result.mix is not None, result.to_dict()
    keys = derive_keys_from_mix(result.mix)
    body = build_receipt_body(result, keys, sources)
    return result, keys, body


def test_corpo_do_recibo_e_valido_e_serializa(run):
    _, _, body = run
    assert validate_body(body) == []
    canonical_bytes(body)  # sem numpy nem bytes escondidos


def test_fontes_registradas(run):
    result, _, body = run
    by_id = {s["source_id"]: s for s in body["sources"]}
    standin, down = by_id["shake_standin"], by_id["remote_down"]
    mi = next(m for m in result.inputs if m.source_id == "shake_standin")
    assert standin["status"] == "mixed" and standin["approved"] is True
    assert standin["batch_hash"] == mi.input_hash
    assert standin["health"]["schema"] == "eal-healthreport-v1"
    assert standin["extraction"]["extractor_type"] == "toeplitz"
    assert down["status"] == "read_failed" and down["approved"] is False
    assert down["is_local"] is False and down["health"] is None
    assert down["reasons"] == ["leitura falhou: TimeoutError"]


def test_mensagem_da_excecao_nao_vai_ao_recibo(run):
    _, _, body = run
    assert "provedor fora do ar" not in json.dumps(body, ensure_ascii=False)


def test_recibo_nao_contem_semente_nem_chave_privada(run):
    result, keys, body = run
    texto = json.dumps(body, ensure_ascii=False)
    for parte in (result.mix.seed, keys.kem_dk[:32], keys.dsa_sk[32:64]):
        assert parte.hex()[:32] not in texto
        assert repr(parte)[2:42] not in texto


def test_chaves_e_semente_do_recibo(run):
    result, keys, body = run
    assert body["seed_hash"] == result.mix.seed_hash
    assert body["keys"] == keys.public_summary()


def test_assinado_salvo_em_texto_e_verificado(run):
    result, _, body = run
    issuer = issuer_key_from_seed(issuer_seed_from_mix(result.mix))
    signed = sign_receipt(body, issuer)
    texto = json.dumps(signed, indent=2, ensure_ascii=False)
    assert verify_receipt(signed, issuer.pk).ok
    assert verify_receipt_text(texto, issuer.pk).ok


def test_semente_da_fonte_de_teste_e_deterministica():
    a, b = ShakeStandin().read(4096), ShakeStandin().read(4096)
    assert a.batch_hash == b.batch_hash
