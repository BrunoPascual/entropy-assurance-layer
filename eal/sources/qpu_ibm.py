"""Dia 6, passo 3b: adaptador da IBM para a coleta de dados crus (envio e recuperação).

Não é uma fonte do pipeline (a seção 6.3 diz que a IBM entra só via script de coleta): envia
jobs com o limite duro de orçamento (``qpu_budget``), grava tudo no log de uso e recupera os
resultados em lotes crus (``storage``), com a conversão e os ``params`` de ``ibm_bits``.

Regras que o código garante (cada uma tem teste):

- nada é enviado sem passar pela guarda de orçamento; a recusa vira uma linha ``refused``;
- a reserva do job é um inteiro >= 1, e esse mesmo valor vai ao ``max_execution_time`` do
  servidor e ao log (o servidor corta o job que passar dele);
- enviar e recuperar são operações separadas: o envio grava ``submitted`` logo depois do
  ``run`` e não espera a fila; a recuperação NUNCA reenvia (reenviar gasta o orçamento duas
  vezes);
- na recuperação os dados crus são salvos ANTES de qualquer linha ``final`` no log;
- ``usage()`` da IBM devolve 0 até o cálculo terminar: sem uso final, o lote é salvo mas o
  ``final`` não é gravado (o job segue contando pela reserva cheia) e o estado é
  ``usage_pending``; recuperar de novo completa o ``final`` sem salvar um segundo lote;
- job que falhou ou foi cancelado recebe ``final`` com o uso, se houver; sem uso conta pela
  reserva cheia;
- o manifesto de cada job (layout, retrato da calibração, versões) é gravado no envio, porque
  só nesse momento se sabe o que foi enviado.

Limites conhecidos: não há trava entre processos; se ``run`` falhar de forma incerta (queda de
rede) o job pode ter sido criado, e só o painel da IBM esclarece; o token nunca passa por aqui
(o serviço já chega aberto).
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import warnings
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
from qiskit import QuantumCircuit
from qiskit.transpiler.preset_passmanagers import generate_preset_pass_manager

from eal import config
from eal.sources.base import RawBatch
from eal.sources.ibm_bits import (
    CLASSICAL_REGISTER, bitarray_to_bits, build_ibm_params, physical_qubits_from_isa,
)
from eal.sources.qpu_budget import (
    BudgetDecision, BudgetPolicy, UsageEntry, append_entry, check_budget, format_row, read_log,
)
from eal.storage import save_batch

SOURCE_VERSION = "0.1.0"
PRIMITIVE = "SamplerV2"
MANIFEST_FORMAT = "eal-qpu-job-manifest-v1"
MANIFEST_DIR = Path("data/logs/qpu_jobs")
_ID_RE = re.compile(r"[A-Za-z0-9._-]{1,64}")
_SESSION_RE = re.compile(r"[A-Za-z0-9-]+")
_NOTE_MAX = 200


class CollectError(Exception):
    """Erro da coleta (base)."""


class BudgetRefused(CollectError):
    """A guarda de orçamento recusou o job; nada foi enviado."""

    def __init__(self, decision: BudgetDecision) -> None:
        super().__init__("o orçamento recusou o job: " + "; ".join(decision.reasons))
        self.decision = decision


class SubmitFailed(CollectError):
    """O envio falhou; o resultado é incerto, confira o painel da IBM antes de reenviar."""


class SubmittedButNotLogged(CollectError):
    """O job FOI enviado, mas a linha ``submitted`` não entrou no log de uso."""

    def __init__(self, job_id: str, row: str) -> None:
        super().__init__(f"o job {job_id} foi ENVIADO, mas o log de uso não foi gravado. "
                         f"Acrescente esta linha ao log à mão: {row.strip()}")
        self.job_id, self.row = job_id, row


class ManifestError(CollectError):
    """O job foi enviado e registrado, mas o manifesto dele não foi gravado."""

    def __init__(self, job_id: str, text: str) -> None:
        super().__init__(f"o job {job_id} foi enviado e registrado, mas o manifesto não foi "
                         f"gravado. Salve este conteúdo em <manifest_dir>/{job_id}.json: {text}")
        self.job_id, self.text = job_id, text


class RetrieveError(CollectError):
    """Não foi possível recuperar o job."""


@dataclass(frozen=True)
class Prepared:
    """Circuito transpilado e o que se sabe do backend no momento do envio."""

    isa: QuantumCircuit
    physical_qubits: list[int]
    readout_error: list[float] | None
    calibration_date: str | None
    rep_delay_seconds: float


@dataclass(frozen=True)
class SubmitResult:
    """Resultado de um envio (ou de um dry-run)."""

    job_id: str
    dry_run: bool
    reserve_seconds: int
    physical_qubits: list[int]
    manifest_path: Path | None = None
    decision: BudgetDecision | None = None


@dataclass(frozen=True)
class RetrieveResult:
    """Estado de uma recuperação: pending, final, usage_pending, failed ou already_final."""

    state: str
    job_id: str
    status: str | None = None
    output_file: str = ""
    quantum_seconds: float | None = None
    duplicate_of: str = ""


def utc_now() -> datetime:
    """Instante atual em UTC, com fuso."""
    return datetime.now(timezone.utc)


def default_sampler_factory(backend: Any, max_execution_time: int) -> Any:
    """SamplerV2 sobre o backend, com o limite de QPU por job aplicado pelo servidor."""
    from qiskit_ibm_runtime import SamplerV2
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message="The SamplerV2 class is deprecated",
                                category=DeprecationWarning)
        sampler = SamplerV2(mode=backend)
    sampler.options.max_execution_time = max_execution_time
    return sampler


def default_sdk_versions() -> dict[str, str]:
    """Versões dos pacotes que entram no registro de cada lote."""
    import qiskit
    import qiskit_ibm_runtime
    return {"qiskit": qiskit.__version__, "qiskit_ibm_runtime": qiskit_ibm_runtime.__version__}


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _hadamard_circuit(n_qubits: int) -> QuantumCircuit:
    """Hadamard em todos os qubits, seguido de medição (registrador clássico ``c``)."""
    circuit = QuantumCircuit(n_qubits, n_qubits)
    circuit.h(range(n_qubits))
    circuit.measure(range(n_qubits), range(n_qubits))
    return circuit


def _bits_digest(npy: Path) -> str:
    """SHA-256 dos bits empacotados de um lote salvo."""
    return hashlib.sha256(np.load(npy, allow_pickle=False).tobytes()).hexdigest()


def _status_name(job: Any) -> str:
    status = job.status()
    return str(getattr(status, "name", status))


def _usage_seconds(job: Any) -> float | None:
    """Uso final do job em segundos de QPU; None se ainda não foi calculado.

    Qualquer falha na leitura vira None (o job passa a contar pela reserva cheia, o lado
    seguro). Zero também é None: um job real nunca usa 0 s, e a IBM devolve 0 enquanto calcula.
    """
    candidates: list[Any] = []
    try:
        metrics = job.metrics()
        usage = metrics.get("usage") if isinstance(metrics, dict) else None
        if isinstance(usage, dict):
            candidates.append(usage.get("quantum_seconds"))
    except Exception:  # noqa: BLE001
        pass
    try:
        candidates.append(job.usage())
    except Exception:  # noqa: BLE001
        pass
    for value in candidates:
        if (isinstance(value, (int, float)) and not isinstance(value, bool)
                and math.isfinite(value) and value > 0):
            return float(value)
    return None


def _operational_qubits(backend: Any) -> list[int]:
    """Qubits operacionais segundo ``backend.properties()``; recusa se não der para saber."""
    try:
        props = backend.properties()
        return [q for q in range(backend.num_qubits) if props.is_qubit_operational(q)]
    except Exception as exc:  # noqa: BLE001
        raise CollectError("não consegui saber quais qubits estão operacionais "
                           f"({type(exc).__name__}); nada foi enviado") from exc


def _check_qubits(qubits: Sequence[int], operational: list[int]) -> list[int]:
    """Qubits pedidos: inteiros distintos e todos operacionais."""
    chosen = list(qubits)
    if (not chosen or any(not _is_int(q) for q in chosen) or len(set(chosen)) != len(chosen)):
        raise ValueError("qubits deve ser uma lista não vazia de inteiros distintos")
    if not set(chosen) <= set(operational):
        raise ValueError("há qubit fora de operação ou inexistente na lista pedida")
    return chosen


def _snapshot(backend: Any, physical: list[int]) -> tuple[list[float] | None, str | None]:
    """Retrato da calibração (erro de leitura por posição e data); None se indisponível."""
    try:
        props = backend.properties()
        errors = [float(props.readout_error(q)) for q in physical]
        return errors, str(props.last_update_date)
    except Exception:  # noqa: BLE001
        return None, None


def _rep_delay(backend: Any) -> float:
    """Intervalo entre shots que o job vai usar (o padrão do backend; não é alterado)."""
    try:
        return float(backend.configuration().default_rep_delay)
    except Exception as exc:  # noqa: BLE001
        raise CollectError(f"não consegui ler o rep_delay do backend ({type(exc).__name__})") from exc


class IbmCollector:
    """Envia jobs e recupera resultados da IBM, com o limite duro de orçamento."""

    def __init__(self, service: Any, *, backend_name: str, policy: BudgetPolicy,
                 log_path: Path | str, raw_dir: Path | str,
                 manifest_dir: Path | str = MANIFEST_DIR,
                 max_shots: int = config.QPU_MAX_SHOTS_PER_JOB,
                 sampler_factory: Callable[[Any, int], Any] = default_sampler_factory,
                 clock: Callable[[], datetime] = utc_now,
                 sdk_versions: dict[str, str] | None = None) -> None:
        self.service = service
        self.backend_name = backend_name
        self.policy = policy
        self.log_path = Path(log_path)
        self.raw_dir = Path(raw_dir)
        self.manifest_dir = Path(manifest_dir)
        self.max_shots = max_shots
        self.sampler_factory = sampler_factory
        self.clock = clock
        self.sdk_versions = sdk_versions if sdk_versions is not None else default_sdk_versions()
        self._backend_cache: Any = None

    # ------------------------------------------------------------------ envio

    def _backend(self) -> Any:
        if self._backend_cache is None:
            self._backend_cache = self.service.backend(self.backend_name)
        return self._backend_cache

    def _check_args(self, shots: Any, reserve_seconds: Any, session: Any) -> None:
        """Argumentos do envio; ValueError se algum for inválido."""
        if not _is_int(shots) or not 1 <= shots <= self.max_shots:
            raise ValueError(f"shots deve ser inteiro entre 1 e {self.max_shots}")
        if (not _is_int(reserve_seconds)
                or not 1 <= reserve_seconds <= self.policy.max_job_reserve_seconds):
            raise ValueError("reserve_seconds deve ser inteiro entre 1 e o máximo por job "
                             f"({self.policy.max_job_reserve_seconds:g})")
        if not isinstance(session, str) or not _SESSION_RE.fullmatch(session):
            raise ValueError("session só pode ter letras, números e hífen (ex.: s1, cal)")

    def prepare(self, qubits: Sequence[int] | None = None) -> Prepared:
        """Monta o circuito com layout fixo e confere o que foi transpilado."""
        backend = self._backend()
        operational = _operational_qubits(backend)
        chosen = list(operational) if qubits is None else _check_qubits(qubits, operational)
        if not chosen:
            raise CollectError("nenhum qubit operacional no backend")
        manager = generate_preset_pass_manager(backend=backend, optimization_level=0,
                                               initial_layout=chosen)
        isa = manager.run(_hadamard_circuit(len(chosen)))
        physical = physical_qubits_from_isa(isa, len(chosen))
        if physical != chosen:
            raise CollectError("o layout do circuito transpilado difere do pedido")
        errors, cal_date = _snapshot(backend, physical)
        return Prepared(isa, physical, errors, cal_date, _rep_delay(backend))

    def _remote_remaining(self) -> Any:
        """Saldo restante informado pela IBM; None se não der para ler."""
        try:
            usage = self.service.usage()
        except Exception:  # noqa: BLE001
            return None
        return usage.get("usage_remaining_seconds") if isinstance(usage, dict) else None

    def _guard(self, reserve_seconds: int, shots: int, n_qubits: int, session: str) -> BudgetDecision:
        """Confere o orçamento; se recusar, registra ``refused`` e levanta BudgetRefused."""
        entries, problems = read_log(self.log_path)
        now = self.clock()
        decision = check_budget(entries, reserve_seconds, self.policy, self._remote_remaining(),
                                now=now, log_problems=problems)
        if decision.allowed:
            return decision
        note = f"session={session}; " + "; ".join(decision.reasons)
        refused = UsageEntry(ts=now.isoformat(), event="refused", backend=self.backend_name,
                             qubits=n_qubits, shots=shots, reserve_seconds=float(reserve_seconds),
                             note=note[:_NOTE_MAX])
        try:
            append_entry(self.log_path, refused)
        except (OSError, ValueError):
            pass  # a recusa vale mesmo que o registro dela falhe (log corrompido, por exemplo)
        raise BudgetRefused(decision)

    def _send(self, prepared: Prepared, shots: int, reserve_seconds: int, dry_run: bool) -> Any:
        """Chama o sampler; falha aqui deixa o resultado incerto."""
        try:
            sampler = self.sampler_factory(self._backend(), reserve_seconds)
            return sampler.run([prepared.isa], shots=shots, dry_run=dry_run)
        except Exception as exc:  # noqa: BLE001
            raise SubmitFailed("o envio falhou com resultado incerto "
                               f"({type(exc).__name__}): confira o painel da IBM antes de reenviar") from exc

    def _log_submitted(self, job_id: str, n_qubits: int, shots: int, reserve_seconds: int,
                       session: str) -> None:
        entry = UsageEntry(ts=self.clock().isoformat(), event="submitted", job_id=job_id,
                           backend=self.backend_name, qubits=n_qubits, shots=shots,
                           reserve_seconds=float(reserve_seconds), note=f"session={session}")
        try:
            row = format_row(entry)
        except ValueError:
            raise SubmittedButNotLogged(job_id, repr(entry)) from None
        try:
            append_entry(self.log_path, entry)
        except (OSError, ValueError) as exc:
            raise SubmittedButNotLogged(job_id, row) from exc

    def _manifest(self, job_id: str, session: str, shots: int, reserve_seconds: int,
                  prepared: Prepared) -> dict[str, Any]:
        return {
            "format": MANIFEST_FORMAT, "job_id": job_id, "session": session,
            "backend": self.backend_name, "shots": shots, "reserve_seconds": reserve_seconds,
            "submitted_at": self.clock().isoformat(),
            "physical_qubits": prepared.physical_qubits, "readout_error": prepared.readout_error,
            "calibration_date": prepared.calibration_date,
            "rep_delay_seconds": prepared.rep_delay_seconds, "primitive": PRIMITIVE,
            "sdk_versions": self.sdk_versions,
        }

    def _write_manifest(self, manifest: dict[str, Any]) -> Path:
        """Grava o manifesto sem sobrescrever; em falha, o erro carrega o conteúdo."""
        job_id = manifest["job_id"]
        text = json.dumps(manifest, indent=2, ensure_ascii=False)
        path = self.manifest_dir / f"{job_id}.json"
        try:
            self.manifest_dir.mkdir(parents=True, exist_ok=True)
            if path.exists():
                raise FileExistsError(str(path))
            tmp = path.with_suffix(".json.tmp")
            with open(tmp, "w", encoding="utf-8") as fh:
                fh.write(text)
                fh.flush()
                os.fsync(fh.fileno())
            os.rename(tmp, path)
        except OSError as exc:
            raise ManifestError(job_id, text) from exc
        return path

    def submit(self, shots: int, reserve_seconds: int, session: str, *,
               qubits: Sequence[int] | None = None, dry_run: bool = False) -> SubmitResult:
        """Envia um job (ou, com ``dry_run``, só valida no servidor, sem log nem manifesto)."""
        self._check_args(shots, reserve_seconds, session)
        prepared = self.prepare(qubits)
        n_qubits = len(prepared.physical_qubits)
        if dry_run:
            job = self._send(prepared, shots, reserve_seconds, dry_run=True)
            return SubmitResult(str(job.job_id()), True, reserve_seconds, prepared.physical_qubits)
        decision = self._guard(reserve_seconds, shots, n_qubits, session)
        job = self._send(prepared, shots, reserve_seconds, dry_run=False)
        job_id = str(job.job_id())
        self._log_submitted(job_id, n_qubits, shots, reserve_seconds, session)
        manifest = self._manifest(job_id, session, shots, reserve_seconds, prepared)
        path = self._write_manifest(manifest)
        return SubmitResult(job_id, False, reserve_seconds, prepared.physical_qubits, path, decision)

    # ------------------------------------------------------------------ recuperação

    def _load_manifest(self, job_id: str) -> dict[str, Any]:
        path = self.manifest_dir / f"{job_id}.json"
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise RetrieveError(f"manifesto do job ausente ou ilegível ({type(exc).__name__})") from exc
        if (not isinstance(manifest, dict) or manifest.get("format") != MANIFEST_FORMAT
                or manifest.get("job_id") != job_id):
            raise RetrieveError("manifesto do job com formato inesperado")
        return manifest

    def _append_final(self, job_id: str, quantum: float | None, output_file: str, note: str) -> None:
        append_entry(self.log_path, UsageEntry(
            ts=self.clock().isoformat(), event="final", job_id=job_id, quantum_seconds=quantum,
            output_file=output_file, note=note[:_NOTE_MAX]))

    def _batch_files(self) -> list[tuple[Path, dict[str, Any]]]:
        """Pares (caminho do .json, metadados) dos lotes já salvos; ilegíveis são ignorados."""
        found: list[tuple[Path, dict[str, Any]]] = []
        for path in sorted(self.raw_dir.glob("*.json")) if self.raw_dir.exists() else []:
            try:
                meta = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if isinstance(meta, dict):
                found.append((path, meta))
        return found

    def _find_batch_for_job(self, job_id: str) -> Path | None:
        for path, meta in self._batch_files():
            params = meta.get("params")
            if isinstance(params, dict) and params.get("job_id") == job_id:
                return path.with_suffix(".npy")
        return None

    def _duplicate_of(self, npy: Path) -> str:
        """Nome de outro lote salvo com os mesmos bits (T3), ou texto vazio.

        Compara o conteúdo salvo, e não o ``batch_hash``, para não depender de como o hash é
        calculado (se ele incluir metadados, como o job_id, nunca veria o mesmo resultado
        devolvido duas vezes).
        """
        files = {path.with_suffix(".npy"): meta for path, meta in self._batch_files()}
        mine = files.get(npy)
        if mine is None:
            return ""
        try:
            digest = _bits_digest(npy)
        except (OSError, ValueError):
            return ""
        for other, meta in files.items():
            if other == npy or meta.get("n_bits") != mine.get("n_bits"):
                continue
            try:
                same = _bits_digest(other) == digest
            except (OSError, ValueError):
                continue
            if same:
                return other.name
        return ""

    def _save_result(self, job: Any, job_id: str, manifest: dict[str, Any]) -> Path:
        """Converte o resultado e salva o lote cru; dado inutilizável fecha a contagem e levanta."""
        try:
            params = build_ibm_params(
                backend_name=manifest["backend"], job_id=job_id, shots=manifest["shots"],
                physical_qubits=manifest["physical_qubits"], readout_error=manifest["readout_error"],
                calibration_date=manifest["calibration_date"],
                rep_delay_seconds=manifest["rep_delay_seconds"],
                max_execution_time_seconds=manifest["reserve_seconds"],
                primitive=manifest["primitive"], sdk_versions=manifest["sdk_versions"])
            bitarray = getattr(job.result()[0].data, CLASSICAL_REGISTER)
            bits = bitarray_to_bits(bitarray, len(manifest["physical_qubits"]), manifest["shots"])
        except (KeyError, ValueError, AttributeError, IndexError, TypeError) as exc:
            self._append_final(job_id, _usage_seconds(job), "",
                               f"status=DONE; dados inutilizaveis: {type(exc).__name__}")
            raise RetrieveError(f"o resultado do job não pôde ser convertido ({exc})") from exc
        batch = RawBatch(source_id=self.backend_name, source_type="qpu_ibm",
                         source_version=SOURCE_VERSION, is_local=False, is_simulated=False,
                         bits=bits, params=params)
        return save_batch(batch, manifest["session"], self.raw_dir)

    def _finish_done(self, job: Any, job_id: str, manifest: dict[str, Any]) -> RetrieveResult:
        npy = self._find_batch_for_job(job_id)
        if npy is None:
            npy = self._save_result(job, job_id, manifest)  # dados crus antes de qualquer final
        quantum = _usage_seconds(job)
        if quantum is None:
            return RetrieveResult("usage_pending", job_id, "DONE", npy.name)
        duplicate = self._duplicate_of(npy)
        note = "status=DONE" + (f"; duplicate_of={duplicate}" if duplicate else "")
        self._append_final(job_id, quantum, npy.name, note)
        return RetrieveResult("final", job_id, "DONE", npy.name, quantum, duplicate)

    def _finish_failed(self, job: Any, job_id: str, status: str) -> RetrieveResult:
        quantum = _usage_seconds(job)
        self._append_final(job_id, quantum, "", f"status={status}")
        return RetrieveResult("failed", job_id, status, "", quantum)

    def retrieve(self, job_id: str) -> RetrieveResult:
        """Recupera um job já enviado; nunca reenvia."""
        if not isinstance(job_id, str) or not _ID_RE.fullmatch(job_id):
            raise RetrieveError("job_id inválido")
        entries, problems = read_log(self.log_path)
        if problems:
            raise RetrieveError("log de uso com problemas: " + "; ".join(problems))
        mine = [e for e in entries if e.job_id == job_id]
        if not any(e.event == "submitted" for e in mine):
            raise RetrieveError("o job não está no log de uso (não foi enviado por aqui)")
        finals = [e for e in mine if e.event == "final"]
        if finals:
            return RetrieveResult("already_final", job_id, None, finals[0].output_file,
                                  finals[0].quantum_seconds)
        manifest = self._load_manifest(job_id)
        job = self.service.job(job_id)
        status = _status_name(job)
        if not job.in_final_state():
            return RetrieveResult("pending", job_id, status)
        if status != "DONE":
            return self._finish_failed(job, job_id, status)
        return self._finish_done(job, job_id, manifest)
