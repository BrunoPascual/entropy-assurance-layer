"""Mutações manuais das linhas novas do passo 2 da DEP_SESSAO (analisar_coleta1 e resumo_coleta1).

Uso:  py -3.12 scripts\\mutacoes_sessao_analise.py

Cada mutação troca um trecho único; se o trecho não aparecer exatamente uma vez, conta como
"âncora inválida". Os testes rodam sem cache e sem bytecode; os módulos são sempre restaurados.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AC = Path("scripts/analisar_coleta1.py")
RC = Path("scripts/resumo_coleta1.py")
TESTS = ["tests/test_sessao_analise.py", "tests/test_analisar_coleta1.py",
         "tests/test_resumo_coleta1.py"]

MUTATIONS = [
    (AC, "sessao sem validacao",
     "if not isinstance(session, str) or not SESSION_RE.fullmatch(session):\n"
     '        raise AnalysisError',
     'if not isinstance(session, str):\n        raise AnalysisError'),
    (AC, "sublinhado aceito na sessao",
     'SESSION_RE = re.compile(r"[A-Za-z0-9]+")', 'SESSION_RE = re.compile(r"[A-Za-z0-9_]+")'),
    (AC, "nome de saida ignora a sessao",
     '    return name.replace("dia6_", f"dia6_{session}_", 1)', "    return name"),
    (AC, "coleta1 tambem ganha prefixo",
     "    if session == SESSION:\n        return name\n", ""),
    (AC, "nome do por_qubit ignora a sessao",
     "out_dir / session_file(QUBIT_NAME, session)]", "out_dir / QUBIT_NAME]"),
    (AC, "inventario nao derivado da sessao",
     "inventory = args.inventario or inventory_for(session)",
     "inventory = args.inventario or INVENTORY_PATH"),
    (AC, "sessao nao repassada ao run",
     "sim_factory=sim_factory, os_factory=os_factory, session=session)",
     "sim_factory=sim_factory, os_factory=os_factory)"),
    (AC, "run nao valida a sessao",
     "    session = check_session(session)\n    sim_factory", "    sim_factory"),
    (AC, "conferencia cedo sem a sessao",
     "check_targets(out_dir, session)  # falha cedo", "check_targets(out_dir)  # falha cedo"),
    (AC, "load_real sem a sessao",
     "real = load_real(raw_dir, inventory, session)", "real = load_real(raw_dir, inventory)"),
    (AC, "gravacao sem a sessao",
     "paths = write_outputs(out_dir, lots_text, qubit_text, session)",
     "paths = write_outputs(out_dir, lots_text, qubit_text)"),
    (AC, "retrato da execucao ignorado no readout_of",
     'return run if run is not None else params.get("readout_error_by_position")',
     'return params.get("readout_error_by_position")'),
    (AC, "analyze_source nao usa readout_of",
     "readout = readout_of(b.params) if use_readout else None",
     'readout = b.params.get("readout_error_by_position") if use_readout else None'),
    (RC, "resumo: sessao sem validacao",
     "if not isinstance(session, str) or not SESSION_RE.fullmatch(session):\n"
     '        raise SummaryError',
     'if not isinstance(session, str):\n        raise SummaryError'),
    (RC, "resumo: nome ignora a sessao",
     '    return name.replace("dia6_", f"dia6_{session}_", 1)', "    return name"),
    (RC, "resumo: entrada nao derivada da sessao",
     "build(args.entrada or input_for(session))", "build(args.entrada or IN_PATH)"),
    (RC, "resumo: nome do resumo fixo",
     "args.out_dir / session_file(RESUMO_NAME, session)", "args.out_dir / RESUMO_NAME"),
    (RC, "resumo: nome do excesso fixo",
     "args.out_dir / session_file(EXCESSO_NAME, session)", "args.out_dir / EXCESSO_NAME"),
]


def _run_tests() -> bool:
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    done = subprocess.run([sys.executable, "-m", "pytest", "-q", "-x", "-p", "no:cacheprovider",
                           *TESTS], cwd=ROOT, env=env, capture_output=True, text=True)
    return done.returncode == 0


def _drop_bytecode(module: Path) -> None:
    for pyc in (ROOT / module.parent / "__pycache__").glob(module.stem + ".*.pyc"):
        pyc.unlink(missing_ok=True)


def main() -> int:
    originals = {m: (ROOT / m).read_bytes() for m in (AC, RC)}
    killed = survived = invalid = 0
    try:
        for m in originals:
            _drop_bytecode(m)
        if not _run_tests():
            print("Os testes já falham sem mutação; nada foi mutado.")
            return 2
        for module, name, old, new in MUTATIONS:
            raw = originals[module]
            crlf = b"\r\n" in raw
            text = raw.decode("utf-8").replace("\r\n", "\n")
            if text.count(old) != 1:
                print(f"[ancora invalida] {name}")
                invalid += 1
                continue
            mutated = text.replace(old, new)
            (ROOT / module).write_bytes(
                (mutated.replace("\n", "\r\n") if crlf else mutated).encode("utf-8"))
            _drop_bytecode(module)
            try:
                if _run_tests():
                    print(f"[SOBREVIVEU] {name}")
                    survived += 1
                else:
                    print(f"[morta] {name}")
                    killed += 1
            finally:
                (ROOT / module).write_bytes(raw)
                _drop_bytecode(module)
    finally:
        for m, raw in originals.items():
            (ROOT / m).write_bytes(raw)
    restored = all((ROOT / m).read_bytes() == raw for m, raw in originals.items())
    print(f"\n{len(MUTATIONS)} mutações: {killed} mortas, {survived} sobreviveram, "
          f"{invalid} com âncora inválida.")
    print(f"módulos restaurados: {restored}")
    return 0 if survived == 0 and invalid == 0 and restored else 1


if __name__ == "__main__":
    sys.exit(main())
