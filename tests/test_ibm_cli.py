"""Testes do ponto de entrada da coleta na IBM (Dia 6): comandos, confirmação e códigos de saída."""
from __future__ import annotations

import csv
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from eal import config, ibm_cli
from eal.sources.qpu_budget import UsageEntry, append_entry
from eal.sources.qpu_calibration import CalibrationPoint, size_next_job
from eal.sources.qpu_ibm import (
    BudgetRefused, CollectError, IbmCollector, RetrieveError, RetrieveResult, SubmitResult,
    SubmittedButNotLogged,
)

T0 = datetime(2026, 11, 2, 15, 0, tzinfo=timezone.utc)
ROOT = Path(__file__).resolve().parent.parent


class Clock:
    def __init__(self, step=timedelta(seconds=1)) -> None:
        self.now, self.step = T0, step

    def __call__(self) -> datetime:
        current = self.now
        self.now += self.step
        return current


class FakeService:
    def __init__(self, remaining=598) -> None:
        self.remaining = remaining

    def usage(self):
        return {"usage_remaining_seconds": self.remaining}


class FakeCollector:
    def __init__(self, n=6) -> None:
        self.n, self.calls = n, []
        self.prepare_error = self.submit_error = self.retrieve_error = None
        self.retrieve_result = RetrieveResult("final", "job0001abc", "DONE", "x.npy", 4.0)

    def prepare(self, qubits=None):
        self.calls.append(("prepare", qubits))
        if self.prepare_error:
            raise self.prepare_error
        return SimpleNamespace(physical_qubits=list(qubits) if qubits else list(range(self.n)))

    def submit(self, shots, reserve, session, *, qubits=None, dry_run=False):
        self.calls.append(("submit", shots, reserve, session, qubits, dry_run))
        if self.submit_error:
            raise self.submit_error
        return SubmitResult("job0001abc", dry_run, reserve, list(range(self.n)),
                            None if dry_run else Path("m.json"))

    def retrieve(self, job_id):
        self.calls.append(("retrieve", job_id))
        if self.retrieve_error:
            raise self.retrieve_error
        return self.retrieve_result


@dataclass
class Result:
    code: int
    text: str
    prompts: list
    collector: FakeCollector
    service: FakeService
    seen: dict


def run(tmp_path, argv, *, answers=(), service=None, collector=None, service_error=None,
        clock=None):
    lines, prompts, seen = [], [], {}
    pending = iter(answers)

    def input_fn(prompt):
        prompts.append(prompt)
        try:
            return next(pending)
        except StopIteration:
            raise EOFError from None

    svc = service or FakeService()
    col = collector or FakeCollector()

    def service_factory(instance):
        seen["instance"] = instance
        if service_error:
            raise service_error
        return svc

    def collector_factory(service_obj, ctx):
        seen["ctx"] = ctx
        return col

    globals_ = ["--logs-dir", str(tmp_path / "logs"), "--raw-dir", str(tmp_path / "raw"),
                "--results-dir", str(tmp_path / "results")]
    code = ibm_cli.main(globals_ + list(argv), service_factory=service_factory,
                        collector_factory=collector_factory, clock=clock or Clock(),
                        input_fn=input_fn, out=lines.append)
    return Result(code, "\n".join(lines), prompts, col, svc, seen)


def log_path(tmp_path):
    return tmp_path / "logs" / config.QPU_USAGE_LOG_NAME


def ts(age=timedelta(hours=1)):
    return (T0 - age).isoformat()


def add_job(tmp_path, job, shots=1000, quantum=3.0, reserve=20.0, note="status=DONE",
            age=timedelta(hours=1), final=True):
    path = log_path(tmp_path)
    append_entry(path, UsageEntry(ts=ts(age), event="submitted", job_id=job,
                                  backend=config.IBM_DEFAULT_BACKEND, qubits=156, shots=shots,
                                  reserve_seconds=reserve))
    if final:
        append_entry(path, UsageEntry(ts=ts(age), event="final", job_id=job,
                                      quantum_seconds=quantum, note=note))


ENVIAR = ["enviar", "--shots", "1000", "--reserva", "20", "--sessao", "cal"]


# ------------------------------------------------------------------ status

def test_status_com_log_vazio(tmp_path):
    r = run(tmp_path, ["status"])
    assert r.code == 0
    assert "Jobs enviados: 0 | concluídos: 0 | pendentes: 0" in r.text
    assert "Saldo remoto informado pela IBM: 598 s" in r.text
    assert "teto de 24 h 330 s" in r.text and "reserva máxima por job 60 s" in r.text


def test_status_com_jobs_e_pendentes(tmp_path):
    add_job(tmp_path, "feito", quantum=4.0)
    add_job(tmp_path, "esperando", reserve=25.0, final=False)
    r = run(tmp_path, ["status"])
    assert r.code == 0
    assert "Jobs enviados: 2 | concluídos: 1 | pendentes: 1" in r.text
    assert "Reservas pendentes: 25 s (jobs: esperando)" in r.text
    assert "Comprometido na janela de 28 dias: 29 s | nas últimas 24 h: 29 s" in r.text


def test_status_sem_servico_continua_e_avisa(tmp_path):
    r = run(tmp_path, ["status"], service_error=CollectError("sem token"))
    assert r.code == 0
    assert "Saldo remoto informado pela IBM: indisponível (serviço indisponível: CollectError)" in r.text


def test_status_com_log_com_problemas_sai_com_erro(tmp_path):
    log_path(tmp_path).parent.mkdir(parents=True)
    log_path(tmp_path).write_bytes(b"a,b,c\n")
    r = run(tmp_path, ["status"])
    assert r.code == 1 and "PROBLEMA NO LOG" in r.text


def test_status_mostra_o_disponivel_pelo_menor_limite(tmp_path):
    r = run(tmp_path, ["status"], service=FakeService(remaining=100))
    assert "Disponível agora para um job (menor entre os limites conhecidos): 70 s" in r.text


def test_status_usa_a_instancia_e_o_backend_pedidos(tmp_path):
    r = run(tmp_path, ["status"])
    assert r.seen["instance"] == config.IBM_DEFAULT_INSTANCE


# ------------------------------------------------------------------ calibrar

def test_calibrar_sem_jobs_sugere_o_primeiro(tmp_path):
    r = run(tmp_path, ["calibrar"])
    assert r.code == 0
    assert "Ainda não há job de calibração concluído" in r.text
    assert (f"enviar --shots {config.QPU_CALIBRATION_FIRST_SHOTS} "
            f"--reserva {config.QPU_CALIBRATION_FIRST_RESERVE_SECONDS} --sessao cal") in r.text
    assert str(config.QPU_CALIBRATION_FIRST_SHOTS * config.QPU_BACKEND_QUBITS) in r.text


def test_calibrar_com_um_ponto_dimensiona_o_segundo(tmp_path):
    add_job(tmp_path, "a", shots=1000, quantum=3.0)
    r = run(tmp_path, ["calibrar"])
    shots, reserve = size_next_job(
        CalibrationPoint(1000, 3.0), target_seconds=config.QPU_CALIBRATION_TARGET_SECONDS,
        safety_factor=config.QPU_RESERVE_SAFETY_FACTOR,
        extra_seconds=config.QPU_RESERVE_EXTRA_SECONDS, max_reserve=60,
        max_shots=config.QPU_MAX_SHOTS_PER_JOB)
    assert r.code == 0
    assert f"enviar --shots {shots} --reserva {reserve} --sessao cal" in r.text
    assert "1000 shots usaram 3 s" in r.text


def test_calibrar_com_shots_iguais_ainda_pede_um_segundo_job(tmp_path):
    add_job(tmp_path, "a", shots=1000, quantum=3.0)
    add_job(tmp_path, "b", shots=1000, quantum=4.0)
    r = run(tmp_path, ["calibrar"])
    assert r.code == 0 and "falta um job com shots diferentes" in r.text


def test_calibrar_com_uso_zero_no_unico_ponto_nao_entra(tmp_path):
    add_job(tmp_path, "a", shots=1000, quantum=0.0)
    r = run(tmp_path, ["calibrar"])
    assert "Ainda não há job de calibração concluído" in r.text


def test_calibrar_ajusta_o_modelo_e_planeja(tmp_path):
    add_job(tmp_path, "a", shots=1000, quantum=3.0)
    add_job(tmp_path, "b", shots=5000, quantum=7.0)
    r = run(tmp_path, ["calibrar"])
    assert r.code == 0
    assert "Modelo com 2 jobs: fixo 2.000 s + 1.0000 ms por shot" in r.text
    assert "2000000 bits: 1 job(s) de 12821 shots" in r.text
    assert "3000000 bits: 1 job(s) de 19231 shots" in r.text
    assert "cabe no teto: sim" in r.text
    assert "Teto de 24 h restante: 320 s" in r.text   # 330 - (3 + 7) usados nas últimas 24 h


def test_calibrar_aceita_bits_e_qubits_pedidos(tmp_path):
    add_job(tmp_path, "a", shots=1000, quantum=3.0)
    add_job(tmp_path, "b", shots=5000, quantum=7.0)
    r = run(tmp_path, ["calibrar", "--bits", "1000000", "--n-qubits", "100"])
    assert "1000000 bits: 1 job(s) de 10000 shots" in r.text and "3000000 bits" not in r.text


def test_calibrar_ignora_jobs_com_erro(tmp_path):
    add_job(tmp_path, "a", shots=1000, quantum=3.0)
    add_job(tmp_path, "b", shots=5000, quantum=50.0, note="status=ERROR")
    r = run(tmp_path, ["calibrar"])
    assert "falta um job com shots diferentes" in r.text


def test_calibrar_grava_o_csv(tmp_path):
    add_job(tmp_path, "a", shots=1000, quantum=3.0)
    add_job(tmp_path, "b", shots=5000, quantum=7.0)
    r = run(tmp_path, ["calibrar", "--csv"])
    assert r.code == 0 and "Resultado gravado em" in r.text
    files = list((tmp_path / "results").glob("dia6_calibracao_*.csv"))
    assert [f.name for f in files] == ["dia6_calibracao_20261102T150001Z.csv"]
    rows = list(csv.DictReader(files[0].open(encoding="utf-8")))
    assert tuple(rows[0].keys()) == ibm_cli.CSV_FIELDS
    kinds = [row["kind"] for row in rows]
    assert kinds == ["model", "point", "point", "plan", "plan"]
    assert float(rows[0]["per_shot_seconds"]) == pytest.approx(0.001)
    assert [int(row["shots"]) for row in rows if row["kind"] == "point"] == [1000, 5000]
    plan = rows[3]
    assert (plan["target_bits"], plan["n_jobs"], plan["shots_per_job"]) == ("2000000", "1", "12821")
    assert plan["fits_budget"] == "True"
    assert not list((tmp_path / "results").glob("*.tmp"))


def test_calibrar_nao_sobrescreve_o_csv(tmp_path):
    add_job(tmp_path, "a", shots=1000, quantum=3.0)
    add_job(tmp_path, "b", shots=5000, quantum=7.0)
    fixed = Clock(step=timedelta(0))
    assert run(tmp_path, ["calibrar", "--csv"], clock=fixed).code == 0
    first = next((tmp_path / "results").glob("*.csv"))
    content = first.read_bytes()
    again = run(tmp_path, ["calibrar", "--csv"], clock=Clock(step=timedelta(0)))
    assert again.code == 1 and "já existe" in again.text
    assert first.read_bytes() == content


def test_calibrar_sem_csv_nao_grava_nada(tmp_path):
    add_job(tmp_path, "a", shots=1000, quantum=3.0)
    add_job(tmp_path, "b", shots=5000, quantum=7.0)
    run(tmp_path, ["calibrar"])
    assert not (tmp_path / "results").exists()


def test_calibrar_com_log_com_problemas(tmp_path):
    log_path(tmp_path).parent.mkdir(parents=True)
    log_path(tmp_path).write_bytes(b"a,b,c\n")
    r = run(tmp_path, ["calibrar"])
    assert r.code == 1 and "PROBLEMA NO LOG" in r.text


def test_calibrar_com_custo_por_shot_nao_positivo(tmp_path):
    add_job(tmp_path, "a", shots=1000, quantum=5.0)
    add_job(tmp_path, "b", shots=5000, quantum=5.0)
    r = run(tmp_path, ["calibrar"])
    assert r.code == 1 and "não positivo" in r.text


def test_calibrar_so_considera_o_backend_pedido(tmp_path):
    add_job(tmp_path, "a", shots=1000, quantum=3.0)             # enviado ao ibm_kingston
    kingston = run(tmp_path, ["calibrar"])
    fez = run(tmp_path, ["--backend", "ibm_fez", "calibrar"])
    assert "1000 shots usaram 3 s" in kingston.text
    assert "Ainda não há job de calibração concluído" in fez.text


# ------------------------------------------------------------------ enviar

def test_enviar_com_sim_envia_sem_perguntar(tmp_path):
    r = run(tmp_path, ENVIAR + ["--sim"])
    assert r.code == 0 and r.prompts == []
    assert ("submit", 1000, 20, "cal", None, False) in r.collector.calls
    assert "Job enviado: job0001abc" in r.text and "recuperar job0001abc" in r.text
    assert "  qubits ...: 6" in r.text and "  bits .....: 6000" in r.text
    assert "orçamento : OK (disponível 330 s)" in r.text


def test_enviar_pergunta_e_so_envia_com_sim_exato(tmp_path):
    r = run(tmp_path, ENVIAR, answers=["SIM"])
    assert r.code == 0 and len(r.prompts) == 1
    assert "20 s de QPU" in r.prompts[0] and "1000 shots" in r.prompts[0]
    assert "6000 bits" in r.prompts[0] and "Digite SIM" in r.prompts[0]
    assert any(call[0] == "submit" for call in r.collector.calls)


def test_enviar_aceita_espacos_em_volta_da_resposta(tmp_path):
    assert run(tmp_path, ENVIAR, answers=["  SIM \n"]).code == 0


@pytest.mark.parametrize("answer", ["sim", "Sim", "s", "yes", "", "SIM!", "NAO"])
def test_enviar_recusa_qualquer_resposta_diferente_de_sim(tmp_path, answer):
    r = run(tmp_path, ENVIAR, answers=[answer])
    assert r.code == 3 and "Cancelado: nada foi enviado." in r.text
    assert not any(call[0] == "submit" for call in r.collector.calls)


def test_enviar_sem_resposta_disponivel_cancela(tmp_path):
    r = run(tmp_path, ENVIAR, answers=[])
    assert r.code == 3 and not any(call[0] == "submit" for call in r.collector.calls)


def test_enviar_recusado_pelo_orcamento_nao_pergunta_nem_envia(tmp_path):
    r = run(tmp_path, ENVIAR, service=FakeService(remaining=40), answers=["SIM"])
    assert r.code == 3 and r.prompts == []
    assert "orçamento : RECUSADO" in r.text and "saldo remoto" in r.text
    assert not any(call[0] == "submit" for call in r.collector.calls)


def test_enviar_recusado_mesmo_com_sim(tmp_path):
    r = run(tmp_path, ENVIAR + ["--sim"], service=FakeService(remaining=40))
    assert r.code == 3 and not any(call[0] == "submit" for call in r.collector.calls)


def test_enviar_com_log_com_problemas_e_recusado(tmp_path):
    log_path(tmp_path).parent.mkdir(parents=True)
    log_path(tmp_path).write_bytes(b"a,b,c\n")
    r = run(tmp_path, ENVIAR + ["--sim"])
    assert r.code == 3 and "RECUSADO" in r.text


def test_dry_run_nao_pergunta_e_passa_o_dry_run(tmp_path):
    r = run(tmp_path, ENVIAR + ["--dry-run"])
    assert r.code == 0 and r.prompts == []
    assert ("submit", 1000, 20, "cal", None, True) in r.collector.calls
    assert "Job validado (dry-run): job0001abc" in r.text and "nada é gravado" in r.text
    assert "consumiu QPU" in r.text


def test_dry_run_funciona_mesmo_com_orcamento_esgotado(tmp_path):
    r = run(tmp_path, ENVIAR + ["--dry-run"], service=FakeService(remaining=0))
    assert r.code == 0 and ("submit", 1000, 20, "cal", None, True) in r.collector.calls
    assert "orçamento : RECUSADO" in r.text


def test_enviar_com_qubits_escolhidos(tmp_path):
    r = run(tmp_path, ENVIAR + ["--qubits", "4", "1", "3", "--sim"])
    assert ("prepare", [4, 1, 3]) in r.collector.calls
    assert ("submit", 1000, 20, "cal", [4, 1, 3], False) in r.collector.calls
    assert "  qubits ...: 3" in r.text and "  bits .....: 3000" in r.text


def test_enviar_prepara_antes_de_perguntar(tmp_path):
    r = run(tmp_path, ENVIAR, answers=["NAO"])
    assert r.collector.calls[0][0] == "prepare"


def test_enviar_sem_servico_sai_com_erro(tmp_path):
    r = run(tmp_path, ENVIAR + ["--sim"], service_error=CollectError("sem token"))
    assert r.code == 1 and "ERRO: sem token" in r.text and r.collector.calls == []


def test_enviar_com_prepare_falhando(tmp_path):
    col = FakeCollector()
    col.prepare_error = CollectError("nenhum qubit operacional")
    r = run(tmp_path, ENVIAR + ["--sim"], collector=col)
    assert r.code == 1 and "nenhum qubit operacional" in r.text
    assert not any(call[0] == "submit" for call in col.calls)


def test_enviar_recusado_pelo_adaptador_sai_com_3(tmp_path):
    col = FakeCollector()
    col.submit_error = BudgetRefused(SimpleNamespace(reasons=("teto das últimas 24 h: x",)))
    r = run(tmp_path, ENVIAR + ["--sim"], collector=col)
    assert r.code == 3 and "RECUSADO:" in r.text and "teto das últimas 24 h" in r.text


def test_enviar_com_job_enviado_e_log_nao_gravado_mostra_a_linha(tmp_path):
    col = FakeCollector()
    col.submit_error = SubmittedButNotLogged("job0009abc", "linha,do,log\n")
    r = run(tmp_path, ENVIAR + ["--sim"], collector=col)
    assert r.code == 1 and "job0009abc" in r.text and "linha,do,log" in r.text


def test_enviar_com_argumento_invalido_do_adaptador(tmp_path):
    col = FakeCollector()
    col.submit_error = ValueError("shots deve ser inteiro entre 1 e 100000")
    r = run(tmp_path, ENVIAR + ["--sim"], collector=col)
    assert r.code == 1 and "shots deve ser inteiro" in r.text


def test_erro_inesperado_mostra_so_o_nome_da_classe(tmp_path):
    col = FakeCollector()
    col.submit_error = RuntimeError("token-super-secreto-123")
    r = run(tmp_path, ENVIAR + ["--sim"], collector=col)
    assert r.code == 1 and "ERRO inesperado: RuntimeError" in r.text
    assert "token-super-secreto-123" not in r.text


@pytest.mark.parametrize("argv", [
    ["enviar", "--reserva", "20", "--sessao", "cal"],
    ["enviar", "--shots", "100", "--sessao", "cal"],
    ["enviar", "--shots", "100", "--reserva", "20"],
    ["enviar", "--shots", "abc", "--reserva", "20", "--sessao", "cal"],
    ["enviar", "--shots", "1.5", "--reserva", "20", "--sessao", "cal"],
    ["recuperar"], [], ["naoexiste"],
])
def test_uso_incorreto_sai_com_2_sem_enviar(tmp_path, argv):
    with pytest.raises(SystemExit) as info:
        run(tmp_path, argv)
    assert info.value.code == 2


# ------------------------------------------------------------------ recuperar

@pytest.mark.parametrize("result,code,fragment", [
    (RetrieveResult("pending", "j", "RUNNING"), 4, "ainda não terminou (status RUNNING)"),
    (RetrieveResult("usage_pending", "j", "DONE", "x.npy"), 4, "ainda não calculou o uso"),
    (RetrieveResult("final", "j", "DONE", "x.npy", 4.0), 0, "Job j fechado: x.npy, uso 4.0 s"),
    (RetrieveResult("already_final", "j", None, "x.npy", 4.0), 0, "já estava fechado"),
    (RetrieveResult("failed", "j", "ERROR", "", 1.0), 1, "terminou com status ERROR (1 s)"),
    (RetrieveResult("failed", "j", "CANCELLED", "", None), 1, "sem uso informado"),
])
def test_recuperar_estados_e_codigos(tmp_path, result, code, fragment):
    col = FakeCollector()
    col.retrieve_result = result
    r = run(tmp_path, ["recuperar", "j"], collector=col)
    assert r.code == code and fragment in r.text
    assert ("retrieve", "j") in col.calls


def test_recuperar_avisa_de_resultado_duplicado(tmp_path):
    col = FakeCollector()
    col.retrieve_result = RetrieveResult("final", "j", "DONE", "b.npy", 4.0, "a.npy")
    r = run(tmp_path, ["recuperar", "j"], collector=col)
    assert r.code == 0 and "ATENÇÃO" in r.text and "a.npy" in r.text and "replay" in r.text


def test_recuperar_nunca_chama_submit(tmp_path):
    col = FakeCollector()
    run(tmp_path, ["recuperar", "j"], collector=col)
    assert all(call[0] != "submit" for call in col.calls)


def test_recuperar_com_erro_do_adaptador(tmp_path):
    col = FakeCollector()
    col.retrieve_error = RetrieveError("o job não está no log de uso")
    r = run(tmp_path, ["recuperar", "j"], collector=col)
    assert r.code == 1 and "ERRO: o job não está no log de uso" in r.text


def test_recuperar_sem_servico(tmp_path):
    r = run(tmp_path, ["recuperar", "j"], service_error=CollectError("sem token"))
    assert r.code == 1 and "ERRO: sem token" in r.text


# ------------------------------------------------------------------ política, serviço e fábrica

def test_politica_vem_do_config():
    policy = ibm_cli.policy_from_config()
    assert (policy.total_seconds, policy.margin_seconds, policy.daily_cap_seconds,
            policy.max_job_reserve_seconds, policy.window_days) == (600, 30, 330, 60, 28)


def test_servico_sem_token_e_recusado():
    with pytest.raises(CollectError, match=config.IBM_TOKEN_ENV):
        ibm_cli.build_service("open-instance", env={})
    with pytest.raises(CollectError, match=config.IBM_TOKEN_ENV):
        ibm_cli.build_service("open-instance", env={config.IBM_TOKEN_ENV: ""})


def test_servico_e_aberto_com_o_token_do_ambiente(monkeypatch):
    calls = {}

    class FakeRuntime:
        def __init__(self, **kwargs):
            calls.update(kwargs)

    monkeypatch.setattr("qiskit_ibm_runtime.QiskitRuntimeService", FakeRuntime)
    service = ibm_cli.build_service("open-instance", env={config.IBM_TOKEN_ENV: "tok-abc"})
    assert isinstance(service, FakeRuntime)
    assert calls == {"channel": "ibm_quantum_platform", "token": "tok-abc",
                     "instance": "open-instance"}


def test_falha_ao_abrir_o_servico_nao_vaza_o_token(monkeypatch):
    class Broken:
        def __init__(self, **kwargs):
            raise RuntimeError(f"falhou com {kwargs['token']}")

    monkeypatch.setattr("qiskit_ibm_runtime.QiskitRuntimeService", Broken)
    with pytest.raises(CollectError) as info:
        ibm_cli.build_service("open-instance", env={config.IBM_TOKEN_ENV: "tok-secreto-xyz"})
    assert "tok-secreto-xyz" not in str(info.value) and "RuntimeError" in str(info.value)
    assert info.value.__cause__ is None


def test_fabrica_padrao_monta_o_coletor_com_os_caminhos_do_contexto(tmp_path):
    ctx = ibm_cli.Context(
        backend="ibm_fez", instance="i", policy=ibm_cli.policy_from_config(),
        log_path=tmp_path / "l.csv", raw_dir=tmp_path / "raw", manifest_dir=tmp_path / "man",
        results_dir=tmp_path / "res", clock=Clock(), out=print, input_fn=input)
    collector = ibm_cli.default_collector_factory(FakeService(), ctx)
    assert isinstance(collector, IbmCollector)
    assert collector.backend_name == "ibm_fez" and collector.log_path == tmp_path / "l.csv"
    assert collector.raw_dir == tmp_path / "raw" and collector.manifest_dir == tmp_path / "man"
    assert collector.policy is ctx.policy and collector.clock is ctx.clock


def test_main_monta_o_contexto_com_logs_dir_raw_dir_e_backend(tmp_path):
    r = run(tmp_path, ENVIAR + ["--sim"])
    ctx = r.seen["ctx"]
    assert ctx.log_path == tmp_path / "logs" / config.QPU_USAGE_LOG_NAME
    assert ctx.manifest_dir == tmp_path / "logs" / "qpu_jobs"
    assert ctx.raw_dir == tmp_path / "raw" and ctx.results_dir == tmp_path / "results"
    assert ctx.backend == config.IBM_DEFAULT_BACKEND and ctx.instance == config.IBM_DEFAULT_INSTANCE


# ------------------------------------------------------------------ lançador

def test_lancador_mostra_a_ajuda_sem_importar_pelo_caminho_do_projeto():
    launcher = ROOT / "scripts" / "coletar_ibm.py"
    done = subprocess.run([sys.executable, "-W", "error::SyntaxWarning", str(launcher), "--help"],
                          capture_output=True, text=True, cwd=ROOT.parent)
    assert done.returncode == 0, done.stderr
    assert "status" in done.stdout and "enviar" in done.stdout and "recuperar" in done.stdout
