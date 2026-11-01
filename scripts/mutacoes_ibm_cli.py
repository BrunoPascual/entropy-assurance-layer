"""Mutações manuais de eal/ibm_cli.py (Dia 6, ponto de entrada da coleta).

Cada mutação troca UM trecho do módulo por uma versão errada e roda os testes; a mutação
"morre" se algum teste falhar. O módulo é sempre restaurado ao final, mesmo com Ctrl-C.
Isso mostra que os testes pegam esses erros, não que o módulo esteja correto.

Uso (na raiz do projeto):
    py -3.12 scripts\\mutacoes_ibm_cli.py
Código de saída: 0 se todas morreram; 1 se alguma sobreviveu ou se uma âncora não bateu.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

MODULE = Path("eal/ibm_cli.py")
TESTS = "tests/test_ibm_cli.py"

# (nome, trecho original, trecho errado). O original precisa aparecer EXATAMENTE uma vez.
MUTATIONS: list[tuple[str, str, str]] = [
    ("confirmacao ignorada", "return ctx.input_fn(prompt).strip() == CONFIRM_WORD", "return True"),
    ("confirmacao sem diferenciar maiuscula",
     "return ctx.input_fn(prompt).strip() == CONFIRM_WORD",
     "return ctx.input_fn(prompt).strip().upper() == CONFIRM_WORD"),
    ("confirmacao sem tirar espacos", "return ctx.input_fn(prompt).strip() == CONFIRM_WORD",
     "return ctx.input_fn(prompt) == CONFIRM_WORD"),
    ("fim da entrada confirma", "    except EOFError:\n        return False",
     "    except EOFError:\n        return True"),
    ("palavra de confirmacao errada", 'CONFIRM_WORD = "SIM"', 'CONFIRM_WORD = "sim"'),
    ("--sim nao pula a pergunta", "    if args.sim:\n        return True",
     "    if False:\n        return True"),
    ("orcamento recusado envia mesmo assim", "    elif not decision.allowed:\n        return EXIT_REFUSED",
     "    elif False:\n        return EXIT_REFUSED"),
    ("recusa de orcamento sai com 0", "    elif not decision.allowed:\n        return EXIT_REFUSED",
     "    elif not decision.allowed:\n        return EXIT_OK"),
    ("cancelamento sai com 0", '        ctx.out("Cancelado: nada foi enviado.")\n        return EXIT_REFUSED',
     '        ctx.out("Cancelado: nada foi enviado.")\n        return EXIT_OK'),
    ("dry-run tratado como envio", '    if args.dry_run:\n        ctx.out("dry-run:',
     '    if False:\n        ctx.out("dry-run:'),
    ("dry-run nao repassado", "dry_run=args.dry_run)", "dry_run=False)"),
    ("qubits nao repassados",
     "result = collector.submit(args.shots, args.reserva, args.sessao, qubits=args.qubits,",
     "result = collector.submit(args.shots, args.reserva, args.sessao, qubits=None,"),
    ("qubits do preparo ignorados",
     "n_qubits = len(collector.prepare(args.qubits).physical_qubits)", "n_qubits = 156"),
    ("bits errados no plano", 'ctx.out(f"  bits .....: {args.shots * n_qubits}")',
     'ctx.out(f"  bits .....: {args.shots}")'),
    ("reserva errada na pergunta", 'prompt = (f"Isto vai gastar até {args.reserva} s',
     'prompt = (f"Isto vai gastar até {args.shots} s'),
    ("saldo remoto ignorado no envio", "_remote_remaining(service),\n", "None,\n"),
    ("job na fila sai com 0",
     '(status {result.status}). {again}")\n        return EXIT_NOT_DONE',
     '(status {result.status}). {again}")\n        return EXIT_OK'),
    ("uso em calculo sai com 0",
     'pela reserva cheia). {again}")\n        return EXIT_NOT_DONE',
     'pela reserva cheia). {again}")\n        return EXIT_OK'),
    ("job que falhou sai com 0", '"não há dados para salvar.")\n        return EXIT_ERROR',
     '"não há dados para salvar.")\n        return EXIT_OK'),
    ("duplicado sem aviso", "    if result.duplicate_of:", "    if False:"),
    ("status ignora problemas do log",
     "return _report_problems(ctx, problems) if problems else EXIT_OK", "return EXIT_OK"),
    ("status sem saldo remoto", "remote = _remote_remaining(service_factory(ctx.instance))",
     "remote = None"),
    ("status conta concluidos errado",
     'closed = {e.job_id for e in entries if e.event == "final"}', "closed = set()"),
    ("calibrar ignora problemas do log",
     "    if problems:\n        return _report_problems(ctx, problems)\n    points",
     "    if False:\n        return _report_problems(ctx, problems)\n    points"),
    ("calibrar sem filtro de backend", "points_from_entries(entries, backend=ctx.backend)",
     "points_from_entries(entries)"),
    ("calibrar com um ponto ajusta o modelo",
     "if len(points) < 2 or len({p.shots for p in points}) < 2:", "if len(points) < 1:"),
    ("calibrar com shots iguais ajusta o modelo",
     " or len({p.shots for p in points}) < 2:", ":"),
    ("orcamento do plano ignora o consumo do dia",
     "budget = ctx.policy.daily_cap_seconds - day", "budget = ctx.policy.daily_cap_seconds"),
    ("csv sobrescreve", '    if path.exists():\n        raise CollectError(f"o arquivo de resultado',
     '    if False:\n        raise CollectError(f"o arquivo de resultado'),
    ("csv sem o instante no nome",
     'stamp = ctx.clock().astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")', 'stamp = "x"'),
    ("csv com tipo de linha errado", '"kind": "model"', '"kind": "modelo"'),
    ("erro inesperado vaza a mensagem", 'ctx.out(f"ERRO inesperado: {type(exc).__name__}")',
     'ctx.out(f"ERRO inesperado: {exc}")'),
    ("abertura do servico vaza a mensagem",
     'raise CollectError(f"não consegui abrir o serviço da IBM ({type(exc).__name__})") from None',
     'raise CollectError(f"não consegui abrir o serviço da IBM ({exc})") from None'),
    ("abertura do servico preserva a causa",
     'raise CollectError(f"não consegui abrir o serviço da IBM ({type(exc).__name__})") from None',
     'raise CollectError(f"não consegui abrir o serviço da IBM ({type(exc).__name__})") from exc'),
    ("token vazio aceito", "    if not token:\n", "    if token is None:\n"),
    ("politica com janela errada", "window_days=config.QPU_BUDGET_WINDOW_DAYS)", "window_days=1)"),
    ("recusa do adaptador sai com 1",
     '    except BudgetRefused as exc:\n        ctx.out(f"RECUSADO: {exc}")\n        return EXIT_REFUSED',
     '    except BudgetRefused as exc:\n        ctx.out(f"RECUSADO: {exc}")\n        return EXIT_ERROR'),
    ("erro conhecido sai com 0",
     '        ctx.out(f"ERRO: {exc}")\n        return EXIT_ERROR\n    except Exception',
     '        ctx.out(f"ERRO: {exc}")\n        return EXIT_OK\n    except Exception'),
    ("backend padrao errado", 'parser.add_argument("--backend", default=config.IBM_DEFAULT_BACKEND)',
     'parser.add_argument("--backend", default="x")'),
    ("pasta do manifesto errada", 'manifest_dir=args.logs_dir / "qpu_jobs"',
     'manifest_dir=args.logs_dir / "jobs"'),
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
