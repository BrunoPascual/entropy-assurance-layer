"""Mutações manuais de eal/sources/qpu_ibm.py (Dia 6, 3b).

Cada mutação troca UM trecho do módulo por uma versão errada e roda os testes; a mutação
"morre" se algum teste falhar. O módulo é sempre restaurado ao final, mesmo com Ctrl-C.
Isso mostra que os testes pegam esses erros, não que o módulo esteja correto.

Uso (na raiz do projeto):
    py -3.12 scripts\\mutacoes_qpu_ibm.py
Código de saída: 0 se todas morreram; 1 se alguma sobreviveu ou se uma âncora não bateu.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

MODULE = Path("eal/sources/qpu_ibm.py")
TESTS = "tests/test_qpu_ibm.py"

# (nome, trecho original, trecho errado). O original precisa aparecer EXATAMENTE uma vez.
MUTATIONS: list[tuple[str, str, str]] = [
    ("guarda de orcamento ignorada",
     "decision = self._guard(reserve_seconds, shots, n_qubits, session)", "decision = None"),
    ("refused nao e registrado", "append_entry(self.log_path, refused)", "pass"),
    ("recusa nao levanta", "        raise BudgetRefused(decision)", "        return decision"),
    ("reserva nao vai ao servidor",
     "sampler = self.sampler_factory(self._backend(), reserve_seconds)",
     "sampler = self.sampler_factory(self._backend(), 1)"),
    ("dry_run sempre falso", "return sampler.run([prepared.isa], shots=shots, dry_run=dry_run)",
     "return sampler.run([prepared.isa], shots=shots, dry_run=False)"),
    ("dry_run grava log e manifesto", "        if dry_run:\n", "        if False:\n"),
    ("reserva nao inteira aceita",
     "(not _is_int(reserve_seconds)\n                or not 1 <= reserve_seconds <= self.policy.max_job_reserve_seconds)",
     "(not 1 <= reserve_seconds <= self.policy.max_job_reserve_seconds)"),
    ("reserva acima do maximo aceita", "reserve_seconds <= self.policy.max_job_reserve_seconds",
     "reserve_seconds <= 10**6"),
    ("shots sem limite", "or not 1 <= shots <= self.max_shots:", "or not 1 <= shots:"),
    ("sessao nao validada",
     "if not isinstance(session, str) or not _SESSION_RE.fullmatch(session):", "if False:"),
    ("submitted nao gravado",
     "            append_entry(self.log_path, entry)\n        except (OSError, ValueError) as exc:\n            raise SubmittedButNotLogged(job_id, row) from exc",
     "            pass\n        except (OSError, ValueError) as exc:\n            raise SubmittedButNotLogged(job_id, row) from exc"),
    ("falha de log engolida", "            raise SubmittedButNotLogged(job_id, row) from exc",
     "            pass"),
    ("manifesto nao gravado", "path = self._write_manifest(manifest)", "path = None"),
    ("manifesto sobrescreve",
     "            if path.exists():\n                raise FileExistsError(str(path))",
     "            if False:\n                raise FileExistsError(str(path))"),
    ("manifesto sem fsync", "                os.fsync(fh.fileno())", "                pass"),
    ("layout diferente aceito", "if physical != chosen:", "if False:"),
    ("qubit fora de operacao aceito",
     "return [q for q in range(backend.num_qubits) if props.is_qubit_operational(q)]",
     "return [q for q in range(backend.num_qubits) if True]"),
    ("qubit pedido nao conferido", "if not set(chosen) <= set(operational):", "if False:"),
    ("qubits repetidos aceitos", " or len(set(chosen)) != len(chosen)", ""),
    ("uso zero conta como uso", "and math.isfinite(value) and value > 0)",
     "and math.isfinite(value) and value >= 0)"),
    ("uso nao finito aceito", "and math.isfinite(value) and value > 0)", "and value > 0)"),
    ("bool conta como uso", "isinstance(value, (int, float)) and not isinstance(value, bool)",
     "isinstance(value, (int, float))"),
    ("usage tem prioridade sobre metrics", "candidates.append(job.usage())",
     "candidates.insert(0, job.usage())"),
    ("lote nao reaproveitado", "npy = self._find_batch_for_job(job_id)", "npy = None"),
    ("usage_pending grava final", "        if quantum is None:\n            return RetrieveResult(",
     "        if False:\n            return RetrieveResult("),
    ("duplicado nao anotado",
     'note = "status=DONE" + (f"; duplicate_of={duplicate}" if duplicate else "")',
     'note = "status=DONE"'),
    ("duplicado compara com ele mesmo", "if other == npy or meta.get", "if False or meta.get"),
    ("status de falha tratado como DONE", '        if status != "DONE":\n', "        if False:\n"),
    ("final repetido reprocessado", "        if finals:\n", "        if False:\n"),
    ("job fora do log aceito",
     'if not any(e.event == "submitted" for e in mine):', "if False:"),
    ("log com problemas ignorado na recuperacao",
     '        if problems:\n            raise RetrieveError("log de uso com problemas: "',
     '        if False:\n            raise RetrieveError("log de uso com problemas: "'),
    ("job na fila nao detectado", "        if not job.in_final_state():\n", "        if False:\n"),
    ("dado inutilizavel escapa sem fechar a conta",
     "except (KeyError, ValueError, AttributeError, IndexError, TypeError) as exc:",
     "except KeyError as exc:"),
    ("source_type errado", 'source_type="qpu_ibm"', 'source_type="qpu_sim"'),
    ("lote marcado como local", "is_local=False", "is_local=True"),
    ("lote marcado como simulado", "is_simulated=False", "is_simulated=True"),
    ("source_id errado", "RawBatch(source_id=self.backend_name,", 'RawBatch(source_id="x",'),
    ("conversao com n errado",
     'bitarray_to_bits(bitarray, len(manifest["physical_qubits"]), manifest["shots"])',
     'bitarray_to_bits(bitarray, manifest["shots"], manifest["shots"])'),
    ("reserva do manifesto perdida", 'max_execution_time_seconds=manifest["reserve_seconds"]',
     "max_execution_time_seconds=1"),
    ("manifesto de outro job aceito", 'or manifest.get("job_id") != job_id', ""),
    ("aviso de obsolescencia vaza", 'warnings.filterwarnings("ignore", message="The SamplerV2 class is deprecated",\n                                category=DeprecationWarning)',
     "pass"),
    ("limite do servidor nao aplicado", "    sampler.options.max_execution_time = max_execution_time\n",
     "    pass\n"),
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
