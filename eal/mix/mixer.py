"""Mixer SHA3-512 com política fail-closed (PROJECT.md 6.9, Dia 4 etapa 2).

Entrada: uma contribuição por fonte, montada por `make_mix_input` a partir do
RawBatch, do HealthReport e do ExtractionResult do MESMO lote. Saída: semente de
64 bytes, somente quando a política é satisfeita; senão MixPolicyError e nada.

keygen:     chave real. Fonte simulada é erro de configuração, mesmo reprovada.
            Fonte reprovada ou sem saída é excluída e registrada. Exige ao menos
            MIN_LOCAL_NON_SIMULATED_SOURCES fonte(s) local(is), não simulada(s) e
            aprovada(s), que juntas contribuam com pelo menos 512 bits extraídos
            (o tamanho da semente). Só este modo marca a semente como utilizável.
experiment: aceita fontes simuladas; exige fonte local aprovada com o mesmo piso
            de bits. A semente nunca é marcada como utilizável para chave.

Flags (`is_local`, `is_simulated`, `approved`) só valem se forem booleanos
(bool ou numpy.bool_). Qualquer outro valor conta como o pior caso.

Codificação (fixada aqui; PROJECT.md 6.9 não dizia como codificar os tamanhos):
    SHA3-512( MIX_DOMAIN ||
              para cada fonte incluída, por ordem de código Unicode do source_id:
                  len(id_utf8) [8 bytes BE] || id_utf8 ||
                  n_bits [8 bytes BE] || packbits(saída) )
O contador é de BITS, não de bytes: packbits preenche o último byte com zeros.

Campos de HealthReport usados: source_id, batch_id, n_bits, approved, reasons.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from eal.config import (
    MIN_LOCAL_NON_SIMULATED_SOURCES,
    MIN_LOCAL_OUTPUT_BITS,
    MIN_LOCAL_SOURCES_EXPERIMENT,
    MIX_DOMAIN,
    SEED_BYTES,
)
from eal.extract.blocks import ExtractionResult, hash_bits, validate_bits

MODES: tuple[str, ...] = ("keygen", "experiment")
MIXER_TYPE = "sha3-512"
_LEN_BYTES = 8  # comprimentos em 8 bytes big-endian, como no batch_hash


class MixPolicyError(ValueError):
    """Política não satisfeita ou entrada inconsistente. Nenhuma semente é gerada."""


def _is_true(value: Any) -> bool:
    return isinstance(value, (bool, np.bool_)) and bool(value)


def _is_false(value: Any) -> bool:
    return isinstance(value, (bool, np.bool_)) and not bool(value)


@dataclass(frozen=True)
class MixInput:
    """Uma contribuição. `input_hash` é hash_bits dos bits do lote, calculado pelo mixer."""

    source_id: str
    batch_id: str
    input_hash: str
    is_local: Any
    is_simulated: Any
    report: Any = field(repr=False)
    extraction: ExtractionResult = field(repr=False)

    @property
    def local(self) -> bool:
        """True só se is_local for booleano verdadeiro (fail-closed)."""
        return _is_true(self.is_local)

    @property
    def simulated(self) -> bool:
        """False só se is_simulated for booleano falso (fail-closed)."""
        return not _is_false(self.is_simulated)


@dataclass(frozen=True)
class Exclusion:
    """Fonte que não entrou na mistura, com os motivos registrados."""

    source_id: str
    batch_id: str
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class MixResult:
    """Semente e proveniência. A semente fica só em memória e não vai para `to_dict()`."""

    mode: str
    usable_for_key: bool
    seed: bytes = field(repr=False, compare=False)
    seed_hash: str
    included: tuple[MixInput, ...] = field(repr=False)
    excluded: tuple[Exclusion, ...]
    mixer_type: str = MIXER_TYPE

    @property
    def included_ids(self) -> tuple[str, ...]:
        """source_id das fontes misturadas, na ordem da combinação."""
        return tuple(m.source_id for m in self.included)

    def to_dict(self) -> dict[str, Any]:
        """Metadados para o recibo: só hashes e contagens, nenhum bit nem byte de semente."""
        return {
            "mode": self.mode,
            "usable_for_key": self.usable_for_key,
            "mixer_type": self.mixer_type,
            "domain": MIX_DOMAIN.decode("ascii"),
            "policy": _policy_text(self.mode),
            "seed_hash": self.seed_hash,
            "included": [
                {
                    "source_id": m.source_id,
                    "batch_id": m.batch_id,
                    "input_hash": m.input_hash,
                    "is_local": m.local,
                    "is_simulated": m.simulated,
                    "n_bits_mixed": m.extraction.n_output_bits,
                }
                for m in self.included
            ],
            "excluded": [
                {"source_id": e.source_id, "batch_id": e.batch_id, "reasons": list(e.reasons)}
                for e in self.excluded
            ],
        }


def make_mix_input(batch: Any, report: Any, extraction: ExtractionResult) -> MixInput:
    """Ponto de entrada normal: amarra relatório e extração ao lote pelos bits."""
    input_hash = hash_bits(validate_bits(batch.bits))
    mi = MixInput(
        source_id=batch.source_id,
        batch_id=batch.batch_id,
        input_hash=input_hash,
        is_local=batch.is_local,
        is_simulated=batch.is_simulated,
        report=report,
        extraction=extraction,
    )
    _check_pairing(mi)
    return mi


def mix(inputs: Sequence[MixInput], mode: str = "keygen") -> MixResult:
    """Aplica a política e combina as saídas aprovadas. Levanta MixPolicyError se falhar."""
    if mode not in MODES:
        raise ValueError(f"modo desconhecido: {mode!r}")
    _check_unique(inputs)
    for mi in inputs:
        _check_pairing(mi)
    if mode == "keygen":
        _refuse_simulated(inputs)
    approved, excluded = _split(inputs)
    _check_policy(approved, mode)
    included = tuple(sorted(approved, key=lambda m: m.source_id))
    seed = _combine(included)
    return MixResult(
        mode=mode,
        usable_for_key=mode == "keygen",
        seed=seed,
        seed_hash=hashlib.sha3_256(seed).hexdigest(),
        included=included,
        excluded=tuple(sorted(excluded, key=lambda e: e.source_id)),
    )


def _policy_text(mode: str) -> str:
    if mode == "keygen":
        return (f"min_local_non_simulated={MIN_LOCAL_NON_SIMULATED_SOURCES};"
                f"min_local_bits={MIN_LOCAL_OUTPUT_BITS};no_simulated")
    return f"min_local={MIN_LOCAL_SOURCES_EXPERIMENT};min_local_bits={MIN_LOCAL_OUTPUT_BITS}"


def _check_unique(inputs: Sequence[MixInput]) -> None:
    for name in ("source_id", "batch_id", "input_hash"):
        values = [getattr(mi, name) for mi in inputs]
        if len(set(values)) != len(values):
            raise MixPolicyError(f"{name} repetido entre as contribuições")


def _check_pairing(mi: MixInput) -> None:
    """Relatório e extração precisam ser do mesmo lote da contribuição."""
    r, e = mi.report, mi.extraction
    if r.batch_id != mi.batch_id or r.source_id != mi.source_id:
        raise MixPolicyError(f"{mi.source_id}: relatório de saúde de outro lote ou fonte")
    if e.input_hash is None or e.input_hash != mi.input_hash:
        raise MixPolicyError(f"{mi.source_id}: extração não feita sobre os bits deste lote")
    if r.n_bits != e.n_input_bits:
        raise MixPolicyError(f"{mi.source_id}: relatório e extração com tamanhos diferentes")


def _refuse_simulated(inputs: Sequence[MixInput]) -> None:
    for mi in inputs:
        if mi.simulated:
            raise MixPolicyError(f"fonte simulada em keygen: {mi.source_id}")


def _split(inputs: Sequence[MixInput]) -> tuple[list[MixInput], list[Exclusion]]:
    approved: list[MixInput] = []
    excluded: list[Exclusion] = []
    for mi in inputs:
        reasons = _exclusion_reasons(mi)
        if reasons:
            excluded.append(Exclusion(mi.source_id, mi.batch_id, reasons))
        else:
            approved.append(mi)
    return approved, excluded


def _exclusion_reasons(mi: MixInput) -> tuple[str, ...]:
    reasons: list[str] = []
    if not _is_true(mi.report.approved):
        motivos = [str(x) for x in mi.report.reasons] or ["sem motivo registrado"]
        reasons.append("reprovada pelo teste de saúde: " + "; ".join(motivos))
    if mi.extraction.n_output_bits == 0:
        reasons.append("sem saída de extração (lote curto ou entropia insuficiente)")
    return tuple(reasons)


def _check_policy(approved: list[MixInput], mode: str) -> None:
    if not approved:
        raise MixPolicyError("política: nenhuma fonte aprovada com saída")
    if mode == "keygen":
        need, what = MIN_LOCAL_NON_SIMULATED_SOURCES, "local e não simulada"
        required = [m for m in approved if m.local and not m.simulated]
    else:
        need, what = MIN_LOCAL_SOURCES_EXPERIMENT, "local"
        required = [m for m in approved if m.local]
    if len(required) < need:
        raise MixPolicyError(f"política: exige {need} fonte(s) aprovada(s) {what}; há {len(required)}")
    local_bits = sum(m.extraction.n_output_bits for m in required)
    if local_bits < MIN_LOCAL_OUTPUT_BITS:
        raise MixPolicyError(
            f"política: fontes {what} somam {local_bits} bits extraídos; mínimo {MIN_LOCAL_OUTPUT_BITS}"
        )


def _combine(included: Sequence[MixInput]) -> bytes:
    """Aplica a codificação descrita no docstring do módulo."""
    h = hashlib.sha3_512()
    h.update(MIX_DOMAIN)
    for mi in included:
        sid = mi.source_id.encode("utf-8")
        bits = validate_bits(mi.extraction.bits)
        h.update(len(sid).to_bytes(_LEN_BYTES, "big"))
        h.update(sid)
        h.update(bits.size.to_bytes(_LEN_BYTES, "big"))
        h.update(np.packbits(bits).tobytes())
    digest = h.digest()
    if len(digest) != SEED_BYTES:
        raise RuntimeError("SEED_BYTES diferente do tamanho do SHA3-512")
    return digest
