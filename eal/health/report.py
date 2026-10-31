"""Relatório de saúde de um lote (HealthReport, PROJECT.md 6.7).

Junta RCT, APT, replay, estimador de min-entropia com limiar e os três testes
estatísticos num veredito único, com a lista de motivos de reprovação.

Regra (fail-closed): `approved` só é verdadeiro se TODOS os testes passaram.
Teste inconclusivo (lote pequeno demais) conta como não aprovado.

Decisões do Dia 3:
  - RCT e APT usam a H DECLARADA da fonte (a H estimada afrouxaria os limites
    justamente nas fontes ruins);
  - a H estimada entra como teste de saúde com limiar fixo (H_MIN_HEALTH);
  - o extrator usará min(H declarada, H estimada) e lê os dois campos daqui.

Um relatório aprovado NÃO prova aleatoriedade: um bom gerador pseudoaleatório
passa em tudo (limitação T4 / N2 do THREAT_MODEL.md).

O formato (nomes dos campos) é estável: vai para o recibo assinado no Dia 5.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from eal.config import H_DECLARED_DEFAULT, H_MIN_HEALTH, STATS_MIN_BITS, STATS_P_MIN
from eal.health.continuous import AptResult, RctResult, run_apt, run_rct
from eal.health.min_entropy import (
    MIN_BITS as MIN_ENTROPY_BITS,
    MinEntropyEstimate,
    entropy_health_ok,
    estimate_min_entropy,
)
from eal.health.replay import ReplayDetector, ReplayResult
from eal.health.stats_tests import StatsReport, run_stats_tests

SCHEMA = "eal-healthreport-v1"


@dataclass(frozen=True)
class HealthReport:
    """Veredito e métricas de um lote. Campos planos e serializáveis em JSON."""

    schema: str
    batch_id: str
    source_id: str
    n_bits: int
    h_declared: float
    # RCT
    rct_pass: bool
    rct_cutoff: int
    rct_max_run: int
    rct_max_run_start: int
    rct_alpha_neg_log2: int
    # APT
    apt_pass: bool
    apt_inconclusive: bool
    apt_cutoff: int
    apt_max_count: int
    apt_n_windows: int
    apt_n_failed_windows: int
    apt_discarded_bits: int
    apt_alpha_neg_log2: int
    # replay
    replay_pass: bool
    replay_history_batches: int
    replay_n_blocks: int
    replay_repeated_blocks: int
    replay_batch_repeated: bool
    # min-entropia (None se o lote tem menos de 16 bits)
    h_bit: float | None
    h_byte: float | None
    h_estimated: float | None
    h_limited_by: str | None
    h_threshold: float
    h_health_pass: bool
    # estatísticos
    stats: dict[str, float]
    stats_pass: bool
    stats_inconclusive: bool
    # veredito
    approved: bool
    reasons: tuple[str, ...]
    notes: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        """Dicionário só com tipos nativos (bool, int, float, str, None, list, dict)."""
        d = asdict(self)
        d["reasons"] = list(self.reasons)
        d["notes"] = list(self.notes)
        d["stats"] = dict(self.stats)
        return d


def _replay_reasons(r: ReplayResult) -> list[str]:
    out = []
    if r.batch_repeated:
        out.append(f"replay: lote idêntico ao lote {r.repeated_batch_of}")
    if r.n_repeated_blocks:
        out.append(
            f"replay: {r.n_repeated_blocks} bloco(s) de {r.block_bits} bits já vistos "
            f"em lote anterior (primeiro: {r.first_match})"
        )
    if r.n_duplicate_blocks_within:
        out.append(
            f"replay: {r.n_duplicate_blocks_within} bloco(s) de {r.block_bits} bits "
            f"repetido(s) dentro do próprio lote"
        )
    return out


def _stats_reasons(s: StatsReport) -> list[str]:
    if s.inconclusive:
        return [f"estatísticos: inconclusivo (lote menor que {STATS_MIN_BITS} bits)"]
    out = []
    for t in s.results:
        if not t.passed:
            extra = f" ({t.note})" if t.note else ""
            out.append(f"{t.name}: p = {t.p_value:.3g} (< {STATS_P_MIN}){extra}")
    return out


def assemble_report(
    *,
    batch_id: str,
    source_id: str,
    n_bits: int,
    h_declared: float,
    rct: RctResult,
    apt: AptResult,
    replay: ReplayResult,
    estimate: MinEntropyEstimate | None,
    stats: StatsReport,
) -> HealthReport:
    """Função pura: monta o veredito a partir dos resultados já calculados."""
    h_ok = estimate is not None and entropy_health_ok(estimate.h_estimated)
    approved = bool(rct.passed and apt.passed and replay.passed and h_ok and stats.passed)

    reasons: list[str] = []
    if not rct.passed:
        reasons.append(
            f"RCT: {rct.max_run} bits iguais seguidos em {rct.max_run_start} "
            f"(limite {rct.cutoff})"
        )
    if apt.inconclusive:
        reasons.append(f"APT: inconclusivo (lote menor que {apt.window} bits)")
    elif not apt.passed:
        reasons.append(
            f"APT: {apt.n_failed_windows} de {apt.n_windows} janelas no limite "
            f"{apt.cutoff} ou acima (máximo {apt.max_count})"
        )
    reasons += _replay_reasons(replay)
    if estimate is None:
        reasons.append(
            f"min-entropia: inconclusiva (lote com menos de {MIN_ENTROPY_BITS} bits)"
        )
    elif not h_ok:
        reasons.append(
            f"min-entropia: H estimada {estimate.h_estimated:.3f} abaixo do limiar "
            f"{H_MIN_HEALTH} (limitada por {estimate.limited_by})"
        )
    reasons += _stats_reasons(stats)

    notes: list[str] = []
    if replay.history_batches == 0:
        notes.append("replay: primeiro lote do histórico; não há lotes anteriores para comparar")
    if replay.discarded_bits:
        notes.append(f"replay: {replay.discarded_bits} bits finais fora de bloco completo não comparados")
    if apt.discarded_bits and not apt.inconclusive:
        notes.append(f"APT: {apt.discarded_bits} bits finais fora de janela completa não testados")

    return HealthReport(
        schema=SCHEMA,
        batch_id=str(batch_id),
        source_id=str(source_id),
        n_bits=int(n_bits),
        h_declared=float(h_declared),
        rct_pass=bool(rct.passed),
        rct_cutoff=int(rct.cutoff),
        rct_max_run=int(rct.max_run),
        rct_max_run_start=int(rct.max_run_start),
        rct_alpha_neg_log2=int(rct.alpha_neg_log2),
        apt_pass=bool(apt.passed),
        apt_inconclusive=bool(apt.inconclusive),
        apt_cutoff=int(apt.cutoff),
        apt_max_count=int(apt.max_count),
        apt_n_windows=int(apt.n_windows),
        apt_n_failed_windows=int(apt.n_failed_windows),
        apt_discarded_bits=int(apt.discarded_bits),
        apt_alpha_neg_log2=int(apt.alpha_neg_log2),
        replay_pass=bool(replay.passed),
        replay_history_batches=int(replay.history_batches),
        replay_n_blocks=int(replay.n_blocks),
        replay_repeated_blocks=int(replay.n_repeated_blocks),
        replay_batch_repeated=bool(replay.batch_repeated),
        h_bit=None if estimate is None else float(estimate.h_bit),
        h_byte=None if estimate is None else float(estimate.h_byte),
        h_estimated=None if estimate is None else float(estimate.h_estimated),
        h_limited_by=None if estimate is None else str(estimate.limited_by),
        h_threshold=float(H_MIN_HEALTH),
        h_health_pass=bool(h_ok),
        stats={k: float(v) for k, v in stats.p_values().items()},
        stats_pass=bool(stats.passed),
        stats_inconclusive=bool(stats.inconclusive),
        approved=approved,
        reasons=tuple(reasons),
        notes=tuple(notes),
    )


def build_health_report(
    batch: Any, detector: ReplayDetector, h_declared: float = H_DECLARED_DEFAULT
) -> HealthReport:
    """Roda todos os testes sobre um RawBatch e devolve o relatório.

    `batch` precisa de: bits, batch_id, source_id e batch_hash (contrato RawBatch).
    O replay é o último a rodar: ele registra o lote no detector, e isso só deve
    acontecer se os demais testes não levantaram exceção.
    """
    bits = batch.bits
    rct = run_rct(bits, h_declared)
    apt = run_apt(bits, h_declared)
    estimate = estimate_min_entropy(bits) if bits.size >= MIN_ENTROPY_BITS else None
    stats = run_stats_tests(bits)
    replay = detector.check(bits, batch_hash=batch.batch_hash, batch_id=batch.batch_id)
    return assemble_report(
        batch_id=batch.batch_id,
        source_id=batch.source_id,
        n_bits=int(bits.size),
        h_declared=h_declared,
        rct=rct,
        apt=apt,
        replay=replay,
        estimate=estimate,
        stats=stats,
    )
