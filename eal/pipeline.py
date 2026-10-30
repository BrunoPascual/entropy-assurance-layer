"""Pipeline mínimo (Dia 4, etapa 4): fontes -> saúde -> extração -> mixer -> semente.

Princípio: a falha de UMA fonte nunca derruba o pipeline; só a política do mixer
derruba a semente. Para cada fonte, o pipeline:

  1. lê um lote; se a leitura levantar exceção, a fonte é registrada como
     `read_failed` e o pipeline segue (T16: fila ou queda do provedor);
  2. roda o teste de saúde (o detector de replay é compartilhado entre as fontes);
  3. se aprovada, extrai com Toeplitz usando uma semente de uma leitura SEPARADA
     de `seed_source` (uma leitura nova por fonte); se reprovada, não extrai:
     cria uma extração vazia ligada ao lote pelo hash, e o mixer a exclui;
  4. monta o MixInput (relatório e extração amarrados aos bits do lote).

No fim chama `mix`. Se a política não for satisfeita (sem fonte local aprovada,
fonte simulada em keygen, nada aprovado), o resultado traz `mix=None` e o motivo
em `error`: nenhuma semente é gerada (fail-closed, T14).

Só `Exception` é capturada; KeyboardInterrupt e afins passam. A mensagem de uma
exceção de fonte ou de teste NÃO é gravada (só o nome da classe), porque pode
conter dados do provedor. A única mensagem gravada é a do ValueError do próprio
extrator, que é escrita por nós e não contém dados externos.

Nenhum bit e nenhum byte de semente vai para `to_dict()`.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from eal.config import (
    DEFAULT_N_BITS,
    EXTRACTOR_EPSILON_LOG2,
    EXTRACTOR_INPUT_BITS,
    H_DECLARED_DEFAULT,
    SEED_READ_BITS,
)
from eal.extract.blocks import ExtractionResult, hash_bits, validate_bits
from eal.extract.toeplitz import extract_toeplitz
from eal.health.min_entropy import extractor_entropy
from eal.mix.mixer import MODES, MixInput, MixPolicyError, MixResult, make_mix_input, mix

STATUSES = (
    "mixed",              # entrou na mistura
    "excluded",           # reprovada (ou sem saída) e registrada com o motivo
    "not_mixed",          # aprovada, mas a política falhou e nenhuma semente saiu
    "read_failed",        # a leitura levantou exceção
    "health_failed",      # o teste de saúde levantou exceção
    "extraction_failed",  # sem como extrair (semente indisponível ou recusada, H ausente)
)


@dataclass(frozen=True)
class SourceOutcome:
    """O que aconteceu com uma fonte nesta execução."""

    source_id: str
    status: str
    batch_id: str | None = None
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class PipelineResult:
    """Resultado de uma execução. A semente (se houver) fica só em `mix`, em memória."""

    mode: str
    outcomes: tuple[SourceOutcome, ...]
    mix: MixResult | None = field(default=None, repr=False)
    error: str | None = None
    inputs: tuple[MixInput, ...] = field(default=(), repr=False)

    @property
    def seed_generated(self) -> bool:
        """True só se o mixer produziu uma semente."""
        return self.mix is not None

    def to_dict(self) -> dict[str, Any]:
        """Metadados para registro: nenhum bit, nenhum byte de semente."""
        return {
            "mode": self.mode,
            "seed_generated": self.seed_generated,
            "error": self.error,
            "outcomes": [
                {"source_id": o.source_id, "status": o.status, "batch_id": o.batch_id, "reasons": list(o.reasons)}
                for o in self.outcomes
            ],
            "mix": None if self.mix is None else self.mix.to_dict(),
        }


def _is_true(value: Any) -> bool:
    return isinstance(value, (bool, np.bool_)) and bool(value)


def _defaults(detector: Any, health_fn: Callable[..., Any] | None) -> tuple[Any, Callable[..., Any]]:
    """Importa os módulos reais só quando o chamador não passou os seus."""
    if health_fn is None:
        from eal.health.report import build_health_report

        health_fn = build_health_report
    if detector is None:
        from eal.health.replay import ReplayDetector

        detector = ReplayDetector()
    return detector, health_fn


def _empty_extraction(batch: Any) -> ExtractionResult:
    """Extração vazia para lote não aprovado: o mixer o exclui, mas o hash prova de que lote veio."""
    bits = validate_bits(batch.bits)
    return ExtractionResult(
        extractor_type="none", guarantee="none", n=EXTRACTOR_INPUT_BITS, m=0, h_used=0.0,
        epsilon_log2=EXTRACTOR_EPSILON_LOG2, n_input_bits=int(bits.size), n_blocks=0,
        discarded_bits=int(bits.size), bits=np.zeros(0, dtype=np.uint8), seed_hash=None,
        notes=("não extraída: lote não aprovado",), input_hash=hash_bits(bits),
    )


def _extract(batch: Any, report: Any, seed_source: Any) -> tuple[ExtractionResult | None, str | None]:
    """Devolve (extração, None) ou (None, motivo). Lote não aprovado vira extração vazia."""
    if not _is_true(report.approved):
        return _empty_extraction(batch), None
    if report.h_estimated is None:
        return None, "H estimada ausente: sem como dimensionar o extrator"
    h_used = extractor_entropy(report.h_declared, report.h_estimated)
    try:
        seed_batch = seed_source.read(SEED_READ_BITS)
        return extract_toeplitz(batch.bits, h_used, seed_batch, input_batch_id=batch.batch_id), None
    except ValueError as exc:
        return None, f"extração recusada: {exc}"
    except Exception as exc:
        return None, f"extração falhou: {type(exc).__name__}"


def _process(
    source: Any, seed_source: Any, n_bits: int, h_declared: float, detector: Any, health_fn: Callable[..., Any]
) -> tuple[SourceOutcome, MixInput | None]:
    """Uma fonte de ponta a ponta. Falhas dela viram SourceOutcome, nunca exceção."""
    fallback_id = str(getattr(source, "source_id", type(source).__name__))
    try:
        batch = source.read(n_bits)
    except Exception as exc:
        return SourceOutcome(fallback_id, "read_failed", None, (f"leitura falhou: {type(exc).__name__}",)), None
    sid = batch.source_id
    try:
        report = health_fn(batch, detector, h_declared)
    except Exception as exc:
        reason = f"teste de saúde falhou: {type(exc).__name__}"
        return SourceOutcome(sid, "health_failed", batch.batch_id, (reason,)), None
    extraction, problem = _extract(batch, report, seed_source)
    if extraction is None:
        return SourceOutcome(sid, "extraction_failed", batch.batch_id, (str(problem),)), None
    return SourceOutcome(sid, "candidate", batch.batch_id), make_mix_input(batch, report, extraction)


def _final_outcomes(
    pending: list[SourceOutcome], inputs: list[MixInput], result: MixResult | None
) -> tuple[SourceOutcome, ...]:
    """Troca o estado provisório 'candidate' pelo estado final, conforme o mixer."""
    by_id = {mi.source_id: mi for mi in inputs}
    excluded = {e.source_id: e.reasons for e in result.excluded} if result is not None else {}
    final: list[SourceOutcome] = []
    for o in pending:
        if o.status != "candidate":
            final.append(o)
            continue
        mi = by_id[o.source_id]
        if result is not None:
            mixed = o.source_id in result.included_ids
            final.append(dataclasses.replace(o, status="mixed" if mixed else "excluded",
                                             reasons=() if mixed else excluded.get(o.source_id, ())))
        elif _is_true(mi.report.approved) and mi.extraction.n_output_bits > 0:
            final.append(dataclasses.replace(
                o, status="not_mixed", reasons=("política não satisfeita: nenhuma semente gerada",)))
        else:
            reasons = tuple(str(r) for r in mi.report.reasons) or ("sem motivo registrado",)
            final.append(dataclasses.replace(o, status="excluded", reasons=reasons))
    return tuple(final)


def run_pipeline(
    sources: Sequence[Any],
    seed_source: Any,
    *,
    mode: str = "keygen",
    n_bits: int = DEFAULT_N_BITS,
    h_declared: float = H_DECLARED_DEFAULT,
    detector: Any = None,
    health_fn: Callable[..., Any] | None = None,
) -> PipelineResult:
    """Roda o pipeline sobre `sources` e devolve o resultado, com ou sem semente.

    `seed_source` fornece as sementes do Toeplitz (leitura separada por fonte).
    Passe o mesmo `detector` em execuções seguidas para detectar replay entre elas.
    """
    if mode not in MODES:
        raise ValueError(f"modo desconhecido: {mode!r}")
    if isinstance(n_bits, bool) or not isinstance(n_bits, int) or n_bits <= 0:
        raise ValueError("n_bits deve ser inteiro positivo")
    detector, health_fn = _defaults(detector, health_fn)
    pending: list[SourceOutcome] = []
    inputs: list[MixInput] = []
    for source in sources:
        outcome, mix_input = _process(source, seed_source, n_bits, h_declared, detector, health_fn)
        pending.append(outcome)
        if mix_input is not None:
            inputs.append(mix_input)
    try:
        result: MixResult | None = mix(inputs, mode)
        error = None
    except MixPolicyError as exc:
        result, error = None, str(exc)
    return PipelineResult(mode, _final_outcomes(pending, inputs, result), result, error, tuple(inputs))
