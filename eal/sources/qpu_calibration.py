"""Dia 6: modelo de custo de QPU por job e planejamento da coleta (contas puras, sem IBM).

Transforma o consumo medido de poucos jobs (``quantum_seconds`` do log de uso) em reserva por
job e em plano de coleta. O consumo vem em segundos INTEIROS, então um job pequeno mede mal o
custo por shot; por isso o modelo nunca subestima:

- ``custo = fixo + por_shot * shots`` por mínimos quadrados, deslocado para cima até cobrir o
  pior ponto observado (``envelope_seconds``): a reta alta nunca fica abaixo de um job medido;
- a reserva de um job é ``ceil(custo_alto * fator + extra)``, e é o ``max_execution_time``
  pedido ao servidor; se passar do máximo por job a função recusa, nunca trunca;
- com um só ponto, assume-se que todo o tempo é por shot (fixo = 0). Isso é um limite
  superior seguro para jobs com mais shots que o medido: se ``t = a + b*s`` com ``a >= 0``,
  então ``t/s >= b`` e ``(t/s)*s2 >= a + b*s2`` para ``s2 >= s``;
- os pontos saem do log de uso (sem número digitado à mão) e só entram jobs ``status=DONE``:
  um job cortado por tempo teria uso próximo da reserva e envenenaria o ajuste.

Nada aqui lê o log do disco nem fala com a IBM; quem chama passa as entradas e os parâmetros.
"""
from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from eal.sources.qpu_budget import UsageEntry


def _is_number(value: Any) -> bool:
    """Número real finito (bool não vale)."""
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value))


def _is_int(value: Any) -> bool:
    """Inteiro de verdade (bool não vale)."""
    return isinstance(value, int) and not isinstance(value, bool)


def _check_policy(safety_factor: Any, extra_seconds: Any, max_reserve: Any) -> None:
    """Parâmetros da reserva; ValueError se algum for inválido."""
    if not _is_number(safety_factor) or safety_factor < 1:
        raise ValueError("safety_factor deve ser um número maior ou igual a 1")
    if not _is_number(extra_seconds) or extra_seconds < 0:
        raise ValueError("extra_seconds deve ser um número maior ou igual a 0")
    if not _is_int(max_reserve) or max_reserve < 1:
        raise ValueError("max_reserve deve ser um inteiro maior ou igual a 1")


def _check_positive_int(name: str, value: Any) -> None:
    if not _is_int(value) or value < 1:
        raise ValueError(f"{name} deve ser um inteiro maior ou igual a 1")


@dataclass(frozen=True)
class CalibrationPoint:
    """Um job medido: quantos shots e quantos segundos de QPU ele usou."""

    shots: int
    seconds: float

    def __post_init__(self) -> None:
        _check_positive_int("shots", self.shots)
        if not _is_number(self.seconds) or self.seconds < 0:
            raise ValueError("seconds deve ser um número maior ou igual a 0")


@dataclass(frozen=True)
class CostModel:
    """Custo de um job em segundos de QPU: ``fixo + por_shot * shots`` (+ envelope no alto)."""

    fixed_seconds: float
    per_shot_seconds: float
    envelope_seconds: float
    n_points: int

    def __post_init__(self) -> None:
        if not _is_number(self.fixed_seconds):
            raise ValueError("fixed_seconds inválido")
        if not _is_number(self.per_shot_seconds) or self.per_shot_seconds <= 0:
            raise ValueError("per_shot_seconds deve ser positivo")
        if not _is_number(self.envelope_seconds) or self.envelope_seconds < 0:
            raise ValueError("envelope_seconds deve ser maior ou igual a 0")
        _check_positive_int("n_points", self.n_points)

    def central_seconds(self, shots: int) -> float:
        """Custo estimado pela reta de mínimos quadrados."""
        return self.fixed_seconds + self.per_shot_seconds * shots

    def upper_seconds(self, shots: int) -> float:
        """Custo alto: a reta deslocada para cobrir o pior ponto observado; nunca negativo."""
        return max(0.0, self.central_seconds(shots) + self.envelope_seconds)


def fit_cost_model(points: Sequence[CalibrationPoint]) -> CostModel:
    """Ajusta o modelo por mínimos quadrados e calcula o envelope.

    ValueError com menos de 2 jobs ou sem 2 números de shots diferentes, e se o custo por shot
    sair não positivo (ruído de arredondamento: use jobs maiores).
    """
    pts = list(points)
    if len(pts) < 2 or len({p.shots for p in pts}) < 2:
        raise ValueError("preciso de ao menos 2 jobs com números de shots diferentes")
    n = len(pts)
    mean_x = sum(p.shots for p in pts) / n
    mean_y = sum(p.seconds for p in pts) / n
    sxx = sum((p.shots - mean_x) ** 2 for p in pts)
    sxy = sum((p.shots - mean_x) * (p.seconds - mean_y) for p in pts)
    per_shot = sxy / sxx
    if not per_shot > 0:
        raise ValueError("custo por shot não positivo: dados insuficientes ou ruído de "
                         "arredondamento; use jobs com mais shots")
    fixed = mean_y - per_shot * mean_x
    envelope = max(0.0, max(p.seconds - (fixed + per_shot * p.shots) for p in pts))
    return CostModel(fixed, per_shot, envelope, n)


def _need(model: CostModel, shots: int, safety_factor: float, extra_seconds: float) -> int:
    """Reserva (inteira, pelo menos 1) que o job precisa, sem conferir o máximo."""
    return max(1, math.ceil(model.upper_seconds(shots) * safety_factor + extra_seconds))


def reserve_for(model: CostModel, shots: int, *, safety_factor: float, extra_seconds: float,
                max_reserve: int) -> int:
    """Reserva (``max_execution_time``) de um job; ValueError se passar do máximo por job."""
    _check_positive_int("shots", shots)
    _check_policy(safety_factor, extra_seconds, max_reserve)
    need = _need(model, shots, safety_factor, extra_seconds)
    if need > max_reserve:
        raise ValueError(f"a reserva necessária ({need} s) passa do máximo por job "
                         f"({max_reserve} s)")
    return need


def max_shots_for_reserve(model: CostModel, *, safety_factor: float, extra_seconds: float,
                          max_reserve: int, max_shots: int) -> int:
    """Maior número de shots cuja reserva cabe em ``max_reserve``; 0 se nem 1 shot couber."""
    _check_policy(safety_factor, extra_seconds, max_reserve)
    _check_positive_int("max_shots", max_shots)
    room = ((max_reserve - extra_seconds) / safety_factor
            - (model.fixed_seconds + model.envelope_seconds))
    guess = math.floor(room / model.per_shot_seconds) if room > 0 else 0
    shots = max(0, min(guess, max_shots))
    while shots > 0 and _need(model, shots, safety_factor, extra_seconds) > max_reserve:
        shots -= 1
    while (shots < max_shots
           and _need(model, shots + 1, safety_factor, extra_seconds) <= max_reserve):
        shots += 1
    return shots


def size_next_job(first: CalibrationPoint, *, target_seconds: float, safety_factor: float,
                  extra_seconds: float, max_reserve: int, max_shots: int) -> tuple[int, int]:
    """Shots e reserva do segundo job de calibração, a partir de um só ponto medido.

    Assume que todo o tempo do primeiro job foi por shot (limite superior seguro para um job
    com mais shots). Devolve ``(shots, reserva)``; nunca menos shots que o primeiro job.
    """
    if not _is_number(target_seconds) or target_seconds <= 0:
        raise ValueError("target_seconds deve ser um número positivo")
    if first.seconds <= 0:
        raise ValueError("uso medido igual a zero: o job foi pequeno demais para medir")
    model = CostModel(0.0, first.seconds / first.shots, 0.0, 1)
    by_target = math.floor(target_seconds / model.per_shot_seconds)
    by_reserve = max_shots_for_reserve(model, safety_factor=safety_factor,
                                       extra_seconds=extra_seconds, max_reserve=max_reserve,
                                       max_shots=max_shots)
    shots = max(first.shots, min(by_target, by_reserve, max_shots))
    reserve = reserve_for(model, shots, safety_factor=safety_factor,
                          extra_seconds=extra_seconds, max_reserve=max_reserve)
    return shots, reserve


@dataclass(frozen=True)
class CollectionPlan:
    """Plano para juntar ``target_bits``: jobs iguais, com a reserva de cada um."""

    n_jobs: int
    shots_per_job: int
    reserve_per_job: int
    total_shots: int
    total_bits: int
    central_seconds: float
    upper_seconds: float
    reserved_seconds: int
    fits_budget: bool


def plan_collection(model: CostModel, *, target_bits: int, qubits: int,
                    session_budget_seconds: float, safety_factor: float, extra_seconds: float,
                    max_reserve: int, max_shots: int) -> CollectionPlan:
    """Menor número de jobs iguais que junta ``target_bits`` com cada reserva dentro do máximo.

    ``fits_budget`` compara o custo ALTO total com o orçamento da sessão (a reserva só vale
    enquanto o job está pendente; o consumo real é o que gasta o saldo).
    """
    _check_positive_int("target_bits", target_bits)
    _check_positive_int("qubits", qubits)
    if not _is_number(session_budget_seconds) or session_budget_seconds < 0:
        raise ValueError("session_budget_seconds deve ser um número maior ou igual a 0")
    per_job_max = max_shots_for_reserve(model, safety_factor=safety_factor,
                                        extra_seconds=extra_seconds, max_reserve=max_reserve,
                                        max_shots=max_shots)
    if per_job_max < 1:
        raise ValueError("nem 1 shot cabe na reserva máxima por job")
    wanted_shots = -(-target_bits // qubits)
    n_jobs = -(-wanted_shots // per_job_max)
    shots_per_job = -(-wanted_shots // n_jobs)
    reserve = reserve_for(model, shots_per_job, safety_factor=safety_factor,
                          extra_seconds=extra_seconds, max_reserve=max_reserve)
    total_shots = shots_per_job * n_jobs
    upper = n_jobs * model.upper_seconds(shots_per_job)
    return CollectionPlan(
        n_jobs=n_jobs, shots_per_job=shots_per_job, reserve_per_job=reserve,
        total_shots=total_shots, total_bits=total_shots * qubits,
        central_seconds=n_jobs * model.fixed_seconds + model.per_shot_seconds * total_shots,
        upper_seconds=upper, reserved_seconds=n_jobs * reserve,
        fits_budget=upper <= session_budget_seconds)


def points_from_entries(entries: Sequence[UsageEntry], *, backend: str | None = None,
                        qubits: int | None = None) -> list[CalibrationPoint]:
    """Pontos de calibração a partir do log de uso (``submitted`` + ``final``).

    Só entram jobs concluídos com ``status=DONE`` e uso informado e positivo; falhas,
    cancelamentos, jobs sem uso e jobs pendentes ficam de fora. ``backend`` e ``qubits``
    filtram pelo que foi enviado.
    """
    submitted = {
        e.job_id: e for e in entries
        if e.event == "submitted" and (backend is None or e.backend == backend)
        and (qubits is None or e.qubits == qubits)}
    points: list[CalibrationPoint] = []
    for entry in entries:
        if (entry.event != "final" or entry.quantum_seconds is None
                or entry.quantum_seconds <= 0 or not entry.note.startswith("status=DONE")):
            continue
        sent = submitted.get(entry.job_id)
        if sent is None or sent.shots is None:
            continue
        points.append(CalibrationPoint(sent.shots, float(entry.quantum_seconds)))
    return points
