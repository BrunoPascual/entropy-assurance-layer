"""Mutações manuais de scripts/inspecionar_job_ibm.py (Dia 6, inspeção só de leitura de um job).

Cada mutação troca UM trecho do módulo por uma versão errada e roda os testes; a mutação
"morre" se algum teste falhar. O módulo é sempre restaurado ao final, mesmo com Ctrl-C.
Isso mostra que os testes pegam esses erros, não que o módulo esteja correto.

Uso (na raiz do projeto):
    py -3.12 scripts\\mutacoes_inspecionar_job_ibm.py
Código de saída: 0 se todas morreram; 1 se alguma sobreviveu ou se uma âncora não bateu.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

MODULE = Path("scripts/inspecionar_job_ibm.py")
TESTS = "tests/test_inspecionar_job_ibm.py"

# (nome, trecho original, trecho errado). O original precisa aparecer EXATAMENTE uma vez.
MUTATIONS: list[tuple[str, str, str]] = [
    ('fila nao devolve 4',
     '        out("O job ainda não terminou: nada a inspecionar do resultado.")\n        return 4',
     '        out("O job ainda não terminou: nada a inspecionar do resultado.")\n        return 0'),
    ('status de falha tenta o resultado',
     '    if status != "DONE":',
     '    if False:'),
    ('conversao falha mas sai 0',
     '    return 0 if _check_adapter(bitarray, matrix, manifest, job_id, out) else 1',
     '    return 0'),
    ('sem manifesto reprova',
     '    if manifest is None:\n        return True',
     '    if manifest is None:\n        return False'),
    ('registrador ausente passa',
     '    if bitarray is None:\n        out(f"ERRO: o resultado não tem o registrador \'{CLASSICAL_REGISTER}\'")\n        return 1',
     '    if False:\n        return 1'),
    ('erro inesperado vaza a mensagem',
     'out(f"ERRO inesperado: {type(exc).__name__}")',
     'out(f"ERRO inesperado: {exc}")'),
    ('colunas enviesadas sem o qubit fisico',
     'where = f" (qubit físico {physical[position]})" if physical and position < len(physical) else ""',
     'where = ""'),
    ('colunas mais enviesadas invertidas',
     'np.argsort(-np.abs(means - 0.5))[:TOP_BIASED]',
     'np.argsort(np.abs(means - 0.5))[:TOP_BIASED]'),
    ('ordem big em vez de little',
     'bitarray.to_bool_array(order="little")',
     'bitarray.to_bool_array(order="big")'),
    ('params nao conferidos',
     '        build_ibm_params(\n            backend_name=manifest["backend"], job_id=job_id,',
     '        (lambda **k: None)(\n            backend_name=manifest["backend"], job_id=job_id,'),
    ('igualdade com o to_bool_array ignorada',
     '        return same\n',
     '        return True\n'),
    ('falha no metrics interrompe',
     '        out(f"metrics(): falhou ({type(exc).__name__})")',
     '        raise'),
    ('CollectError sem mensagem',
     'out(f"ERRO: {exc}")',
     'out("ERRO")'),
    ('instancia ignorada',
     'service_factory(args.instance)',
     'service_factory(config.IBM_DEFAULT_INSTANCE)'),
    ('tempo decorrido com sinal trocado',
     'return (current - created).total_seconds() / 60',
     'return (created - current).total_seconds() / 60'),
    ('fila tambem para job final',
     '    if final:\n        return\n',
     '    if False:\n        return\n'),
    ('instantes sempre iguais',
     '            return bool(a == b)',
     '            return True'),
    ('texto sempre igual',
     '    return str(first) == str(second)',
     '    return True'),
    ('calibracao diferente sem destaque',
     '+ ("igual" if same else "DIFERENTE: o retrato do manifesto pode não valer para este job"))',
     '+ "igual")'),
    ('pior deriva pelo minimo',
     'worst, qubit = max(diffs)',
     'worst, qubit = min(diffs)'),
    ('deriva sem modulo',
     'diffs = [(abs(props.readout_error(q) - e), q)',
     'diffs = [(props.readout_error(q) - e, q)'),
    ('properties que falha interrompe',
     '        out(f"calibração no início do job: indisponível ({type(exc).__name__})")\n        return',
     '        raise'),
    ('estimativa que falha interrompe',
     '        out(f"usage_estimation: falhou ({type(exc).__name__})")',
     '        raise'),
    ('fila que falha interrompe',
     '        out(f"fila do backend: indisponível ({type(exc).__name__})")',
     '        raise'),
    ('data de criacao ausente nao tratada',
     '        if created is not None:',
     '        if True:'),
    ('calibracao sem retrato do envio',
     '    if manifest is None or manifest.get("calibration_date") is None:\n        return',
     '    if False:\n        return'),
    ('calibracao so apos o resultado',
     '    _print_calibration(job, manifest, out)\n    code = _inspect_result',
     '    code = _inspect_result'),
    ('tempo na fila nao e mostrado',
     '    _print_timing(job, final, out, now)\n',
     ''),
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
