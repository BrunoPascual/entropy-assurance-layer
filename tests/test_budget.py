"""Testes da contabilidade de perdas do extrator (Dia 4, etapa 3, passo 1).

Respostas calculadas à mão. Onde H é diádico (0,5, 0,75, 1,0, 129/2048) a
igualdade é exata; onde H não é representável em ponto flutuante (0,9, 0,954)
as parcelas fracionárias são comparadas com tolerância, mas a SOMA é sempre
conferida de forma exata com Fraction.

Sem `random`: dados de teste determinísticos (SHAKE256 com rótulo).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from fractions import Fraction

import numpy as np
import pytest

from eal.extract.budget import LossBreakdown, loss_breakdown, yield_ratio
from eal.extract.sha3 import extract_sha3
from eal.extract.toeplitz import extract_toeplitz


def det_bits(label: str, n: int) -> np.ndarray:
    raw = hashlib.shake_256(label.encode()).digest((n + 7) // 8)
    return np.unpackbits(np.frombuffer(raw, dtype=np.uint8))[:n]


@dataclass
class FakeSeedSource:
    bits: np.ndarray
    is_local: bool = True
    is_simulated: bool = False
    batch_id: str = "seed-batch"


# ------------------------------------------------------ respostas à mão


def test_h_0954_one_million_bits() -> None:
    b = loss_breakdown(1_000_000, 0.954)
    assert (b.n_blocks, b.m, b.tail_bits, b.margin_bits, b.output_bits) == (488, 1825, 576, 488 * 128, 890_600)
    assert float(b.deficit_bits) == pytest.approx(488 * 94.208, rel=1e-9)  # 45973,504
    assert float(b.rounding_bits) == pytest.approx(488 * 0.792, rel=1e-9)  # 386,496
    assert b.low_entropy_discard_bits == 0
    assert b.accounted_bits == 1_000_000


def test_h_09_one_block() -> None:
    b = loss_breakdown(2048, 0.9)
    assert (b.n_blocks, b.m, b.margin_bits, b.output_bits, b.tail_bits) == (1, 1715, 128, 1715, 0)
    assert float(b.deficit_bits) == pytest.approx(204.8)
    assert float(b.rounding_bits) == pytest.approx(0.2)
    assert b.accounted_bits == 2048


@pytest.mark.parametrize(
    ("h", "deficit", "output"),
    [(1.0, 0, 1920), (0.75, 512, 1408), (0.5, 1024, 896), (129 / 2048, 1919, 1)],
)
def test_dyadic_h_is_exact(h: float, deficit: int, output: int) -> None:
    b = loss_breakdown(2048, h)
    assert b.deficit_bits == deficit  # igualdade exata, sem tolerância
    assert b.rounding_bits == 0
    assert (b.margin_bits, b.output_bits) == (128, output)
    assert b.accounted_bits == 2048


def test_low_entropy_discards_whole_lot() -> None:
    b = loss_breakdown(1_000_000, 128 / 2048)  # k = 128, m = 0
    assert b.m == 0 and b.n_blocks == 0 and b.output_bits == 0
    assert b.low_entropy_discard_bits == 1_000_000
    assert (b.deficit_bits, b.rounding_bits, b.margin_bits, b.tail_bits) == (0, 0, 0, 0)
    assert b.accounted_bits == 1_000_000


def test_partial_block_only_goes_to_tail() -> None:
    b = loss_breakdown(2047, 0.9)
    assert (b.n_blocks, b.output_bits, b.tail_bits) == (0, 0, 2047)
    assert (b.deficit_bits, b.rounding_bits, b.margin_bits) == (0, 0, 0)
    assert b.accounted_bits == 2047


def test_empty_input() -> None:
    b = loss_breakdown(0, 0.9)
    assert b.accounted_bits == 0 and b.total_yield is None and b.n_blocks == 0


def test_yield_ratio_known_values() -> None:
    assert yield_ratio(1.0) == 0.9375
    assert yield_ratio(0.9) == 1715 / 2048
    assert yield_ratio(0.5) == 896 / 2048
    assert yield_ratio(128 / 2048) == 0.0


def test_total_yield_counts_the_tail() -> None:
    b = loss_breakdown(1_000_000, 0.954)
    assert b.total_yield == pytest.approx(890_600 / 1_000_000)
    assert b.total_yield < yield_ratio(0.954)  # o resto baixa o rendimento do lote


def test_custom_dimensions() -> None:
    b = loss_breakdown(10_240, 0.9, n=1024, epsilon_log2=-32)
    assert (b.n_blocks, b.m, b.margin_bits, b.output_bits) == (10, 857, 10 * 64, 8570)  # margem total = 10 blocos x 64 bits
    assert b.accounted_bits == 10_240


# ----------------------------------------------------------- invariantes


@pytest.mark.parametrize("n_input", [0, 1, 2047, 2048, 2049, 5000, 1_000_000])
def test_sum_of_parts_is_exactly_the_input(n_input: int) -> None:
    for h in [i / 1000 for i in range(1, 1001)]:
        assert loss_breakdown(n_input, h).accounted_bits == n_input


def test_sum_is_exact_for_other_dimensions() -> None:
    for n, eps in [(512, -16), (1024, -32), (4096, -64), (8192, -64)]:
        for h in (0.3, 0.7, 0.9, 0.954, 1.0):
            assert loss_breakdown(100_000, h, n=n, epsilon_log2=eps).accounted_bits == 100_000


def test_yield_never_decreases_with_h() -> None:
    values = [yield_ratio(i / 1000) for i in range(1, 1001)]
    assert all(a <= b for a, b in zip(values, values[1:], strict=False))


@pytest.mark.parametrize("h", [0.9, 0.954, 0.3, 129 / 2048, 128 / 2048, 1.0])
def test_model_matches_both_real_extractors(h: float) -> None:
    bits = det_bits(f"match-{h}", 2048 * 5 + 300)
    model = loss_breakdown(bits.size, h)
    toe = extract_toeplitz(bits, h, FakeSeedSource(det_bits("seed", 8000)))
    sha = extract_sha3(bits, h)
    for real in (toe, sha):
        assert real.n_output_bits == model.output_bits
        assert real.n_blocks == model.n_blocks
        assert real.m == model.m
        # bits que o extrator reporta como descartados = resto, ou o lote todo se m = 0
        assert real.discarded_bits == model.tail_bits + model.low_entropy_discard_bits


# ------------------------------------------------------------ validação


@pytest.mark.parametrize("h", [0, 0.0, -0.1, 1.0000001, float("nan"), float("inf"), None, True, "0.9"])
def test_invalid_h_refused(h: object) -> None:
    with pytest.raises(ValueError):
        loss_breakdown(2048, h)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        yield_ratio(h)  # type: ignore[arg-type]


@pytest.mark.parametrize("n_input", [-1, 2048.0, True, None, "2048"])
def test_invalid_n_input_bits_refused(n_input: object) -> None:
    with pytest.raises(ValueError):
        loss_breakdown(n_input, 0.9)  # type: ignore[arg-type]


def test_to_dict_is_plain_and_serializable() -> None:
    d = loss_breakdown(1_000_000, 0.954).to_dict()
    json.dumps(d)
    assert d["n_blocks"] == 488 and d["output_bits"] == 890_600
    assert all(not isinstance(v, Fraction) for v in d.values())
    assert isinstance(loss_breakdown(2048, 0.9), LossBreakdown)
