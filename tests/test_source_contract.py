"""Testes do contrato de fonte (Source) e do lote cru (RawBatch).

Não testa criptografia ainda. Prova que a estrutura funciona e que o contrato
está sendo cobrado de toda fonte.
"""

import numpy as np
import pytest

from eal.sources import RawBatch, Source
from eal.testing import assert_source_contract


class FakeSource(Source):
    """Fonte falsa só para testes. Usa numpy com semente fixa (regra do PROJECT.md:
    aleatoriedade fora das fontes só é permitida em código de teste)."""

    source_id = "fake"
    source_type = "faulty"
    is_local = True
    is_simulated = True

    def __init__(self, seed: int = 0) -> None:
        self._seed = seed
        self._rng = np.random.default_rng(seed)

    def read(self, n_bits: int) -> RawBatch:
        n_bits = self.validate_n_bits(n_bits)
        bits = self._rng.integers(0, 2, size=n_bits, dtype=np.uint8)
        return self._build_batch(bits, {"seed": self._seed})


def _batch(bits: np.ndarray, **overrides) -> RawBatch:
    """Cria um RawBatch válido, permitindo trocar campos para testar erros."""
    fields = dict(
        source_id="fake",
        source_type="faulty",
        source_version="0.1.0",
        is_local=True,
        is_simulated=True,
        bits=bits,
    )
    fields.update(overrides)
    return RawBatch(**fields)


# ---------- contrato da fonte ----------

def test_fonte_falsa_cumpre_o_contrato():
    batch = assert_source_contract(FakeSource(), n_bits=1024)
    assert batch.params == {"seed": 0}


@pytest.mark.parametrize("n_bits", [1, 8, 1000, 4097])
def test_read_devolve_exatamente_n_bits(n_bits):
    assert FakeSource().read(n_bits).n_bits == n_bits


def test_bits_sao_uint8_com_so_0_e_1():
    bits = FakeSource().read(5000).bits
    assert bits.dtype == np.uint8
    assert set(np.unique(bits).tolist()) <= {0, 1}


def test_metadados_sao_copiados_da_fonte():
    source = FakeSource()
    batch = source.read(16)
    assert batch.source_id == "fake"
    assert batch.source_type == "faulty"
    assert batch.source_version == "0.1.0"
    assert batch.is_local is True
    assert batch.is_simulated is True
    assert batch.created_at.endswith("Z")


@pytest.mark.parametrize("n_bits", [0, -5, 3.5, "10", True])
def test_n_bits_invalido_levanta_erro(n_bits):
    with pytest.raises(ValueError):
        FakeSource().read(n_bits)


def test_source_abstrata_nao_pode_ser_instanciada():
    with pytest.raises(TypeError):
        Source()  # type: ignore[abstract]


# ---------- RawBatch ----------

def test_raw_batch_rejeita_valor_diferente_de_0_ou_1():
    with pytest.raises(ValueError):
        _batch(np.array([0, 1, 2], dtype=np.uint8))


def test_raw_batch_rejeita_dtype_errado():
    with pytest.raises(ValueError):
        _batch(np.array([0, 1, 1], dtype=np.int64))


def test_raw_batch_rejeita_lote_vazio():
    with pytest.raises(ValueError):
        _batch(np.array([], dtype=np.uint8))


def test_raw_batch_rejeita_array_com_duas_dimensoes():
    with pytest.raises(ValueError):
        _batch(np.zeros((2, 4), dtype=np.uint8))


def test_raw_batch_rejeita_tipo_de_fonte_desconhecido():
    with pytest.raises(ValueError):
        _batch(np.zeros(8, dtype=np.uint8), source_type="magica")


def test_bits_do_lote_sao_somente_leitura():
    original = np.array([0, 1, 0, 1], dtype=np.uint8)
    batch = _batch(original)
    with pytest.raises(ValueError):
        batch.bits[0] = 1
    original[0] = 1  # mexer no array original não afeta o lote
    assert batch.bits[0] == 0


# ---------- hash do lote (base da detecção de replay) ----------

def test_hash_e_estavel_para_os_mesmos_bits():
    bits = np.array([1, 0, 1, 1, 0, 0, 1, 0], dtype=np.uint8)
    assert _batch(bits).batch_hash == _batch(bits.copy()).batch_hash


def test_hash_muda_quando_um_bit_muda():
    a = np.array([1, 0, 1, 1, 0, 0, 1, 0], dtype=np.uint8)
    b = a.copy()
    b[3] ^= 1
    assert _batch(a).batch_hash != _batch(b).batch_hash


def test_hash_diferencia_tamanhos_com_o_mesmo_empacotamento():
    # 8 zeros e 9 zeros empacotam parecido; o hash precisa distinguir.
    assert (
        _batch(np.zeros(8, dtype=np.uint8)).batch_hash
        != _batch(np.zeros(9, dtype=np.uint8)).batch_hash
    )


def test_batch_ids_sao_unicos():
    source = FakeSource()
    assert source.read(8).batch_id != source.read(8).batch_id
