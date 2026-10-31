"""Mutações manuais de eal/sources/qpu_budget.py (Dia 6, G7/T12).

Cada mutação troca UM trecho do módulo por uma versão errada e roda os testes; a mutação
"morre" se algum teste falhar. O módulo é sempre restaurado ao final, mesmo com Ctrl-C.
Isso mostra que os testes pegam esses erros, não que o módulo esteja correto.

Uso (na raiz do projeto):
    py -3.12 scripts\\mutacoes_qpu_budget.py
Código de saída: 0 se todas morreram; 1 se alguma sobreviveu ou se uma âncora não bateu.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

MODULE = Path("eal/sources/qpu_budget.py")
TESTS = "tests/test_qpu_budget.py"

# (nome, trecho original, trecho errado). O original precisa aparecer EXATAMENTE uma vez.
MUTATIONS: list[tuple[str, str, str]] = [
    ("now sem fuso aceito", "if now.tzinfo is None:", "if False:"),
    ("janela de 28 dias inclui o limite", "if j.ts > cutoff}", "if j.ts >= cutoff}"),
    ("teto de 24 h inclui o limite", "if j.ts > now - _DAY]", "if j.ts >= now - _DAY]"),
    ("job concluido sem uso conta zero",
     "        return job.quantum\n    return job.reserve", "        return job.quantum\n    return 0.0"),
    ("job concluido conta sempre o uso", "if job.final and job.quantum is not None:",
     "if job.final:"),
    ("saldo remoto sem descontar pendentes",
     "(remote_remaining_seconds - policy.margin_seconds\n                                 - pending_reserve)",
     "(remote_remaining_seconds - policy.margin_seconds)"),
    ("saldo remoto sem margem",
     "(remote_remaining_seconds - policy.margin_seconds\n", "(remote_remaining_seconds\n"),
    ("saldo local sem margem",
     "policy.total_seconds - policy.margin_seconds - committed",
     "policy.total_seconds - committed"),
    ("teto diario ignora o comprometido", "policy.daily_cap_seconds - day_committed",
     "policy.daily_cap_seconds"),
    ("reserva igual ao disponivel recusa", "if room is not None and reserve > room:",
     "if room is not None and reserve >= room:"),
    ("reserva igual ao maximo por job recusa", "if reserve > policy.max_job_reserve_seconds:",
     "if reserve >= policy.max_job_reserve_seconds:"),
    ("saldo remoto zero vira invalido", "remote_remaining_seconds >= 0",
     "remote_remaining_seconds > 0"),
    ("bool vale como numero", " and not isinstance(value, bool)\n            and math.isfinite",
     "\n            and math.isfinite"),
    ("infinito e nan valem como numero", "\n            and math.isfinite(value))", ")"),
    ("final sem submitted aceito", "            if job is None:\n", "            if False:\n"),
    ("submitted repetido aceito", "if entry.job_id in jobs:", "if False:"),
    ("final repetido aceito", "elif job.final:", "elif False:"),
    ("pendentes incluem concluidos",
     "pending = sorted(jid for jid, j in window.items() if not j.final)",
     "pending = sorted(jid for jid, j in window.items())"),
    ("reserva pendente nao conta",
     "pending_reserve = sum(j.reserve for j in window.values() if not j.final)",
     "pending_reserve = 0.0"),
    ("comprometido so do dia",
     "committed = sum(_cost(j) for j in window.values())",
     "committed = sum(_cost(j) for j in today)"),
    ("available pode ser negativo", "available_seconds=max(min(known), 0.0))",
     "available_seconds=min(known))"),
    ("append sem fsync", "        os.fsync(fh.fileno())", "        pass"),
    ("append aceita cabecalho diferente",
     'if first.rstrip(b"\\r\\n") != ",".join(USAGE_FIELDS).encode("utf-8"):', "if False:"),
    ("append aceita log sem quebra final", 'if last != b"\\n":', "if False:"),
    ("read_log nao acusa falta de quebra final", 'if not text.endswith("\\n"):', "if False:"),
    ("parse aceita cabecalho diferente",
     "if not rows or tuple(rows[0]) != USAGE_FIELDS:", "if not rows:"),
    ("parse aceita qualquer numero", '_FLOAT_CELL_RE = re.compile(r"[0-9]+(\\.[0-9]+)?([eE][+-]?[0-9]+)?")',
     '_FLOAT_CELL_RE = re.compile(r".*")'),
    ("ts sem fuso aceito", "    if moment.tzinfo is None:\n        return None\n",
     "    if False:\n        return None\n"),
    ("margem igual ao total aceita", "if self.margin_seconds >= self.total_seconds:",
     "if self.margin_seconds > self.total_seconds:"),
    ("teto diario no limite recusa",
     "if self.daily_cap_seconds > self.total_seconds - self.margin_seconds:",
     "if self.daily_cap_seconds >= self.total_seconds - self.margin_seconds:"),
    ("submitted sem job_id aceito", "((needs_job or job != \"\") and", "((job != \"\") and"),
    ("reserva zero aceita em submitted",
     "        if not _is_number(reserve) or reserve <= 0:\n            problems.append",
     "        if not _is_number(reserve):\n            problems.append"),
    ("uso zero recusado", "elif not _is_number(quantum) or quantum < 0:",
     "elif not _is_number(quantum) or quantum <= 0:"),
    ("qubits zero aceito", 'if value is not None and (not _is_int(value) or value <= 0):',
     'if value is not None and (not _is_int(value) or value < 0):'),
]


def run_tests() -> bool:
    """True se a suíte do módulo passa."""
    done = subprocess.run([sys.executable, "-m", "pytest", "-q", "-x", TESTS],
                          capture_output=True, text=True)
    return done.returncode == 0


def apply(text: str, old: str, new: str) -> str:
    """Troca ``old`` por ``new`` respeitando o fim de linha do arquivo; exige 1 ocorrência."""
    eol = "\r\n" if "\r\n" in text else "\n"
    old, new = old.replace("\n", eol), new.replace("\n", eol)
    if text.count(old) != 1:
        raise ValueError(f"âncora aparece {text.count(old)} vez(es)")
    return text.replace(old, new)


def main() -> int:
    """Roda todas as mutações; restaura o módulo no final."""
    original = MODULE.read_bytes()
    text = original.decode("utf-8")
    if not run_tests():
        print("A suíte NÃO passa no módulo original; corrija antes de mutar.")
        return 1
    survived: list[str] = []
    anchors: list[str] = []
    try:
        for name, old, new in MUTATIONS:
            try:
                mutated = apply(text, old, new)
            except ValueError as exc:
                anchors.append(f"{name}: {exc}")
                print(f"[ÂNCORA] {name}: {exc}")
                continue
            MODULE.write_bytes(mutated.encode("utf-8"))
            killed = not run_tests()
            print(f"[{'morta' if killed else 'SOBREVIVEU'}] {name}")
            if not killed:
                survived.append(name)
    finally:
        MODULE.write_bytes(original)
    ok = len(MUTATIONS) - len(survived) - len(anchors)
    print(f"\n{len(MUTATIONS)} mutações: {ok} mortas, {len(survived)} sobreviveram, "
          f"{len(anchors)} com âncora inválida.")
    print("módulo restaurado:", MODULE.read_bytes() == original)
    return 0 if not survived and not anchors else 1


if __name__ == "__main__":
    raise SystemExit(main())
