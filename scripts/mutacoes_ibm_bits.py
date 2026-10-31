"""Mutações manuais de eal/sources/ibm_bits.py (Dia 6, passo 2).

Cada mutação troca UM trecho do módulo por uma versão errada e roda os testes; a mutação
"morre" se algum teste falhar. O módulo é sempre restaurado ao final, mesmo com Ctrl-C.
Isso mostra que os testes pegam esses erros, não que o módulo esteja correto.

Uso (na raiz do projeto):
    py -3.12 scripts\\mutacoes_ibm_bits.py
Código de saída: 0 se todas morreram; 1 se alguma sobreviveu ou se uma âncora não bateu.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

MODULE = Path("eal/sources/ibm_bits.py")
TESTS = "tests/test_ibm_bits.py"

# (nome, trecho original, trecho errado). O original precisa aparecer EXATAMENTE uma vez.
MUTATIONS: list[tuple[str, str, str]] = [
    ("ordem big em vez de little", 'to_bool_array(order="little")', 'to_bool_array(order="big")'),
    ("achatamento qubit a qubit", "matrix.astype(np.uint8).reshape(-1)",
     "matrix.astype(np.uint8).T.reshape(-1)"),
    ("bits em int8", ".astype(np.uint8)", ".astype(np.int8)"),
    ("resultado que nao e BitArray aceito", "if not isinstance(bitarray, BitArray):",
     "if False:"),
    ("varredura de parametros aceita", "if bitarray.shape != ():", "if False:"),
    ("num_bits nao conferido", "if bitarray.num_bits != n_qubits:", "if False:"),
    ("num_shots nao conferido", "if bitarray.num_shots != shots:", "if False:"),
    ("registrador nao conferido", "if registers != [(CLASSICAL_REGISTER, n_qubits)]:",
     "if False:"),
    ("porta de dois qubits aceita",
     'if inst.operation.name != "barrier" and len(inst.qubits) > 1:', "if False:"),
    ("barrier conta como porta de varios qubits",
     'if inst.operation.name != "barrier" and len(inst.qubits) > 1:',
     "if len(inst.qubits) > 1:"),
    ("clbit medido duas vezes aceito", "if clbit in mapping:", "if False:"),
    ("clbit nao medido aceito", "if sorted(mapping) != list(range(n_qubits)):", "if False:"),
    ("mapa fora da ordem dos clbits", "physical = [mapping[i] for i in range(n_qubits)]",
     "physical = sorted(mapping.values())"),
    ("qubit fisico repetido aceito", "if len(set(physical)) != n_qubits:", "if False:"),
    ("job_id nao validado", '"job_id": _check_text("job_id", job_id),', '"job_id": job_id,'),
    ("backend nao validado", '"backend": _check_text("backend_name", backend_name),',
     '"backend": backend_name,'),
    ("qubits errado nos params", '"qubits": len(physical),', '"qubits": len(physical) + 1,'),
    ("n_qubits errado nos params", '"n_qubits": len(physical),',
     '"n_qubits": len(physical) + 1,'),
    ("bits descartados nao zero", '"discarded_bits": 0,', '"discarded_bits": 1,'),
    ("texto da ordem dos bits muda",
     'BIT_ORDER = "shot-major; posicao i do shot = physical_qubits[i]"',
     'BIT_ORDER = "shot-major; posicao i do shot = physical_qubits[i + 1]"'),
    ("calibracao pela metade aceita",
     "if readout_error is None or calibration_date is None:", "if False:"),
    ("erro de leitura com tamanho errado aceito", "if len(errors) != n_qubits:", "if False:"),
    ("erro de leitura fora de 0 a 1 aceito",
     '_check_float("readout_error", e, 0.0, 1.0)',
     '_check_float("readout_error", e, -1e9, 1e9)'),
    ("shots invalido aceito", "if not _is_int(shots) or shots < 1:", "if False:"),
    ("qubit fisico negativo aceito", "not _is_int(q) or q < 0", "not _is_int(q)"),
    ("qubit fisico repetido aceito nos params",
     "\n            or len(set(physical)) != len(physical)):", "):"),
    ("tempo maximo zero aceito", "if max_time <= 0:", "if False:"),
    ("intervalo entre shots sem teto",
     '"rep_delay_seconds": _check_float("rep_delay_seconds", rep_delay_seconds, 0.0, 1.0),',
     '"rep_delay_seconds": _check_float("rep_delay_seconds", rep_delay_seconds, 0.0, 1e9),'),
    ("bool vale como numero", "isinstance(value, bool) or not isinstance(value, (int, float))",
     "not isinstance(value, (int, float))"),
    ("texto sem padrao aceito",
     "if not isinstance(value, str) or not _TEXT_RE.fullmatch(value):",
     "if not isinstance(value, str):"),
    ("texto com quebra de linha aceito", "\n            or not value.isprintable()):", "):"),
    ("texto longo aceito", " or len(value) > _SHORT_MAX", ""),
    ("sdk_versions vazio aceito", "if not isinstance(sdk_versions, dict) or not sdk_versions:",
     "if not isinstance(sdk_versions, dict):"),
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
