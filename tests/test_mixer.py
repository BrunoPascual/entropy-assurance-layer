"""Testes do mixer (Dia 4, etapa 2). Respostas calculadas à mão e política nos dois lados.

Sem `random`: os bits de teste são fixos, para que cada byte esperado possa ser
conferido à mão a partir da codificação do docstring de eal/mix/mixer.py.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
from dataclasses import dataclass

import numpy as np
import pytest

from eal.extract.blocks import ExtractionResult, hash_bits
from eal.mix import mixer
from eal.mix.mixer import MIN_LOCAL_OUTPUT_BITS, MixInput, MixPolicyError, make_mix_input, mix

# 520 bits: 1,0,1,1,0,0,0,0 | 1 | 511 zeros.  packbits = b"\xb0\x80" + 63 bytes zero (65 bytes)
OS_BITS = [1, 0, 1, 1, 0, 0, 0, 0, 1] + [0] * 511
OS_PACKED = b"\xb0\x80" + b"\x00" * 63
# 520 bits: 0,1,1 | 517 zeros.  packbits = b"\x60" + 64 bytes zero
OS_BITS_B = [0, 1, 1] + [0] * 517
OS_PACKED_B = b"\x60" + b"\x00" * 64
N_INPUT = 2048


@dataclass
class FakeReport:
    """Stand-in com os campos do HealthReport que o mixer lê."""

    batch_id: str
    source_id: str
    n_bits: int = N_INPUT
    approved: object = True
    reasons: tuple[str, ...] = ()


@dataclass
class FakeBatch:
    """Stand-in com os campos do RawBatch que o make_mix_input lê."""

    source_id: str
    batch_id: str
    is_local: object
    is_simulated: object
    bits: np.ndarray


def extraction_of(bits: list[int], input_hash: str | None, n_input_bits: int = N_INPUT) -> ExtractionResult:
    arr = np.array(bits, dtype=np.uint8)
    return ExtractionResult(
        extractor_type="toeplitz", guarantee="leftover_hash_lemma", n=2048, m=int(arr.size),
        h_used=0.9, epsilon_log2=-64, n_input_bits=n_input_bits, n_blocks=1 if arr.size else 0,
        discarded_bits=0, bits=arr, input_hash=input_hash,
    )


def contrib(
    sid: str,
    bits: list[int],
    *,
    approved: object = True,
    reasons: tuple[str, ...] = (),
    local: object = True,
    sim: object = False,
) -> MixInput:
    """Contribuição consistente: relatório, extração e hash do mesmo lote fictício."""
    bid, ih = f"batch-{sid}", f"hash-{sid}"
    return MixInput(
        source_id=sid, batch_id=bid, input_hash=ih, is_local=local, is_simulated=sim,
        report=FakeReport(bid, sid, approved=approved, reasons=reasons),
        extraction=extraction_of(bits, ih),
    )


def spec_seed(parts: list[tuple[str, list[int]]], domain: bytes = b"EAL-v1-mix") -> bytes:
    """Referência escrita a partir da especificação, sem reaproveitar o código do mixer."""
    h = hashlib.sha3_512(domain)
    for sid, bits in sorted(parts, key=lambda p: p[0]):
        sb, arr = sid.encode("utf-8"), np.array(bits, dtype=np.uint8)
        h.update(len(sb).to_bytes(8, "big") + sb)
        h.update(arr.size.to_bytes(8, "big") + np.packbits(arr).tobytes())
    return h.digest()


# ------------------------------------------------------ respostas conhecidas


def test_known_vector_single_source() -> None:
    expected = hashlib.sha3_512(
        b"EAL-v1-mix" + (2).to_bytes(8, "big") + b"os" + (520).to_bytes(8, "big") + OS_PACKED
    ).digest()
    assert mix([contrib("os", OS_BITS)]).seed == expected


def test_known_vector_two_sources_in_code_point_order() -> None:
    # "ibm_kingston" (12 bytes; 1 bit -> b"\x80") vem antes de "os"
    expected = hashlib.sha3_512(
        b"EAL-v1-mix"
        + (12).to_bytes(8, "big") + b"ibm_kingston" + (1).to_bytes(8, "big") + b"\x80"
        + (2).to_bytes(8, "big") + b"os" + (520).to_bytes(8, "big") + OS_PACKED_B
    ).digest()
    res = mix([contrib("os", OS_BITS_B), contrib("ibm_kingston", [1], local=False)])
    assert res.seed == expected
    assert res.included_ids == ("ibm_kingston", "os")


def test_code_point_order_puts_uppercase_first() -> None:
    res = mix([contrib("os", OS_BITS), contrib("Zeta", [1], local=False)])
    assert res.included_ids == ("Zeta", "os")  # "Z" (U+005A) < "o" (U+006F)


def test_matches_spec_reference_with_three_sources() -> None:
    parts = [("os", OS_BITS), ("qpu_ibm_x", [1, 1, 0, 1]), ("a", [0] * 17)]
    res = mix([contrib(s, b, local=(s == "os")) for s, b in parts])
    assert res.seed == spec_seed(parts)


def test_seed_size_and_hash_recorded() -> None:
    res = mix([contrib("os", OS_BITS)])
    assert len(res.seed) == 64
    assert res.seed_hash == hashlib.sha3_256(res.seed).hexdigest()


# --------------------------------------------------------- sensibilidade


def test_input_order_does_not_change_result() -> None:
    a = mix([contrib("os", OS_BITS), contrib("q", [1, 1, 0], local=False),
             contrib("r", [1], approved=False, local=False), contrib("b", [1], approved=False, local=False)])
    b = mix([contrib("b", [1], approved=False, local=False), contrib("q", [1, 1, 0], local=False),
             contrib("r", [1], approved=False, local=False), contrib("os", OS_BITS)])
    assert a.seed == b.seed
    assert a.to_dict() == b.to_dict()  # recibo determinístico, inclusive a lista de excluídas
    assert [e.source_id for e in a.excluded] == ["b", "r"]


def test_one_bit_change_changes_seed() -> None:
    changed = OS_BITS.copy()
    changed[300] ^= 1
    assert mix([contrib("os", OS_BITS)]).seed != mix([contrib("os", changed)]).seed


def test_removing_an_approved_source_changes_seed() -> None:
    both = mix([contrib("os", OS_BITS), contrib("q", [1, 1, 0], local=False)])
    assert both.seed != mix([contrib("os", OS_BITS)]).seed


def test_bit_count_is_part_of_the_input() -> None:
    # packbits([1]) == packbits([1,0,0,0,0,0,0,0]) == b"\x80": só o contador diferencia
    short = mix([contrib("os", OS_BITS), contrib("q", [1], local=False)])
    padded = mix([contrib("os", OS_BITS), contrib("q", [1, 0, 0, 0, 0, 0, 0, 0], local=False)])
    assert short.seed != padded.seed


def test_source_id_is_part_of_the_input() -> None:
    assert mix([contrib("os", OS_BITS)]).seed != mix([contrib("oz", OS_BITS)]).seed


def test_domain_is_part_of_the_input(monkeypatch: pytest.MonkeyPatch) -> None:
    before = mix([contrib("os", OS_BITS)]).seed
    monkeypatch.setattr(mixer, "MIX_DOMAIN", b"outro-dominio")
    assert mix([contrib("os", OS_BITS)]).seed != before


# ----------------------------------------------------- exclusão registrada


def test_rejected_source_is_excluded_with_reason() -> None:
    res = mix([contrib("os", OS_BITS),
               contrib("ibm_kingston", [1, 1], approved=False, reasons=("RCT falhou",), local=False)])
    assert res.included_ids == ("os",)
    assert res.excluded[0].source_id == "ibm_kingston"
    assert res.excluded[0].batch_id == "batch-ibm_kingston"
    assert "RCT falhou" in res.excluded[0].reasons[0]
    assert res.seed == mix([contrib("os", OS_BITS)]).seed


def test_rejected_without_reason_is_still_excluded() -> None:
    res = mix([contrib("os", OS_BITS), contrib("x", [1], approved=False, local=False)])
    assert "sem motivo registrado" in res.excluded[0].reasons[0]


def test_zero_output_source_is_excluded_not_mixed() -> None:
    res = mix([contrib("os", OS_BITS), contrib("ibm_kingston", [], local=False)])
    assert res.included_ids == ("os",)
    assert "sem saída" in res.excluded[0].reasons[0]
    assert res.seed == mix([contrib("os", OS_BITS)]).seed


def test_rejected_and_empty_records_both_reasons() -> None:
    res = mix([contrib("os", OS_BITS), contrib("x", [], approved=False, reasons=("APT",), local=False)])
    assert len(res.excluded[0].reasons) == 2


def test_rejected_in_experiment_is_also_excluded() -> None:
    res = mix([contrib("os", OS_BITS), contrib("qpu_sim", [1, 0, 1], approved=False, sim=True)],
              mode="experiment")
    assert res.included_ids == ("os",)
    assert res.excluded[0].source_id == "qpu_sim"


# ------------------------------------------- flags: só booleanos valem


def test_numpy_bools_are_accepted() -> None:
    res = mix([contrib("os", OS_BITS, approved=np.True_, local=np.True_, sim=np.False_)])
    assert res.included_ids == ("os",) and res.usable_for_key is True
    json.dumps(res.to_dict())  # np.bool_ não pode vazar para o recibo


def test_numpy_false_approved_is_excluded() -> None:
    res = mix([contrib("os", OS_BITS), contrib("x", [1], approved=np.False_, local=False)])
    assert res.excluded[0].source_id == "x"


@pytest.mark.parametrize("flag", [None, 1, "True", "yes"])
def test_non_boolean_approved_is_excluded(flag: object) -> None:
    res = mix([contrib("os", OS_BITS), contrib("x", [1], approved=flag, local=False)])
    assert res.excluded[0].source_id == "x"


@pytest.mark.parametrize("flag", [None, 0, "False", "no"])
def test_non_boolean_simulated_counts_as_simulated(flag: object) -> None:
    with pytest.raises(MixPolicyError, match="simulada em keygen"):
        mix([contrib("os", OS_BITS), contrib("x", [1, 0], sim=flag)])


@pytest.mark.parametrize("flag", [None, 1, "yes"])
def test_non_boolean_local_does_not_count_as_local(flag: object) -> None:
    with pytest.raises(MixPolicyError, match="local e não simulada"):
        mix([contrib("x", OS_BITS, local=flag)])


# ---------------------------------------------------- política em keygen


def test_keygen_empty_input_refused() -> None:
    with pytest.raises(MixPolicyError):
        mix([])


def test_keygen_all_rejected_refused_no_seed() -> None:
    with pytest.raises(MixPolicyError, match="nenhuma fonte aprovada"):
        mix([contrib("os", OS_BITS, approved=False, reasons=("APT",))])


def test_keygen_only_nonlocal_refused() -> None:
    with pytest.raises(MixPolicyError, match="exige 1 fonte"):
        mix([contrib("ibm_kingston", OS_BITS, local=False)])


def test_keygen_only_zero_output_refused() -> None:
    with pytest.raises(MixPolicyError, match="nenhuma fonte aprovada"):
        mix([contrib("os", [])])


def test_keygen_source_count_rule_independent_of_floor(monkeypatch: pytest.MonkeyPatch) -> None:
    # com mínimo de 2 fontes locais, uma só não basta, mesmo com bits de sobra
    monkeypatch.setattr(mixer, "MIN_LOCAL_NON_SIMULATED_SOURCES", 2)
    with pytest.raises(MixPolicyError, match="exige 2 fonte"):
        mix([contrib("os", OS_BITS)])
    assert mix([contrib("os", OS_BITS), contrib("os2", OS_BITS_B)]).included_ids == ("os", "os2")


def test_keygen_local_below_floor_refused_even_with_big_remote() -> None:
    assert MIN_LOCAL_OUTPUT_BITS == 512
    with pytest.raises(MixPolicyError, match="mínimo 512"):
        mix([contrib("os", [1] * 511), contrib("ibm", [1] * 4000, local=False)])


def test_keygen_local_exactly_at_floor_accepted() -> None:
    assert mix([contrib("os", [1] * 512)]).included_ids == ("os",)


def test_keygen_floor_counts_only_local_non_simulated() -> None:
    # os aprovada com 300 bits + outra local real com 300 bits = 600 >= 512
    res = mix([contrib("os", [1] * 300), contrib("os2", [0] * 300)])
    assert res.included_ids == ("os", "os2")


def test_keygen_refuses_simulated_even_alongside_os() -> None:
    with pytest.raises(MixPolicyError, match="simulada em keygen"):
        mix([contrib("os", OS_BITS), contrib("qpu_sim", [1, 0, 1], sim=True)])


def test_keygen_refuses_simulated_even_if_rejected() -> None:
    with pytest.raises(MixPolicyError, match="simulada em keygen"):
        mix([contrib("os", OS_BITS), contrib("faulty_biased", [1, 1], approved=False, sim=True)])


def test_keygen_result_is_usable_for_key() -> None:
    assert mix([contrib("os", OS_BITS)]).usable_for_key is True


@pytest.mark.parametrize("field_name", ["source_id", "batch_id", "input_hash"])
def test_duplicates_refused(field_name: str) -> None:
    a, b = contrib("os", OS_BITS), contrib("os2", OS_BITS_B)
    b = dataclasses.replace(
        b, **{field_name: getattr(a, field_name)},
        report=FakeReport(a.batch_id if field_name == "batch_id" else b.batch_id,
                          a.source_id if field_name == "source_id" else b.source_id),
        extraction=extraction_of(OS_BITS_B, a.input_hash if field_name == "input_hash" else b.input_hash),
    )
    with pytest.raises(MixPolicyError, match="repetido"):
        mix([a, b])


def test_unknown_mode_refused() -> None:
    with pytest.raises(ValueError):
        mix([contrib("os", OS_BITS)], mode="producao")


# ------------------------------------------------- política em experiment


def test_experiment_accepts_simulated_local_and_marks_unusable() -> None:
    res = mix([contrib("qpu_sim", OS_BITS, sim=True)], mode="experiment")
    assert (res.mode, res.usable_for_key, res.included_ids) == ("experiment", False, ("qpu_sim",))


def test_experiment_marks_unusable_even_without_simulated() -> None:
    assert mix([contrib("os", OS_BITS)], mode="experiment").usable_for_key is False


def test_experiment_needs_at_least_one_local_source() -> None:
    with pytest.raises(MixPolicyError, match="local"):
        mix([contrib("ibm_kingston", OS_BITS, local=False)], mode="experiment")


def test_experiment_also_has_local_floor() -> None:
    with pytest.raises(MixPolicyError, match="mínimo 512"):
        mix([contrib("qpu_sim", [1] * 100, sim=True)], mode="experiment")


# ------------------------------------------------- pareamento de entradas


def test_report_from_another_batch_refused() -> None:
    with pytest.raises(MixPolicyError, match="outro lote"):
        mix([dataclasses.replace(contrib("os", OS_BITS), batch_id="outro-lote")])


def test_report_from_another_source_refused() -> None:
    with pytest.raises(MixPolicyError, match="outro lote ou fonte"):
        mix([dataclasses.replace(contrib("os", OS_BITS), source_id="outra")])


def test_extraction_of_other_bits_refused() -> None:
    mi = contrib("os", OS_BITS)
    with pytest.raises(MixPolicyError, match="não feita sobre os bits"):
        mix([dataclasses.replace(mi, extraction=extraction_of(OS_BITS, "hash-de-outro-lote"))])


def test_extraction_without_input_hash_refused() -> None:
    mi = contrib("os", OS_BITS)
    with pytest.raises(MixPolicyError, match="não feita sobre os bits"):
        mix([dataclasses.replace(mi, extraction=extraction_of(OS_BITS, None))])


def test_report_and_extraction_size_mismatch_refused() -> None:
    mi = contrib("os", OS_BITS)
    with pytest.raises(MixPolicyError, match="tamanhos diferentes"):
        mix([dataclasses.replace(mi, report=FakeReport(mi.batch_id, "os", n_bits=N_INPUT + 1))])


def _batch_and_parts() -> tuple[FakeBatch, FakeReport, ExtractionResult]:
    bits = np.array(OS_BITS * 4, dtype=np.uint8)  # 2080 bits
    batch = FakeBatch("os", "b1", True, False, bits)
    report = FakeReport("b1", "os", n_bits=int(bits.size))
    extraction = extraction_of(OS_BITS, hash_bits(bits), n_input_bits=int(bits.size))
    return batch, report, extraction


def test_make_mix_input_builds_from_batch_and_mixes() -> None:
    batch, report, extraction = _batch_and_parts()
    mi = make_mix_input(batch, report, extraction)
    assert (mi.source_id, mi.batch_id, mi.input_hash) == ("os", "b1", hash_bits(batch.bits))
    assert mix([mi]).included_ids == ("os",)


def test_make_mix_input_refuses_extraction_of_other_batch() -> None:
    batch, report, _ = _batch_and_parts()
    other = np.array(OS_BITS_B * 4, dtype=np.uint8)
    with pytest.raises(MixPolicyError, match="não feita sobre os bits"):
        make_mix_input(batch, report, extraction_of(OS_BITS, hash_bits(other), n_input_bits=2080))


@pytest.mark.parametrize("report", [FakeReport("outro", "os", n_bits=2080), FakeReport("b1", "outra", n_bits=2080),
                                    FakeReport("b1", "os", n_bits=2081)])
def test_make_mix_input_refuses_mismatched_report(report: FakeReport) -> None:
    batch, _, extraction = _batch_and_parts()
    with pytest.raises(MixPolicyError):
        make_mix_input(batch, report, extraction)


# ------------------------------------------------------------ registro


def test_to_dict_has_no_seed_or_bits() -> None:
    res = mix([contrib("os", OS_BITS), contrib("ibm_kingston", [1], approved=False, local=False)])
    d = res.to_dict()
    text = json.dumps(d)
    assert res.seed.hex() not in text
    assert "bits" not in d and "seed" not in d
    assert [x["source_id"] for x in d["included"]] == ["os"]
    assert d["included"][0]["n_bits_mixed"] == 520
    assert d["included"][0]["input_hash"] == "hash-os"
    assert d["excluded"][0]["source_id"] == "ibm_kingston"
    assert d["policy"].startswith("min_local_non_simulated=1")


def test_repr_does_not_leak_seed() -> None:
    res = mix([contrib("os", OS_BITS)])
    assert res.seed.hex() not in repr(res)
