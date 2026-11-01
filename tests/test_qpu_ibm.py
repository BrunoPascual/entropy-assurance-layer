"""Testes do adaptador da IBM (Dia 6, 3b): envio com limite duro de orçamento e recuperação."""
from __future__ import annotations

import json
import warnings
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import numpy as np
import pytest
from qiskit.primitives import BitArray, StatevectorSampler
from qiskit.providers.fake_provider import GenericBackendV2

from eal.sources import qpu_ibm
from eal.sources.ibm_bits import physical_qubits_from_isa
from eal.sources.qpu_budget import BudgetPolicy, UsageEntry, append_entry, check_budget, read_log
from eal.sources.qpu_ibm import (
    BudgetRefused, CollectError, IbmCollector, ManifestError, RetrieveError, SubmitFailed,
    SubmittedButNotLogged,
)
from eal.storage import load_batch

POLICY = BudgetPolicy(total_seconds=600, margin_seconds=30, daily_cap_seconds=330,
                      max_job_reserve_seconds=60, window_days=28)
T0 = datetime(2026, 11, 2, 15, 0, tzinfo=timezone.utc)
CAL_DATE = datetime(2026, 10, 31, 19, 21, 17, tzinfo=timezone(timedelta(hours=-3)))
# metrics()['usage'] como a IBM devolveu no job dbji1pgnceqs73ak2c8g (ibm_kingston, 01/11/2026).
USAGE_REAL = {"qpu_charge_time_seconds": 2, "value": 0.032717, "unit": "resource_units",
              "status": "complete",
              "details": [{"value": 0.032717, "unit": "resource_units",
                           "metric": {"id": "caffe3ca-729c-5750-8777-df63bbf8bfd9", "value": 2}}]}
SIX = np.array([[1, 0, 1, 0, 1, 0], [0, 1, 0, 1, 0, 1],
                [1, 1, 0, 0, 1, 1], [0, 0, 1, 1, 0, 0]], dtype=bool)


class Clock:
    """Relógio falso: cada chamada avança um segundo."""

    def __init__(self) -> None:
        self.now = T0

    def __call__(self) -> datetime:
        current = self.now
        self.now += timedelta(seconds=1)
        return current


class FakeProps:
    def __init__(self, down=(), readout_fail=False) -> None:
        self.down, self.readout_fail = set(down), readout_fail
        self.last_update_date = CAL_DATE

    def is_qubit_operational(self, q: int) -> bool:
        return q not in self.down

    def readout_error(self, q: int) -> float:
        if self.readout_fail:
            raise RuntimeError("sem leitura")
        return 0.01 + 0.001 * q


class FakeBackend(GenericBackendV2):
    """Backend de verdade (transpilação real) com properties e configuration falsas."""

    def __init__(self, n=6, down=(), props_fail=False, readout_fail=False,
                 config_fail=False) -> None:
        super().__init__(num_qubits=n, seed=1)
        self.name = "ibm_fake"
        self._props = FakeProps(down, readout_fail)
        self._props_fail, self._config_fail = props_fail, config_fail

    def properties(self):
        if self._props_fail:
            raise RuntimeError("sem properties")
        return self._props

    def configuration(self):
        if self._config_fail:
            raise RuntimeError("sem configuration")
        return SimpleNamespace(default_rep_delay=0.00025)


class FakeJob:
    def __init__(self, job_id: str, bitarray, expected, defaults: dict) -> None:
        self._id, self.bitarray, self.expected_bits = job_id, bitarray, expected
        self.status_name = defaults["status_name"]
        self.metrics_value = defaults["metrics"]
        self.usage_value = defaults["usage"]

    def job_id(self) -> str:
        return self._id

    def status(self):
        return SimpleNamespace(name=self.status_name)

    def in_final_state(self) -> bool:
        return self.status_name in ("DONE", "ERROR", "CANCELLED")

    def result(self):
        return [SimpleNamespace(data=SimpleNamespace(c=self.bitarray))]

    def metrics(self):
        if isinstance(self.metrics_value, Exception):
            raise self.metrics_value
        return self.metrics_value

    def usage(self, partial: bool = False):
        if isinstance(self.usage_value, Exception):
            raise self.usage_value
        return self.usage_value


class Sampler:
    def __init__(self, harness) -> None:
        self.h = harness

    def run(self, pubs, shots, dry_run=False):
        h = self.h
        h.run_calls.append({"pub": pubs[0], "shots": shots, "dry_run": dry_run})
        if h.run_error is not None:
            raise h.run_error
        h.counter += 1
        n = pubs[0].cregs[0].size
        if h.use_statevector:
            bitarray = StatevectorSampler(seed=5).run(pubs, shots=shots).result()[0].data.c
            expected = None
        else:
            rows = h.rows if h.rows is not None else np.random.default_rng(h.counter).random((shots, n)) < 0.5
            bitarray = BitArray.from_bool_array(rows, order="little")
            expected = rows.astype(np.uint8).reshape(-1)
        job_id = h.job_id_override or f"job{h.counter:04d}abc"
        job = FakeJob(job_id, bitarray, expected, h.job_defaults)
        h.jobs[job_id] = job
        return job


class Harness:
    """Serviço falso (backend, usage, job) com o coletor já montado."""

    def __init__(self, tmp_path, **backend_kw) -> None:
        self.backend_obj = FakeBackend(**backend_kw)
        self.jobs, self.remaining, self.usage_error, self.usage_payload = {}, 598, False, None
        self.factory_calls, self.run_calls, self.run_error = [], [], None
        self.job_id_override, self.rows, self.use_statevector, self.counter = None, None, False, 0
        self.job_error = None
        self.job_defaults = {"status_name": "DONE",
                             "metrics": {"usage": {**USAGE_REAL, "qpu_charge_time_seconds": 4}},
                             "usage": 4}
        self.clock = Clock()
        self.log_path = tmp_path / "logs" / "qpu_usage.csv"
        self.raw_dir = tmp_path / "raw"
        self.manifest_dir = tmp_path / "logs" / "qpu_jobs"
        self.collector = IbmCollector(
            self, backend_name="ibm_fake", policy=POLICY, log_path=self.log_path,
            raw_dir=self.raw_dir, manifest_dir=self.manifest_dir,
            sampler_factory=self._factory, clock=self.clock,
            sdk_versions={"qiskit": "2.6.1", "qiskit_ibm_runtime": "0.51.0"})

    def _factory(self, backend, max_execution_time):
        self.factory_calls.append(max_execution_time)
        return Sampler(self)

    def backend(self, name):
        if name != "ibm_fake":
            raise KeyError(name)
        return self.backend_obj

    def usage(self):
        if self.usage_error:
            raise RuntimeError("sem rede")
        if self.usage_payload is not None:
            return self.usage_payload
        return {"usage_remaining_seconds": self.remaining, "usage_consumed_seconds": 2}

    def job(self, job_id):
        if self.job_error is not None:
            raise self.job_error
        return self.jobs[job_id]

    def send(self, shots=4, reserve=20, session="s1", **kw):
        result = self.collector.submit(shots, reserve, session, **kw)
        return result, self.jobs.get(result.job_id)

    def log(self):
        entries, problems = read_log(self.log_path)
        assert problems == []
        return entries

    def events(self):
        return [(e.event, e.job_id) for e in self.log()]

    def raw_jsons(self):
        return sorted(self.raw_dir.glob("*.json")) if self.raw_dir.exists() else []


@pytest.fixture
def h(tmp_path):
    return Harness(tmp_path)


def at(delta: timedelta) -> str:
    return (T0 - delta).isoformat()


# ------------------------------------------------------------------ envio: caminho feliz

def test_envio_grava_submitted_manifesto_e_usa_a_reserva_no_servidor(h):
    result, _ = h.send(shots=4, reserve=20, session="s1")
    assert result.dry_run is False and result.physical_qubits == [0, 1, 2, 3, 4, 5]
    entries = h.log()
    assert [e.event for e in entries] == ["submitted"]
    e = entries[0]
    assert (e.job_id, e.backend, e.qubits, e.shots, e.reserve_seconds, e.note) == (
        result.job_id, "ibm_fake", 6, 4, 20.0, "session=s1")
    assert h.factory_calls == [20]
    assert len(h.run_calls) == 1 and h.run_calls[0]["shots"] == 4 and h.run_calls[0]["dry_run"] is False
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["job_id"] == result.job_id and manifest["session"] == "s1"
    assert manifest["backend"] == "ibm_fake" and manifest["shots"] == 4
    assert manifest["reserve_seconds"] == 20 and manifest["primitive"] == "SamplerV2"
    assert manifest["physical_qubits"] == [0, 1, 2, 3, 4, 5]
    assert len(manifest["readout_error"]) == 6 and manifest["rep_delay_seconds"] == 0.00025
    assert manifest["calibration_date"] == str(CAL_DATE)
    assert manifest["sdk_versions"] == {"qiskit": "2.6.1", "qiskit_ibm_runtime": "0.51.0"}
    assert result.decision.allowed


def test_qubits_padrao_excluem_os_fora_de_operacao(tmp_path):
    h = Harness(tmp_path, down=(2,))
    result, _ = h.send()
    assert result.physical_qubits == [0, 1, 3, 4, 5]
    assert h.log()[0].qubits == 5


def test_layout_embaralhado_e_respeitado_no_circuito_enviado(h):
    result, _ = h.send(qubits=[4, 1, 3])
    assert result.physical_qubits == [4, 1, 3]
    sent = h.run_calls[0]["pub"]
    assert physical_qubits_from_isa(sent, 3) == [4, 1, 3]
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["physical_qubits"] == [4, 1, 3]
    assert manifest["readout_error"] == [0.01 + 0.001 * q for q in (4, 1, 3)]


def test_retrato_de_calibracao_indisponivel_nao_impede_o_envio(tmp_path):
    h = Harness(tmp_path, readout_fail=True)
    result, _ = h.send()
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["readout_error"] is None and manifest["calibration_date"] is None


# ------------------------------------------------------------------ envio: orçamento

def test_job_pendente_conta_pela_reserva_no_envio_seguinte(h):
    h.send(reserve=40)
    h.remaining = 89   # 89 - 30 de margem - 40 pendentes = 19 < 20
    with pytest.raises(BudgetRefused):
        h.send(reserve=20)
    h.remaining = 90   # 20 >= 20
    h.send(reserve=20)
    assert h.events().count(("submitted", "job0002abc")) == 1


def test_recusa_por_orcamento_nao_envia_e_registra_refused(h):
    h.remaining = 40   # 40 - 30 = 10 < 20
    with pytest.raises(BudgetRefused) as info:
        h.send(reserve=20)
    assert h.factory_calls == [] and h.run_calls == []
    assert not h.manifest_dir.exists()
    entries = h.log()
    assert [e.event for e in entries] == ["refused"]
    assert "session=s1" in entries[0].note and "saldo remoto" in entries[0].note
    assert entries[0].reserve_seconds == 20.0 and entries[0].job_id == ""
    assert any("saldo remoto" in r for r in info.value.decision.reasons)


def test_refused_nao_conta_no_orcamento(h):
    h.remaining = 40
    with pytest.raises(BudgetRefused):
        h.send(reserve=20)
    h.remaining = 598
    result, _ = h.send(reserve=20)
    assert result.decision.window_committed_seconds == 0


@pytest.mark.parametrize("breakage", ["erro", "sem_chave", "negativo", "texto"])
def test_saldo_remoto_ilegivel_recusa(h, breakage):
    if breakage == "erro":
        h.usage_error = True
    elif breakage == "sem_chave":
        h.usage_payload = {"usage_consumed_seconds": 2}
    elif breakage == "negativo":
        h.usage_payload = {"usage_remaining_seconds": -5}
    else:
        h.usage_payload = {"usage_remaining_seconds": "598"}
    with pytest.raises(BudgetRefused) as info:
        h.send()
    assert any("saldo remoto indisponível" in r for r in info.value.decision.reasons)
    assert h.run_calls == []


def test_teto_das_24_horas_recusa(h):
    append_entry(h.log_path, UsageEntry(ts=at(timedelta(hours=1)), event="submitted", job_id="old",
                                        reserve_seconds=60.0))
    append_entry(h.log_path, UsageEntry(ts=at(timedelta(hours=1)), event="final", job_id="old",
                                        quantum_seconds=300.0))
    with pytest.raises(BudgetRefused) as info:
        h.send(reserve=40)   # teto 330 - 300 = 30 < 40
    assert any("24 h" in r for r in info.value.decision.reasons)
    assert h.run_calls == []


def test_log_com_problemas_recusa_sem_alterar_o_log(h):
    h.log_path.parent.mkdir(parents=True)
    h.log_path.write_bytes(b"a,b,c\n1,2,3\n")
    with pytest.raises(BudgetRefused) as info:
        h.send()
    assert any("cabeçalho" in r for r in info.value.decision.reasons)
    assert h.run_calls == [] and h.log_path.read_bytes() == b"a,b,c\n1,2,3\n"


# ------------------------------------------------------------------ envio: argumentos

@pytest.mark.parametrize("shots", [0, -1, True, 1.5, 100_001, "4"])
def test_shots_invalidos_nao_enviam_nada(h, shots):
    with pytest.raises(ValueError):
        h.collector.submit(shots, 20, "s1")
    assert h.factory_calls == [] and not h.log_path.exists()


@pytest.mark.parametrize("reserve", [0, -1, True, 1.5, 20.0, 61, "20"])
def test_reserva_precisa_ser_inteira_entre_1_e_o_maximo(h, reserve):
    with pytest.raises(ValueError):
        h.collector.submit(4, reserve, "s1")
    assert h.factory_calls == [] and not h.log_path.exists()


@pytest.mark.parametrize("session", ["", "a b", "s_1", "s/1", 5, None])
def test_sessao_invalida(h, session):
    with pytest.raises(ValueError):
        h.collector.submit(4, 20, session)
    assert h.factory_calls == []


@pytest.mark.parametrize("qubits", [[], [1, 1], [True], [99], [0.5], [-1]])
def test_qubits_invalidos(h, qubits):
    with pytest.raises(ValueError):
        h.send(qubits=qubits)
    assert h.factory_calls == [] and not h.log_path.exists()


def test_qubit_fora_de_operacao_pedido_e_recusado(tmp_path):
    h = Harness(tmp_path, down=(2,))
    with pytest.raises(ValueError, match="fora de operação"):
        h.send(qubits=[1, 2])


def test_limite_de_shots_do_construtor(h):
    h.collector.max_shots = 10
    h.send(shots=10)
    with pytest.raises(ValueError):
        h.send(shots=11)


def test_sem_saber_os_qubits_operacionais_nada_e_enviado(tmp_path):
    h = Harness(tmp_path, props_fail=True)
    with pytest.raises(CollectError, match="operacionais"):
        h.send()
    assert h.run_calls == [] and not h.log_path.exists()


def test_sem_o_rep_delay_nada_e_enviado(tmp_path):
    h = Harness(tmp_path, config_fail=True)
    with pytest.raises(CollectError, match="rep_delay"):
        h.send()
    assert h.run_calls == [] and not h.log_path.exists()


# ------------------------------------------------------------------ envio: falhas

def test_falha_do_run_vira_submit_failed_sem_log(h):
    h.run_error = TimeoutError("rede")
    with pytest.raises(SubmitFailed, match="painel"):
        h.send()
    assert not h.log_path.exists() and not h.manifest_dir.exists()


def test_falha_ao_gravar_o_log_depois_do_envio(h, monkeypatch):
    def broken(path, entry):
        raise OSError("disco cheio")
    monkeypatch.setattr(qpu_ibm, "append_entry", broken)
    with pytest.raises(SubmittedButNotLogged) as info:
        h.send()
    assert info.value.job_id == "job0001abc" and "job0001abc" in info.value.row
    assert "job0001abc" in h.jobs and not h.manifest_dir.exists()


def test_job_id_invalido_da_ibm_nao_pode_ser_logado(h):
    h.job_id_override = "id com espaco"
    with pytest.raises(SubmittedButNotLogged) as info:
        h.send()
    assert info.value.job_id == "id com espaco"
    assert not h.log_path.exists()


def test_falha_no_manifesto_carrega_o_conteudo(h):
    h.manifest_dir.parent.mkdir(parents=True)
    h.manifest_dir.write_text("sou um arquivo, nao uma pasta", encoding="utf-8")
    with pytest.raises(ManifestError) as info:
        h.send()
    assert json.loads(info.value.text)["job_id"] == "job0001abc"
    assert h.events() == [("submitted", "job0001abc")]


def test_manifesto_existente_nao_e_sobrescrito(h):
    h.manifest_dir.mkdir(parents=True)
    existing = h.manifest_dir / "job0001abc.json"
    existing.write_text("nao toque", encoding="utf-8")
    with pytest.raises(ManifestError):
        h.send()
    assert existing.read_text(encoding="utf-8") == "nao toque"
    # A recusa tem que vir ANTES de criar o temporário. Se só o os.rename recusar (caso do
    # Windows, que não sobrescreve), o temporário fica para trás: isso é o que este teste pega.
    assert list(h.manifest_dir.glob("*.tmp")) == []


class QiskitBackendNotFoundError(Exception):
    """Mesmo nome da exceção do Qiskit que o dry-run levanta quando falta o backend mock_."""


def test_falha_do_dry_run_diz_que_nada_foi_gasto(h):
    h.run_error = TimeoutError("rede")
    with pytest.raises(SubmitFailed) as info:
        h.send(dry_run=True)
    message = str(info.value)
    assert "o dry-run falhou (TimeoutError)" in message and "nada foi gasto" in message
    assert "incerto" not in message and "painel" not in message
    assert not h.log_path.exists() and not h.manifest_dir.exists()


def test_dry_run_sem_backend_mock_explica_o_open_plan(h):
    h.run_error = QiskitBackendNotFoundError("mock_kingston")
    with pytest.raises(SubmitFailed) as info:
        h.send(dry_run=True)
    message = str(info.value)
    assert "QiskitBackendNotFoundError" in message and "nada foi gasto" in message
    assert "backend mock" in message and "Open Plan" in message


def test_dry_run_com_outro_erro_nao_cita_o_open_plan(h):
    h.run_error = TimeoutError("rede")
    with pytest.raises(SubmitFailed, match="dry-run falhou") as info:
        h.send(dry_run=True)
    assert "Open Plan" not in str(info.value) and "mock" not in str(info.value)


def test_falha_do_envio_real_continua_incerta_mesmo_com_o_erro_do_mock(h):
    h.run_error = QiskitBackendNotFoundError("x")
    with pytest.raises(SubmitFailed) as info:
        h.send(dry_run=False)
    message = str(info.value)
    assert "incerto" in message and "painel" in message
    assert "dry-run" not in message and "Open Plan" not in message
    assert "nada foi gasto" not in message


# ------------------------------------------------------------------ envio: dry-run

def test_dry_run_nao_grava_log_nem_manifesto(h):
    result, _ = h.send(dry_run=True)
    assert result.dry_run is True and result.manifest_path is None and result.decision is None
    assert h.run_calls[0]["dry_run"] is True and h.factory_calls == [20]
    assert not h.log_path.exists() and not h.manifest_dir.exists()


def test_dry_run_nao_consulta_o_orcamento_mas_valida_argumentos(h):
    h.remaining = 0
    h.usage_error = True
    result, _ = h.send(dry_run=True)
    assert result.dry_run is True
    with pytest.raises(ValueError):
        h.send(shots=0, dry_run=True)


# ------------------------------------------------------------------ recuperação

def test_job_na_fila_fica_pending_e_nada_e_escrito(h):
    result, job = h.send()
    job.status_name = "RUNNING"
    before = h.log_path.read_bytes()
    out = h.collector.retrieve(result.job_id)
    assert (out.state, out.status) == ("pending", "RUNNING")
    assert h.log_path.read_bytes() == before and h.raw_jsons() == []


def test_recuperacao_salva_o_lote_cru_e_fecha_a_conta(h):
    result, job = h.send(shots=4)
    out = h.collector.retrieve(result.job_id)
    assert out.state == "final" and out.quantum_seconds == 4.0 and out.duplicate_of == ""
    batch = load_batch(h.raw_dir / out.output_file)
    assert np.array_equal(batch.bits, job.expected_bits)
    assert batch.source_type == "qpu_ibm" and batch.is_local is False and batch.is_simulated is False
    assert batch.source_id == "ibm_fake"
    assert batch.params["job_id"] == result.job_id and batch.params["qubits"] == 6
    assert batch.params["shots"] == 4 and batch.params["discarded_bits"] == 0
    assert batch.params["max_execution_time_seconds"] == 20
    final = h.log()[-1]
    assert (final.event, final.job_id, final.quantum_seconds, final.output_file, final.note) == (
        "final", result.job_id, 4.0, out.output_file, "status=DONE")


def test_ordem_dos_bits_ponta_a_ponta(h):
    h.rows = np.array([[1, 0, 1], [0, 1, 1]], dtype=bool)   # coluna i = clbit i
    result, _ = h.send(shots=2, qubits=[4, 1, 3])
    out = h.collector.retrieve(result.job_id)
    batch = load_batch(h.raw_dir / out.output_file)
    assert batch.bits.tolist() == [1, 0, 1, 0, 1, 1]          # shot a shot
    assert batch.params["physical_qubits"] == [4, 1, 3]
    assert batch.params["readout_error_by_position"] == [0.01 + 0.001 * q for q in (4, 1, 3)]


def test_ponta_a_ponta_com_transpilacao_real_e_statevector(h):
    h.use_statevector = True
    result, _ = h.send(shots=16)
    out = h.collector.retrieve(result.job_id)
    batch = load_batch(h.raw_dir / out.output_file)
    assert batch.bits.size == 16 * 6 and set(np.unique(batch.bits)) <= {0, 1}
    assert batch.params["qubits"] == batch.params["n_qubits"] == 6


def test_recuperar_nunca_reenvia(h):
    result, _ = h.send()
    h.collector.retrieve(result.job_id)
    h.collector.retrieve(result.job_id)
    assert h.factory_calls == [20] and len(h.run_calls) == 1


def test_segunda_recuperacao_e_already_final_sem_escrever_nada(h):
    result, _ = h.send()
    first = h.collector.retrieve(result.job_id)
    before_log, before_files = h.log_path.read_bytes(), [p.name for p in h.raw_dir.iterdir()]
    again = h.collector.retrieve(result.job_id)
    assert again.state == "already_final" and again.output_file == first.output_file
    assert again.quantum_seconds == 4.0
    assert h.log_path.read_bytes() == before_log
    assert [p.name for p in h.raw_dir.iterdir()] == before_files


def test_uso_ainda_nao_calculado_salva_o_lote_mas_nao_fecha_a_conta(h):
    result, job = h.send()
    job.metrics_value, job.usage_value = {"usage": {"quantum_seconds": 0}}, 0.0
    first = h.collector.retrieve(result.job_id)
    assert first.state == "usage_pending" and first.quantum_seconds is None
    assert len(h.raw_jsons()) == 1 and ("final", result.job_id) not in h.events()
    job.metrics_value = {"usage": {"quantum_seconds": 3.5}}
    second = h.collector.retrieve(result.job_id)
    assert second.state == "final" and second.quantum_seconds == 3.5
    assert second.output_file == first.output_file and len(h.raw_jsons()) == 1
    assert h.events().count(("final", result.job_id)) == 1


def test_job_pendente_sem_uso_conta_pela_reserva_cheia(h):
    result, job = h.send(reserve=25)
    job.metrics_value, job.usage_value = {}, 0.0
    h.collector.retrieve(result.job_id)
    decision = check_budget(h.log(), 10, POLICY, 598, now=h.clock())
    assert decision.pending_job_ids == (result.job_id,) and decision.window_committed_seconds == 25


def test_uso_vem_do_metrics_e_cai_para_o_usage(h):
    result, job = h.send()
    job.metrics_value, job.usage_value = RuntimeError("rede"), 2.5
    assert h.collector.retrieve(result.job_id).quantum_seconds == 2.5


def test_qpu_charge_tem_prioridade_sobre_o_usage(h):
    result, job = h.send()
    job.metrics_value, job.usage_value = {"usage": {**USAGE_REAL, "qpu_charge_time_seconds": 3}}, 9
    assert h.collector.retrieve(result.job_id).quantum_seconds == 3.0


def test_formato_real_da_ibm_fecha_a_conta(h):
    result, job = h.send()
    job.metrics_value, job.usage_value = {"usage": USAGE_REAL}, 2
    out = h.collector.retrieve(result.job_id)
    assert out.state == "final" and out.quantum_seconds == 2.0
    assert h.log()[-1].quantum_seconds == 2.0


def test_conta_fecha_com_o_uso_real(h):
    result, _ = h.send()
    h.collector.retrieve(result.job_id)
    decision = check_budget(h.log(), 10, POLICY, 598, now=h.clock())
    assert decision.window_committed_seconds == 4.0 and decision.pending_job_ids == ()


@pytest.mark.parametrize("status", ["ERROR", "CANCELLED"])
def test_job_que_falhou_fecha_a_conta_sem_lote(h, status):
    result, job = h.send(reserve=20)
    job.status_name = status
    job.metrics_value, job.usage_value = {"usage": {"quantum_seconds": 1}}, 1.0
    out = h.collector.retrieve(result.job_id)
    assert out.state == "failed" and out.status == status and out.quantum_seconds == 1.0
    assert h.raw_jsons() == []
    final = h.log()[-1]
    assert final.event == "final" and final.note == f"status={status}" and final.output_file == ""


def test_job_que_falhou_sem_uso_conta_pela_reserva(h):
    result, job = h.send(reserve=20)
    job.status_name = "CANCELLED"
    job.metrics_value, job.usage_value = {}, 0.0
    out = h.collector.retrieve(result.job_id)
    assert out.state == "failed" and out.quantum_seconds is None
    decision = check_budget(h.log(), 10, POLICY, 598, now=h.clock())
    assert decision.window_committed_seconds == 20.0


def test_resultado_inutilizavel_fecha_a_conta_e_levanta(h):
    result, job = h.send()
    job.bitarray = BitArray.from_bool_array(np.zeros((4, 2), dtype=bool), order="little")
    with pytest.raises(RetrieveError, match="não pôde ser convertido"):
        h.collector.retrieve(result.job_id)
    final = h.log()[-1]
    assert final.event == "final" and "inutilizaveis" in final.note and final.output_file == ""
    assert h.raw_jsons() == []
    assert h.collector.retrieve(result.job_id).state == "already_final"


def test_dados_crus_sao_salvos_antes_do_final(h, monkeypatch):
    result, _ = h.send()
    real = qpu_ibm.append_entry

    def fail_on_final(path, entry):
        if entry.event == "final":
            raise OSError("disco cheio")
        return real(path, entry)

    monkeypatch.setattr(qpu_ibm, "append_entry", fail_on_final)
    with pytest.raises(OSError):
        h.collector.retrieve(result.job_id)
    assert len(h.raw_jsons()) == 1 and ("final", result.job_id) not in h.events()
    monkeypatch.undo()
    out = h.collector.retrieve(result.job_id)
    assert out.state == "final" and len(h.raw_jsons()) == 1


def test_mesmo_resultado_devolvido_duas_vezes_e_anotado(h):
    h.rows = SIX
    first_job, _ = h.send(shots=4)
    second_job, _ = h.send(shots=4)
    first = h.collector.retrieve(first_job.job_id)
    second = h.collector.retrieve(second_job.job_id)
    assert first.duplicate_of == "" and second.duplicate_of == first.output_file
    assert f"duplicate_of={first.output_file}" in h.log()[-1].note


def test_resultados_diferentes_nao_sao_duplicados(h):
    a, _ = h.send(shots=4)
    b, _ = h.send(shots=4)
    h.collector.retrieve(a.job_id)
    assert h.collector.retrieve(b.job_id).duplicate_of == ""


# ------------------------------------------------------------------ recuperação: recusas

@pytest.mark.parametrize("job_id", ["", "a b", "a/b", None, 5, "x" * 65])
def test_job_id_invalido_na_recuperacao(h, job_id):
    with pytest.raises(RetrieveError, match="job_id inválido"):
        h.collector.retrieve(job_id)


def test_job_fora_do_log_e_recusado(h):
    h.send()
    with pytest.raises(RetrieveError, match="não foi enviado por aqui"):
        h.collector.retrieve("naoexiste")


def test_manifesto_ausente_e_recusado(h):
    result, _ = h.send()
    result.manifest_path.unlink()
    with pytest.raises(RetrieveError, match="manifesto"):
        h.collector.retrieve(result.job_id)


@pytest.mark.parametrize("content", ["{nao json", "[]", '{"format": "outro"}'])
def test_manifesto_com_formato_inesperado_e_recusado(h, content):
    result, _ = h.send()
    result.manifest_path.write_text(content, encoding="utf-8")
    with pytest.raises(RetrieveError, match="manifesto"):
        h.collector.retrieve(result.job_id)


def test_manifesto_de_outro_job_e_recusado(h):
    result, _ = h.send()
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    manifest["job_id"] = "outrojob"
    result.manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(RetrieveError, match="manifesto"):
        h.collector.retrieve(result.job_id)


def test_log_com_problemas_na_recuperacao(h):
    h.log_path.parent.mkdir(parents=True)
    h.log_path.write_bytes(b"a,b,c\n")
    with pytest.raises(RetrieveError, match="log de uso com problemas"):
        h.collector.retrieve("job0001abc")


def test_falha_de_rede_ao_buscar_o_job_nao_escreve_nada(h):
    result, _ = h.send()
    h.job_error = RuntimeError("rede")
    before = h.log_path.read_bytes()
    with pytest.raises(RuntimeError):
        h.collector.retrieve(result.job_id)
    assert h.log_path.read_bytes() == before and h.raw_jsons() == []


# ------------------------------------------------------------------ lacunas apontadas pelas mutações

def test_envio_chama_fsync_no_log_e_no_manifesto(h, monkeypatch):
    calls = []
    real = qpu_ibm.os.fsync
    monkeypatch.setattr(qpu_ibm.os, "fsync", lambda fd: (calls.append(fd), real(fd))[1])
    h.send()
    assert len(calls) == 2   # uma do log de uso, uma do manifesto


def test_layout_transpilado_diferente_do_pedido_e_recusado(h, monkeypatch):
    monkeypatch.setattr(qpu_ibm, "physical_qubits_from_isa",
                        lambda isa, n: list(reversed(range(n))))
    with pytest.raises(CollectError, match="difere do pedido"):
        h.send()
    assert h.run_calls == [] and not h.log_path.exists()


def test_job_com_erro_e_uso_em_calculo_conta_pela_reserva(h):
    result, job = h.send(reserve=30)
    job.status_name = "ERROR"
    job.metrics_value, job.usage_value = {"usage": {"quantum_seconds": 0}}, 0.0
    assert h.collector.retrieve(result.job_id).state == "failed"
    decision = check_budget(h.log(), 10, POLICY, 598, now=h.clock())
    assert decision.window_committed_seconds == 30.0


# ------------------------------------------------------------------ fábricas que tocam o runtime

def test_fabrica_do_sampler_aplica_o_limite_e_nao_vaza_o_aviso():
    backend = FakeBackend(n=4)
    with warnings.catch_warnings():
        warnings.simplefilter("error", DeprecationWarning)
        sampler = qpu_ibm.default_sampler_factory(backend, 20)
    assert type(sampler).__name__ == "SamplerV2"
    assert sampler.options.max_execution_time == 20


def test_versoes_do_sdk_sao_as_instaladas():
    import qiskit
    import qiskit_ibm_runtime
    assert qpu_ibm.default_sdk_versions() == {
        "qiskit": qiskit.__version__, "qiskit_ibm_runtime": qiskit_ibm_runtime.__version__}


# ------------------------------------------------------------------ leitura de uso

class UsageJob:
    def __init__(self, metrics, usage) -> None:
        self._metrics, self._usage = metrics, usage

    def metrics(self):
        if isinstance(self._metrics, Exception):
            raise self._metrics
        return self._metrics

    def usage(self):
        if isinstance(self._usage, Exception):
            raise self._usage
        return self._usage


@pytest.mark.parametrize("metrics,usage,expected", [
    ({"usage": {"quantum_seconds": 5}}, 0.0, 5.0),
    ({"usage": {"quantum_seconds": 0}}, 0.0, None),
    ({"usage": {"quantum_seconds": float("nan")}}, 0.0, None),
    ({"usage": {"quantum_seconds": float("inf")}}, 0.0, None),
    ({"usage": {"quantum_seconds": True}}, 0.0, None),
    ({"usage": {"quantum_seconds": -1}}, 0.0, None),
    ({"usage": {"quantum_seconds": "5"}}, 0.0, None),
    ({"usage": {}}, 7.0, 7.0),
    ({}, 7.0, 7.0),
    ("nao e dict", 7.0, 7.0),
    (RuntimeError("x"), 7.0, 7.0),
    (RuntimeError("x"), RuntimeError("y"), None),
    ({}, 0.0, None),
    ({}, float("nan"), None),
    ({}, True, None),
    # formato real e prioridade: qpu_charge_time_seconds > usage() > quantum_seconds
    ({"usage": USAGE_REAL}, 2, 2.0),
    ({"usage": USAGE_REAL}, RuntimeError("y"), 2.0),
    ({"usage": USAGE_REAL}, 0, 2.0),
    ({"usage": {"qpu_charge_time_seconds": 3}}, 9.0, 3.0),
    ({"usage": {"qpu_charge_time_seconds": 3, "quantum_seconds": 8}}, 0.0, 3.0),
    ({"usage": {"qpu_charge_time_seconds": 3, "quantum_seconds": 8}}, 9.0, 3.0),
    ({"usage": {"quantum_seconds": 8}}, 9.0, 9.0),
    # qpu_charge_time_seconds inválido cai para o próximo
    ({"usage": {"qpu_charge_time_seconds": 0, "quantum_seconds": 8}}, 5.0, 5.0),
    ({"usage": {"qpu_charge_time_seconds": 0, "quantum_seconds": 8}}, 0.0, 8.0),
    ({"usage": {"qpu_charge_time_seconds": float("nan")}}, 5.0, 5.0),
    ({"usage": {"qpu_charge_time_seconds": True}}, 5.0, 5.0),
    ({"usage": {"qpu_charge_time_seconds": -1}}, 5.0, 5.0),
    ({"usage": {"qpu_charge_time_seconds": "2"}}, 5.0, 5.0),
    ({"usage": {**USAGE_REAL, "qpu_charge_time_seconds": 0, "status": "pending"}}, 0, None),
    ({"usage": "nao e dict"}, 5.0, 5.0),
])
def test_leitura_do_uso(metrics, usage, expected):
    assert qpu_ibm._usage_seconds(UsageJob(metrics, usage)) == expected


def test_nome_do_status_aceita_enum_e_texto():
    class Enumish:
        name = "DONE"
    assert qpu_ibm._status_name(SimpleNamespace(status=lambda: Enumish())) == "DONE"
    assert qpu_ibm._status_name(SimpleNamespace(status=lambda: "RUNNING")) == "RUNNING"
