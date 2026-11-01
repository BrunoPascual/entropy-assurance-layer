"""Mutações manuais de eal/sources/qpu_calibration.py (Dia 6, modelo de custo de QPU).

Cada mutação troca UM trecho do módulo por uma versão errada e roda os testes; a mutação
"morre" se algum teste falhar. O módulo é sempre restaurado ao final, mesmo com Ctrl-C.
Isso mostra que os testes pegam esses erros, não que o módulo esteja correto.

Uso (na raiz do projeto):
    py -3.12 scripts\\mutacoes_qpu_calibration.py
Código de saída: 0 se todas morreram; 1 se alguma sobreviveu ou se uma âncora não bateu.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

MODULE = Path("eal/sources/qpu_calibration.py")
TESTS = "tests/test_qpu_calibration.py"

# (nome, trecho original, trecho errado). O original precisa aparecer EXATAMENTE uma vez.
MUTATIONS: list[tuple[str, str, str]] = [
    ("ajuste sem envelope",
     "envelope = max(0.0, max(p.seconds - (fixed + per_shot * p.shots) for p in pts))",
     "envelope = 0.0"),
    ("custo por shot nao positivo aceito", "if not per_shot > 0:", "if False:"),
    ("shots iguais aceitos", " or len({p.shots for p in pts}) < 2:", ":"),
    ("reta sem o termo fixo", "fixed = mean_y - per_shot * mean_x", "fixed = mean_y"),
    ("inclinacao errada", "per_shot = sxy / sxx", "per_shot = sxy / (sxx + 1)"),
    ("custo alto sem envelope",
     "return max(0.0, self.central_seconds(shots) + self.envelope_seconds)",
     "return max(0.0, self.central_seconds(shots))"),
    ("custo alto pode ser negativo",
     "return max(0.0, self.central_seconds(shots) + self.envelope_seconds)",
     "return self.central_seconds(shots) + self.envelope_seconds"),
    ("reserva sem fator de seguranca",
     "math.ceil(model.upper_seconds(shots) * safety_factor + extra_seconds)",
     "math.ceil(model.upper_seconds(shots) + extra_seconds)"),
    ("reserva sem segundos extras",
     "math.ceil(model.upper_seconds(shots) * safety_factor + extra_seconds)",
     "math.ceil(model.upper_seconds(shots) * safety_factor)"),
    ("reserva arredonda para baixo", "return max(1, math.ceil(", "return max(1, math.floor("),
    ("reserva pode ser zero", "return max(1, math.ceil(", "return max(0, math.ceil("),
    ("reserva acima do maximo aceita", "    if need > max_reserve:", "    if False:"),
    ("reserva no limite recusada", "    if need > max_reserve:", "    if need >= max_reserve:"),
    ("maximo sem ajuste para cima",
     "    while (shots < max_shots\n           and _need(model, shots + 1, safety_factor, extra_seconds) <= max_reserve):\n        shots += 1\n",
     "    pass\n"),
    ("maximo sem ajuste para baixo",
     "    while shots > 0 and _need(model, shots, safety_factor, extra_seconds) > max_reserve:\n        shots -= 1\n",
     "    pass\n"),
    ("maximo sem teto do backend", "shots = max(0, min(guess, max_shots))", "shots = max(0, guess)"),
    ("segundo job com custo por shot errado",
     "model = CostModel(0.0, first.seconds / first.shots, 0.0, 1)",
     "model = CostModel(0.0, first.seconds / (first.shots * 2), 0.0, 1)"),
    ("segundo job ignora o alvo",
     "shots = max(first.shots, min(by_target, by_reserve, max_shots))",
     "shots = max(first.shots, min(by_reserve, max_shots))"),
    ("segundo job com menos shots que o primeiro",
     "shots = max(first.shots, min(by_target, by_reserve, max_shots))",
     "shots = min(by_target, by_reserve, max_shots)"),
    ("segundo job aceita uso zero", "if first.seconds <= 0:", "if False:"),
    ("plano arredonda n_jobs para baixo", "n_jobs = -(-wanted_shots // per_job_max)",
     "n_jobs = wanted_shots // per_job_max"),
    ("plano sem balancear os shots", "shots_per_job = -(-wanted_shots // n_jobs)",
     "shots_per_job = per_job_max"),
    ("plano arredonda o alvo para baixo", "wanted_shots = -(-target_bits // qubits)",
     "wanted_shots = target_bits // qubits"),
    ("plano cabe com custo igual ao orcamento", "fits_budget=upper <= session_budget_seconds",
     "fits_budget=upper < session_budget_seconds"),
    ("plano nao recusa quando nada cabe", "if per_job_max < 1:", "if False:"),
    ("job com erro entra no ajuste",
     ' or not entry.note.startswith("status=DONE")', ""),
    ("uso zero entra no ajuste", "or entry.quantum_seconds <= 0", "or entry.quantum_seconds < 0"),
    ("filtro de backend ignorado", "and (backend is None or e.backend == backend)", "and True"),
    ("filtro de qubits ignorado", "and (qubits is None or e.qubits == qubits)}", "and True}"),
    ("job sem shots no log entra", "if sent is None or sent.shots is None:", "if sent is None:"),
    ("final entra como submitted", 'if e.event == "submitted"', "if True"),
]


def run_tests() -> bool:
    """True se a suíte do módulo passa.

    Roda sem gravar bytecode: o Python valida o .pyc só por data (em segundos) e tamanho, e uma
    mutação de mesmo tamanho feita no mesmo segundo da anterior reaproveitaria o bytecode errado.
    """
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    done = subprocess.run([sys.executable, "-B", "-m", "pytest", "-q", "-x", TESTS],
                          capture_output=True, text=True, env=env)
    return done.returncode == 0


def drop_bytecode() -> None:
    """Apaga o bytecode em cache do módulo, para a próxima importação recompilar o fonte."""
    for pyc in MODULE.parent.glob(f"__pycache__/{MODULE.stem}.*.pyc"):
        pyc.unlink(missing_ok=True)


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
        drop_bytecode()
    ok = len(MUTATIONS) - len(survived) - len(anchors)
    print(f"\n{len(MUTATIONS)} mutações: {ok} mortas, {len(survived)} sobreviveram, "
          f"{len(anchors)} com âncora inválida.")
    print("módulo restaurado:", MODULE.read_bytes() == original)
    return 0 if not survived and not anchors else 1


if __name__ == "__main__":
    raise SystemExit(main())
