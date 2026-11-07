"""Testes do limite duro de orçamento de QPU e do log de uso (G7 / T12)."""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

import pytest

from eal.sources import qpu_budget as qb
from eal.sources.qpu_budget import (
    USAGE_FIELDS, BudgetPolicy, UsageEntry, UsageLogError, append_entry, check_budget,
    entry_problems, format_header, format_row, parse_usage_log, read_log,
)

NOW = datetime(2026, 11, 2, 15, 0, tzinfo=timezone.utc)
POLICY = BudgetPolicy(total_seconds=600, margin_seconds=30, daily_cap_seconds=330,
                      max_job_reserve_seconds=60, window_days=28)
HOUR = timedelta(hours=1)
DAY = timedelta(days=1)


def at(age: timedelta) -> str:
    """Instante ISO que está ``age`` antes de NOW."""
    return (NOW - age).isoformat()


def sub(job: str, reserve: float = 20, age: timedelta = HOUR) -> UsageEntry:
    return UsageEntry(ts=at(age), event="submitted", job_id=job, backend="ibm_kingston",
                      qubits=156, shots=4096, reserve_seconds=reserve)


def fin(job: str, quantum: float | None = 5, age: timedelta = HOUR) -> UsageEntry:
    return UsageEntry(ts=at(age), event="final", job_id=job, quantum_seconds=quantum)


def check(entries, reserve=20, remote=598, **kw):
    return check_budget(entries, reserve, POLICY, remote, now=NOW, **kw)


# ---------------------------------------------------------------- política

@pytest.mark.parametrize("kwargs", [
    {"total_seconds": 0}, {"total_seconds": -1}, {"total_seconds": math.nan},
    {"total_seconds": True}, {"total_seconds": "600"}, {"margin_seconds": 0},
    {"margin_seconds": 600}, {"daily_cap_seconds": 571}, {"daily_cap_seconds": 0},
    {"max_job_reserve_seconds": 331}, {"max_job_reserve_seconds": 0},
    {"window_days": 0}, {"window_days": True}, {"window_days": 28.0},
])
def test_politica_invalida_e_recusada(kwargs):
    base = dict(total_seconds=600, margin_seconds=30, daily_cap_seconds=330,
                max_job_reserve_seconds=60, window_days=28)
    base.update(kwargs)
    with pytest.raises(ValueError):
        BudgetPolicy(**base)


def test_margem_igual_ao_total_tem_mensagem_propria():
    with pytest.raises(ValueError, match="a margem deve ser menor que o total"):
        BudgetPolicy(total_seconds=600, margin_seconds=600, daily_cap_seconds=330,
                     max_job_reserve_seconds=60, window_days=28)


def test_politica_aceita_os_limites_exatos():
    BudgetPolicy(total_seconds=600, margin_seconds=30, daily_cap_seconds=570,
                 max_job_reserve_seconds=570, window_days=1)


def test_now_sem_fuso_e_erro_de_uso():
    with pytest.raises(ValueError):
        check_budget([], 20, POLICY, 598, now=datetime(2026, 11, 2, 15, 0))


# ---------------------------------------------------------------- contas

def test_log_vazio_o_teto_diario_manda():
    d = check([])
    assert d.allowed and d.reasons == ()
    assert d.available_seconds == 330
    assert d.pending_job_ids == () and d.window_committed_seconds == 0


def test_borda_do_saldo_local():
    entries = []
    for i in range(9):  # 9 jobs de 60 s, todos de 2 dias atras ou mais: 540 s comprometidos
        age = (2 + i) * DAY
        entries += [sub(f"a{i}", 60, age), fin(f"a{i}", 60, age)]
    # saldo local = 600 - 30 - 540 = 30; teto diario (330) e saldo remoto (568) folgados
    d = check(entries, reserve=30)
    assert d.window_committed_seconds == 540 and d.day_committed_seconds == 0
    assert d.allowed and d.available_seconds == 30
    d = check(entries, reserve=31)
    assert not d.allowed and any("saldo local" in r for r in d.reasons)


def test_borda_do_saldo_remoto():
    assert check([], reserve=20, remote=50).allowed          # 50 - 30 = 20
    d = check([], reserve=20, remote=49.5)                   # 19,5 < 20
    assert not d.allowed and any("saldo remoto" in r for r in d.reasons)


def test_saldo_remoto_zero_e_valido_e_recusa_por_falta_de_saldo():
    d = check([], reserve=20, remote=0)
    assert not d.allowed
    assert any(r.startswith("saldo remoto: reserva") for r in d.reasons)
    assert not any("indisponível" in r for r in d.reasons)


@pytest.mark.parametrize("remote", [None, math.nan, math.inf, -1, True, "598"])
def test_saldo_remoto_ausente_ou_invalido_recusa(remote):
    d = check([], remote=remote)
    assert not d.allowed
    assert any("saldo remoto indisponível" in r for r in d.reasons)


def test_job_pendente_conta_pela_reserva_cheia_e_reduz_o_saldo_remoto():
    d = check([sub("a", 40)], reserve=20, remote=598)
    assert d.allowed
    assert d.pending_job_ids == ("a",) and d.pending_reserve_seconds == 40
    assert d.window_committed_seconds == 40 and d.day_committed_seconds == 40
    # local 600-30-40=530; remoto 598-30-40=528; teto 330-40=290
    assert d.available_seconds == 290
    # a reserva pendente também sai do saldo remoto (a IBM pode não ter contado ainda)
    assert check([sub("a", 40)], reserve=20, remote=89).allowed is False
    assert check([sub("a", 40)], reserve=20, remote=90).allowed is True


def test_job_concluido_conta_pelo_uso_real():
    d = check([sub("a", 40), fin("a", 5)])
    assert d.pending_job_ids == () and d.window_committed_seconds == 5


def test_final_sem_uso_informado_conta_pela_reserva():
    d = check([sub("a", 25), fin("a", None)])
    assert d.window_committed_seconds == 25 and d.pending_job_ids == ()


def test_uso_real_maior_que_a_reserva_conta_o_real():
    d = check([sub("a", 10), fin("a", 15)])
    assert d.window_committed_seconds == 15


def test_uso_zero_e_valido():
    d = check([sub("a", 10), fin("a", 0)])
    assert d.window_committed_seconds == 0


def test_teto_diario_e_janela_rolante_de_24_horas():
    entries = [sub("a", 60, 23 * HOUR), fin("a", 300, 23 * HOUR)]
    d = check(entries, reserve=30)
    assert d.day_committed_seconds == 300
    assert d.allowed and d.available_seconds == 30      # 330 - 300 manda
    d = check(entries, reserve=31)
    assert not d.allowed and any("24 h" in r for r in d.reasons)


def test_job_com_exatamente_24_horas_fica_fora_do_teto_diario():
    d = check([sub("a", 60, 24 * HOUR), fin("a", 300, 24 * HOUR)], reserve=60)
    assert d.day_committed_seconds == 0 and d.allowed
    d = check([sub("a", 60, 24 * HOUR - timedelta(seconds=1)),
               fin("a", 300, 24 * HOUR - timedelta(seconds=1))], reserve=60)
    assert d.day_committed_seconds == 300 and not d.allowed


def test_job_fora_da_janela_de_28_dias_nao_conta():
    # 520 s comprometidos deixam 600 - 30 - 520 = 50 s: uma reserva de 60 s nao cabe
    old = [sub("a", 60, 28 * DAY), fin("a", 520, 28 * DAY)]
    d = check(old, reserve=60)
    assert d.window_committed_seconds == 0 and d.allowed
    inside = [sub("a", 60, 28 * DAY - timedelta(seconds=1)),
              fin("a", 520, 28 * DAY - timedelta(seconds=1))]
    d = check(inside, reserve=60)
    assert d.window_committed_seconds == 520 and not d.allowed
    assert any("saldo local" in r for r in d.reasons)


def test_job_pendente_fora_da_janela_nao_entra_nas_pendencias():
    d = check([sub("velho", 60, 40 * DAY)])
    assert d.pending_job_ids == () and d.pending_reserve_seconds == 0


def test_relogio_adiantado_conta_como_recente():
    future = UsageEntry(ts=(NOW + HOUR).isoformat(), event="submitted", job_id="f",
                        reserve_seconds=50)
    d = check([future, UsageEntry(ts=(NOW + HOUR).isoformat(), event="final", job_id="f",
                                  quantum_seconds=50)])
    assert d.day_committed_seconds == 50


def test_pendentes_vem_ordenados():
    d = check([sub("b"), sub("a"), sub("c")])
    assert d.pending_job_ids == ("a", "b", "c")


@pytest.mark.parametrize("reserve", [0, -1, math.nan, math.inf, True, "20", None])
def test_reserva_invalida_recusa_sem_levantar(reserve):
    d = check([], reserve=reserve)
    assert not d.allowed and "reserva do job inválida" in d.reasons


def test_reserva_acima_do_maximo_por_job():
    d = check([], reserve=61)
    assert not d.allowed and any("máximo por job" in r for r in d.reasons)
    assert check([], reserve=60).allowed


def test_varios_motivos_aparecem_juntos():
    d = check([sub("a", 60, HOUR), fin("a", 330, HOUR)], reserve=61, remote=10)
    assert not d.allowed and len(d.reasons) >= 3


def test_available_nunca_e_negativo():
    d = check([sub("a", 60, HOUR), fin("a", 330, HOUR)], remote=0)
    assert d.available_seconds == 0


# ---------------------------------------------------------------- log inconsistente

def test_final_sem_submitted_recusa():
    d = check([fin("a")])
    assert not d.allowed and any("final sem submitted" in r for r in d.reasons)


def test_submitted_repetido_recusa():
    d = check([sub("a"), sub("a")])
    assert not d.allowed and any("repetido em submitted" in r for r in d.reasons)


def test_final_repetido_recusa():
    d = check([sub("a"), fin("a"), fin("a")])
    assert not d.allowed and any("final repetido" in r for r in d.reasons)


def test_entrada_invalida_recusa():
    bad = UsageEntry(ts=at(HOUR), event="xpto", job_id="a")
    d = check([bad])
    assert not d.allowed and any("event inválido" in r for r in d.reasons)


def test_problemas_do_parse_viram_motivos():
    d = check([], log_problems=["linha 3: 9 campos em vez de 10"])
    assert not d.allowed and any("linha 3" in r for r in d.reasons)


def test_refused_nao_conta_no_orcamento():
    refused = UsageEntry(ts=at(HOUR), event="refused", note="orcamento")
    d = check([refused])
    assert d.allowed and d.window_committed_seconds == 0


# ---------------------------------------------------------------- entradas

def test_entrada_valida_nao_tem_problemas():
    assert entry_problems(sub("dbgiga4dgr2s73crj1h0")) == []
    assert entry_problems(fin("dbgiga4dgr2s73crj1h0")) == []
    assert entry_problems(UsageEntry(ts=at(HOUR), event="refused", note="x")) == []


@pytest.mark.parametrize("changes", [
    {"ts": "2026-11-02T15:00:00"},            # sem fuso
    {"ts": "ontem"}, {"ts": 5},
    {"event": "submitted", "job_id": "a b"},  # espaço no job_id
    {"event": "submitted", "job_id": ""},
    {"event": "submitted", "job_id": "a" * 65},
    {"event": "submitted", "reserve_seconds": None},
    {"event": "submitted", "reserve_seconds": 0},
    {"event": "submitted", "reserve_seconds": math.nan},
    {"event": "submitted", "reserve_seconds": True},
    {"qubits": 0}, {"qubits": True}, {"shots": -1}, {"shots": 1.5},
    {"backend": "ibm kingston"}, {"output_file": "a\nb"}, {"note": "x" * 201},
    {"note": "a\rb"}, {"quantum_seconds": 1.0},  # quantum só vale em final
])
def test_entrada_invalida_tem_problemas(changes):
    base = dict(ts=at(HOUR), event="submitted", job_id="a", reserve_seconds=10)
    base.update(changes)
    assert entry_problems(UsageEntry(**base))


@pytest.mark.parametrize("quantum", [-1, math.nan, math.inf, True])
def test_quantum_invalido_em_final(quantum):
    assert entry_problems(UsageEntry(ts=at(HOUR), event="final", job_id="a",
                                     quantum_seconds=quantum))


def test_job_id_invalido_em_refused_quando_informado():
    assert entry_problems(UsageEntry(ts=at(HOUR), event="refused", job_id="a b"))


# ---------------------------------------------------------------- formato e parse

def test_cabecalho():
    assert format_header() == ",".join(USAGE_FIELDS) + "\n"


def test_ida_e_volta_de_todas_as_entradas():
    entries = [
        UsageEntry(ts=at(HOUR), event="submitted", job_id="dbgiga4dgr2s73crj1h0",
                   backend="ibm_kingston", qubits=156, shots=4096, reserve_seconds=20.5,
                   output_file="data/raw/x.npy", note="calibracao, com virgula"),
        UsageEntry(ts=at(HOUR), event="final", job_id="dbgiga4dgr2s73crj1h0",
                   quantum_seconds=3.25),
        UsageEntry(ts=at(HOUR), event="final", job_id="b", quantum_seconds=None),
        UsageEntry(ts=at(HOUR), event="refused", note='motivo "entre aspas"'),
    ]
    text = format_header() + "".join(format_row(e) for e in entries)
    parsed, problems = parse_usage_log(text)
    assert problems == [] and parsed == entries


def test_parse_aceita_crlf():
    text = format_header() + format_row(sub("a"))
    parsed, problems = parse_usage_log(text.replace("\n", "\r\n"))
    assert problems == [] and len(parsed) == 1


def test_format_row_recusa_entrada_invalida():
    with pytest.raises(ValueError):
        format_row(UsageEntry(ts="ontem", event="submitted", job_id="a", reserve_seconds=1))


def test_parse_cabecalho_diferente():
    parsed, problems = parse_usage_log("a,b,c\n1,2,3\n")
    assert parsed == [] and problems
    assert parse_usage_log("") == ([], ["cabeçalho do log de uso diferente do esperado"])


def test_parse_cabecalho_com_colunas_trocadas_e_recusado():
    swapped = list(USAGE_FIELDS)
    swapped[6], swapped[7] = swapped[7], swapped[6]  # reserve_seconds <-> quantum_seconds
    text = ",".join(swapped) + "\n" + format_row(sub("a"))
    parsed, problems = parse_usage_log(text)
    assert parsed == [] and problems == ["cabeçalho do log de uso diferente do esperado"]


def test_parse_linha_com_campos_a_menos_e_linha_vazia():
    good = format_row(sub("a"))
    text = format_header() + good + "a,b\n" + "\n" + good.replace("a,", "b,", 1)
    parsed, problems = parse_usage_log(text)
    assert len(parsed) == 2
    assert any("linha 3" in p for p in problems) and any("linha 4" in p for p in problems)


@pytest.mark.parametrize("field,value", [
    ("reserve_seconds", "nan"), ("reserve_seconds", "inf"), ("reserve_seconds", "-5"),
    ("reserve_seconds", "1_0"), ("reserve_seconds", " 5"), ("qubits", "1.5"),
    ("qubits", "-1"), ("shots", "abc"), ("quantum_seconds", "x"),
])
def test_parse_numero_invalido_vira_problema(field, value):
    cells = dict(zip(USAGE_FIELDS, format_row(sub("a")).rstrip("\n").split(",")))
    cells[field] = value
    line = ",".join(cells[name] for name in USAGE_FIELDS) + "\n"
    parsed, problems = parse_usage_log(format_header() + line)
    assert parsed == [] and any("linha 2" in p for p in problems)


def test_parse_negativo_em_quantum_vira_problema():
    line = f"{at(HOUR)},final,a,,,,,-3,,\n"
    parsed, problems = parse_usage_log(format_header() + line)
    assert parsed == [] and problems


def test_parse_event_desconhecido_vira_problema():
    line = f"{at(HOUR)},cancelled,a,,,,,,,\n"
    parsed, problems = parse_usage_log(format_header() + line)
    assert parsed == [] and any("event inválido" in p for p in problems)


# ---------------------------------------------------------------- disco

def test_append_cria_cabecalho_e_depois_so_linhas(tmp_path):
    path = tmp_path / "logs" / "qpu_usage.csv"
    append_entry(path, sub("a"))
    append_entry(path, fin("a"))
    lines = path.read_bytes().decode("utf-8").split("\n")
    assert lines[0] == ",".join(USAGE_FIELDS)
    assert len(lines) == 4 and lines[3] == ""
    assert b"\r" not in path.read_bytes()
    entries, problems = read_log(path)
    assert problems == [] and [e.event for e in entries] == ["submitted", "final"]


def test_append_nao_cria_nada_se_a_entrada_for_invalida(tmp_path):
    path = tmp_path / "novo" / "qpu_usage.csv"
    with pytest.raises(ValueError):
        append_entry(path, UsageEntry(ts="ontem", event="refused"))
    assert not path.exists() and not path.parent.exists()


def test_append_recusa_cabecalho_diferente(tmp_path):
    path = tmp_path / "qpu_usage.csv"
    path.write_bytes(b"a,b,c\n1,2,3\n")
    with pytest.raises(UsageLogError):
        append_entry(path, sub("a"))
    assert path.read_bytes() == b"a,b,c\n1,2,3\n"


def test_append_recusa_log_sem_quebra_de_linha_final(tmp_path):
    path = tmp_path / "qpu_usage.csv"
    append_entry(path, sub("a"))
    path.write_bytes(path.read_bytes().rstrip(b"\n"))
    before = path.read_bytes()
    with pytest.raises(UsageLogError):
        append_entry(path, fin("a"))
    assert path.read_bytes() == before


def test_append_aceita_log_com_crlf_no_cabecalho(tmp_path):
    path = tmp_path / "qpu_usage.csv"
    path.write_bytes(format_header().replace("\n", "\r\n").encode() + format_row(sub("a")).encode())
    append_entry(path, fin("a"))
    entries, problems = read_log(path)
    assert problems == [] and len(entries) == 2


def test_append_chama_fsync_uma_vez_por_gravacao(tmp_path, monkeypatch):
    calls: list[int] = []
    real = qb.os.fsync
    monkeypatch.setattr(qb.os, "fsync", lambda fd: (calls.append(fd), real(fd))[1])
    append_entry(tmp_path / "qpu_usage.csv", sub("a"))
    assert len(calls) == 1
    append_entry(tmp_path / "qpu_usage.csv", fin("a"))
    assert len(calls) == 2


def test_read_log_ausente_e_vazio(tmp_path):
    assert read_log(tmp_path / "nao_existe.csv") == ([], [])
    empty = tmp_path / "vazio.csv"
    empty.write_bytes(b"")
    assert read_log(empty) == ([], [])


def test_read_log_utf8_invalido(tmp_path):
    path = tmp_path / "ruim.csv"
    path.write_bytes(b"\xff\xfe\x00")
    entries, problems = read_log(path)
    assert entries == [] and any("UTF-8" in p for p in problems)


def test_read_log_sem_quebra_final_acusa(tmp_path):
    path = tmp_path / "log.csv"
    path.write_bytes((format_header() + format_row(sub("a"))).rstrip("\n").encode())
    entries, problems = read_log(path)
    assert any("não termina em quebra de linha" in p for p in problems)


def test_ponta_a_ponta_log_em_disco_e_guarda(tmp_path):
    path = tmp_path / "qpu_usage.csv"
    append_entry(path, sub("a", 60, 2 * HOUR))
    entries, problems = read_log(path)
    d = check(entries, reserve=60, remote=100, log_problems=problems)
    # remoto: 100 - 30 - 60 pendente = 10 < 60
    assert not d.allowed and d.pending_job_ids == ("a",)
    append_entry(path, fin("a", 4, 2 * HOUR))
    entries, problems = read_log(path)
    d = check(entries, reserve=60, remote=100, log_problems=problems)
    assert d.allowed and d.window_committed_seconds == 4


def test_format_row_grava_numpy_float_como_numero_puro():
    import numpy as np

    e = sub("a")
    e = UsageEntry(ts=e.ts, event="submitted", job_id="j1", backend="ibm_kingston", qubits=156, shots=100,
                   reserve_seconds=np.float64(10.0))
    row = format_row(e)
    assert "np.float64" not in row and "10.0" in row
    parsed, problems = parse_usage_log(format_header() + row)
    assert problems == [] and parsed[0].reserve_seconds == 10.0
