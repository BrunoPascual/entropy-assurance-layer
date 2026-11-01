"""Testes do modelo de custo de QPU e do planejamento da coleta (Dia 6)."""
from __future__ import annotations

import math

import pytest

from eal.sources.qpu_budget import UsageEntry
from eal.sources.qpu_calibration import (
    CalibrationPoint, CostModel, fit_cost_model, max_shots_for_reserve, plan_collection,
    points_from_entries, reserve_for, size_next_job,
)

POLICY = dict(safety_factor=1.5, extra_seconds=2, max_reserve=60)
MODEL = CostModel(fixed_seconds=2.0, per_shot_seconds=0.001, envelope_seconds=0.5, n_points=3)
TS = "2026-11-02T15:00:00+00:00"


# ------------------------------------------------------------------ validação dos tipos

@pytest.mark.parametrize("shots", [0, -1, True, 1.5, "10", None])
def test_ponto_com_shots_invalido(shots):
    with pytest.raises(ValueError):
        CalibrationPoint(shots, 1.0)


@pytest.mark.parametrize("seconds", [-1, math.nan, math.inf, True, "1", None])
def test_ponto_com_segundos_invalidos(seconds):
    with pytest.raises(ValueError):
        CalibrationPoint(100, seconds)


def test_ponto_aceita_zero_segundos():
    assert CalibrationPoint(100, 0).seconds == 0


@pytest.mark.parametrize("kwargs", [
    {"fixed_seconds": math.nan}, {"fixed_seconds": True}, {"per_shot_seconds": 0},
    {"per_shot_seconds": -0.1}, {"per_shot_seconds": math.inf}, {"envelope_seconds": -0.1},
    {"envelope_seconds": math.nan}, {"n_points": 0}, {"n_points": True},
])
def test_modelo_invalido(kwargs):
    base = dict(fixed_seconds=1.0, per_shot_seconds=0.001, envelope_seconds=0.0, n_points=2)
    base.update(kwargs)
    with pytest.raises(ValueError):
        CostModel(**base)


def test_custo_central_e_alto():
    assert MODEL.central_seconds(1000) == pytest.approx(3.0)
    assert MODEL.upper_seconds(1000) == pytest.approx(3.5)


def test_custo_alto_nunca_e_negativo():
    assert CostModel(-100.0, 0.001, 0.0, 2).upper_seconds(10) == 0.0


# ------------------------------------------------------------------ ajuste

def test_ajuste_de_uma_reta_exata():
    model = fit_cost_model([CalibrationPoint(1000, 3.0), CalibrationPoint(5000, 7.0)])
    assert model.per_shot_seconds == pytest.approx(0.001)
    assert model.fixed_seconds == pytest.approx(2.0)
    assert model.envelope_seconds == pytest.approx(0.0, abs=1e-9)
    assert model.n_points == 2


def test_ajuste_com_tres_pontos_e_envelope():
    points = [CalibrationPoint(1000, 3), CalibrationPoint(5000, 8), CalibrationPoint(10000, 12)]
    model = fit_cost_model(points)
    residuals = [p.seconds - model.central_seconds(p.shots) for p in points]
    assert model.envelope_seconds == pytest.approx(max(0.0, max(residuals)))
    assert model.envelope_seconds > 0


@pytest.mark.parametrize("data", [
    [(1000, 3), (5000, 8), (10000, 12)],
    [(500, 2), (4096, 3), (8192, 5), (20000, 11)],
    [(1000, 2), (2000, 2), (4000, 3)],
    [(100, 1), (10000, 40)],
    [(4096, 2), (4096, 3), (8192, 4)],
])
def test_o_custo_alto_nunca_fica_abaixo_de_um_job_medido(data):
    points = [CalibrationPoint(s, t) for s, t in data]
    model = fit_cost_model(points)
    for p in points:
        assert model.upper_seconds(p.shots) >= p.seconds - 1e-9


def test_ajuste_pede_dois_jobs():
    with pytest.raises(ValueError, match="ao menos 2"):
        fit_cost_model([CalibrationPoint(1000, 3)])
    with pytest.raises(ValueError, match="ao menos 2"):
        fit_cost_model([])


def test_ajuste_pede_shots_diferentes():
    with pytest.raises(ValueError, match="shots diferentes"):
        fit_cost_model([CalibrationPoint(1000, 3), CalibrationPoint(1000, 4)])


@pytest.mark.parametrize("data", [[(1000, 5), (5000, 5)], [(1000, 6), (5000, 4)]])
def test_custo_por_shot_nao_positivo_e_recusado(data):
    with pytest.raises(ValueError, match="não positivo"):
        fit_cost_model([CalibrationPoint(s, t) for s, t in data])


# ------------------------------------------------------------------ reserva

def test_reserva_de_12821_shots():
    # custo alto = 2 + 12,821 + 0,5 = 15,321; x 1,5 = 22,9815; + 2 = 24,9815 -> 25
    assert reserve_for(MODEL, 12821, **POLICY) == 25


def test_reserva_minima_e_um():
    tiny = CostModel(0.0, 1e-9, 0.0, 1)
    assert reserve_for(tiny, 1, safety_factor=1.0, extra_seconds=0, max_reserve=60) == 1


def test_reserva_nunca_e_zero_mesmo_com_custo_alto_zero():
    flat = CostModel(-100.0, 0.001, 0.0, 2)          # custo alto = 0 para poucos shots
    assert flat.upper_seconds(10) == 0.0
    assert reserve_for(flat, 10, safety_factor=1.0, extra_seconds=0, max_reserve=60) == 1


def test_reserva_no_limite_exato_passa_e_um_shot_a_mais_nao():
    assert reserve_for(MODEL, 36166, **POLICY) == 60
    with pytest.raises(ValueError, match="passa do máximo"):
        reserve_for(MODEL, 36167, **POLICY)


def test_reserva_acima_do_maximo_e_recusada_e_nao_truncada():
    with pytest.raises(ValueError, match="156 s"):
        reserve_for(MODEL, 100_000, **POLICY)


@pytest.mark.parametrize("policy", [
    {"safety_factor": 0.9}, {"safety_factor": math.nan}, {"safety_factor": True},
    {"extra_seconds": -1}, {"extra_seconds": math.inf}, {"max_reserve": 0},
    {"max_reserve": 1.5}, {"max_reserve": True},
])
def test_parametros_invalidos_da_reserva(policy):
    kwargs = dict(POLICY)
    kwargs.update(policy)
    with pytest.raises(ValueError):
        reserve_for(MODEL, 100, **kwargs)


@pytest.mark.parametrize("shots", [0, -1, True, 1.5])
def test_shots_invalidos_na_reserva(shots):
    with pytest.raises(ValueError):
        reserve_for(MODEL, shots, **POLICY)


# ------------------------------------------------------------------ máximo de shots por reserva

def test_maximo_de_shots_pela_reserva():
    assert max_shots_for_reserve(MODEL, max_shots=100_000, **POLICY) == 36166


def test_maximo_de_shots_limitado_pelo_backend():
    assert max_shots_for_reserve(MODEL, max_shots=5000, **POLICY) == 5000


def test_nem_um_shot_cabe():
    heavy = CostModel(100.0, 0.001, 0.0, 2)
    assert max_shots_for_reserve(heavy, max_shots=100_000, **POLICY) == 0


@pytest.mark.parametrize("model", [
    CostModel(2.0, 0.001, 0.5, 3), CostModel(0.0, 0.004, 0.0, 1),
    CostModel(-5.0, 0.01, 0.0, 2), CostModel(1.7, 0.0005, 1.2, 4),
    CostModel(10.0, 0.02, 0.0, 2), CostModel(0.3, 0.0000123, 0.7, 5),
])
@pytest.mark.parametrize("policy", [
    dict(safety_factor=1.5, extra_seconds=2, max_reserve=60),
    dict(safety_factor=1.0, extra_seconds=0, max_reserve=10),
    dict(safety_factor=2.0, extra_seconds=5, max_reserve=100),
])
def test_o_maximo_e_o_maior_que_cabe(model, policy):
    top = max_shots_for_reserve(model, max_shots=100_000, **policy)
    if top >= 1:
        assert reserve_for(model, top, **policy) <= policy["max_reserve"]
    if top < 100_000:
        with pytest.raises(ValueError):
            reserve_for(model, top + 1, **policy)


# ------------------------------------------------------------------ segundo job de calibração

def test_segundo_job_pelo_alvo():
    # por shot = 2/500 = 0,004; alvo 8 s -> 2000 shots; reserva = ceil(8 x 1,5 + 2) = 14
    assert size_next_job(CalibrationPoint(500, 2.0), target_seconds=8, max_shots=100_000,
                         **POLICY) == (2000, 14)


def test_segundo_job_limitado_pela_reserva():
    # a reserva maxima de 60 s cabe 9666 shots a 0,004 s por shot
    assert size_next_job(CalibrationPoint(500, 2.0), target_seconds=1000, max_shots=100_000,
                         **POLICY) == (9666, 60)


def test_segundo_job_limitado_pelo_backend():
    shots, _ = size_next_job(CalibrationPoint(500, 2.0), target_seconds=1000, max_shots=3000,
                             **POLICY)
    assert shots == 3000


def test_segundo_job_nunca_tem_menos_shots_que_o_primeiro():
    assert size_next_job(CalibrationPoint(500, 2.0), target_seconds=0.5, max_shots=100_000,
                         **POLICY) == (500, 5)


@pytest.mark.parametrize("fixed,per_shot", [(0.0, 0.004), (1.0, 0.002), (1.7, 0.0005),
                                              (1.9, 0.0001), (0.5, 0.003)])
def test_a_reserva_do_segundo_job_cobre_o_custo_real(fixed, per_shot):
    """Para qualquer divisão entre custo fixo e por shot, a reserva cobre o job real."""
    first = CalibrationPoint(500, fixed + per_shot * 500)
    shots, reserve = size_next_job(first, target_seconds=8, max_shots=100_000, **POLICY)
    assert fixed + per_shot * shots <= reserve


def test_segundo_job_sem_uso_medido_e_recusado():
    with pytest.raises(ValueError, match="igual a zero"):
        size_next_job(CalibrationPoint(500, 0), target_seconds=8, max_shots=100_000, **POLICY)


@pytest.mark.parametrize("target", [0, -1, math.nan, True, "8"])
def test_alvo_invalido(target):
    with pytest.raises(ValueError):
        size_next_job(CalibrationPoint(500, 2.0), target_seconds=target, max_shots=100_000,
                      **POLICY)


def test_primeiro_job_grande_demais_para_a_reserva_e_recusado():
    with pytest.raises(ValueError, match="passa do máximo"):
        size_next_job(CalibrationPoint(20000, 100.0), target_seconds=8, max_shots=100_000,
                      **POLICY)


# ------------------------------------------------------------------ plano da coleta

def plan(model=MODEL, target_bits=2_000_000, qubits=156, budget=330, max_shots=100_000, **kw):
    kwargs = dict(POLICY)
    kwargs.update(kw)
    return plan_collection(model, target_bits=target_bits, qubits=qubits,
                           session_budget_seconds=budget, max_shots=max_shots, **kwargs)


def test_plano_de_2_milhoes_de_bits_cabe_em_um_job():
    p = plan()
    assert (p.n_jobs, p.shots_per_job, p.reserve_per_job) == (1, 12821, 25)
    assert p.total_shots == 12821 and p.total_bits == 12821 * 156 == 2_000_076
    assert p.central_seconds == pytest.approx(14.821)
    assert p.upper_seconds == pytest.approx(15.321)
    assert p.reserved_seconds == 25 and p.fits_budget is True


def test_plano_com_varios_jobs_iguais():
    p = plan(target_bits=20_000_000)
    assert (p.n_jobs, p.shots_per_job) == (4, 32052)
    assert p.total_shots == 4 * 32052 and p.total_bits == p.total_shots * 156
    assert p.total_bits >= 20_000_000
    assert p.reserve_per_job <= 60 and p.reserved_seconds == 4 * p.reserve_per_job


def test_plano_limitado_pelo_maximo_de_shots_do_backend():
    p = plan(max_shots=5000)
    assert (p.n_jobs, p.shots_per_job, p.total_shots) == (3, 4274, 12822)


def test_plano_com_alvo_divisivel():
    p = plan(target_bits=156_000)
    assert (p.n_jobs, p.shots_per_job, p.total_bits) == (1, 1000, 156_000)


def test_plano_usa_o_menor_numero_de_jobs():
    for target in (1, 155, 156, 157, 1_000_000, 5_000_000, 50_000_000):
        p = plan(target_bits=target)
        per_job_max = max_shots_for_reserve(MODEL, max_shots=100_000, **POLICY)
        wanted = -(-target // 156)
        assert p.shots_per_job <= per_job_max
        assert p.total_shots >= wanted
        assert (p.n_jobs - 1) * per_job_max < wanted
        assert p.total_bits >= target


def test_plano_cabe_no_orcamento_na_borda():
    base = plan()
    assert plan(budget=base.upper_seconds).fits_budget is True
    assert plan(budget=base.upper_seconds - 0.001).fits_budget is False
    assert plan(budget=0).fits_budget is False


@pytest.mark.parametrize("kwargs", [
    {"target_bits": 0}, {"target_bits": True}, {"target_bits": 1.5}, {"qubits": 0},
    {"qubits": True}, {"budget": -1}, {"budget": math.nan}, {"budget": True},
])
def test_plano_com_argumentos_invalidos(kwargs):
    with pytest.raises(ValueError):
        plan(**kwargs)


def test_plano_recusa_quando_nem_um_shot_cabe():
    with pytest.raises(ValueError, match="nem 1 shot"):
        plan(model=CostModel(100.0, 0.001, 0.0, 2))


# ------------------------------------------------------------------ pontos a partir do log

def sub(job, shots=4096, qubits=156, backend="ibm_kingston"):
    return UsageEntry(ts=TS, event="submitted", job_id=job, backend=backend, qubits=qubits,
                      shots=shots, reserve_seconds=20.0)


def fin(job, quantum=3.0, note="status=DONE"):
    return UsageEntry(ts=TS, event="final", job_id=job, quantum_seconds=quantum, note=note)


def test_pontos_de_jobs_concluidos():
    entries = [sub("a", 1000), fin("a", 3.0), sub("b", 5000), fin("b", 7.0)]
    assert points_from_entries(entries) == [CalibrationPoint(1000, 3.0),
                                            CalibrationPoint(5000, 7.0)]


def test_falhas_cancelamentos_e_pendentes_ficam_de_fora():
    entries = [
        sub("ok", 1000), fin("ok", 3.0),
        sub("erro", 2000), fin("erro", 9.0, note="status=ERROR"),
        sub("cancel", 3000), fin("cancel", 20.0, note="status=CANCELLED"),
        sub("semuso", 4000), fin("semuso", None),
        sub("zero", 5000), fin("zero", 0.0),
        sub("pendente", 6000),
        fin("orfao", 4.0),
    ]
    assert points_from_entries(entries) == [CalibrationPoint(1000, 3.0)]


def test_filtro_por_backend_e_por_qubits():
    entries = [sub("a", 1000, 156, "ibm_kingston"), fin("a", 3.0),
               sub("b", 2000, 156, "ibm_fez"), fin("b", 4.0),
               sub("c", 3000, 20, "ibm_kingston"), fin("c", 5.0)]
    assert len(points_from_entries(entries)) == 3
    assert points_from_entries(entries, backend="ibm_kingston") == [
        CalibrationPoint(1000, 3.0), CalibrationPoint(3000, 5.0)]
    assert points_from_entries(entries, qubits=156) == [
        CalibrationPoint(1000, 3.0), CalibrationPoint(2000, 4.0)]
    assert points_from_entries(entries, backend="ibm_kingston", qubits=156) == [
        CalibrationPoint(1000, 3.0)]


def test_job_enviado_sem_shots_no_log_e_ignorado():
    entries = [UsageEntry(ts=TS, event="submitted", job_id="a", reserve_seconds=10.0),
               fin("a", 3.0)]
    assert points_from_entries(entries) == []


def test_refused_e_ignorado():
    refused = UsageEntry(ts=TS, event="refused", note="status=DONE")
    assert points_from_entries([refused]) == []


def test_pontos_do_log_alimentam_o_ajuste():
    entries = [sub("a", 1000), fin("a", 3.0), sub("b", 5000), fin("b", 7.0)]
    model = fit_cost_model(points_from_entries(entries))
    assert model.per_shot_seconds == pytest.approx(0.001)
