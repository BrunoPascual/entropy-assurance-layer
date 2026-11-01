"""Dia 6: inspeção SÓ DE LEITURA de um job da IBM (nada é salvo, nada entra no log de uso).

Mostra o que a IBM devolveu (estado, uso, formato do resultado, estatística dos bits) e roda,
sem efeito colateral, as mesmas funções puras que o ``recuperar`` usa (conversão do BitArray e
construção dos params). Serve para descobrir um problema de formato ANTES de o ``recuperar``
fechar a conta do job no log: se a conversão falhar lá, a linha ``final`` já foi gravada e uma
nova tentativa devolve ``already_final`` sem salvar o lote.

Uso (na raiz do projeto):
    py -3.12 scripts\\inspecionar_job_ibm.py JOB_ID [--logs-dir data/logs]

Códigos de saída: 0 tudo certo; 1 problema (erro, job que falhou ou conversão que falhou);
4 o job ainda não terminou. O token nunca é impresso: de uma exceção desconhecida só o nome
da classe aparece.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

# O scripts/ não tem a raiz do projeto no caminho de importação; este script a acrescenta.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np  # noqa: E402

from eal import config  # noqa: E402
from eal.ibm_cli import build_service  # noqa: E402
from eal.sources.ibm_bits import CLASSICAL_REGISTER, bitarray_to_bits, build_ibm_params  # noqa: E402
from eal.sources.qpu_ibm import CollectError  # noqa: E402

TOP_BIASED = 3
PREVIEW_SHOTS, PREVIEW_BITS = 2, 24


def _scalars(value: Any) -> str:
    """Resumo de um dict: números, booleanos e textos curtos; o resto vira o nome do tipo."""
    if not isinstance(value, dict):
        return repr(value) if isinstance(value, (int, float, bool, type(None))) else type(value).__name__
    parts = []
    for key in sorted(value, key=str):
        item = value[key]
        if isinstance(item, (int, float, bool, type(None))) or (isinstance(item, str) and len(item) <= 40):
            parts.append(f"{key}={item!r}")
        else:
            parts.append(f"{key}=<{type(item).__name__}>")
    return "{" + ", ".join(parts) + "}"


def _status_name(job: Any) -> str:
    status = job.status()
    return str(getattr(status, "name", status))


def _print_metrics(job: Any, out: Callable[[str], None]) -> None:
    """Uso e métricas do job; falha de leitura vira aviso, nunca interrompe."""
    try:
        metrics = job.metrics()
        out(f"metrics(): chaves {sorted(metrics, key=str) if isinstance(metrics, dict) else type(metrics).__name__}")
        if isinstance(metrics, dict):
            out(f"metrics()['usage']: {_scalars(metrics.get('usage'))}")
    except Exception as exc:  # noqa: BLE001
        out(f"metrics(): falhou ({type(exc).__name__})")
    try:
        out(f"usage(): {job.usage()!r}  (a IBM devolve 0 enquanto o uso não foi calculado)")
    except Exception as exc:  # noqa: BLE001
        out(f"usage(): falhou ({type(exc).__name__})")


def _elapsed_minutes(created: datetime, now: Callable[[], datetime] | None) -> float | None:
    """Minutos desde a criação do job; None se os fusos não permitirem a conta."""
    current = now() if now else (datetime.now(created.tzinfo) if created.tzinfo else datetime.now())
    try:
        return (current - created).total_seconds() / 60
    except TypeError:
        return None


def _print_timing(job: Any, final: bool, out: Callable[[str], None],
                  now: Callable[[], datetime] | None) -> None:
    """Há quanto tempo o job existe, a estimativa de uso da IBM e (na fila) o tamanho da fila."""
    try:
        created = job.creation_date
        if created is not None:
            minutes = _elapsed_minutes(created, now)
            ago = "" if minutes is None else f"; há {minutes:.0f} min"
            out(f"criado em {created:%Y-%m-%d %H:%M:%S}{ago}")
    except Exception as exc:  # noqa: BLE001
        out(f"creation_date: falhou ({type(exc).__name__})")
    try:
        out(f"estimativa de uso da IBM (usage_estimation): {_scalars(job.usage_estimation)}")
    except Exception as exc:  # noqa: BLE001
        out(f"usage_estimation: falhou ({type(exc).__name__})")
    if final:
        return
    try:
        backend = job.backend()
        state = backend.status()
        out(f"fila do {backend.name}: {state.pending_jobs} jobs pendentes; "
            f"operacional: {state.operational}")
    except Exception as exc:  # noqa: BLE001
        out(f"fila do backend: indisponível ({type(exc).__name__})")


def _same_instant(first: Any, second: Any) -> bool:
    """Compara dois instantes (datetime ou texto ISO); sem como comparar, usa o texto."""
    def parse(value: Any) -> Any:
        if isinstance(value, datetime):
            return value
        try:
            return datetime.fromisoformat(str(value))
        except ValueError:
            return None
    a, b = parse(first), parse(second)
    try:
        if a is not None and b is not None:
            return bool(a == b)
    except TypeError:
        pass
    return str(first) == str(second)


def _print_calibration(job: Any, manifest: dict[str, Any] | None, out: Callable[[str], None]) -> None:
    """Calibração no início da execução contra o retrato guardado no envio (deriva na fila)."""
    try:
        props = job.properties()
        at_run = props.last_update_date
    except Exception as exc:  # noqa: BLE001
        out(f"calibração no início do job: indisponível ({type(exc).__name__})")
        return
    out(f"calibração no início do job (properties()): {at_run}")
    if manifest is None or manifest.get("calibration_date") is None:
        return
    same = _same_instant(manifest["calibration_date"], at_run)
    out(f"calibração no envio: {manifest['calibration_date']} -> "
        + ("igual" if same else "DIFERENTE: o retrato do manifesto pode não valer para este job"))
    try:
        diffs = [(abs(props.readout_error(q) - e), q)
                 for q, e in zip(manifest["physical_qubits"], manifest["readout_error"])]
        worst, qubit = max(diffs)
        out(f"maior diferença de erro de leitura entre envio e execução: {worst:.5f} (qubit {qubit})")
    except Exception as exc:  # noqa: BLE001
        out(f"diferença de erro de leitura: indisponível ({type(exc).__name__})")


def _load_manifest(manifest_dir: Path, job_id: str, out: Callable[[str], None]) -> dict[str, Any] | None:
    path = manifest_dir / f"{job_id}.json"
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        out(f"manifesto: ausente ou ilegível em {path} ({type(exc).__name__}); "
            "a conferência do adaptador será pulada")
        return None
    out(f"manifesto: ok ({len(manifest.get('physical_qubits', []))} qubits, "
        f"{manifest.get('shots')} shots, reserva {manifest.get('reserve_seconds')} s)")
    return manifest


def _describe_bits(matrix: np.ndarray, manifest: dict[str, Any] | None, out: Callable[[str], None]) -> None:
    """Estatística simples dos bits: fração de 1 geral e as colunas mais afastadas de 0,5."""
    shots, n = matrix.shape
    means = matrix.mean(axis=0)
    out(f"bits: {shots} shots x {n} colunas; fração geral de 1: {matrix.mean():.4f}")
    physical = manifest.get("physical_qubits") if manifest else None
    order = np.argsort(-np.abs(means - 0.5))[:TOP_BIASED]
    for position in order:
        where = f" (qubit físico {physical[position]})" if physical and position < len(physical) else ""
        out(f"  posição {int(position)}{where}: fração de 1 = {means[position]:.4f}")
    for row in range(min(PREVIEW_SHOTS, shots)):
        out(f"  shot {row}: " + "".join("1" if bit else "0" for bit in matrix[row][:PREVIEW_BITS]) + "...")


def _check_adapter(bitarray: Any, matrix: np.ndarray, manifest: dict[str, Any] | None,
                   job_id: str, out: Callable[[str], None]) -> bool:
    """Roda as funções puras do adaptador; True se a conversão e os params passaram."""
    if manifest is None:
        return True
    try:
        n = len(manifest["physical_qubits"])
        bits = bitarray_to_bits(bitarray, n, manifest["shots"])
        same = np.array_equal(bits.reshape(manifest["shots"], n), matrix)
        out(f"conversão do adaptador: OK ({bits.size} bits, {bits.dtype}); "
            f"igual ao to_bool_array(order='little'): {same}")
        build_ibm_params(
            backend_name=manifest["backend"], job_id=job_id, shots=manifest["shots"],
            physical_qubits=manifest["physical_qubits"], readout_error=manifest["readout_error"],
            calibration_date=manifest["calibration_date"],
            rep_delay_seconds=manifest["rep_delay_seconds"],
            max_execution_time_seconds=manifest["reserve_seconds"],
            primitive=manifest["primitive"], sdk_versions=manifest["sdk_versions"])
        out("params do lote: OK")
        return same
    except (KeyError, ValueError, TypeError) as exc:
        out(f"conversão do adaptador: FALHOU ({type(exc).__name__}: {exc})")
        return False


def _inspect_result(job: Any, manifest: dict[str, Any] | None, job_id: str,
                    out: Callable[[str], None]) -> int:
    result = job.result()
    out(f"result: tipo {type(result).__name__}, {len(result)} pub(s)")
    pub = result[0]
    data = pub.data
    fields = sorted(data.keys()) if hasattr(data, "keys") else "?"
    out(f"pub.data: tipo {type(data).__name__}, campos {fields}")
    meta = getattr(pub, "metadata", None)
    out(f"pub.metadata: {sorted(meta, key=str) if isinstance(meta, dict) else type(meta).__name__}")
    bitarray = getattr(data, CLASSICAL_REGISTER, None)
    if bitarray is None:
        out(f"ERRO: o resultado não tem o registrador '{CLASSICAL_REGISTER}'")
        return 1
    out(f"BitArray: num_bits={bitarray.num_bits} num_shots={bitarray.num_shots} "
        f"shape={bitarray.shape} array={bitarray.array.shape}/{bitarray.array.dtype}")
    matrix = bitarray.to_bool_array(order="little")
    _describe_bits(matrix, manifest, out)
    return 0 if _check_adapter(bitarray, matrix, manifest, job_id, out) else 1


def inspect_job(job: Any, job_id: str, manifest_dir: Path, out: Callable[[str], None],
                now: Callable[[], datetime] | None = None) -> int:
    """Inspeciona um job já obtido do serviço; não grava nada."""
    status = _status_name(job)
    final = job.in_final_state()
    out(f"job {job_id}: status {status}; em estado final: {final}")
    _print_timing(job, final, out, now)
    _print_metrics(job, out)
    manifest = _load_manifest(manifest_dir, job_id, out)
    if not final:
        out("O job ainda não terminou: nada a inspecionar do resultado.")
        return 4
    if status != "DONE":
        out(f"O job terminou com status {status}: não há resultado para inspecionar.")
        return 1
    _print_calibration(job, manifest, out)
    code = _inspect_result(job, manifest, job_id, out)
    out("NADA FOI SALVO e nada foi gravado no log de uso.")
    return code


def main(argv: Sequence[str] | None = None, *,
         service_factory: Callable[[str], Any] = build_service,
         out: Callable[[str], None] = print,
         now: Callable[[], datetime] | None = None) -> int:
    """Obtém o job no serviço e o inspeciona; nunca imprime o token."""
    parser = argparse.ArgumentParser(prog="inspecionar_job_ibm", description=__doc__.split("\n\n")[0])
    parser.add_argument("job_id")
    parser.add_argument("--instance", default=config.IBM_DEFAULT_INSTANCE)
    parser.add_argument("--logs-dir", type=Path, default=Path("data/logs"))
    args = parser.parse_args(argv)
    try:
        job = service_factory(args.instance).job(args.job_id)
        return inspect_job(job, args.job_id, args.logs_dir / "qpu_jobs", out, now)
    except CollectError as exc:
        out(f"ERRO: {exc}")
    except Exception as exc:  # noqa: BLE001
        out(f"ERRO inesperado: {type(exc).__name__}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
