"""Testes das constantes da política de QPU e do acesso à IBM em eal/config.py (Dia 6, 3a)."""
from __future__ import annotations

import re

import pytest

from eal import config
from eal.sources.qpu_budget import BudgetPolicy


def policy() -> BudgetPolicy:
    return BudgetPolicy(
        total_seconds=config.QPU_TOTAL_BUDGET_SECONDS,
        margin_seconds=config.QPU_BUDGET_MARGIN_SECONDS,
        daily_cap_seconds=config.QPU_DAILY_CAP_SECONDS,
        max_job_reserve_seconds=config.QPU_MAX_JOB_RESERVE_SECONDS,
        window_days=config.QPU_BUDGET_WINDOW_DAYS)


def test_as_constantes_formam_uma_politica_valida():
    assert policy().total_seconds == 600


def test_valores_do_plano_do_dia_6():
    assert config.QPU_TOTAL_BUDGET_SECONDS == 600
    assert config.QPU_BUDGET_MARGIN_SECONDS == 30
    assert config.QPU_BUDGET_WINDOW_DAYS == 28
    assert config.QPU_DAILY_CAP_SECONDS == 330
    assert config.QPU_MAX_JOB_RESERVE_SECONDS == 60
    assert config.QPU_MAX_SHOTS_PER_JOB == 100_000


@pytest.mark.parametrize("name", [
    "QPU_TOTAL_BUDGET_SECONDS", "QPU_BUDGET_MARGIN_SECONDS", "QPU_BUDGET_WINDOW_DAYS",
    "QPU_DAILY_CAP_SECONDS", "QPU_MAX_JOB_RESERVE_SECONDS", "QPU_MAX_SHOTS_PER_JOB",
])
def test_numeros_sao_inteiros_positivos(name):
    value = getattr(config, name)
    assert type(value) is int and value > 0


def test_o_teto_diario_cabe_no_total_menos_a_margem():
    assert config.QPU_DAILY_CAP_SECONDS <= config.QPU_TOTAL_BUDGET_SECONDS - config.QPU_BUDGET_MARGIN_SECONDS
    assert config.QPU_MAX_JOB_RESERVE_SECONDS <= config.QPU_DAILY_CAP_SECONDS


def test_backend_e_instancia_seguem_o_padrao_de_texto_do_recibo():
    pattern = re.compile(config.RECEIPT_BATCH_PARAM_TEXT_PATTERN)
    assert pattern.fullmatch(config.IBM_DEFAULT_BACKEND)
    assert config.IBM_DEFAULT_BACKEND == "ibm_kingston"
    assert config.IBM_DEFAULT_INSTANCE == "open-instance"


def test_nome_do_log_e_um_arquivo_csv_sem_caminho():
    name = config.QPU_USAGE_LOG_NAME
    assert name == "qpu_usage.csv" and "/" not in name and "\\" not in name


def test_o_config_so_guarda_o_nome_da_variavel_do_token():
    assert re.fullmatch(r"[A-Z][A-Z0-9_]{2,39}", config.IBM_TOKEN_ENV)
    assert config.IBM_TOKEN_ENV == "IBM_QUANTUM_TOKEN"
    text = open(config.__file__, encoding="utf-8").read()
    assert not re.search(r"token\s*=\s*['\"][A-Za-z0-9_-]{20,}", text, flags=re.IGNORECASE)
