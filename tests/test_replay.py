"""Testes de eal/health/replay.py.

Vetores "aleatórios": saída fixa do SHAKE-256 (determinística; não é fonte).
Os testes de limitação (replay transformado, deslocado, curto) afirmam que o
detector NÃO pega esses casos: a limitação fica documentada e travada.
"""
import dataclasses
import hashlib

import numpy as np
import pytest

from eal.config import REPLAY_BLOCK_BITS
from eal.health.replay import ReplayDetector, block_digests

B = REPLAY_BLOCK_BITS  # 4096


def shake_bits(n_bits: int, label: bytes = b"replay-A") -> np.ndarray:
    data = hashlib.shake_256(label).digest(n_bits // 8)
    return np.unpackbits(np.frombuffer(data, dtype=np.uint8))


def h(bits: np.ndarray) -> str:
    """batch_hash no formato do contrato: n_bits (8 bytes) + bits empacotados."""
    payload = len(bits).to_bytes(8, "big") + np.packbits(bits).tobytes()
    return hashlib.sha3_256(payload).hexdigest()


def check(det: ReplayDetector, bits: np.ndarray, batch_id: str):
    return det.check(bits, batch_hash=h(bits), batch_id=batch_id)


def test_block_size_is_4096():
    assert B == 4096


# ---------- primeiro lote e lotes distintos ----------

def test_first_batch_passes_with_empty_history():
    r = check(ReplayDetector(), shake_bits(B * 10), "b1")
    assert r.passed and r.history_batches == 0 and r.n_blocks == 10
    assert r.n_repeated_blocks == 0 and not r.batch_repeated


def test_distinct_batches_pass_and_history_grows():
    det = ReplayDetector()
    assert check(det, shake_bits(B * 10, b"A"), "b1").passed
    r2 = check(det, shake_bits(B * 10, b"B"), "b2")
    assert r2.passed and r2.history_batches == 1
    assert det.history_batches == 2


# ---------- replay exato ----------

def test_exact_replay_fails_with_batch_and_blocks():
    det = ReplayDetector()
    bits = shake_bits(B * 10)
    check(det, bits, "b1")
    r = check(det, bits.copy(), "b2")
    assert not r.passed and r.batch_repeated and r.repeated_batch_of == "b1"
    assert r.n_repeated_blocks == 10
    assert r.first_match == "bloco 0 igual a b1#0"


# ---------- replay por prefixo (o caso do faulty_replay) ----------

def test_prefix_replay_changes_batch_hash_but_blocks_match():
    det = ReplayDetector()
    bits = shake_bits(B * 10)
    check(det, bits, "b1")
    prefix = bits[: B * 4]
    assert h(prefix) != h(bits)  # o hash do lote NÃO coincide
    r = check(det, prefix, "b2")
    assert not r.passed and not r.batch_repeated  # só os blocos pegam
    assert r.n_repeated_blocks == 4


def test_prefix_not_multiple_of_block_counts_full_blocks_only():
    det = ReplayDetector()
    bits = shake_bits(B * 10)
    check(det, bits, "b1")
    r = check(det, bits[: B * 3 + 100], "b2")
    assert not r.passed and r.n_repeated_blocks == 3 and r.discarded_bits == 100


def test_aligned_suffix_replay_is_detected():
    det = ReplayDetector()
    bits = shake_bits(B * 10)
    check(det, bits, "b1")
    r = check(det, bits[B * 6 :], "b2")
    assert not r.passed and r.n_repeated_blocks == 4


# ---------- limitações: o detector NÃO pega ----------

def test_limitation_transformed_replay_one_bit_per_block_passes():
    det = ReplayDetector()
    bits = shake_bits(B * 10)
    check(det, bits, "b1")
    altered = bits.copy()
    altered[::B] ^= 1  # inverte o 1º bit de cada bloco
    assert check(det, altered, "b2").passed  # replay transformado passa


def test_limitation_one_altered_block_still_caught_by_the_others():
    det = ReplayDetector()
    bits = shake_bits(B * 10)
    check(det, bits, "b1")
    altered = bits.copy()
    altered[0] ^= 1  # só o bloco 0 muda; os outros 9 coincidem
    r = check(det, altered, "b2")
    assert not r.passed and r.n_repeated_blocks == 9


def test_limitation_unaligned_offset_replay_passes():
    det = ReplayDetector()
    bits = shake_bits(B * 10)
    check(det, bits, "b1")
    assert check(det, bits[100 : 100 + B * 5], "b2").passed


def test_limitation_replay_shorter_than_one_block_passes_unless_identical():
    det = ReplayDetector()
    bits = shake_bits(B * 10)
    check(det, bits, "b1")
    assert check(det, bits[:1000], "b2").passed  # sem bloco completo, hash difere
    small = shake_bits(1000, b"small")
    check(det, small, "b3")
    r = check(det, small.copy(), "b4")  # idêntico: o hash do lote pega
    assert not r.passed and r.batch_repeated and r.n_blocks == 0


# ---------- repetição dentro do lote e entre fontes ----------

def test_duplicate_block_within_batch_fails():
    one = shake_bits(B, b"one")
    two = shake_bits(B, b"two")
    r = check(ReplayDetector(), np.concatenate([one, two, one]), "b1")
    assert not r.passed and r.n_duplicate_blocks_within == 1
    assert r.n_repeated_blocks == 0 and "próprio lote" in r.first_match


def test_all_zero_batch_fails_within_batch():
    r = check(ReplayDetector(), np.zeros(B * 5, dtype=np.uint8), "b1")
    assert not r.passed and r.n_duplicate_blocks_within == 4


def test_detector_is_global_across_sources():
    # o detector só conhece batch_id e bits; outra "fonte" repetindo os bits é pega
    det = ReplayDetector()
    bits = shake_bits(B * 4)
    check(det, bits, "os-batch")
    assert not check(det, bits, "qpu-batch").passed


# ---------- registro e referência ----------

def test_failed_batch_is_still_registered():
    det = ReplayDetector()
    bits = shake_bits(B * 4)
    check(det, bits, "b1")
    assert not check(det, bits, "b2").passed
    assert not check(det, bits, "b3").passed
    assert det.history_batches == 3


def test_reference_points_to_first_batch():
    det = ReplayDetector()
    bits = shake_bits(B * 4)
    check(det, bits, "b1")
    check(det, bits, "b2")
    r = check(det, bits, "b3")
    assert r.repeated_batch_of == "b1" and r.first_match == "bloco 0 igual a b1#0"


def test_blocks_come_from_bits_not_from_declared_hash():
    det = ReplayDetector()
    bits = shake_bits(B * 4)
    det.check(bits, batch_hash="hash-falso-1", batch_id="b1")
    r = det.check(bits, batch_hash="hash-falso-2", batch_id="b2")
    assert not r.passed and not r.batch_repeated and r.n_repeated_blocks == 4


def test_remainder_is_discarded_and_reported():
    r = check(ReplayDetector(), shake_bits(B * 3 + 8, b"rem"), "b1")
    assert r.n_blocks == 3 and r.discarded_bits == 8


def test_custom_block_size():
    det = ReplayDetector(block_bits=64)
    bits = shake_bits(64 * 5)
    check(det, bits, "b1")
    r = check(det, bits[:128], "b2")
    assert not r.passed and r.n_repeated_blocks == 2 and r.block_bits == 64


# ---------- digests ----------

def test_block_digests_known_value():
    # bloco de 4096 zeros = 512 bytes 0x00
    d = block_digests(np.zeros(B, dtype=np.uint8))
    assert d == [hashlib.sha3_256(bytes(512)).digest()]


def test_block_digests_short_batch_is_empty():
    assert block_digests(shake_bits(B - 8)) == []


# ---------- validação ----------

def test_same_batch_id_twice_is_error():
    det = ReplayDetector()
    bits = shake_bits(B)
    check(det, bits, "b1")
    with pytest.raises(ValueError):
        check(det, shake_bits(B, b"other"), "b1")


@pytest.mark.parametrize("bad", ["", None, 5])
def test_rejects_bad_ids(bad):
    with pytest.raises(TypeError):
        ReplayDetector().check(shake_bits(B), batch_hash="x", batch_id=bad)
    with pytest.raises(TypeError):
        ReplayDetector().check(shake_bits(B), batch_hash=bad, batch_id="x")


@pytest.mark.parametrize("block_bits", [0, -8, 12])
def test_rejects_bad_block_size_values(block_bits):
    with pytest.raises(ValueError):
        ReplayDetector(block_bits=block_bits)


@pytest.mark.parametrize("block_bits", [True, 8.0, "8"])
def test_rejects_bad_block_size_types(block_bits):
    with pytest.raises(TypeError):
        ReplayDetector(block_bits=block_bits)


def test_rejects_list_and_wrong_dtype():
    with pytest.raises(TypeError):
        check(ReplayDetector(), [0, 1] * 100, "b1")
    with pytest.raises(TypeError):
        check(ReplayDetector(), np.zeros(100, dtype=np.int64), "b1")


@pytest.mark.parametrize(
    "bits", [np.array([], dtype=np.uint8), np.array([0, 2], dtype=np.uint8),
             np.zeros((2, 8), dtype=np.uint8)]
)
def test_rejects_bad_shape_or_values(bits):
    with pytest.raises(ValueError):
        ReplayDetector().check(bits, batch_hash="x", batch_id="b1")


def test_result_is_frozen():
    r = check(ReplayDetector(), shake_bits(B), "b1")
    with pytest.raises(dataclasses.FrozenInstanceError):
        r.passed = False
