"""Testes de eal/health/report.py.

Duas camadas:
  - assemble_report (função pura) com resultados fabricados à mão: prova que
    `approved` e `reasons` seguem a regra em todas as 32 combinações de falha;
  - build_health_report com lotes reais de vetores determinísticos (SHAKE-256).
"""
import hashlib
import itertools
import json
from dataclasses import dataclass

import numpy as np
import pytest

from eal.config import H_MIN_HEALTH, STATS_MIN_BITS
from eal.health.continuous import AptResult, RctResult
from eal.health.min_entropy import McvResult, MinEntropyEstimate
from eal.health.replay import ReplayDetector, ReplayResult
from eal.health.report import SCHEMA, assemble_report, build_health_report
from eal.health.stats_tests import StatsReport, StatTestResult

N = STATS_MIN_BITS


# ---------- lotes de teste ----------

@dataclass(frozen=True)
class FakeBatch:
    """Mesmos atributos do RawBatch usados pelo relatório."""

    batch_id: str
    source_id: str
    bits: np.ndarray

    @property
    def batch_hash(self) -> str:
        payload = len(self.bits).to_bytes(8, "big") + np.packbits(self.bits).tobytes()
        return hashlib.sha3_256(payload).hexdigest()


def shake_bits(n_bits: int, label: bytes = b"report-A") -> np.ndarray:
    data = hashlib.shake_256(label).digest(n_bits // 8)
    return np.unpackbits(np.frombuffer(data, dtype=np.uint8))


def shake_bytes(n: int, label: bytes = b"report-B") -> np.ndarray:
    return np.frombuffer(hashlib.shake_256(label).digest(n), dtype=np.uint8)


def good(batch_id="g1", label=b"report-A", n=N) -> FakeBatch:
    return FakeBatch(batch_id, "os", shake_bits(n, label))


def biased() -> FakeBatch:
    # byte < 141 → P(1) = 141/256 ≈ 0,551
    return FakeBatch("biased", "faulty_biased", (shake_bytes(N) < 141).astype(np.uint8))


def stuck() -> FakeBatch:
    bits = shake_bits(N, b"stuck").copy()
    for s in range(0, N - 1024, 1024):
        bits[s + 100 : s + 164] = 0
    return FakeBatch("stuck", "faulty_stuck", bits)


def correlated() -> FakeBatch:
    # cada bit repetido duas vezes: bits e monobit normais, bytes só com 16 valores
    return FakeBatch("corr", "faulty_correlated", np.repeat(shake_bits(N // 2, b"corr"), 2))


# ---------- resultados fabricados à mão ----------

def rct(passed=True):
    return RctResult(passed, 41, 12 if passed else 70, 5, 1.0, 40)


def apt(passed=True, inconclusive=False):
    if inconclusive:
        return AptResult(False, True, 589, 0, 1024, 0, 0, None, 500, 1.0, 20)
    return AptResult(passed, False, 589, 560 if passed else 700, 1024, 976,
                     0 if passed else 3, None if passed else 2, 576, 1.0, 20)


def replay(passed=True, history=3):
    if passed:
        return ReplayResult(True, history, False, None, 244, 0, 0, None, 0, 4096)
    return ReplayResult(False, history, False, None, 244, 5, 0, "bloco 0 igual a x#0", 0, 4096)


def estimate(h=0.96):
    bit = McvResult(0.995, 0.5, 0.501, 500, 1000, 1, 0)
    byte = McvResult(h, 0.01, 0.01, 10, 1000, 8, 0)
    return MinEntropyEstimate(bit, byte, min(0.995, h), "byte")


def stats(passed=True, inconclusive=False):
    def t(name, ok):
        return StatTestResult(name, 0.5 if ok else 0.0, 0.0, ok and not inconclusive,
                              inconclusive, N, "")
    return StatsReport(t("monobit", passed), t("block", True), t("runs", True))


def assemble(r=None, a=None, rp=None, e="default", s=None, **kw):
    return assemble_report(
        batch_id="b1", source_id="src", n_bits=N, h_declared=1.0,
        rct=r or rct(), apt=a or apt(), replay=rp or replay(),
        estimate=estimate() if e == "default" else e, stats=s or stats(), **kw
    )


# ---------- regra de decisão: 32 combinações ----------

PREFIX = {"rct": "RCT", "apt": "APT", "replay": "replay", "h": "min-entropia", "stats": "monobit"}


@pytest.mark.parametrize("fails", list(itertools.product([False, True], repeat=5)))
def test_approved_iff_no_component_fails_and_reasons_match(fails):
    f_rct, f_apt, f_rep, f_h, f_stats = fails
    rep = assemble(
        r=rct(not f_rct), a=apt(not f_apt), rp=replay(not f_rep),
        e=estimate(0.5 if f_h else 0.96), s=stats(not f_stats),
    )
    assert rep.approved == (not any(fails))
    assert (len(rep.reasons) == 0) == rep.approved
    for failed, key in zip(fails, ["rct", "apt", "replay", "h", "stats"]):
        has = any(x.startswith(PREFIX[key]) for x in rep.reasons)
        assert has == failed, f"{key}: falhou={failed}, motivo presente={has}"


def test_all_pass_has_no_reasons():
    rep = assemble()
    assert rep.approved and rep.reasons == ()


# ---------- limiar de H ----------

def test_h_threshold_boundary():
    low = assemble(e=estimate(0.8999))
    ok = assemble(e=estimate(0.9))
    assert not low.approved and not low.h_health_pass
    assert ok.approved and ok.h_health_pass
    assert H_MIN_HEALTH == 0.9


def test_h_reason_mentions_value_and_limiter():
    rep = assemble(e=estimate(0.75))
    (reason,) = rep.reasons
    assert "0.750" in reason and "0.9" in reason and "byte" in reason


# ---------- inconclusivos ----------

def test_apt_inconclusive_blocks_approval():
    rep = assemble(a=apt(inconclusive=True))
    assert not rep.approved and rep.apt_inconclusive
    assert any("APT: inconclusivo" in x for x in rep.reasons)


def test_stats_inconclusive_blocks_approval_with_single_reason():
    rep = assemble(s=stats(inconclusive=True))
    assert not rep.approved and rep.stats_inconclusive
    assert [x for x in rep.reasons if x.startswith("estatísticos")] != []
    assert not any(x.startswith("monobit") for x in rep.reasons)


def test_no_estimate_blocks_approval_and_fields_are_none():
    rep = assemble(e=None)
    assert not rep.approved and rep.h_estimated is None and rep.h_bit is None
    assert rep.h_byte is None and rep.h_limited_by is None and not rep.h_health_pass
    assert any("inconclusiva" in x for x in rep.reasons)


# ---------- notas (não reprovam) ----------

def test_first_batch_note():
    rep = assemble(rp=replay(history=0))
    assert rep.approved
    assert any("primeiro lote" in x for x in rep.notes)


def test_later_batch_has_no_first_batch_note():
    assert not any("primeiro lote" in x for x in assemble().notes)


def test_apt_discarded_bits_note():
    assert any("576 bits finais" in x for x in assemble().notes)


# ---------- formato estável e JSON ----------

EXPECTED_KEYS = {
    "schema", "batch_id", "source_id", "n_bits", "h_declared",
    "rct_pass", "rct_cutoff", "rct_max_run", "rct_max_run_start", "rct_alpha_neg_log2",
    "apt_pass", "apt_inconclusive", "apt_cutoff", "apt_max_count", "apt_n_windows",
    "apt_n_failed_windows", "apt_discarded_bits", "apt_alpha_neg_log2",
    "replay_pass", "replay_history_batches", "replay_n_blocks", "replay_repeated_blocks",
    "replay_batch_repeated",
    "h_bit", "h_byte", "h_estimated", "h_limited_by", "h_threshold", "h_health_pass",
    "stats", "stats_pass", "stats_inconclusive",
    "approved", "reasons", "notes",
}


def _native(value) -> bool:
    if isinstance(value, dict):
        return all(isinstance(k, str) and _native(v) for k, v in value.items())
    if isinstance(value, list):
        return all(_native(v) for v in value)
    return type(value) in (bool, int, float, str, type(None))


def test_to_dict_keys_are_the_stable_contract():
    assert set(assemble().to_dict()) == EXPECTED_KEYS


def test_schema_value():
    assert assemble().schema == SCHEMA == "eal-healthreport-v1"


def test_to_dict_has_only_native_types_and_roundtrips_json():
    d = assemble(r=rct(False), rp=replay(False)).to_dict()
    assert _native(d)
    assert json.loads(json.dumps(d)) == d


def test_stats_keys_match_receipt_example():
    assert set(assemble().stats) == {"monobit", "block", "runs"}


def test_reasons_serialized_as_list():
    d = assemble(r=rct(False)).to_dict()
    assert isinstance(d["reasons"], list) and isinstance(d["notes"], list)


# ---------- lotes reais ----------

def test_good_batch_is_approved_with_native_types():
    rep = build_health_report(good(), ReplayDetector())
    assert rep.approved, rep.reasons
    assert rep.reasons == () and rep.n_bits == N and rep.source_id == "os"
    assert 0.9 <= rep.h_estimated <= 1.0
    assert rep.h_declared == 1.0
    assert _native(rep.to_dict())
    assert rep.rct_alpha_neg_log2 == 40 and rep.apt_alpha_neg_log2 == 20


def test_biased_batch_is_rejected_by_apt_stats_and_entropy():
    rep = build_health_report(biased(), ReplayDetector())
    assert not rep.approved
    assert not rep.apt_pass and not rep.stats_pass and not rep.h_health_pass
    assert rep.rct_pass  # o viés não trava bits


def test_stuck_batch_is_rejected_by_rct():
    rep = build_health_report(stuck(), ReplayDetector())
    assert not rep.approved and not rep.rct_pass
    assert rep.rct_max_run >= 64


def test_correlated_batch_is_rejected_by_entropy_and_stats_not_by_rct_apt():
    rep = build_health_report(correlated(), ReplayDetector())
    assert not rep.approved
    assert rep.rct_pass and rep.apt_pass
    assert not rep.h_health_pass and rep.h_estimated < 0.6
    assert rep.stats["monobit"] >= 0.01 and not rep.stats_pass


def test_replayed_batch_fails_only_replay():
    det = ReplayDetector()
    first = build_health_report(good("g1"), det)
    second = build_health_report(good("g2"), det)  # mesmos bits, outro batch_id
    assert first.approved
    assert not second.approved and not second.replay_pass
    assert second.rct_pass and second.apt_pass and second.h_health_pass and second.stats_pass
    assert second.replay_batch_repeated and second.replay_repeated_blocks == N // 4096
    assert any(x.startswith("replay") for x in second.reasons)


def test_prefix_replay_is_caught_by_blocks():
    det = ReplayDetector()
    full = good("g1")
    build_health_report(full, det)
    prefix = FakeBatch("g2", "faulty_replay", full.bits[: 4096 * 100])
    rep = build_health_report(prefix, det)
    assert not rep.replay_pass and not rep.replay_batch_repeated
    assert rep.replay_repeated_blocks == 100


def test_different_good_batches_both_approved():
    det = ReplayDetector()
    a = build_health_report(good("g1", b"report-A"), det)
    b = build_health_report(good("g2", b"report-C"), det)
    assert a.approved and b.approved and b.replay_history_batches == 1


def test_short_batch_is_not_approved():
    rep = build_health_report(good("s1", n=8192), ReplayDetector())
    assert not rep.approved and rep.stats_inconclusive
    assert rep.rct_pass and rep.replay_pass
    assert any("inconclusivo" in x for x in rep.reasons)


def test_tiny_batch_has_no_entropy_estimate():
    bits = np.array([0, 1, 1, 0, 1, 0, 0, 1], dtype=np.uint8)
    rep = build_health_report(FakeBatch("t1", "x", bits), ReplayDetector())
    assert not rep.approved and rep.h_estimated is None and rep.apt_inconclusive
    assert _native(rep.to_dict())


def test_custom_declared_h_changes_cutoffs():
    det = ReplayDetector()
    rep = build_health_report(good(), det, h_declared=0.9)
    assert rep.h_declared == 0.9 and rep.rct_cutoff == 46 and rep.apt_cutoff == 625


def test_invalid_declared_h_raises_before_registering_the_batch():
    det = ReplayDetector()
    with pytest.raises(ValueError):
        build_health_report(good(), det, h_declared=0.0)
    assert det.history_batches == 0  # o lote não foi registrado


def test_report_is_frozen():
    import dataclasses
    rep = assemble()
    with pytest.raises(dataclasses.FrozenInstanceError):
        rep.approved = False
