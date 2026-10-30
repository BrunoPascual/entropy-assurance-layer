"""Testes do script de resiliência (Dia 4, etapa 4).

Usam um catálogo de fontes falsas e determinísticas e uma função de saúde falsa que
imita o que os testes reais fazem nos casos conhecidos (trecho travado, viés, replay).
Provam a LÓGICA de veredito e a fiação dos cenários; o comportamento com os testes
estatísticos reais é o que a execução do script mede.
"""

from __future__ import annotations

import csv
import dataclasses
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from eal.pipeline import PipelineResult, run_pipeline
from scripts import resilience_dia4 as rs

N_BITS = 8192
REJECT = {"faulty_stuck": "RCT falhou", "faulty_biased": "APT falhou", "faulty_correlated": "H abaixo do limiar"}


def det_bits(label: str, n: int) -> np.ndarray:
    raw = hashlib.shake_256(label.encode()).digest((n + 7) // 8)
    return np.unpackbits(np.frombuffer(raw, dtype=np.uint8))[:n]


@dataclass
class FakeBatch:
    source_id: str
    batch_id: str
    is_local: bool
    is_simulated: bool
    bits: np.ndarray


class FakeSource:
    def __init__(self, source_id: str, *, simulated: bool = False, local: bool = True, tag: str = "") -> None:
        self.source_id, self.simulated, self.local, self.tag, self.calls = source_id, simulated, local, tag, 0

    def read(self, n_bits: int) -> FakeBatch:
        self.calls += 1
        bits = det_bits(f"{self.source_id}|{self.tag}|{self.calls}|{n_bits}", n_bits)
        return FakeBatch(self.source_id, f"{self.source_id}-{self.tag}-{self.calls}", self.local, self.simulated, bits)


class ReplayFake(FakeSource):
    """Devolve os mesmos bits em toda leitura depois da primeira (batch_id novo)."""

    def __init__(self) -> None:
        super().__init__("faulty_replay", simulated=True)
        self.stored: np.ndarray | None = None

    def read(self, n_bits: int) -> FakeBatch:
        batch = super().read(n_bits)
        if self.stored is None:
            self.stored = batch.bits
        return dataclasses.replace(batch, bits=self.stored)


class SeedSource:
    def __init__(self) -> None:
        self.calls = 0

    def read(self, n_bits: int) -> FakeBatch:
        self.calls += 1
        return FakeBatch("os", f"seed-{self.calls}", True, False, det_bits(f"seed-{self.calls}", n_bits))


@dataclass
class FakeReport:
    batch_id: str
    source_id: str
    n_bits: int
    h_declared: float
    h_estimated: float | None
    approved: bool
    reasons: tuple[str, ...]


class ScenarioHealth:
    """Saúde falsa: rejeita fontes listadas, trecho de zeros (RCT) e lote repetido (replay)."""

    def __init__(self, reject: dict[str, str] | None = None, *, accept_all: bool = False,
                 reject_os_first: bool = False) -> None:
        self.reject = REJECT if reject is None else reject
        self.accept_all, self.reject_os_first, self._os_done = accept_all, reject_os_first, False

    def __call__(self, batch: FakeBatch, detector: set[str], h_declared: float) -> FakeReport:
        digest = hashlib.sha3_256(batch.bits.tobytes()).hexdigest()
        reasons: list[str] = []
        if not self.accept_all:
            if batch.source_id in self.reject:
                reasons.append(self.reject[batch.source_id])
            if not batch.bits[rs.TAMPER_START:rs.TAMPER_START + rs.TAMPER_LENGTH].any():
                reasons.append("RCT: trecho travado")
            if digest in detector:
                reasons.append("replay de lote")
        detector.add(digest)
        if self.reject_os_first and batch.source_id == "os" and not self._os_done:
            self._os_done = True
            reasons.append("falso alarme")
        return FakeReport(batch.batch_id, batch.source_id, int(batch.bits.size), h_declared, 0.96,
                          not reasons, tuple(reasons))


def fake_catalog(seen: list[tuple[str, int]] | None = None) -> rs.Catalog:
    log = seen if seen is not None else []

    def make(name: str, build: Any) -> rs.Factory:
        def factory(rep: int) -> Any:
            log.append((name, rep))
            return build(rep)
        return factory

    return rs.Catalog(
        os=make("os", lambda r: FakeSource("os", tag=f"r{r}")),
        qpu_ideal=make("qpu_ideal", lambda r: FakeSource("qpu_sim", simulated=True, tag=f"r{r}")),
        qpu_noise=make("qpu_noise", lambda r: FakeSource("qpu_sim", simulated=True, tag=f"n{r}")),
        biased=make("biased", lambda r: FakeSource("faulty_biased", simulated=True, tag=f"r{r}")),
        stuck=make("stuck", lambda r: FakeSource("faulty_stuck", simulated=True, tag=f"r{r}")),
        correlated=make("correlated", lambda r: FakeSource("faulty_correlated", simulated=True, tag=f"r{r}")),
        replay=make("replay", lambda r: ReplayFake()),
        prng=make("prng", lambda r: FakeSource("faulty_prng", simulated=True, tag="fixo")),
        os_down=make("os_down", lambda r: rs.FailingSource("os", local=True)),
        os_tampered=make("os_tampered", lambda r: rs.TamperedSource(FakeSource("os", tag=f"t{r}"))),
        remote_up=make("remote_up", lambda r: FakeSource("ibm_standin", local=False, tag=f"q{r}")),
        remote_down=make("remote_down", lambda r: rs.FailingSource("ibm_down", local=False)),
        detector=set,
    )


def run_all(health: Any = None, reps: int = 2, **kw: Any) -> list[dict[str, Any]]:
    return rs.run_all(fake_catalog(), SeedSource(), reps=reps, n_bits=N_BITS,
                      health_fn=health or ScenarioHealth(), **kw)


def rows_of(rows: list[dict[str, Any]], scenario: str) -> list[dict[str, Any]]:
    return [r for r in rows if r["scenario"] == scenario]


def one_result(mode: str = "experiment", reject: dict[str, str] | None = None) -> PipelineResult:
    """os + uma segunda fonte: qpu_sim (experiment) ou a remota não simulada (keygen)."""
    other = FakeSource("qpu_sim", simulated=True) if mode == "experiment" else FakeSource("ibm_standin", local=False)
    default_reject = {other.source_id: "x"}
    return run_pipeline([FakeSource("os"), other], SeedSource(), mode=mode, n_bits=N_BITS, detector=set(),
                        health_fn=ScenarioHealth(default_reject if reject is None else reject))


# ------------------------------------------------------------ cenários


def test_scenarios_and_modes() -> None:
    assert [s.name for s in rs.SCENARIOS] == [
        "BASE", "BASE_NOISE", "C1_stuck", "C2_biased_correlated", "C3_replay", "C5c_os_down_experiment",
        "C6_prng", "K1_keygen_standin", "C4_remote_down", "C5a_os_down", "C5b_os_tampered"]
    keygen = {s.name for s in rs.SCENARIOS if s.mode == "keygen"}
    assert keygen == {"K1_keygen_standin", "C4_remote_down", "C5a_os_down", "C5b_os_tampered"}
    assert {s.mode for s in rs.SCENARIOS if s.name not in keygen} == {"experiment"}


def test_good_detection_gives_no_violation_and_expected_verdicts() -> None:
    rows = run_all()
    assert len(rows) == 2 * 12  # 11 cenários, C3 com duas passagens
    for name in ("BASE", "BASE_NOISE", "C1_stuck", "C2_biased_correlated", "C3_replay/first",
                 "C3_replay/second", "C6_prng", "K1_keygen_standin", "C4_remote_down"):
        assert {r["verdict"] for r in rows_of(rows, name)} == {"ok"}, name
    for name in ("C5a_os_down", "C5b_os_tampered"):
        assert {r["verdict"] for r in rows_of(rows, name)} == {"ok_fail_closed"}, name
        assert not any(r["seed_generated"] for r in rows_of(rows, name))
    assert {r["verdict"] for r in rows_of(rows, "C5c_os_down_experiment")} == {"ok_experiment_only"}
    ok, problems = rs.gate(rows)
    assert ok and problems == []
    assert rs.os_false_alarms(rows) == 0


def test_c1_row_content() -> None:
    row = rows_of(run_all(), "C1_stuck")[0]
    assert row["statuses"] == "os:mixed;faulty_stuck:excluded" and row["mixed"] == "os"
    assert "faulty_stuck: " in row["not_mixed_reasons"] and "RCT falhou" in row["not_mixed_reasons"]
    assert row["must_exclude"] == "faulty_stuck" and row["seed_equals_without_bad"] is True
    assert len(row["seed_hash"]) == 64 and row["error"] == ""


def test_c3_second_pass_sees_the_replay() -> None:
    rows = run_all()
    first, second = rows_of(rows, "C3_replay/first")[0], rows_of(rows, "C3_replay/second")[0]
    assert "faulty_replay:mixed" in first["statuses"]
    assert "faulty_replay:excluded" in second["statuses"] and "replay" in second["not_mixed_reasons"]
    assert first["seed_hash"] != second["seed_hash"]


def test_k1_mixes_os_and_the_remote_standin_in_keygen() -> None:
    row = rows_of(run_all(), "K1_keygen_standin")[0]
    assert row["mode"] == "keygen" and row["usable_for_key"] is True
    assert row["statuses"] == "os:mixed;ibm_standin:mixed" and row["mixed"] == "ibm_standin;os"


def test_c5_keygen_without_the_os_never_generates_a_seed() -> None:
    """G2: com a remota no ar e a os fora (leitura falha ou lote adulterado), nenhuma semente."""
    rows = run_all()
    a, b = rows_of(rows, "C5a_os_down")[0], rows_of(rows, "C5b_os_tampered")[0]
    assert a["statuses"] == "os:read_failed;ibm_standin:not_mixed"
    assert b["statuses"] == "os:excluded;ibm_standin:not_mixed"
    for r in (a, b):
        assert r["seed_generated"] is False and r["seed_hash"] == "" and r["mode"] == "keygen"
        assert "local e não simulada" in r["error"]


def test_c5c_experiment_keeps_a_seed_but_marks_it_unusable() -> None:
    row = rows_of(run_all(), "C5c_os_down_experiment")[0]
    assert row["statuses"] == "os:read_failed;qpu_sim:mixed" and row["mixed"] == "qpu_sim"
    assert row["seed_generated"] is True and row["usable_for_key"] is False and len(row["seed_hash"]) == 64


def test_c4_runs_in_keygen_with_a_usable_seed() -> None:
    row = rows_of(run_all(), "C4_remote_down")[0]
    assert row["mode"] == "keygen" and row["usable_for_key"] is True
    assert row["statuses"] == "os:mixed;ibm_down:read_failed"
    assert "ConnectionError" in row["not_mixed_reasons"] and "indisponível" not in row["not_mixed_reasons"]


def test_c5_rows_flag_os_as_expected_to_fail() -> None:
    rows = run_all()
    for name in ("C5a_os_down", "C5b_os_tampered", "C5c_os_down_experiment"):
        assert all(r["os_expected_to_fail"] is True for r in rows_of(rows, name)), name
    assert all(r["os_expected_to_fail"] is False for r in rows_of(rows, "BASE"))
    assert rows_of(rows, "C5a_os_down")[0]["os_status"] == "read_failed"
    assert rows_of(rows, "C5b_os_tampered")[0]["os_status"] == "excluded"


def test_fresh_sources_for_every_repetition() -> None:
    seen: list[tuple[str, int]] = []
    rs.run_all(fake_catalog(seen), SeedSource(), reps=3, n_bits=N_BITS, health_fn=ScenarioHealth(),
               scenarios=(rs.SCENARIOS[0],))  # BASE
    assert seen == [("os", 1), ("qpu_ideal", 1), ("os", 2), ("qpu_ideal", 2), ("os", 3), ("qpu_ideal", 3)]


def test_progress_callback_and_rep_validation() -> None:
    messages: list[str] = []
    run_all(reps=1, scenarios=(rs.SCENARIOS[0],), progress=messages.append)
    assert messages == ["BASE repetição 1/1"]
    for bad in (0, -1, True, 1.5):
        with pytest.raises(ValueError, match="reps"):
            rs.run_all(fake_catalog(), SeedSource(), reps=bad, n_bits=N_BITS)  # type: ignore[arg-type]


# -------------------------------------------------- vereditos que não são ok


def test_detection_miss_when_a_bad_source_passes() -> None:
    rows = run_all(ScenarioHealth(accept_all=True))
    assert {r["verdict"] for r in rows_of(rows, "C1_stuck")} == {"DETECTION_MISS: faulty_stuck"}
    assert {r["verdict"] for r in rows_of(rows, "C2_biased_correlated")} == {
        "DETECTION_MISS: faulty_biased,faulty_correlated"}
    assert {r["verdict"] for r in rows_of(rows, "C5b_os_tampered")} == {"DETECTION_MISS: os"}
    assert rs.gate(rows)[0] is True  # falha de detecção não é violação do pipeline


def test_unexpected_when_prng_is_rejected() -> None:
    rows = run_all(ScenarioHealth(reject={**REJECT, "faulty_prng": "APT falhou"}))
    assert {r["verdict"] for r in rows_of(rows, "C6_prng")} == {"UNEXPECTED: não entrou na mistura: faulty_prng"}


def test_os_false_alarm_is_fail_closed_and_counted() -> None:
    rows = run_all(ScenarioHealth(reject_os_first=True), reps=2, scenarios=(rs.SCENARIOS[0],))
    first, second = rows
    # BASE roda em experiment: sem a os, a qpu_sim local basta e a semente sai marcada como inutilizável
    assert first["os_status"] == "excluded" and first["verdict"] == "ok_experiment_only"
    assert first["seed_generated"] is True and first["usable_for_key"] is False
    assert second["verdict"] == "ok" and rs.os_false_alarms(rows) == 1
    assert rs.gate(rows)[0] is True  # uma repetição com a os aprovada basta
    assert rs.gate(rows[:1])[0] is False  # só falso alarme: sem evidência


# ------------------------------------------------------ julgamento direto


def test_judge_ok_on_real_result() -> None:
    j = rs.judge(one_result(), rs.PassSpec(must_exclude=("qpu_sim",)))
    assert j.verdict == "ok" and j.equals_without_bad is True and j.mixed == ("os",)


def without_os(res: PipelineResult) -> PipelineResult:
    outcomes = tuple(dataclasses.replace(o, status="excluded") if o.source_id == "os" else o for o in res.outcomes)
    return dataclasses.replace(res, outcomes=outcomes)


def test_violation_keygen_seed_without_local_source() -> None:
    res = without_os(one_result("keygen", reject={}))
    assert rs.judge(res, rs.PassSpec()).verdict == "VIOLATION: semente gerada sem a fonte local aprovada"


def test_experiment_seed_without_os_is_ok_only_if_unusable() -> None:
    res = without_os(one_result("experiment", reject={}))
    assert rs.judge(res, rs.PassSpec()).verdict == "ok_experiment_only"
    bad = dataclasses.replace(res, mix=dataclasses.replace(res.mix, usable_for_key=True))  # type: ignore[type-var]
    assert rs.judge(bad, rs.PassSpec()).verdict == "VIOLATION: semente de experiment marcada como utilizável"


def test_violation_local_source_mixed_but_no_seed() -> None:
    res = dataclasses.replace(one_result(reject={}), mix=None)
    assert rs.judge(res, rs.PassSpec()).verdict == "VIOLATION: fonte local aprovada, mas nenhuma semente"


def test_violation_usable_for_key_incoherent_with_mode() -> None:
    res = one_result()
    bad = dataclasses.replace(res, mix=dataclasses.replace(res.mix, usable_for_key=True))  # type: ignore[type-var]
    assert rs.judge(bad, rs.PassSpec()).verdict == "VIOLATION: usable_for_key incoerente com o modo"
    key = one_result("keygen")
    bad_key = dataclasses.replace(key, mix=dataclasses.replace(key.mix, usable_for_key=False))  # type: ignore[type-var]
    assert rs.judge(bad_key, rs.PassSpec()).verdict == "VIOLATION: usable_for_key incoerente com o modo"


def test_violation_seed_differs_from_seed_without_bad() -> None:
    res = one_result()
    bad = dataclasses.replace(res, mix=dataclasses.replace(res.mix, seed=b"x" * 64))  # type: ignore[type-var]
    j = rs.judge(bad, rs.PassSpec(must_exclude=("qpu_sim",)))
    assert j.verdict == "VIOLATION: semente difere da semente sem as fontes ruins" and j.equals_without_bad is False


def test_kind_and_summarize() -> None:
    assert rs.kind("DETECTION_MISS: x,y") == "DETECTION_MISS" and rs.kind("ok") == "ok"
    rows = [{"scenario": "A", "verdict": "ok"}, {"scenario": "A", "verdict": "ok"},
            {"scenario": "A", "verdict": "DETECTION_MISS: s"}, {"scenario": "B", "verdict": "ok_fail_closed"}]
    assert rs.summarize(rows) == {"A": {"ok": 2, "DETECTION_MISS": 1}, "B": {"ok_fail_closed": 1}}


# ------------------------------------------------------------------ gate


def base_row(**kw: Any) -> dict[str, Any]:
    return {"scenario": "BASE", "rep": 1, "os_status": "mixed", "seed_generated": True, "usable_for_key": False,
            "verdict": "ok", **kw}


def test_gate_cases() -> None:
    assert rs.gate([base_row()]) == (True, [])
    ok, problems = rs.gate([base_row(verdict="VIOLATION: x", scenario="C1_stuck")])
    assert not ok and "C1_stuck rep 1: VIOLATION: x" in problems  # violação em outro cenário reprova
    ok, problems = rs.gate([base_row(usable_for_key=True)])
    assert not ok and "utilizável para chave" in problems[0]
    ok, problems = rs.gate([base_row(seed_generated=False)])
    assert not ok and "sem semente" in problems[0]
    ok, problems = rs.gate([])
    assert not ok and "sem evidência" in problems[0]
    assert rs.gate([base_row(), base_row(os_status="excluded", seed_generated=False, usable_for_key=None)])[0] is True
    assert rs.gate([base_row(scenario="BASE_NOISE")])[0] is False  # só o BASE conta para o gate


# ---------------------------------------------------- fontes auxiliares


def test_tampered_source_zeroes_only_the_window() -> None:
    inner = FakeSource("os", tag="x")
    original = FakeSource("os", tag="x").read(N_BITS).bits
    batch = rs.TamperedSource(inner).read(N_BITS)
    lo, hi = rs.TAMPER_START, rs.TAMPER_START + rs.TAMPER_LENGTH
    assert not batch.bits[lo:hi].any() and original[lo:hi].any()
    assert np.array_equal(batch.bits[:lo], original[:lo]) and np.array_equal(batch.bits[hi:], original[hi:])
    assert batch.source_id == "os" and rs.TamperedSource(inner).source_id == "os"


def test_tampered_source_does_not_modify_the_inner_batch() -> None:
    class Spy(FakeSource):
        last: FakeBatch

        def read(self, n_bits: int) -> FakeBatch:
            self.last = super().read(n_bits)
            return self.last

    spy = Spy("os", tag="spy")
    rs.TamperedSource(spy).read(N_BITS)
    assert spy.last.bits[rs.TAMPER_START:rs.TAMPER_START + rs.TAMPER_LENGTH].any()  # o original segue intacto


def test_failing_source_raises_and_has_flags() -> None:
    src = rs.FailingSource("ibm_down", local=False)
    assert (src.source_id, src.is_local, src.is_simulated) == ("ibm_down", False, False)
    with pytest.raises(ConnectionError):
        src.read(10)


# ---------------------------------------------------------------- arquivos


def test_write_outputs(tmp_path: Path) -> None:
    rows = run_all()
    meta = rs.write_outputs(rows, {"reps": 2}, tmp_path)
    csv_path = Path(meta["csv"])
    assert hashlib.sha3_256(csv_path.read_bytes()).hexdigest() == meta["csv_sha3_256"]
    with csv_path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        assert reader.fieldnames == rs.CSV_FIELDS
        assert len(list(reader)) == len(rows) == meta["n_rows"]
    saved = json.loads(Path(meta["meta_path"]).read_text(encoding="utf-8"))
    assert saved["gate"] == {"ok": True, "problems": []} and saved["os_false_alarms"] == 0
    assert saved["verdicts_by_scenario"]["C1_stuck"] == {"ok": 2}
    assert [c for c in rs.CSV_FIELDS if "seed" in c] == ["seed_generated", "seed_equals_without_bad", "seed_hash"]


def test_write_outputs_never_overwrites(tmp_path: Path) -> None:
    rows = run_all(reps=1, scenarios=(rs.SCENARIOS[0],))
    a, b = rs.write_outputs(rows, {}, tmp_path), rs.write_outputs(rows, {}, tmp_path)
    assert a["meta_path"] != b["meta_path"] and a["csv"] != b["csv"]
    assert len(list(tmp_path.glob("*.csv"))) == 2


def test_write_outputs_refuses_an_existing_file_even_if_the_tag_collides(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    existing = tmp_path / "dia4_resilience_FIXO.csv"
    existing.write_text("original", encoding="utf-8")
    monkeypatch.setattr(rs, "unique_tag", lambda directory, stamp: "FIXO")
    with pytest.raises(FileExistsError):
        rs.write_outputs([], {}, tmp_path)
    assert existing.read_text(encoding="utf-8") == "original"


def test_unique_tag_never_collides(tmp_path: Path) -> None:
    assert rs.unique_tag(tmp_path, "S") == "S"
    (tmp_path / "dia4_resilience_S.csv").write_text("x")
    assert rs.unique_tag(tmp_path, "S") == "S_2"
    (tmp_path / "dia4_resilience_S_2.meta.json").write_text("x")
    assert rs.unique_tag(tmp_path, "S") == "S_3"
