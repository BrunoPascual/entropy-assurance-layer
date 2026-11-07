"""G7 / T12: limite duro do orçamento de QPU e log de uso (contas e texto, sem IBM).

O módulo não importa Qiskit nem fala com a IBM. Quem chama informa o saldo remoto (o campo
``usage_remaining_seconds`` do ``service.usage()``) e o instante atual; o módulo decide se um
novo job pode ser enviado, lendo o log de uso (``data/logs/qpu_usage.csv``, só com acréscimos).

Contas, todas em segundos de QPU e todas fail-closed:

- um job enviado e não concluído conta pela RESERVA cheia (o ``max_execution_time`` pedido);
- um job concluído conta pelo uso real; sem uso informado, conta pela reserva;
- o novo job só passa se couber, ao mesmo tempo, no saldo local (total - margem - já
  comprometido na janela), no saldo remoto (informado - margem - reservas pendentes, que a
  IBM pode ainda não ter contado) e no teto das últimas 24 h (janela rolante, sem fuso);
- log ilegível ou inconsistente, saldo remoto ausente ou reserva inválida: recusa.

Limites conhecidos: não há trava entre dois processos (duas coletas ao mesmo tempo podem passar
juntas pela conferência); um job que ficou pendente no log (processo caiu) segue contando pela
reserva cheia até alguém registrar o ``final`` dele.
"""
from __future__ import annotations

import csv
import io
import math
import os
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

USAGE_FIELDS: tuple[str, ...] = (
    "ts", "event", "job_id", "backend", "qubits", "shots",
    "reserve_seconds", "quantum_seconds", "output_file", "note",
)
EVENTS: tuple[str, ...] = ("submitted", "final", "refused")
_ID_RE = re.compile(r"[A-Za-z0-9._-]{1,64}")
_FLOAT_CELL_RE = re.compile(r"[0-9]+(\.[0-9]+)?([eE][+-]?[0-9]+)?")
_INT_CELL_RE = re.compile(r"[0-9]+")
_TEXT_MAX = 200
_DAY = timedelta(hours=24)


class UsageLogError(ValueError):
    """Erro de gravação do log de uso."""


def _is_number(value: Any) -> bool:
    """Número real finito (bool não vale)."""
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value))


def _is_int(value: Any) -> bool:
    """Inteiro de verdade (bool não vale)."""
    return isinstance(value, int) and not isinstance(value, bool)


@dataclass(frozen=True)
class BudgetPolicy:
    """Parâmetros do limite duro; todos explícitos (os valores vivem em eal/config.py)."""

    total_seconds: float
    margin_seconds: float
    daily_cap_seconds: float
    max_job_reserve_seconds: float
    window_days: int

    def __post_init__(self) -> None:
        names = ("total_seconds", "margin_seconds", "daily_cap_seconds",
                 "max_job_reserve_seconds")
        for name in names:
            value = getattr(self, name)
            if not _is_number(value) or value <= 0:
                raise ValueError(f"{name} deve ser um número positivo")
        if not _is_int(self.window_days) or self.window_days < 1:
            raise ValueError("window_days deve ser um inteiro maior ou igual a 1")
        if self.margin_seconds >= self.total_seconds:
            raise ValueError("a margem deve ser menor que o total")
        if self.daily_cap_seconds > self.total_seconds - self.margin_seconds:
            raise ValueError("o teto diário passa do total menos a margem")
        if self.max_job_reserve_seconds > self.daily_cap_seconds:
            raise ValueError("a reserva máxima por job passa do teto diário")


@dataclass(frozen=True)
class UsageEntry:
    """Uma linha do log de uso. ``ts`` é ISO 8601 com fuso."""

    ts: str
    event: str
    job_id: str = ""
    backend: str = ""
    qubits: int | None = None
    shots: int | None = None
    reserve_seconds: float | None = None
    quantum_seconds: float | None = None
    output_file: str = ""
    note: str = ""


@dataclass(frozen=True)
class BudgetDecision:
    """Resultado da conferência; ``allowed`` só é True sem nenhum motivo de recusa."""

    allowed: bool
    reasons: tuple[str, ...]
    window_committed_seconds: float
    day_committed_seconds: float
    pending_reserve_seconds: float
    pending_job_ids: tuple[str, ...]
    available_seconds: float


def _parse_ts(text: Any) -> datetime | None:
    """ISO 8601 com fuso, em UTC; None se inválido ou sem fuso."""
    if not isinstance(text, str):
        return None
    try:
        moment = datetime.fromisoformat(text)
    except ValueError:
        return None
    if moment.tzinfo is None:
        return None
    return moment.astimezone(timezone.utc)


def _numeric_problems(entry: UsageEntry) -> list[str]:
    """Problemas nos campos numéricos de uma entrada."""
    problems: list[str] = []
    for name in ("qubits", "shots"):
        value = getattr(entry, name)
        if value is not None and (not _is_int(value) or value <= 0):
            problems.append(f"{name} inválido")
    reserve = entry.reserve_seconds
    if entry.event == "submitted":
        if not _is_number(reserve) or reserve <= 0:
            problems.append("reserve_seconds inválido")
    elif reserve is not None and (not _is_number(reserve) or reserve <= 0):
        problems.append("reserve_seconds inválido")
    quantum = entry.quantum_seconds
    if quantum is not None:
        if entry.event != "final":
            problems.append("quantum_seconds só vale em final")
        elif not _is_number(quantum) or quantum < 0:
            problems.append("quantum_seconds inválido")
    return problems


def _text_problems(entry: UsageEntry) -> list[str]:
    """Problemas nos campos de texto de uma entrada."""
    problems: list[str] = []
    needs_job = entry.event in ("submitted", "final")
    job = entry.job_id
    if not isinstance(job, str) or ((needs_job or job != "") and not _ID_RE.fullmatch(job)):
        problems.append("job_id inválido")
    backend = entry.backend
    if not isinstance(backend, str) or (backend != "" and not _ID_RE.fullmatch(backend)):
        problems.append("backend inválido")
    for name in ("output_file", "note"):
        value = getattr(entry, name)
        if (not isinstance(value, str) or len(value) > _TEXT_MAX
                or "\n" in value or "\r" in value):
            problems.append(f"{name} inválido")
    return problems


def entry_problems(entry: UsageEntry) -> list[str]:
    """Lista de problemas de uma entrada (vazia se estiver válida)."""
    problems: list[str] = []
    if _parse_ts(entry.ts) is None:
        problems.append("ts inválido (precisa de fuso)")
    if entry.event not in EVENTS:
        problems.append("event inválido")
        return problems
    return problems + _text_problems(entry) + _numeric_problems(entry)


def format_header() -> str:
    """Linha de cabeçalho do log, com quebra de linha."""
    return ",".join(USAGE_FIELDS) + "\n"


def _cell(value: Any) -> str:
    """Texto de uma célula do CSV."""
    if value is None:
        return ""
    return repr(float(value)) if isinstance(value, float) else str(value)


def format_row(entry: UsageEntry) -> str:
    """Linha CSV de uma entrada (com ``\\n``); recusa entrada inválida."""
    problems = entry_problems(entry)
    if problems:
        raise ValueError("entrada do log de uso inválida: " + "; ".join(problems))
    out = io.StringIO()
    csv.writer(out, lineterminator="\n").writerow(
        [_cell(getattr(entry, name)) for name in USAGE_FIELDS])
    return out.getvalue()


def _to_entry(row: list[str]) -> UsageEntry:
    """Monta uma entrada de uma linha já separada; ValueError se um número for inválido."""
    cells = dict(zip(USAGE_FIELDS, row))

    def number(name: str) -> float | None:
        if cells[name] == "":
            return None
        if not _FLOAT_CELL_RE.fullmatch(cells[name]):
            raise ValueError(f"campo {name} não é número")
        return float(cells[name])

    def integer(name: str) -> int | None:
        if cells[name] == "":
            return None
        if not _INT_CELL_RE.fullmatch(cells[name]):
            raise ValueError(f"campo {name} não é inteiro")
        return int(cells[name])

    return UsageEntry(
        ts=cells["ts"], event=cells["event"], job_id=cells["job_id"],
        backend=cells["backend"], qubits=integer("qubits"), shots=integer("shots"),
        reserve_seconds=number("reserve_seconds"), quantum_seconds=number("quantum_seconds"),
        output_file=cells["output_file"], note=cells["note"])


def parse_usage_log(text: str) -> tuple[list[UsageEntry], list[str]]:
    """Lê o texto do log: devolve as entradas válidas e os problemas (por número de linha)."""
    try:
        rows = list(csv.reader(io.StringIO(text, newline="")))
    except csv.Error:
        return [], ["log de uso ilegível como CSV"]
    if not rows or tuple(rows[0]) != USAGE_FIELDS:
        return [], ["cabeçalho do log de uso diferente do esperado"]
    entries: list[UsageEntry] = []
    problems: list[str] = []
    for number, row in enumerate(rows[1:], start=2):
        if len(row) != len(USAGE_FIELDS):
            problems.append(f"linha {number}: {len(row)} campos em vez de {len(USAGE_FIELDS)}")
            continue
        try:
            entry = _to_entry(row)
        except ValueError as exc:
            problems.append(f"linha {number}: {exc}")
            continue
        bad = entry_problems(entry)
        if bad:
            problems.append(f"linha {number}: " + "; ".join(bad))
        else:
            entries.append(entry)
    return entries, problems


@dataclass
class _Job:
    """Estado de um job no log: enviado e, se houver, concluído."""

    ts: datetime
    reserve: float
    final: bool = False
    quantum: float | None = None


def _job_states(entries: Sequence[UsageEntry]) -> tuple[dict[str, _Job], list[str]]:
    """Estado de cada job, na ordem do log; inconsistências viram problemas."""
    jobs: dict[str, _Job] = {}
    problems: list[str] = []
    for index, entry in enumerate(entries, start=1):
        bad = entry_problems(entry)
        if bad:
            problems.append(f"entrada {index}: " + "; ".join(bad))
            continue
        if entry.event == "submitted":
            if entry.job_id in jobs:
                problems.append(f"entrada {index}: job_id repetido em submitted")
            else:
                jobs[entry.job_id] = _Job(_parse_ts(entry.ts), float(entry.reserve_seconds))
        elif entry.event == "final":
            job = jobs.get(entry.job_id)
            if job is None:
                problems.append(f"entrada {index}: final sem submitted")
            elif job.final:
                problems.append(f"entrada {index}: final repetido")
            else:
                job.final = True
                job.quantum = (None if entry.quantum_seconds is None
                               else float(entry.quantum_seconds))
    return jobs, problems


def _cost(job: _Job) -> float:
    """Custo contado de um job: uso real se concluído e informado; senão a reserva."""
    if job.final and job.quantum is not None:
        return job.quantum
    return job.reserve


def check_budget(entries: Sequence[UsageEntry], reserve_seconds: Any, policy: BudgetPolicy,
                 remote_remaining_seconds: Any, *, now: datetime,
                 log_problems: Sequence[str] = ()) -> BudgetDecision:
    """Decide se um job com esta reserva pode ser enviado agora.

    Nunca levanta exceção por causa do conteúdo do log ou dos números recebidos: qualquer
    dúvida vira motivo de recusa. ``now`` precisa ter fuso (erro de uso, ValueError).
    """
    if now.tzinfo is None:
        raise ValueError("now precisa ter fuso")
    now = now.astimezone(timezone.utc)
    jobs, problems = _job_states(entries)
    reasons = [f"log de uso: {p}" for p in (*log_problems, *problems)]
    cutoff = now - timedelta(days=policy.window_days)
    window = {jid: j for jid, j in jobs.items() if j.ts > cutoff}
    today = [j for j in window.values() if j.ts > now - _DAY]
    pending = sorted(jid for jid, j in window.items() if not j.final)
    pending_reserve = sum(j.reserve for j in window.values() if not j.final)
    committed = sum(_cost(j) for j in window.values())
    day_committed = sum(_cost(j) for j in today)
    rooms: dict[str, float | None] = {
        "saldo local": policy.total_seconds - policy.margin_seconds - committed,
        "teto das últimas 24 h": policy.daily_cap_seconds - day_committed,
        "saldo remoto": None,
    }
    if _is_number(remote_remaining_seconds) and remote_remaining_seconds >= 0:
        rooms["saldo remoto"] = (remote_remaining_seconds - policy.margin_seconds
                                 - pending_reserve)
    else:
        reasons.append("saldo remoto indisponível ou inválido")
    reasons += _reserve_reasons(reserve_seconds, policy, rooms)
    known = [room for room in rooms.values() if room is not None]
    return BudgetDecision(
        allowed=not reasons, reasons=tuple(reasons),
        window_committed_seconds=committed, day_committed_seconds=day_committed,
        pending_reserve_seconds=pending_reserve, pending_job_ids=tuple(pending),
        available_seconds=max(min(known), 0.0))


def _reserve_reasons(reserve: Any, policy: BudgetPolicy,
                     rooms: dict[str, float | None]) -> list[str]:
    """Motivos de recusa ligados ao tamanho da reserva pedida."""
    if not _is_number(reserve) or reserve <= 0:
        return ["reserva do job inválida"]
    reasons: list[str] = []
    if reserve > policy.max_job_reserve_seconds:
        reasons.append(f"reserva de {reserve:g} s acima do máximo por job "
                       f"({policy.max_job_reserve_seconds:g} s)")
    for name, room in rooms.items():
        if room is not None and reserve > room:
            reasons.append(f"{name}: reserva de {reserve:g} s acima do disponível "
                           f"({max(room, 0.0):g} s)")
    return reasons


def _check_existing(path: Path) -> None:
    """O log existente precisa ter o cabeçalho certo e terminar em quebra de linha."""
    with open(path, "rb") as fh:
        first = fh.readline()
        fh.seek(-1, os.SEEK_END)
        last = fh.read(1)
    if first.rstrip(b"\r\n") != ",".join(USAGE_FIELDS).encode("utf-8"):
        raise UsageLogError("cabeçalho do log de uso diferente do esperado")
    if last != b"\n":
        raise UsageLogError("o log de uso não termina em quebra de linha: intervenção manual")


def append_entry(path: Path | str, entry: UsageEntry) -> None:
    """Acrescenta uma entrada ao log (modo ``ab``, ``flush`` e ``fsync``); nunca reescreve."""
    row = format_row(entry)  # valida antes de tocar no disco
    target = Path(path)
    payload = row
    if target.exists() and target.stat().st_size > 0:
        _check_existing(target)
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = format_header() + row
    with open(target, "ab") as fh:
        fh.write(payload.encode("utf-8"))
        fh.flush()
        os.fsync(fh.fileno())


def read_log(path: Path | str) -> tuple[list[UsageEntry], list[str]]:
    """Lê o log do disco; arquivo ausente ou vazio é um log sem entradas."""
    target = Path(path)
    if not target.exists():
        return [], []
    raw = target.read_bytes()
    if not raw:
        return [], []
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return [], ["log de uso não é UTF-8 válido"]
    entries, problems = parse_usage_log(text)
    if not text.endswith("\n"):
        problems.append("o log de uso não termina em quebra de linha")
    return entries, problems
