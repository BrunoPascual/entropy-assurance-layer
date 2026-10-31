"""Dia 6, etapa 0: reconhecimento SÓ DE LEITURA da conta e do backend IBM.

Não envia job, não grava arquivo, não gasta tempo de QPU. Nunca imprime o token
(a mensagem de uma exceção também não é impressa, só o nome da classe).

Uso (PowerShell, na raiz do projeto):
    py -3.12 scripts\\reconhecimento_ibm_dia6.py
    py -3.12 scripts\\reconhecimento_ibm_dia6.py --backend ibm_kingston --instance open-instance
"""
from __future__ import annotations

import argparse
import inspect
import os
import sys
import warnings
from typing import Any

TOKEN_ENV = "IBM_QUANTUM_TOKEN"


def sec(title: str) -> None:
    """Imprime o cabeçalho de uma seção."""
    print(f"\n=== {title} ===")


def fail(what: str, exc: BaseException) -> None:
    """Imprime só o nome da classe da exceção (a mensagem pode conter dados da conta)."""
    print(f"[ERRO] {what}: {type(exc).__name__}")


def show_warnings(caught: list[warnings.WarningMessage]) -> None:
    """Imprime categoria e início do texto de cada aviso capturado."""
    if not caught:
        print("  avisos: nenhum")
        return
    for w in caught:
        print(f"  aviso: {w.category.__name__}: {str(w.message)[:160]}")


def print_versions() -> None:
    """Versões dos pacotes que o script de coleta vai usar."""
    sec("1. Versões")
    print(f"python: {sys.version.split()[0]}")
    for name in ("qiskit", "qiskit_aer", "qiskit_ibm_runtime", "numpy"):
        try:
            mod = __import__(name)
            print(f"{name}: {getattr(mod, '__version__', '?')}")
        except Exception as exc:  # noqa: BLE001
            fail(f"import {name}", exc)


def print_primitives() -> None:
    """SamplerV2 (legado) e o Sampler do lado do cliente: existência, avisos e assinatura do run."""
    sec("2. Primitivos")
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        try:
            from qiskit_ibm_runtime import SamplerV2  # noqa: F401
            print("import SamplerV2: ok")
        except Exception as exc:  # noqa: BLE001
            fail("import SamplerV2", exc)
    show_warnings(caught)
    try:
        from qiskit_ibm_runtime.executor_sampler import Sampler as ClientSampler
        print("import executor_sampler.Sampler: ok")
        print(f"  assinatura do run: {inspect.signature(ClientSampler.run)}")
    except Exception as exc:  # noqa: BLE001
        fail("import executor_sampler.Sampler", exc)
    try:
        from qiskit_ibm_runtime import SamplerV2
        print(f"  assinatura do SamplerV2.run: {inspect.signature(SamplerV2.run)}")
    except Exception as exc:  # noqa: BLE001
        fail("assinatura do SamplerV2.run", exc)


def connect(instance: str) -> Any:
    """Abre o serviço com o token do .env; devolve None se não der."""
    sec("4. Conexão")
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except Exception as exc:  # noqa: BLE001
        fail("python-dotenv", exc)
    token = os.environ.get(TOKEN_ENV)
    if not token:
        print(f"[ERRO] variável {TOKEN_ENV} ausente (conferir o .env)")
        return None
    try:
        from qiskit_ibm_runtime import QiskitRuntimeService
        service = QiskitRuntimeService(
            channel="ibm_quantum_platform", token=token, instance=instance)
        print(f"serviço aberto (instance={instance})")
        return service
    except Exception as exc:  # noqa: BLE001
        fail("QiskitRuntimeService", exc)
        return None


def print_usage(service: Any) -> None:
    """Saldo da instância: só valores numéricos e booleanos são impressos."""
    sec("5. service.usage()")
    try:
        usage = service.usage()
    except Exception as exc:  # noqa: BLE001
        fail("service.usage()", exc)
        return
    if not isinstance(usage, dict):
        print(f"tipo devolvido: {type(usage).__name__}")
        return
    for key in sorted(usage):
        value = usage[key]
        if value is None or isinstance(value, (bool, int, float)):
            print(f"  {key}: {value}")
        else:
            print(f"  {key}: (valor do tipo {type(value).__name__} omitido)")


def operational_qubits(backend: Any) -> tuple[list[int] | None, str]:
    """Lista de qubits operacionais segundo backend.properties(), ou None com o motivo."""
    try:
        props = backend.properties()
    except Exception as exc:  # noqa: BLE001
        return None, f"properties() falhou: {type(exc).__name__}"
    if props is None:
        return None, "properties() devolveu None"
    ops: list[int] = []
    for q in range(backend.num_qubits):
        try:
            if props.is_qubit_operational(q):
                ops.append(q)
        except Exception as exc:  # noqa: BLE001
            return None, f"is_qubit_operational falhou: {type(exc).__name__}"
    return ops, "ok"


def print_backend(service: Any, name: str) -> None:
    """Backends da instância e detalhes do backend escolhido."""
    sec("6. Backends da instância")
    try:
        names = sorted(b.name for b in service.backends())
        print(f"{len(names)} backend(s): {', '.join(names)}")
    except Exception as exc:  # noqa: BLE001
        fail("service.backends()", exc)
    sec(f"7. Backend {name}")
    try:
        backend = service.backend(name)
    except Exception as exc:  # noqa: BLE001
        fail("service.backend()", exc)
        return
    print(f"num_qubits: {backend.num_qubits}")
    for attr in ("max_shots", "max_circuits", "version"):
        try:
            print(f"{attr}: {getattr(backend, attr)}")
        except Exception as exc:  # noqa: BLE001
            print(f"{attr}: indisponível ({type(exc).__name__})")
    try:
        st = backend.status()
        print(f"operational: {st.operational}; pending_jobs: {st.pending_jobs}")
    except Exception as exc:  # noqa: BLE001
        fail("backend.status()", exc)
    ops, why = operational_qubits(backend)
    if ops is None:
        print(f"qubits operacionais: não determinado ({why})")
    else:
        off = backend.num_qubits - len(ops)
        print(f"qubits operacionais: {len(ops)} de {backend.num_qubits} ({off} fora de operação)")
        print(f"  fora de operação: {sorted(set(range(backend.num_qubits)) - set(ops))}")
    print_options(backend)


def print_options(backend: Any) -> None:
    """Cria o SamplerV2 (sem enviar nada) e confere onde fica o max_execution_time."""
    sec("8. Opções do SamplerV2 (sem enviar job)")
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        try:
            from qiskit_ibm_runtime import SamplerV2
            sampler = SamplerV2(mode=backend)
            opts = sampler.options
            print(f"options.max_execution_time existe: {hasattr(opts, 'max_execution_time')}")
            print(f"default_shots existe: {hasattr(opts, 'default_shots')}")
            print(f"opção dry_run em options: {hasattr(opts, 'dry_run')}")
        except Exception as exc:  # noqa: BLE001
            fail("SamplerV2(mode=backend)", exc)
    show_warnings(caught)


def print_job_api() -> None:
    """Confere que o job tem os métodos de uso que o script de coleta vai chamar."""
    sec("3. API do job")
    try:
        from qiskit_ibm_runtime import RuntimeJobV2
        for meth in ("metrics", "usage", "job_id", "in_final_state", "wait_for_final_state"):
            print(f"RuntimeJobV2.{meth}: {hasattr(RuntimeJobV2, meth)}")
        print(f"  assinatura de usage: {inspect.signature(RuntimeJobV2.usage)}")
    except Exception as exc:  # noqa: BLE001
        fail("RuntimeJobV2", exc)


def main() -> int:
    """Roda o reconhecimento; sempre termina com código 0 (é só diagnóstico)."""
    parser = argparse.ArgumentParser(description="Reconhecimento só de leitura da conta IBM.")
    parser.add_argument("--backend", default="ibm_kingston")
    parser.add_argument("--instance", default="open-instance")
    args = parser.parse_args()
    print("Reconhecimento IBM (só leitura): nenhum job será enviado.")
    print_versions()
    print_primitives()
    print_job_api()
    service = connect(args.instance)
    if service is not None:
        print_usage(service)
        print_backend(service, args.backend)
    print("\nFim. Nada foi enviado e nenhum arquivo foi gravado.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
