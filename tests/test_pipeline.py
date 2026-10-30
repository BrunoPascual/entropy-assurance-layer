"""Testes do pipeline e da resiliência a falhas de fonte (Dia 4, etapa 4).

As fontes são falsas e determinísticas (SHAKE256 com rótulo): `os` local real,
`ibm_fake` remota não simulada (no papel da IBM) e fontes simuladas. A função de
saúde é injetada, para testar a POLÍTICA do pipeline sem depender dos testes
estatísticos; com os módulos reais, quem prova o comportamento é o script de
resiliência. "Saída boa" aqui NÃO é medida por teste estatístico da semente (o
SHA3-512 de lixo também parece uniforme): é medida por política, isolamento e
dependência da fonte local.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

import numpy as np
import pytest

from eal import pipeline as pl
from eal.extract.blocks import ExtractionResult, hash_bits
from eal.mix.mixer import MixInput, mix
from eal.pipeline import run_pipeline

N_BITS = 8192  # 4 blocos de 2048; com H = 0,96 dá 4 x 1838 bits por fonte


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
    """Fonte determinística. `fail` levanta essa exceção em toda leitura."""

    def __init__(self, source_id: str, *, local: bool = True, simulated: bool = False,
                 fail: BaseException | None = None, tag: str = "") -> None:
        self.source_id, self.local, self.simulated, self.fail, self.tag = source_id, local, simulated, fail, tag
        self.calls = 0

    def read(self, n_bits: int) -> FakeBatch:
        self.calls += 1
        if self.fail is not None:
            raise self.fail
        bits = det_bits(f"{self.source_id}|{self.tag}|{self.calls}|{n_bits}", n_bits)
        return FakeBatch(self.source_id, f"{self.source_id}-{self.tag}-{self.calls}", self.local, self.simulated, bits)


class SeedSource:
    """Fornece sementes do Toeplitz como uma leitura local e não simulada da `os`."""

    def __init__(self, *, fail_on: int | None = None, constant: bool = False, simulated: bool = False) -> None:
        self.calls, self.fail_on, self.constant, self.simulated = 0, fail_on, constant, simulated

    def read(self, n_bits: int) -> FakeBatch:
        self.calls += 1
        if self.fail_on == self.calls:
            raise RuntimeError("semente indisponível")
        label = "const-seed" if self.constant else f"seed-{self.calls}"
        return FakeBatch("os", f"seed-batch-{self.calls}", True, self.simulated, det_bits(label, n_bits))


@dataclass
class FakeReport:
    batch_id: str
    source_id: str
    n_bits: int
    h_declared: float
    h_estimated: float | None
    approved: Any
    reasons: tuple[str, ...]


class FakeHealth:
    """Saúde injetada: reprova as fontes listadas em `reject`, levanta nas de `explode`."""

    def __init__(self, reject: dict[str, tuple[str, ...]] | None = None, explode: set[str] | None = None,
                 h_estimated: float | None = 0.96, approved_value: Any = True) -> None:
        self.reject, self.explode, self.h_estimated, self.approved_value = (
            reject or {}, explode or set(), h_estimated, approved_value)
        self.detectors: list[Any] = []
        self.h_declared_seen: list[float] = []

    def __call__(self, batch: FakeBatch, detector: Any, h_declared: float) -> FakeReport:
        self.detectors.append(detector)
        self.h_declared_seen.append(h_declared)
        if batch.source_id in self.explode:
            raise ValueError("segredo-do-provedor-123")
        rejected = batch.source_id in self.reject
        return FakeReport(batch.batch_id, batch.source_id, int(batch.bits.size), h_declared, self.h_estimated,
                          False if rejected else self.approved_value, self.reject.get(batch.source_id, ()))


def run(sources: list[Any], *, health: FakeHealth | None = None, seed: SeedSource | None = None,
        mode: str = "keygen", detector: Any = None, h_declared: float = 1.0) -> pl.PipelineResult:
    return run_pipeline(sources, seed or SeedSource(), mode=mode, n_bits=N_BITS, h_declared=h_declared,
                        detector=detector if detector is not None else object(), health_fn=health or FakeHealth())


def status(result: pl.PipelineResult) -> dict[str, str]:
    return {o.source_id: o.status for o in result.outcomes}


def seed_without(result: pl.PipelineResult, *excluded_ids: str) -> bytes:
    """Contrafactual: mistura só as contribuições (já extraídas) que não estão em `excluded_ids`."""
    keep = [mi for mi in result.inputs if mi.source_id not in excluded_ids]
    return mix(keep, result.mode).seed


def os_src() -> FakeSource:
    return FakeSource("os")


def remote() -> FakeSource:
    return FakeSource("ibm_fake", local=False)


# ------------------------------------------------------ caminho feliz


def test_good_sources_are_mixed() -> None:
    res = run([os_src(), remote()])
    assert res.seed_generated and res.error is None
    assert status(res) == {"os": "mixed", "ibm_fake": "mixed"}
    assert len(res.mix.seed) == 64 and res.mix.usable_for_key is True  # type: ignore[union-attr]
    assert [o.reasons for o in res.outcomes] == [(), ()]


# ----------------------------------------- C1/C2: fonte reprovada é isolada


def test_rejected_source_is_excluded_and_seed_equals_seed_without_it() -> None:
    seed_src = SeedSource()
    res = run([os_src(), FakeSource("bad_local")], health=FakeHealth(reject={"bad_local": ("RCT falhou",)}),
              seed=seed_src)
    assert res.seed_generated
    assert status(res) == {"os": "mixed", "bad_local": "excluded"}
    assert any("RCT falhou" in r for r in res.outcomes[1].reasons)
    assert res.mix.seed == seed_without(res, "bad_local")  # type: ignore[union-attr]
    bad_input = next(mi for mi in res.inputs if mi.source_id == "bad_local")
    assert bad_input.extraction.extractor_type == "none" and bad_input.extraction.n_output_bits == 0
    assert seed_src.calls == 1  # só a fonte aprovada gastou uma semente de Toeplitz


def test_two_rejected_sources_leave_only_the_good_one() -> None:
    health = FakeHealth(reject={"biased": ("APT",), "corr": ("H abaixo do limiar",)})
    res = run([os_src(), FakeSource("biased"), FakeSource("corr")], health=health)
    assert status(res) == {"os": "mixed", "biased": "excluded", "corr": "excluded"}
    assert res.mix.seed == seed_without(res, "biased", "corr")  # type: ignore[union-attr]
    assert res.mix.included_ids == ("os",)  # type: ignore[union-attr]


def test_rejected_source_changes_nothing_about_the_seed_when_its_bits_change() -> None:
    a = run([os_src(), FakeSource("bad", tag="a")], health=FakeHealth(reject={"bad": ("x",)}), seed=SeedSource(constant=True))
    b = run([os_src(), FakeSource("bad", tag="b")], health=FakeHealth(reject={"bad": ("x",)}), seed=SeedSource(constant=True))
    assert a.mix.seed == b.mix.seed  # type: ignore[union-attr]  # mesmos bits da os, outra fonte ruim, mesma semente


# --------------------------------------- C4: fonte remota indisponível


def test_remote_read_failure_is_recorded_and_seed_still_generated() -> None:
    sources = [os_src(), FakeSource("ibm_fake", local=False, fail=RuntimeError("token=ABC123 queue down"))]
    res = run(sources)
    assert res.seed_generated and status(res) == {"os": "mixed", "ibm_fake": "read_failed"}
    assert res.outcomes[1].reasons == ("leitura falhou: RuntimeError",)
    assert "ABC123" not in json.dumps(res.to_dict())  # a mensagem da exceção não é gravada
    assert res.mix.seed == seed_without(res)  # type: ignore[union-attr]


def test_health_exception_is_isolated_and_message_not_recorded() -> None:
    res = run([os_src(), FakeSource("flaky")], health=FakeHealth(explode={"flaky"}))
    assert res.seed_generated and status(res) == {"os": "mixed", "flaky": "health_failed"}
    assert "segredo-do-provedor-123" not in json.dumps(res.to_dict())
    assert res.outcomes[1].reasons == ("teste de saúde falhou: ValueError",)


# --------------------------------------------- C5: a `os` falha -> sem semente


def test_os_rejected_means_no_seed() -> None:
    res = run([os_src(), remote()], health=FakeHealth(reject={"os": ("APT falhou",)}))
    assert not res.seed_generated and res.mix is None
    assert res.error is not None and "local e não simulada" in res.error
    assert status(res) == {"os": "excluded", "ibm_fake": "not_mixed"}
    assert any("APT falhou" in r for r in res.outcomes[0].reasons)


def test_os_read_failure_means_no_seed() -> None:
    res = run([FakeSource("os", fail=OSError("disco")), remote()])
    assert not res.seed_generated
    assert status(res) == {"os": "read_failed", "ibm_fake": "not_mixed"}


def test_os_health_exception_means_no_seed() -> None:
    res = run([os_src(), remote()], health=FakeHealth(explode={"os"}))
    assert not res.seed_generated and status(res)["os"] == "health_failed"


def test_all_reads_failing_means_no_seed() -> None:
    res = run([FakeSource("os", fail=OSError()), FakeSource("ibm_fake", local=False, fail=OSError())])
    assert not res.seed_generated and res.error is not None and "nenhuma fonte aprovada" in res.error
    assert set(status(res).values()) == {"read_failed"}


def test_no_sources_means_no_seed() -> None:
    res = run([])
    assert not res.seed_generated and res.outcomes == ()


# ---------------------------------------------- semente de extração indisponível


def test_seed_source_failure_excludes_sources_that_needed_it() -> None:
    res = run([os_src(), remote()], seed=SeedSource(fail_on=2))  # a 2ª extração (ibm_fake) não acha semente
    assert res.seed_generated and status(res) == {"os": "mixed", "ibm_fake": "extraction_failed"}
    assert res.outcomes[1].reasons == ("extração falhou: RuntimeError",)


def test_seed_source_down_for_os_means_no_seed() -> None:
    res = run([os_src(), remote()], seed=SeedSource(fail_on=1))
    assert not res.seed_generated and status(res)["os"] == "extraction_failed"


def test_simulated_seed_source_is_refused_by_the_extractor() -> None:
    res = run([os_src()], seed=SeedSource(simulated=True))
    assert not res.seed_generated
    assert res.outcomes[0].status == "extraction_failed"
    assert "extração recusada" in res.outcomes[0].reasons[0] and "simulada" in res.outcomes[0].reasons[0]


def test_missing_h_estimated_is_an_extraction_failure() -> None:
    res = run([os_src()], health=FakeHealth(h_estimated=None))
    assert not res.seed_generated and res.outcomes[0].status == "extraction_failed"
    assert "H estimada ausente" in res.outcomes[0].reasons[0]


def test_each_approved_source_reads_a_fresh_extractor_seed() -> None:
    seed_src = SeedSource()
    res = run([os_src(), remote()], seed=seed_src)
    assert seed_src.calls == 2
    hashes = {mi.extraction.seed_hash for mi in res.inputs}
    assert len(hashes) == 2 and None not in hashes


def test_h_used_is_min_of_declared_and_estimated() -> None:
    res = run([os_src()], health=FakeHealth(h_estimated=0.9), h_declared=1.0)
    assert res.inputs[0].extraction.m == 1715  # floor(2048 * 0,9) - 128
    res = run([os_src()], health=FakeHealth(h_estimated=0.96), h_declared=0.8)
    assert res.inputs[0].extraction.m == 1510  # floor(2048 * 0,8) - 128
    assert res.inputs[0].extraction.h_used == 0.8


# -------------------------------------------------- política do mixer em keygen


def test_keygen_with_simulated_source_is_a_policy_error() -> None:
    res = run([os_src(), FakeSource("qpu_sim", simulated=True)])
    assert not res.seed_generated and res.error is not None and "simulada em keygen" in res.error
    assert status(res) == {"os": "not_mixed", "qpu_sim": "not_mixed"}


def test_experiment_accepts_simulated_and_marks_unusable() -> None:
    res = run([os_src(), FakeSource("qpu_sim", simulated=True)], mode="experiment")
    assert res.seed_generated and res.mix.usable_for_key is False  # type: ignore[union-attr]
    assert status(res) == {"os": "mixed", "qpu_sim": "mixed"}


def test_rejected_simulated_source_in_experiment_is_excluded() -> None:
    res = run([os_src(), FakeSource("faulty_stuck", simulated=True)], mode="experiment",
              health=FakeHealth(reject={"faulty_stuck": ("RCT",)}))
    assert status(res) == {"os": "mixed", "faulty_stuck": "excluded"}
    assert res.mix.seed == seed_without(res, "faulty_stuck")  # type: ignore[union-attr]


def test_non_boolean_approved_counts_as_rejected() -> None:
    for value in (None, 1, "True"):
        res = run([os_src(), FakeSource("odd")], health=FakeHealth(reject={}, approved_value=value))
        assert not res.seed_generated  # nem a `os` é aprovada com valor não booleano
        assert status(res)["os"] == "excluded"


# ---------------------------- C6: fonte que passa nos testes (T4) e a dependência da `os`


def test_deterministic_source_that_passes_does_not_make_the_seed_deterministic() -> None:
    def go(os_tag: str) -> pl.PipelineResult:
        prng = FakeSource("faulty_prng", simulated=True, tag="fixo")  # sempre os mesmos bits
        return run([FakeSource("os", tag=os_tag), prng], mode="experiment", seed=SeedSource(constant=True))

    a, b = go("a"), go("b")
    prng_a = next(mi for mi in a.inputs if mi.source_id == "faulty_prng")
    prng_b = next(mi for mi in b.inputs if mi.source_id == "faulty_prng")
    assert np.array_equal(prng_a.extraction.bits, prng_b.extraction.bits)  # a fonte previsível é a mesma
    assert status(a)["faulty_prng"] == "mixed"  # passou nos testes: entra (limitação T4)
    assert a.mix.seed != b.mix.seed  # type: ignore[union-attr]  # mas a semente muda com a `os`


def test_seed_depends_on_every_mixed_source_bit() -> None:
    base = run([os_src()], seed=SeedSource(constant=True))
    changed = run([FakeSource("os", tag="outro")], seed=SeedSource(constant=True))
    assert base.mix.seed != changed.mix.seed  # type: ignore[union-attr]


# -------------------------------- C7: fonte adaptativa que vê a saída da `os`


def mix_input(source_id: str, bits: np.ndarray, *, local: bool) -> MixInput:
    batch_bits = det_bits(f"lote-{source_id}", 2048)
    ih = hash_bits(batch_bits)
    report = FakeReport(f"b-{source_id}", source_id, 2048, 1.0, 0.96, True, ())
    extraction = ExtractionResult(
        extractor_type="toeplitz", guarantee="leftover_hash_lemma", n=2048, m=int(bits.size), h_used=0.96,
        epsilon_log2=-64, n_input_bits=2048, n_blocks=1, discarded_bits=0, bits=bits, input_hash=ih)
    return MixInput(source_id, f"b-{source_id}", ih, local, False, report, extraction)


def xor_combine(parts: list[np.ndarray]) -> bytes:
    """Contraexemplo (decisão do plano): XOR existe só aqui, nunca em eal/."""
    acc = parts[0].copy()
    for p in parts[1:]:
        acc ^= p
    return np.packbits(acc).tobytes()


def test_adaptive_source_collapses_xor_but_not_the_hash_mixer() -> None:
    """Fonte que vê a saída da `os` e escolhe a sua para forçar um alvo fixo.

    Com XOR, a semente vira o alvo para qualquer `os`: a entropia da `os` é cancelada
    (para quem não vê a `os`, a semente é conhecida). Com SHA3-512, a semente continua
    dependendo da `os`: cancelar a `os` exigiria colisões (cerca de 2^256 de trabalho).
    O que isto NÃO mostra: quem vê a saída da `os` calcula a semente do mesmo jeito
    (G3 vale só para quem não conhece a saída da fonte local aprovada), e uma fonte
    adaptativa pode "moer" candidatos (2^k de trabalho para fixar k bits da semente).
    """
    target = det_bits("alvo-do-adversario", 512)
    os_outputs = [det_bits(f"os-saida-{i}", 512) for i in range(8)]
    adversary_outputs = [o ^ target for o in os_outputs]  # adapta-se a cada saída da `os`

    xor_seeds = {xor_combine([o, a]) for o, a in zip(os_outputs, adversary_outputs, strict=True)}
    assert xor_seeds == {np.packbits(target).tobytes()}  # 8 execuções, 1 só semente: a do adversário

    hash_seeds = [
        mix([mix_input("os", o, local=True), mix_input("adversario", a, local=False)], "keygen").seed
        for o, a in zip(os_outputs, adversary_outputs, strict=True)
    ]
    assert len(set(hash_seeds)) == 8  # a dependência da `os` sobrevive
    assert np.packbits(target).tobytes() not in {s[: len(np.packbits(target))] for s in hash_seeds}


# ------------------------------------------------------ infraestrutura


def test_same_detector_is_passed_to_every_source() -> None:
    health, detector = FakeHealth(), object()
    run([os_src(), remote(), FakeSource("x")], health=health, detector=detector)
    assert len(health.detectors) == 3 and all(d is detector for d in health.detectors)
    assert health.h_declared_seen == [1.0, 1.0, 1.0]


def test_invalid_mode_reads_nothing() -> None:
    src, seed_src = os_src(), SeedSource()
    with pytest.raises(ValueError, match="modo"):
        run_pipeline([src], seed_src, mode="producao", n_bits=N_BITS, detector=object(), health_fn=FakeHealth())
    assert src.calls == 0 and seed_src.calls == 0


@pytest.mark.parametrize("n_bits", [0, -1, True, 1.5, None, "8192"])
def test_invalid_n_bits_reads_nothing(n_bits: Any) -> None:
    src = os_src()
    with pytest.raises(ValueError, match="n_bits"):
        run_pipeline([src], SeedSource(), n_bits=n_bits, detector=object(), health_fn=FakeHealth())
    assert src.calls == 0


def test_only_exception_is_caught() -> None:
    with pytest.raises(KeyboardInterrupt):
        run([FakeSource("os", fail=KeyboardInterrupt()), remote()])


def test_to_dict_has_no_seed_no_bits_and_is_json() -> None:
    res = run([os_src(), remote(), FakeSource("bad")], health=FakeHealth(reject={"bad": ("RCT",)}))
    d = res.to_dict()
    text = json.dumps(d)
    assert res.mix.seed.hex() not in text  # type: ignore[union-attr]
    assert "bits" not in d and "seed" not in d
    assert d["seed_generated"] is True and d["mix"]["usable_for_key"] is True
    assert [o["status"] for o in d["outcomes"]] == ["mixed", "mixed", "excluded"]
    assert pl.PipelineResult("keygen", (), None, "x").to_dict()["mix"] is None


def test_repr_does_not_leak_seed_or_inputs() -> None:
    res = run([os_src()])
    assert res.mix.seed.hex() not in repr(res)  # type: ignore[union-attr]
