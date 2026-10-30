"""Testes do extrator Toeplitz e da alternativa SHA3 (Dia 4, etapa 1).

Dados de teste são determinísticos (derivados de SHAKE256 com um rótulo), sem
`random` nem gerador de números aleatórios: não há aleatoriedade de produção aqui.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

import numpy as np
import pytest

from eal.extract.blocks import (
    block_min_entropy_bits,
    block_output_bits,
    hash_bits,
    plan_extraction,
    split_blocks,
    validate_bits,
)
from eal.extract.sha3 import SHA3_EXTRACT_DOMAIN, extract_sha3, sha3_extract_block
from eal.extract.toeplitz import extract_toeplitz, toeplitz_apply, toeplitz_matrix


def det_bits(label: str, n: int) -> np.ndarray:
    """Bits determinísticos para fixtures de teste."""
    raw = hashlib.shake_256(label.encode()).digest((n + 7) // 8)
    return np.unpackbits(np.frombuffer(raw, dtype=np.uint8))[:n]


@dataclass
class FakeSeedSource:
    """Stand-in com os atributos que o extrator lê de um RawBatch."""

    bits: np.ndarray
    is_local: bool = True
    is_simulated: bool = False
    batch_id: str = "seed-batch"


def naive_toeplitz(block: np.ndarray, seed: np.ndarray, m: int) -> np.ndarray:
    """Oráculo em laço puro: out[i] = XOR_j (seed[j - i + m - 1] AND block[j])."""
    n = len(block)
    out = []
    for i in range(m):
        acc = 0
        for j in range(n):
            acc ^= int(seed[j - i + m - 1]) & int(block[j])
        out.append(acc)
    return np.array(out, dtype=np.uint8)


# ---------------------------------------------------------------- blocks.py


@pytest.mark.parametrize(
    ("h", "m"),
    [
        (0.9, 1715),
        (0.954, 1825),
        (0.75, 1408),
        (0.5, 896),
        (1.0, 1920),
        (128 / 2048, 0),
        (129 / 2048, 1),
        (0.0625, 0),
        (0.01, 0),
    ],
)
def test_block_output_bits(h: float, m: int) -> None:
    assert block_output_bits(h) == m


def test_block_min_entropy_bits() -> None:
    assert block_min_entropy_bits(0.9) == 1843
    assert block_min_entropy_bits(0.954) == 1953
    assert block_min_entropy_bits(0.5) == 1024


def test_block_output_bits_custom_dimensions() -> None:
    assert block_output_bits(0.9, n=1024, epsilon_log2=-32) == 921 - 64


@pytest.mark.parametrize("h", [0, 0.0, -0.1, 1.0000001, 2, float("nan"), float("inf"), None, True, "0.9"])
def test_invalid_entropy_is_refused(h: object) -> None:
    with pytest.raises(ValueError):
        block_output_bits(h)  # type: ignore[arg-type]


def test_split_blocks_one_million_bits() -> None:
    bits = det_bits("split-1m", 1_000_000)
    blocks, discarded = split_blocks(bits)
    assert blocks.shape == (488, 2048)
    assert discarded == 576


def test_split_blocks_edges_and_order() -> None:
    bits = det_bits("split-order", 2048 * 3 + 100)
    blocks, discarded = split_blocks(bits)
    assert discarded == 100
    for b in range(3):
        assert np.array_equal(blocks[b], bits[2048 * b : 2048 * (b + 1)])
    assert split_blocks(det_bits("a", 2048))[0].shape == (1, 2048)
    assert split_blocks(det_bits("a", 2048))[1] == 0
    blocks, discarded = split_blocks(det_bits("b", 2047))
    assert blocks.shape == (0, 2048)
    assert discarded == 2047


def test_validate_bits_rejects_bad_input() -> None:
    with pytest.raises(ValueError):
        validate_bits(np.array([0, 1, 2], dtype=np.uint8))
    with pytest.raises(ValueError):
        validate_bits(np.array([0, 1], dtype=np.int64))
    with pytest.raises(ValueError):
        validate_bits(np.zeros((2, 2), dtype=np.uint8))
    with pytest.raises(ValueError):
        validate_bits([0, 1])  # type: ignore[arg-type]


def test_hash_bits_follows_batch_hash_convention() -> None:
    bits = det_bits("hash", 1000)
    expected = hashlib.sha3_256(
        (1000).to_bytes(8, "big") + np.packbits(bits).tobytes()
    ).hexdigest()
    assert hash_bits(bits) == expected
    # o comprimento entra no hash: 7 zeros e 8 zeros empacotam no mesmo byte
    assert hash_bits(np.zeros(7, dtype=np.uint8)) != hash_bits(np.zeros(8, dtype=np.uint8))


def test_plan_low_entropy_discards_everything() -> None:
    plan = plan_extraction(det_bits("low", 4096), 128 / 2048)
    assert plan.m == 0
    assert plan.blocks.shape[0] == 0
    assert plan.discarded_bits == 4096


# -------------------------------------------------------------- toeplitz.py


def test_hand_example_matrix() -> None:
    seed = np.array([1, 0, 1, 1], dtype=np.uint8)
    t = toeplitz_matrix(seed, n=3, m=2)
    assert t.tolist() == [[0, 1, 1], [1, 0, 1]]


def test_hand_example_products() -> None:
    seed = np.array([1, 0, 1, 1], dtype=np.uint8)
    blocks = np.array([[1, 1, 0], [1, 0, 1], [0, 0, 0]], dtype=np.uint8)
    out = toeplitz_apply(blocks, seed, m=2)
    assert out.tolist() == [[1, 1], [1, 0], [0, 0]]


def test_diagonal_structure_and_borders() -> None:
    n, m = 64, 40
    seed = det_bits("struct", n + m - 1)
    t = toeplitz_matrix(seed, n, m)
    assert t.shape == (m, n)
    assert np.array_equal(t[:-1, :-1], t[1:, 1:])
    assert np.array_equal(t[0, :], seed[m - 1 :])  # primeira linha
    assert np.array_equal(t[:, 0], seed[m - 1 :: -1])  # primeira coluna


@pytest.mark.parametrize("size", [0, 5, 100, 102, 104])
def test_seed_with_wrong_length_is_refused(size: int) -> None:
    with pytest.raises(ValueError):
        toeplitz_matrix(det_bits("len", size), n=64, m=40)  # certo seria 103


def test_seed_with_bad_values_is_refused() -> None:
    bad = np.full(103, 2, dtype=np.uint8)
    with pytest.raises(ValueError):
        toeplitz_matrix(bad, n=64, m=40)
    with pytest.raises(ValueError):
        toeplitz_matrix(np.zeros(103, dtype=np.int64), n=64, m=40)


def test_linearity_and_zero() -> None:
    n, m = 96, 50
    seed = det_bits("lin-seed", n + m - 1)
    x = det_bits("lin-x", n * 4).reshape(4, n)
    y = det_bits("lin-y", n * 4).reshape(4, n)
    assert np.array_equal(
        toeplitz_apply(x ^ y, seed, m), toeplitz_apply(x, seed, m) ^ toeplitz_apply(y, seed, m)
    )
    assert not toeplitz_apply(np.zeros((2, n), dtype=np.uint8), seed, m).any()


@pytest.mark.parametrize("case", range(12))
def test_vectorized_matches_naive_oracle_small(case: int) -> None:
    n, m = 8 + 5 * case, 3 + 4 * case
    seed = det_bits(f"small-seed-{case}", n + m - 1)
    blocks = det_bits(f"small-x-{case}", n * 3).reshape(3, n)
    fast = toeplitz_apply(blocks, seed, m)
    slow = np.stack([naive_toeplitz(b, seed, m) for b in blocks])
    assert np.array_equal(fast, slow)


def test_vectorized_matches_naive_oracle_full_size() -> None:
    n, m = 2048, 1825
    seed = det_bits("full-seed", n + m - 1)
    block = det_bits("full-x", n)
    fast = toeplitz_apply(block.reshape(1, n), seed, m)[0]
    assert np.array_equal(fast, naive_toeplitz(block, seed, m))


def test_determinism_and_seed_sensitivity() -> None:
    n, m = 128, 60
    seed = det_bits("det-seed", n + m - 1)
    x = det_bits("det-x", n * 8).reshape(8, n)
    a = toeplitz_apply(x, seed, m)
    assert np.array_equal(a, toeplitz_apply(x, seed, m))
    flipped = seed.copy()
    flipped[n // 2] ^= 1
    assert not np.array_equal(a, toeplitz_apply(x, flipped, m))


def test_extract_toeplitz_one_million_bits() -> None:
    bits = det_bits("million", 1_000_000)
    seed_bits = det_bits("million-seed", 1_000_000)
    res = extract_toeplitz(bits, 0.954, FakeSeedSource(seed_bits))
    assert (res.n, res.m, res.n_blocks, res.discarded_bits) == (2048, 1825, 488, 576)
    assert res.n_output_bits == 488 * 1825 == 890_600
    assert res.bits.dtype == np.uint8 and int(res.bits.max()) <= 1
    need = 2048 + 1825 - 1
    expected = hashlib.sha3_256(
        need.to_bytes(8, "big") + np.packbits(seed_bits[:need]).tobytes()
    ).hexdigest()
    assert res.seed_hash == expected
    assert res.guarantee == "leftover_hash_lemma"
    # epsilon total: 488 * 2^-64, ou seja, log2 = -64 + log2(488)
    assert res.epsilon_total_log2 == pytest.approx(-64 + np.log2(488))


def test_extract_toeplitz_matches_blockwise_oracle() -> None:
    bits = det_bits("e2e", 2048 * 2)
    seed_bits = det_bits("e2e-seed", 4000)
    res = extract_toeplitz(bits, 0.9, FakeSeedSource(seed_bits))
    m = 1715
    seed = seed_bits[: 2048 + m - 1]
    expected = np.concatenate([naive_toeplitz(bits[:2048], seed, m), naive_toeplitz(bits[2048:], seed, m)])
    assert np.array_equal(res.bits, expected)


def test_extract_does_not_modify_input() -> None:
    bits = det_bits("immut", 2048 * 2)
    before = bits.copy()
    extract_toeplitz(bits, 0.9, FakeSeedSource(det_bits("immut-seed", 4000)))
    assert np.array_equal(bits, before)


def test_low_entropy_returns_empty_and_does_not_need_seed() -> None:
    res = extract_toeplitz(det_bits("low", 4096), 128 / 2048, FakeSeedSource(det_bits("s", 10)))
    assert res.n_output_bits == 0 and res.n_blocks == 0 and res.seed_hash is None
    assert res.epsilon_total_log2 is None


def test_seed_source_refusals() -> None:
    bits = det_bits("ref", 2048 * 2)
    good = det_bits("ref-seed", 4000)
    with pytest.raises(ValueError, match="local"):
        extract_toeplitz(bits, 0.9, FakeSeedSource(good, is_local=False))
    with pytest.raises(ValueError, match="simulada"):
        extract_toeplitz(bits, 0.9, FakeSeedSource(good, is_simulated=True))
    with pytest.raises(ValueError, match="curta"):
        extract_toeplitz(bits, 0.9, FakeSeedSource(good[:100]))
    with pytest.raises(ValueError, match="idêntica"):
        extract_toeplitz(bits, 0.9, FakeSeedSource(bits.copy()))
    with pytest.raises(ValueError, match="início"):
        extract_toeplitz(bits, 0.9, FakeSeedSource(np.concatenate([bits[:3762], good[:500]])))
    with pytest.raises(ValueError, match="batch_id"):
        extract_toeplitz(bits, 0.9, FakeSeedSource(good, batch_id="X"), input_batch_id="X")


def test_to_dict_has_no_bits() -> None:
    res = extract_toeplitz(det_bits("d", 2048), 0.9, FakeSeedSource(det_bits("ds", 4000)))
    d = res.to_dict()
    assert "bits" not in d
    json.dumps(d)  # tudo serializável: nenhum ndarray escapou
    assert d["n_output_bits"] == 1715 and d["m"] == 1715


# ------------------------------------------------------------------ sha3.py


def reference_sha3_bits(block: np.ndarray, m: int, domain: bytes) -> str:
    """Referência independente: string binária via inteiro, sem unpackbits."""
    nbytes = (m + 7) // 8
    digest = hashlib.shake_256(domain + np.packbits(block).tobytes()).digest(nbytes)
    return format(int.from_bytes(digest, "big"), f"0{8 * nbytes}b")[:m]


@pytest.mark.parametrize("m", [1715, 1825, 1920, 1, 7, 8, 9])
def test_sha3_block_matches_reference(m: int) -> None:
    block = det_bits(f"sha-{m}", 2048)
    out = sha3_extract_block(block, m)
    assert out.size == m
    assert "".join(map(str, out.tolist())) == reference_sha3_bits(block, m, SHA3_EXTRACT_DOMAIN)


def test_sha3_same_shape_as_toeplitz() -> None:
    bits = det_bits("shape", 1_000_000)
    t = extract_toeplitz(bits, 0.954, FakeSeedSource(det_bits("shape-seed", 100_000)))
    s = extract_sha3(bits, 0.954)
    assert (s.m, s.n_blocks, s.discarded_bits, s.n_output_bits) == (
        t.m,
        t.n_blocks,
        t.discarded_bits,
        t.n_output_bits,
    )
    assert s.guarantee == "heuristic_random_oracle" and s.seed_hash is None
    assert not np.array_equal(s.bits, t.bits)


def test_sha3_domain_changes_output() -> None:
    block = det_bits("dom", 2048)
    assert not np.array_equal(sha3_extract_block(block, 1715), sha3_extract_block(block, 1715, b"outro"))


def test_sha3_blocks_are_independent() -> None:
    bits = det_bits("indep", 2048 * 3)
    changed = bits.copy()
    changed[2048 + 5] ^= 1  # só o bloco 1 muda
    a, b = extract_sha3(bits, 0.9), extract_sha3(changed, 0.9)
    m = a.m
    assert np.array_equal(a.bits[:m], b.bits[:m])
    assert not np.array_equal(a.bits[m : 2 * m], b.bits[m : 2 * m])
    assert np.array_equal(a.bits[2 * m :], b.bits[2 * m :])


def test_sha3_refusals_and_low_entropy() -> None:
    with pytest.raises(ValueError):
        extract_sha3(det_bits("x", 2048), 0.9, n=2049)
    res = extract_sha3(det_bits("low", 4096), 128 / 2048)
    assert res.n_output_bits == 0 and res.n_blocks == 0
    with pytest.raises(ValueError):
        sha3_extract_block(np.zeros(2047, dtype=np.uint8), 10)
    with pytest.raises(ValueError):
        sha3_extract_block(np.zeros(2048, dtype=np.uint8), 0)


def test_both_extractors_record_input_hash() -> None:
    bits = det_bits("ih", 2048 * 2)
    t = extract_toeplitz(bits, 0.9, FakeSeedSource(det_bits("ih-seed", 4000)))
    s = extract_sha3(bits, 0.9)
    low = extract_toeplitz(bits, 128 / 2048, FakeSeedSource(det_bits("x", 10)))
    assert t.input_hash == s.input_hash == low.input_hash == hash_bits(bits)
    assert t.to_dict()["input_hash"] == hash_bits(bits)
