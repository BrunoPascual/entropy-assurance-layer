"""Dia 6: ponto de entrada da coleta na IBM (status, calibrar, enviar, recuperar).

Uso (na raiz do projeto; as opções globais vêm ANTES do comando):

    py -3.12 scripts\\coletar_ibm.py status
    py -3.12 scripts\\coletar_ibm.py calibrar [--bits N [N ...]] [--n-qubits N] [--csv]
    py -3.12 scripts\\coletar_ibm.py enviar --shots N --reserva S --sessao cal [--qubits Q ...]
                                            [--dry-run] [--sim]
    py -3.12 scripts\\coletar_ibm.py recuperar JOB_ID

Códigos de saída: 0 ok; 1 erro; 2 uso incorreto (argparse); 3 recusado (orçamento ou você
respondeu não); 4 ainda não terminou (job na fila ou uso ainda em cálculo na IBM).

Regras: ``enviar`` mostra o plano e só gasta QPU depois de você digitar exatamente ``SIM``
(``--sim`` pula a pergunta; ``--dry-run`` nunca pergunta, não grava log nem manifesto);
``recuperar`` nunca reenvia; o token só é lido do ambiente (``.env``) e nunca é impresso:
de uma exceção desconhecida só o nome da classe aparece.
"""
from __future__ import annotations

import argparse
import csv
import io
import os
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from eal import config
from eal.sources.qpu_budget import BudgetPolicy, check_budget, read_log
from eal.sources.qpu_calibration import (
    CalibrationPoint, CostModel, fit_cost_model, plan_collection, points_from_entries,
    size_next_job,
)
from eal.sources.qpu_ibm import BudgetRefused, CollectError, IbmCollector, utc_now

EXIT_OK, EXIT_ERROR, EXIT_REFUSED, EXIT_NOT_DONE = 0, 1, 3, 4
CONFIRM_WORD = "SIM"
CSV_FIELDS = (
    "kind", "shots", "seconds", "target_bits", "n_jobs", "shots_per_job", "reserve_per_job",
    "total_bits", "central_seconds", "upper_seconds", "fits_budget", "fixed_seconds",
    "per_shot_seconds", "envelope_seconds",
)
LAUNCHER = "py -3.12 scripts\\coletar_ibm.py"


def policy_from_config() -> BudgetPolicy:
    """Política de orçamento montada com as constantes de ``eal/config.py``."""
    return BudgetPolicy(
        total_seconds=config.QPU_TOTAL_BUDGET_SECONDS,
        margin_seconds=config.QPU_BUDGET_MARGIN_SECONDS,
        daily_cap_seconds=config.QPU_DAILY_CAP_SECONDS,
        max_job_reserve_seconds=config.QPU_MAX_JOB_RESERVE_SECONDS,
        window_days=config.QPU_BUDGET_WINDOW_DAYS)


def build_service(instance: str, env: Mapping[str, str] | None = None) -> Any:
    """Abre o serviço da IBM com o token do ambiente; nunca imprime nem repassa o token."""
    if env is None:
        try:
            from dotenv import load_dotenv
            load_dotenv()
        except ImportError:
            pass
        env = os.environ
    token = env.get(config.IBM_TOKEN_ENV)
    if not token:
        raise CollectError(f"a variável {config.IBM_TOKEN_ENV} não está definida (confira o .env)")
    from qiskit_ibm_runtime import QiskitRuntimeService
    try:
        return QiskitRuntimeService(channel="ibm_quantum_platform", token=token,
                                    instance=instance)
    except Exception as exc:  # noqa: BLE001
        raise CollectError(f"não consegui abrir o serviço da IBM ({type(exc).__name__})") from None


@dataclass(frozen=True)
class Context:
    """O que todos os comandos compartilham."""

    backend: str
    instance: str
    policy: BudgetPolicy
    log_path: Path
    raw_dir: Path
    manifest_dir: Path
    results_dir: Path
    clock: Callable[[], datetime]
    out: Callable[[str], None]
    input_fn: Callable[[str], str]


def default_collector_factory(service: Any, ctx: Context) -> IbmCollector:
    """Coletor de verdade, com os caminhos e a política do contexto."""
    return IbmCollector(service, backend_name=ctx.backend, policy=ctx.policy,
                        log_path=ctx.log_path, raw_dir=ctx.raw_dir,
                        manifest_dir=ctx.manifest_dir, clock=ctx.clock)


def _remote_remaining(service: Any) -> Any:
    """Saldo restante informado pela IBM; None se não der para ler."""
    try:
        usage = service.usage()
    except Exception:  # noqa: BLE001
        return None
    return usage.get("usage_remaining_seconds") if isinstance(usage, dict) else None


def _report_problems(ctx: Context, problems: Sequence[str]) -> int:
    for problem in problems:
        ctx.out(f"PROBLEMA NO LOG: {problem}")
    return EXIT_ERROR


# ------------------------------------------------------------------ status

def cmd_status(ctx: Context, service_factory: Callable[[str], Any]) -> int:
    """Resume o log de uso, o orçamento local e o saldo remoto, sem gastar QPU."""
    entries, problems = read_log(ctx.log_path)
    remote, remote_note = None, ""
    try:
        remote = _remote_remaining(service_factory(ctx.instance))
    except Exception as exc:  # noqa: BLE001
        remote_note = f" (serviço indisponível: {type(exc).__name__})"
    decision = check_budget(entries, 1, ctx.policy, remote, now=ctx.clock(),
                            log_problems=problems)
    sent = [e for e in entries if e.event == "submitted"]
    closed = {e.job_id for e in entries if e.event == "final"}
    policy = ctx.policy
    ctx.out(f"Log de uso: {ctx.log_path}")
    ctx.out(f"Jobs enviados: {len(sent)} | concluídos: {len(closed)} | "
            f"pendentes: {len(decision.pending_job_ids)}")
    ctx.out(f"Comprometido na janela de {policy.window_days} dias: "
            f"{decision.window_committed_seconds:g} s | nas últimas 24 h: "
            f"{decision.day_committed_seconds:g} s")
    ctx.out(f"Reservas pendentes: {decision.pending_reserve_seconds:g} s "
            f"(jobs: {', '.join(decision.pending_job_ids) or 'nenhum'})")
    shown = "indisponível" if remote is None else f"{remote} s"
    ctx.out(f"Saldo remoto informado pela IBM: {shown}{remote_note}")
    ctx.out(f"Limites: total {policy.total_seconds:g} s, margem {policy.margin_seconds:g} s, "
            f"teto de 24 h {policy.daily_cap_seconds:g} s, reserva máxima por job "
            f"{policy.max_job_reserve_seconds:g} s")
    ctx.out(f"Disponível agora para um job (menor entre os limites conhecidos): "
            f"{decision.available_seconds:g} s")
    return _report_problems(ctx, problems) if problems else EXIT_OK


# ------------------------------------------------------------------ calibrar

def _policy_kwargs(ctx: Context) -> dict[str, Any]:
    return dict(safety_factor=config.QPU_RESERVE_SAFETY_FACTOR,
                extra_seconds=config.QPU_RESERVE_EXTRA_SECONDS,
                max_reserve=int(ctx.policy.max_job_reserve_seconds))


def _suggest_first(ctx: Context) -> int:
    bits = config.QPU_CALIBRATION_FIRST_SHOTS * config.QPU_BACKEND_QUBITS
    ctx.out("Ainda não há job de calibração concluído (status=DONE) no log.")
    ctx.out(f"Sugestão para o 1º job ({bits} bits com {config.QPU_BACKEND_QUBITS} qubits); "
            "rode antes com --dry-run se quiser:")
    ctx.out(f"  {LAUNCHER} enviar --shots {config.QPU_CALIBRATION_FIRST_SHOTS} "
            f"--reserva {config.QPU_CALIBRATION_FIRST_RESERVE_SECONDS} --sessao cal")
    return EXIT_OK


def _suggest_second(ctx: Context, point: CalibrationPoint) -> int:
    try:
        shots, reserve = size_next_job(
            point, target_seconds=config.QPU_CALIBRATION_TARGET_SECONDS,
            max_shots=config.QPU_MAX_SHOTS_PER_JOB, **_policy_kwargs(ctx))
    except ValueError as exc:
        ctx.out(f"ERRO: {exc}")
        return EXIT_ERROR
    ctx.out(f"Um ponto medido: {point.shots} shots usaram {point.seconds:g} s. Para separar "
            "o custo fixo do custo por shot, falta um job com shots diferentes.")
    ctx.out("Sugestão para o 2º job (limite superior seguro, assume custo fixo zero):")
    ctx.out(f"  {LAUNCHER} enviar --shots {shots} --reserva {reserve} --sessao cal")
    return EXIT_OK


def _csv_rows(model: CostModel, points: Sequence[CalibrationPoint],
              plans: Sequence[Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = [{
        "kind": "model", "fixed_seconds": repr(model.fixed_seconds),
        "per_shot_seconds": repr(model.per_shot_seconds),
        "envelope_seconds": repr(model.envelope_seconds)}]
    rows += [{"kind": "point", "shots": p.shots, "seconds": repr(p.seconds)} for p in points]
    for target, plan in plans:
        rows.append({
            "kind": "plan", "target_bits": target, "n_jobs": plan.n_jobs,
            "shots_per_job": plan.shots_per_job, "reserve_per_job": plan.reserve_per_job,
            "total_bits": plan.total_bits, "central_seconds": repr(plan.central_seconds),
            "upper_seconds": repr(plan.upper_seconds), "fits_budget": plan.fits_budget})
    return rows


def _write_csv(ctx: Context, rows: Sequence[Mapping[str, Any]]) -> Path:
    """Grava o resultado da calibração sem sobrescrever (nome com o instante, em UTC)."""
    stamp = ctx.clock().astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = ctx.results_dir / f"dia6_calibracao_{stamp}.csv"
    if path.exists():
        raise CollectError(f"o arquivo de resultado já existe: {path}")
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=CSV_FIELDS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    ctx.results_dir.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".csv.tmp")
    tmp.write_text(buffer.getvalue(), encoding="utf-8")
    os.rename(tmp, path)
    return path


def _report_model(ctx: Context, args: argparse.Namespace, entries: Sequence[Any],
                  points: Sequence[CalibrationPoint]) -> int:
    try:
        model = fit_cost_model(points)
    except ValueError as exc:
        ctx.out(f"ERRO: {exc}")
        return EXIT_ERROR
    day = check_budget(entries, 1, ctx.policy, None, now=ctx.clock()).day_committed_seconds
    budget = ctx.policy.daily_cap_seconds - day
    ctx.out(f"Modelo com {model.n_points} jobs: fixo {model.fixed_seconds:.3f} s + "
            f"{model.per_shot_seconds * 1000:.4f} ms por shot (envelope {model.envelope_seconds:.3f} s)")
    ctx.out(f"Teto de 24 h restante: {budget:g} s")
    plans: list[tuple[int, Any]] = []
    for target in args.bits:
        try:
            plan = plan_collection(
                model, target_bits=target, qubits=args.n_qubits, session_budget_seconds=budget,
                max_shots=config.QPU_MAX_SHOTS_PER_JOB, **_policy_kwargs(ctx))
        except ValueError as exc:
            ctx.out(f"ERRO ao planejar {target} bits: {exc}")
            return EXIT_ERROR
        plans.append((target, plan))
        ctx.out(f"  {target} bits: {plan.n_jobs} job(s) de {plan.shots_per_job} shots, reserva "
                f"{plan.reserve_per_job} s cada, custo alto {plan.upper_seconds:.1f} s, "
                f"{plan.total_bits} bits, cabe no teto: {'sim' if plan.fits_budget else 'NÃO'}")
    if args.csv:
        ctx.out(f"Resultado gravado em {_write_csv(ctx, _csv_rows(model, points, plans))}")
    return EXIT_OK


def cmd_calibrar(ctx: Context, args: argparse.Namespace) -> int:
    """Sugere o 1º job, dimensiona o 2º ou ajusta o modelo e planeja a coleta."""
    entries, problems = read_log(ctx.log_path)
    if problems:
        return _report_problems(ctx, problems)
    points = points_from_entries(entries, backend=ctx.backend)
    if not points:
        return _suggest_first(ctx)
    if len(points) < 2 or len({p.shots for p in points}) < 2:
        return _suggest_second(ctx, points[0])
    return _report_model(ctx, args, entries, points)


# ------------------------------------------------------------------ enviar

def _preview(ctx: Context, args: argparse.Namespace, n_qubits: int, decision: Any) -> None:
    ctx.out("Plano de envio")
    ctx.out(f"  backend ..: {ctx.backend}")
    ctx.out(f"  qubits ...: {n_qubits}")
    ctx.out(f"  shots ....: {args.shots}")
    ctx.out(f"  bits .....: {args.shots * n_qubits}")
    ctx.out(f"  reserva ..: {args.reserva} s (max_execution_time)")
    ctx.out(f"  sessão ...: {args.sessao}")
    if decision.allowed:
        ctx.out(f"  orçamento : OK (disponível {decision.available_seconds:g} s)")
    else:
        ctx.out("  orçamento : RECUSADO")
        for reason in decision.reasons:
            ctx.out(f"    - {reason}")


def _confirmed(ctx: Context, args: argparse.Namespace, n_qubits: int) -> bool:
    if args.sim:
        return True
    prompt = (f"Isto vai gastar até {args.reserva} s de QPU ({args.shots} shots, "
              f"{args.shots * n_qubits} bits). Digite {CONFIRM_WORD} para enviar: ")
    try:
        return ctx.input_fn(prompt).strip() == CONFIRM_WORD
    except EOFError:
        return False


def cmd_enviar(ctx: Context, args: argparse.Namespace, service_factory: Callable[[str], Any],
               collector_factory: Callable[[Any, Context], Any]) -> int:
    """Mostra o plano, pede confirmação e envia; ``--dry-run`` só valida no servidor."""
    service = service_factory(ctx.instance)
    collector = collector_factory(service, ctx)
    n_qubits = len(collector.prepare(args.qubits).physical_qubits)
    entries, problems = read_log(ctx.log_path)
    decision = check_budget(entries, args.reserva, ctx.policy, _remote_remaining(service),
                            now=ctx.clock(), log_problems=problems)
    _preview(ctx, args, n_qubits, decision)
    if args.dry_run:
        ctx.out("dry-run: o servidor valida o job; nada é gravado no log nem no manifesto.")
    elif not decision.allowed:
        return EXIT_REFUSED
    elif not _confirmed(ctx, args, n_qubits):
        ctx.out("Cancelado: nada foi enviado.")
        return EXIT_REFUSED
    result = collector.submit(args.shots, args.reserva, args.sessao, qubits=args.qubits,
                              dry_run=args.dry_run)
    ctx.out(f"Job {'validado (dry-run)' if result.dry_run else 'enviado'}: {result.job_id}")
    if result.dry_run:
        ctx.out(f"Compare o saldo antes e depois com '{LAUNCHER} status' para ver se o dry-run "
                "consumiu QPU.")
    else:
        ctx.out(f"Próximo passo: {LAUNCHER} recuperar {result.job_id}")
    return EXIT_OK


# ------------------------------------------------------------------ recuperar

def cmd_recuperar(ctx: Context, args: argparse.Namespace, service_factory: Callable[[str], Any],
                  collector_factory: Callable[[Any, Context], Any]) -> int:
    """Recupera um job já enviado; nunca reenvia."""
    collector = collector_factory(service_factory(ctx.instance), ctx)
    result = collector.retrieve(args.job_id)
    again = f"Rode de novo mais tarde: {LAUNCHER} recuperar {args.job_id}"
    if result.state == "pending":
        ctx.out(f"O job {result.job_id} ainda não terminou (status {result.status}). {again}")
        return EXIT_NOT_DONE
    if result.state == "usage_pending":
        ctx.out(f"Dados salvos em {result.output_file}, mas a IBM ainda não calculou o uso "
                f"(o job segue contando pela reserva cheia). {again}")
        return EXIT_NOT_DONE
    if result.state == "failed":
        used = "sem uso informado" if result.quantum_seconds is None else f"{result.quantum_seconds:g} s"
        ctx.out(f"O job {result.job_id} terminou com status {result.status} ({used}); "
                "não há dados para salvar.")
        return EXIT_ERROR
    label = "já estava fechado" if result.state == "already_final" else "fechado"
    ctx.out(f"Job {result.job_id} {label}: {result.output_file or 'sem arquivo'}, "
            f"uso {result.quantum_seconds if result.quantum_seconds is not None else '?'} s")
    if result.duplicate_of:
        ctx.out(f"ATENÇÃO: os bits são idênticos aos de {result.duplicate_of} (possível replay).")
    return EXIT_OK


# ------------------------------------------------------------------ main

def build_parser() -> argparse.ArgumentParser:
    """Parser de argumentos; as opções globais vêm antes do comando."""
    parser = argparse.ArgumentParser(prog="coletar_ibm", description=__doc__.split("\n\n")[0])
    parser.add_argument("--backend", default=config.IBM_DEFAULT_BACKEND)
    parser.add_argument("--instance", default=config.IBM_DEFAULT_INSTANCE)
    parser.add_argument("--logs-dir", type=Path, default=Path("data/logs"))
    parser.add_argument("--raw-dir", type=Path, default=Path("data/raw"))
    parser.add_argument("--results-dir", type=Path, default=Path("data/results"))
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status", help="resume o log e o orçamento, sem gastar QPU")
    cal = sub.add_parser("calibrar", help="sugere jobs de calibração e planeja a coleta")
    cal.add_argument("--bits", type=int, nargs="+",
                     default=[config.QPU_TARGET_BITS_MIN, config.QPU_TARGET_BITS_MAX])
    cal.add_argument("--n-qubits", type=int, default=config.QPU_BACKEND_QUBITS)
    cal.add_argument("--csv", action="store_true", help="grava o resultado em data/results")
    env = sub.add_parser("enviar", help="envia um job (pede confirmação)")
    env.add_argument("--shots", type=int, required=True)
    env.add_argument("--reserva", type=int, required=True)
    env.add_argument("--sessao", required=True)
    env.add_argument("--qubits", type=int, nargs="+")
    env.add_argument("--dry-run", action="store_true")
    env.add_argument("--sim", action="store_true", help="não pergunta antes de enviar")
    rec = sub.add_parser("recuperar", help="recupera um job já enviado")
    rec.add_argument("job_id")
    return parser


def main(argv: Sequence[str] | None = None, *,
         service_factory: Callable[[str], Any] = build_service,
         collector_factory: Callable[[Any, Context], Any] = default_collector_factory,
         clock: Callable[[], datetime] = utc_now, input_fn: Callable[[str], str] = input,
         out: Callable[[str], None] = print) -> int:
    """Roda um comando; nunca imprime o token e devolve o código de saída."""
    args = build_parser().parse_args(argv)
    ctx = Context(
        backend=args.backend, instance=args.instance, policy=policy_from_config(),
        log_path=args.logs_dir / config.QPU_USAGE_LOG_NAME, raw_dir=args.raw_dir,
        manifest_dir=args.logs_dir / "qpu_jobs", results_dir=args.results_dir,
        clock=clock, out=out, input_fn=input_fn)
    handlers: dict[str, Callable[[], int]] = {
        "status": lambda: cmd_status(ctx, service_factory),
        "calibrar": lambda: cmd_calibrar(ctx, args),
        "enviar": lambda: cmd_enviar(ctx, args, service_factory, collector_factory),
        "recuperar": lambda: cmd_recuperar(ctx, args, service_factory, collector_factory),
    }
    try:
        return handlers[args.command]()
    except BudgetRefused as exc:
        ctx.out(f"RECUSADO: {exc}")
        return EXIT_REFUSED
    except (CollectError, ValueError) as exc:
        ctx.out(f"ERRO: {exc}")
        return EXIT_ERROR
    except Exception as exc:  # noqa: BLE001
        ctx.out(f"ERRO inesperado: {type(exc).__name__}")
        return EXIT_ERROR
