"""Testes da inspeção só de leitura de um job da IBM (Dia 6)."""
from __future__ import annotations

import importlib.util
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from qiskit.primitives import BitArray

from eal.sources.qpu_ibm import CollectError

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "inspecionar_job_ibm.py"
_spec = importlib.util.spec_from_file_location("inspecionar_job_ibm", SCRIPT)
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)

JOB_ID = "dbji1pgnceqs73ak2c8g"
PHYSICAL = [4, 1, 3, 0, 2, 5]
SHOTS = 20


def manifest(**changes):
    base = {
        "format": "eal-qpu-job-manifest-v1", "job_id": JOB_ID, "session": "cal",
        "backend": "ibm_kingston", "shots": SHOTS, "reserve_seconds": 20,
        "submitted_at": "2026-11-01T08:21:43+00:00", "physical_qubits": PHYSICAL,
        "readout_error": [0.01, 0.02, 0.03, 0.04, 0.05, 0.06],
        "calibration_date": "2026-11-01 04:30:15-03:00", "rep_delay_seconds": 0.00025,
        "primitive": "SamplerV2", "sdk_versions": {"qiskit": "2.6.1", "qiskit_ibm_runtime": "0.51.0"},
    }
    base.update(changes)
    return base


class FakeJob:
    def __init__(self, rows=None, status="DONE", metrics=None, usage=3.0, register="c") -> None:
        rng = np.random.default_rng(1)
        self.rows = rows if rows is not None else rng.random((SHOTS, len(PHYSICAL))) < 0.5
        self.status_name, self.register = status, register
        self.metrics_value = metrics if metrics is not None else {"usage": {"quantum_seconds": 3},
                                                                  "timestamps": {"created": "x"}}
        self.usage_value = usage
        self.result_calls = 0
        self.bitarray = BitArray.from_bool_array(self.rows, order="little")

    def status(self):
        return SimpleNamespace(name=self.status_name)

    def in_final_state(self):
        return self.status_name in ("DONE", "ERROR", "CANCELLED")

    def metrics(self):
        if isinstance(self.metrics_value, Exception):
            raise self.metrics_value
        return self.metrics_value

    def usage(self):
        return self.usage_value

    def result(self):
        self.result_calls += 1
        data = SimpleNamespace(**{self.register: self.bitarray})
        data.keys = lambda: [self.register]
        return [SimpleNamespace(data=data, metadata={"circuit_metadata": {}})]


class FakeService:
    def __init__(self, job) -> None:
        self.job_obj, self.asked = job, []

    def job(self, job_id):
        self.asked.append(job_id)
        return self.job_obj


def write_manifest(tmp_path, **changes):
    folder = tmp_path / "logs" / "qpu_jobs"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{JOB_ID}.json").write_text(json.dumps(manifest(**changes)), encoding="utf-8")


def snapshot(tmp_path):
    return sorted(str(p.relative_to(tmp_path)) for p in tmp_path.rglob("*"))


def run(tmp_path, job, *, with_manifest=True, factory=None, argv_extra=()):
    if with_manifest:
        write_manifest(tmp_path)
    lines = []
    service = FakeService(job)
    code = mod.main([JOB_ID, "--logs-dir", str(tmp_path / "logs"), *argv_extra],
                    service_factory=factory or (lambda instance: service), out=lines.append)
    return code, "\n".join(lines), service


def test_job_ok_mostra_o_formato_e_confere_o_adaptador(tmp_path):
    job = FakeJob()
    code, text, service = run(tmp_path, job)
    assert code == 0 and service.asked == [JOB_ID]
    assert f"job {JOB_ID}: status DONE; em estado final: True" in text
    assert "metrics()['usage']: {quantum_seconds=3}" in text and "usage(): 3.0" in text
    assert "manifesto: ok (6 qubits, 20 shots, reserva 20 s)" in text
    assert "pub.data: tipo SimpleNamespace, campos ['c']" in text
    assert f"BitArray: num_bits=6 num_shots={SHOTS} shape=() array=({SHOTS}, 1)/uint8" in text
    assert "bits: 20 shots x 6 colunas" in text
    assert "conversão do adaptador: OK (120 bits, uint8)" in text
    assert "igual ao to_bool_array(order='little'): True" in text
    assert "params do lote: OK" in text and "NADA FOI SALVO" in text


def test_inspecao_nao_grava_nada(tmp_path):
    write_manifest(tmp_path)
    before = snapshot(tmp_path)
    run(tmp_path, FakeJob(), with_manifest=False)
    assert snapshot(tmp_path) == before
    assert not (tmp_path / "logs" / "qpu_usage.csv").exists()
    assert not (tmp_path / "raw").exists()


def test_coluna_enviesada_aparece_com_o_qubit_fisico(tmp_path):
    rows = np.random.default_rng(2).random((SHOTS, 6)) < 0.5
    rows[:, 2] = True                                    # posição 2 sempre 1 -> qubit físico 3
    code, text, _ = run(tmp_path, FakeJob(rows=rows))
    assert code == 0
    assert "posição 2 (qubit físico 3): fração de 1 = 1.0000" in text


def test_pre_visualizacao_dos_primeiros_shots(tmp_path):
    rows = np.zeros((SHOTS, 6), dtype=bool)
    rows[0] = [1, 0, 1, 0, 0, 1]
    code, text, _ = run(tmp_path, FakeJob(rows=rows))
    assert "shot 0: 101001..." in text and "shot 1: 000000..." in text


def test_job_na_fila_sai_com_4_sem_pedir_o_resultado(tmp_path):
    job = FakeJob(status="RUNNING")
    code, text, _ = run(tmp_path, job)
    assert code == 4 and "status RUNNING; em estado final: False" in text
    assert "ainda não terminou" in text and job.result_calls == 0


@pytest.mark.parametrize("status", ["ERROR", "CANCELLED"])
def test_job_que_falhou_sai_com_1_sem_pedir_o_resultado(tmp_path, status):
    job = FakeJob(status=status)
    code, text, _ = run(tmp_path, job)
    assert code == 1 and f"terminou com status {status}" in text and job.result_calls == 0


def test_sem_manifesto_pula_so_a_conferencia_do_adaptador(tmp_path):
    code, text, _ = run(tmp_path, FakeJob(), with_manifest=False)
    assert code == 0 and "manifesto: ausente ou ilegível" in text
    assert "a conferência do adaptador será pulada" in text
    assert "conversão do adaptador" not in text and "bits: 20 shots x 6 colunas" in text


def test_manifesto_ilegivel_tambem_pula(tmp_path):
    folder = tmp_path / "logs" / "qpu_jobs"
    folder.mkdir(parents=True)
    (folder / f"{JOB_ID}.json").write_text("{nao json", encoding="utf-8")
    code, text, _ = run(tmp_path, FakeJob(), with_manifest=False)
    assert code == 0 and "ausente ou ilegível" in text


def test_numero_de_qubits_do_manifesto_diferente_do_resultado_falha(tmp_path):
    write_manifest(tmp_path, physical_qubits=[0, 1, 2, 3], readout_error=[0.1] * 4)
    code, text, _ = run(tmp_path, FakeJob(), with_manifest=False)
    assert code == 1 and "conversão do adaptador: FALHOU (ValueError" in text
    assert "NADA FOI SALVO" in text


def test_numero_de_shots_do_manifesto_diferente_do_resultado_falha(tmp_path):
    write_manifest(tmp_path, shots=SHOTS + 1)
    code, text, _ = run(tmp_path, FakeJob(), with_manifest=False)
    assert code == 1 and "FALHOU (ValueError" in text


def test_params_invalidos_no_manifesto_falham(tmp_path):
    write_manifest(tmp_path, readout_error=[2.0] * 6)
    code, text, _ = run(tmp_path, FakeJob(), with_manifest=False)
    assert code == 1 and "conversão do adaptador: OK" in text and "FALHOU" in text


def test_manifesto_sem_campo_obrigatorio_falha_sem_estourar(tmp_path):
    folder = tmp_path / "logs" / "qpu_jobs"
    folder.mkdir(parents=True)
    broken = manifest()
    del broken["backend"]
    (folder / f"{JOB_ID}.json").write_text(json.dumps(broken), encoding="utf-8")
    code, text, _ = run(tmp_path, FakeJob(), with_manifest=False)
    assert code == 1 and "FALHOU (KeyError" in text


def test_conversao_que_roda_mas_devolve_outros_bits_e_reprovada(tmp_path, monkeypatch):
    """O erro silencioso: o adaptador não levanta, mas os bits não são os que a IBM entregou."""
    monkeypatch.setattr(mod, "bitarray_to_bits",
                        lambda bitarray, n, shots: np.zeros(n * shots, dtype=np.uint8))
    rows = np.random.default_rng(3).random((SHOTS, 6)) < 0.5
    rows[0] = True                                       # garante que não são todos zero
    code, text, _ = run(tmp_path, FakeJob(rows=rows))
    assert code == 1
    assert "conversão do adaptador: OK (120 bits, uint8)" in text
    assert "igual ao to_bool_array(order='little'): False" in text


def test_resultado_sem_o_registrador_c(tmp_path):
    code, text, _ = run(tmp_path, FakeJob(register="meas"))
    assert code == 1 and "o resultado não tem o registrador 'c'" in text


def test_falha_no_metrics_nao_interrompe(tmp_path):
    code, text, _ = run(tmp_path, FakeJob(metrics=RuntimeError("rede")))
    assert code == 0 and "metrics(): falhou (RuntimeError)" in text and "usage(): 3.0" in text


def test_uso_zero_e_mostrado_com_o_aviso(tmp_path):
    code, text, _ = run(tmp_path, FakeJob(usage=0.0, metrics={"usage": {"quantum_seconds": 0}}))
    assert code == 0 and "usage(): 0.0" in text and "enquanto o uso não foi calculado" in text


def test_erro_do_servico_mostra_a_mensagem_do_projeto(tmp_path):
    def broken(instance):
        raise CollectError("a variável IBM_QUANTUM_TOKEN não está definida (confira o .env)")
    code, text, _ = run(tmp_path, FakeJob(), factory=broken)
    assert code == 1 and "ERRO: a variável IBM_QUANTUM_TOKEN não está definida" in text


def test_erro_inesperado_mostra_so_o_nome_da_classe(tmp_path):
    def broken(instance):
        raise RuntimeError("token-super-secreto-123")
    code, text, _ = run(tmp_path, FakeJob(), factory=broken)
    assert code == 1 and "ERRO inesperado: RuntimeError" in text
    assert "token-super-secreto-123" not in text


def test_job_que_nao_existe_vira_erro_sem_vazar_a_mensagem(tmp_path):
    class Service:
        def job(self, job_id):
            raise KeyError("segredo-do-servidor")
    code, text, _ = run(tmp_path, FakeJob(), factory=lambda instance: Service())
    assert code == 1 and "ERRO inesperado: KeyError" in text and "segredo-do-servidor" not in text


def test_sem_job_id_e_uso_incorreto(tmp_path):
    with pytest.raises(SystemExit) as info:
        mod.main([], service_factory=lambda instance: None, out=lambda line: None)
    assert info.value.code == 2


def test_usa_a_instancia_pedida(tmp_path):
    seen = []
    write_manifest(tmp_path)
    mod.main([JOB_ID, "--instance", "outra-instancia", "--logs-dir", str(tmp_path / "logs")],
             service_factory=lambda instance: (seen.append(instance), FakeService(FakeJob()))[1],
             out=lambda line: None)
    assert seen == ["outra-instancia"]


# ------------------------------------------------------------------ fila, estimativa e deriva de calibração

CREATED = datetime(2026, 11, 1, 8, 21, 43)
CAL_AT_SUBMIT = "2026-11-01 04:30:15-03:00"
CAL_INSTANT = datetime(2026, 11, 1, 4, 30, 15, tzinfo=timezone(timedelta(hours=-3)))


class RichProps:
    def __init__(self, date=CAL_INSTANT, shift=None) -> None:
        self.last_update_date = date
        errors = dict(zip(PHYSICAL, manifest()["readout_error"]))
        if shift:
            errors[shift[0]] += shift[1]
        self.errors = errors

    def readout_error(self, qubit):
        return self.errors[qubit]


class RichJob(FakeJob):
    """Job com os campos extras que o RuntimeJobV2 real expõe."""

    def __init__(self, *, created=CREATED, estimate=None, pending=49, props=None, **kw) -> None:
        super().__init__(**kw)
        self.creation_date = created
        self.usage_estimation = estimate if estimate is not None else {"quantum_seconds": 3}
        self.pending, self.props = pending, props if props is not None else RichProps()

    def backend(self):
        if isinstance(self.pending, Exception):
            raise self.pending
        return SimpleNamespace(
            name="ibm_kingston",
            status=lambda: SimpleNamespace(pending_jobs=self.pending, operational=True))

    def properties(self):
        if isinstance(self.props, Exception):
            raise self.props
        return self.props


def run_rich(tmp_path, job, **kw):
    write_manifest(tmp_path, calibration_date=kw.pop("cal", CAL_AT_SUBMIT))
    lines = []
    now = kw.pop("now", lambda: CREATED + timedelta(minutes=28))
    code = mod.main([JOB_ID, "--logs-dir", str(tmp_path / "logs")],
                    service_factory=lambda instance: FakeService(job), out=lines.append, now=now)
    return code, "\n".join(lines)


def test_job_na_fila_mostra_tempo_estimativa_e_tamanho_da_fila(tmp_path):
    code, text = run_rich(tmp_path, RichJob(status="QUEUED"))
    assert code == 4
    assert "criado em 2026-11-01 08:21:43; há 28 min" in text
    assert "estimativa de uso da IBM (usage_estimation): {quantum_seconds=3}" in text
    assert "fila do ibm_kingston: 49 jobs pendentes; operacional: True" in text


def test_job_ja_concluido_nao_mostra_a_fila(tmp_path):
    code, text = run_rich(tmp_path, RichJob(status="DONE"))
    assert code == 0 and "criado em" in text and "usage_estimation" in text
    assert "fila do" not in text


def test_job_sem_data_de_criacao_nao_quebra(tmp_path):
    code, text = run_rich(tmp_path, RichJob(status="QUEUED", created=None))
    assert code == 4 and "criado em" not in text and "creation_date" not in text


def test_falha_ao_ler_a_data_de_criacao_e_avisada(tmp_path):
    class Broken(RichJob):
        @property
        def creation_date(self):
            raise RuntimeError("rede")

        @creation_date.setter
        def creation_date(self, value):
            pass
    code, text = run_rich(tmp_path, Broken(status="QUEUED"))
    assert code == 4 and "creation_date: falhou (RuntimeError)" in text


def test_fusos_incompativeis_omitem_so_o_tempo_decorrido(tmp_path):
    aware = datetime(2026, 11, 1, 8, 21, 43, tzinfo=timezone.utc)
    code, text = run_rich(tmp_path, RichJob(status="QUEUED", created=aware),
                          now=lambda: datetime(2026, 11, 1, 9, 0, 0))
    created_line = next(line for line in text.splitlines() if line.startswith("criado em"))
    assert code == 4 and created_line == "criado em 2026-11-01 08:21:43"


def test_falha_na_estimativa_de_uso_e_avisada(tmp_path):
    class Broken(RichJob):
        @property
        def usage_estimation(self):
            raise RuntimeError("rede")

        @usage_estimation.setter
        def usage_estimation(self, value):
            pass
    code, text = run_rich(tmp_path, Broken(status="QUEUED"))
    assert code == 4 and "usage_estimation: falhou (RuntimeError)" in text


def test_falha_ao_ler_a_fila_nao_impede_o_resto(tmp_path):
    code, text = run_rich(tmp_path, RichJob(status="QUEUED", pending=RuntimeError("rede")))
    assert code == 4 and "fila do backend: indisponível (RuntimeError)" in text
    assert "criado em" in text and "estimativa de uso" in text


def test_calibracao_igual_no_envio_e_na_execucao(tmp_path):
    code, text = run_rich(tmp_path, RichJob(status="DONE"))
    assert code == 0
    assert f"calibração no início do job (properties()): {CAL_INSTANT}" in text
    assert f"calibração no envio: {CAL_AT_SUBMIT} -> igual" in text
    assert "maior diferença de erro de leitura entre envio e execução: 0.00000" in text


def test_mesmo_instante_em_fusos_diferentes_conta_como_igual(tmp_path):
    utc = CAL_INSTANT.astimezone(timezone.utc)
    code, text = run_rich(tmp_path, RichJob(status="DONE", props=RichProps(date=utc)))
    assert code == 0 and "-> igual" in text and "DIFERENTE" not in text


def test_calibracao_diferente_e_destacada_com_a_pior_deriva(tmp_path):
    later = CAL_INSTANT + timedelta(hours=20)
    props = RichProps(date=later, shift=(3, 0.0123))
    code, text = run_rich(tmp_path, RichJob(status="DONE", props=props))
    assert code == 0
    assert "-> DIFERENTE: o retrato do manifesto pode não valer para este job" in text
    assert "maior diferença de erro de leitura entre envio e execução: 0.01230 (qubit 3)" in text


def test_deriva_negativa_do_erro_de_leitura_tambem_conta(tmp_path):
    props = RichProps(date=CAL_INSTANT + timedelta(hours=20), shift=(1, -0.02))
    code, text = run_rich(tmp_path, RichJob(status="DONE", props=props))
    assert code == 0
    assert "maior diferença de erro de leitura entre envio e execução: 0.02000 (qubit 1)" in text


def test_falha_no_properties_nao_impede_a_conferencia_do_resultado(tmp_path):
    code, text = run_rich(tmp_path, RichJob(status="DONE", props=RuntimeError("rede")))
    assert code == 0 and "calibração no início do job: indisponível (RuntimeError)" in text
    assert "conversão do adaptador: OK" in text and "NADA FOI SALVO" in text


def test_falha_na_leitura_de_erro_por_qubit_e_avisada(tmp_path):
    class NoReadout(RichProps):
        def readout_error(self, qubit):
            raise RuntimeError("sem leitura")
    code, text = run_rich(tmp_path, RichJob(status="DONE", props=NoReadout()))
    assert code == 0 and "diferença de erro de leitura: indisponível (RuntimeError)" in text


def test_manifesto_sem_retrato_de_calibracao_so_mostra_a_da_execucao(tmp_path):
    write_manifest(tmp_path, calibration_date=None, readout_error=None)
    lines = []
    mod.main([JOB_ID, "--logs-dir", str(tmp_path / "logs")],
             service_factory=lambda instance: FakeService(RichJob(status="DONE")), out=lines.append)
    text = "\n".join(lines)
    assert "calibração no início do job (properties())" in text
    assert "calibração no envio" not in text


def test_sem_manifesto_so_mostra_a_calibracao_da_execucao(tmp_path):
    lines = []
    mod.main([JOB_ID, "--logs-dir", str(tmp_path / "logs")],
             service_factory=lambda instance: FakeService(RichJob(status="DONE")), out=lines.append)
    text = "\n".join(lines)
    assert "calibração no início do job (properties())" in text and "calibração no envio" not in text


@pytest.mark.parametrize("first,second,expected", [
    (CAL_AT_SUBMIT, CAL_INSTANT, True),
    (CAL_INSTANT, CAL_INSTANT.astimezone(timezone.utc), True),
    (CAL_AT_SUBMIT, CAL_INSTANT + timedelta(seconds=1), False),
    ("2026-11-01 04:30:15", datetime(2026, 11, 1, 4, 30, 15), True),
    ("2026-11-01 04:30:15", datetime(2026, 11, 1, 4, 30, 16), False),
    ("2026-11-01 04:30:15-03:00", datetime(2026, 11, 1, 4, 30, 15), False),
    ("nao e data", "nao e data", True),
    ("nao e data", "outra coisa", False),
])
def test_comparacao_de_instantes(first, second, expected):
    assert mod._same_instant(first, second) is expected


def test_minutos_decorridos():
    base = datetime(2026, 11, 1, 8, 0, 0)
    assert mod._elapsed_minutes(base, lambda: base + timedelta(minutes=90)) == 90
    aware = base.replace(tzinfo=timezone.utc)
    assert mod._elapsed_minutes(aware, lambda: base) is None


@pytest.mark.parametrize("value,expected", [
    ({"a": 1, "b": "x", "c": None, "d": True}, "{a=1, b='x', c=None, d=True}"),
    ({"longo": "x" * 41}, "{longo=<str>}"),
    ({"aninhado": {"k": 1}}, "{aninhado=<dict>}"),
    (5, "5"), (None, "None"), ("texto", "str"), ([1], "list"),
])
def test_resumo_de_escalares(value, expected):
    assert mod._scalars(value) == expected
