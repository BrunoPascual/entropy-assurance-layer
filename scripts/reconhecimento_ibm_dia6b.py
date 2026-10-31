"""Dia 6, etapa 0b: complemento SÓ DE LEITURA do reconhecimento da conta IBM.

Responde o que a primeira sonda deixou em aberto: a janela do orçamento (usage_period),
o limite de shots por job, o erro de leitura por qubit (dado que o E1 vai precisar) e o
texto completo do aviso de obsolescência do SamplerV2. Não envia job e não grava arquivo.
Nunca imprime o token; de uma exceção, só o nome da classe.

Precisa de scripts\\reconhecimento_ibm_dia6.py na mesma pasta (reaproveita as funções dele).

Uso (PowerShell, na raiz do projeto):
    py -3.12 scripts\\reconhecimento_ibm_dia6b.py
"""
from __future__ import annotations

import argparse
import statistics
import warnings
from typing import Any

from reconhecimento_ibm_dia6 import connect, fail, sec

# Campos de configuração que interessam ao desenho da coleta.
CONFIG_FIELDS = (
    "max_shots", "max_experiments", "rep_delay_range", "default_rep_delay",
    "dynamic_reprate_enabled", "n_qubits",
)
# Chaves de topo do service.usage() que NÃO são impressas (identificam a conta).
HIDDEN_USAGE_KEYS = ("instance_id", "plan_id")


def print_scalars(value: Any, prefix: str, depth: int = 0) -> None:
    """Imprime valores escalares de um dict, em profundidade limitada; texto longo é cortado."""
    if isinstance(value, dict) and depth < 3:
        for key in sorted(value):
            print_scalars(value[key], f"{prefix}.{key}" if prefix else str(key), depth + 1)
    elif value is None or isinstance(value, (bool, int, float)):
        print(f"  {prefix}: {value}")
    elif isinstance(value, str):
        print(f"  {prefix}: {value[:80]}")
    else:
        print(f"  {prefix}: (tipo {type(value).__name__} omitido)")


def print_usage_period(service: Any) -> None:
    """Mostra a janela do orçamento (rolante de 28 dias ou mês de calendário) e o consumo fino."""
    sec("1. Janela do orçamento (service.usage)")
    try:
        usage = service.usage()
    except Exception as exc:  # noqa: BLE001
        fail("service.usage()", exc)
        return
    if not isinstance(usage, dict):
        print(f"tipo devolvido: {type(usage).__name__}")
        return
    for key in sorted(usage):
        if key in HIDDEN_USAGE_KEYS:
            continue
        print_scalars(usage[key], key)


def print_config(backend: Any) -> None:
    """Campos de backend.configuration(), que o BackendV2 não expõe direto."""
    sec("2. Configuração do backend")
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        try:
            cfg = backend.configuration()
        except Exception as exc:  # noqa: BLE001
            fail("backend.configuration()", exc)
            cfg = None
        if cfg is not None:
            for name in CONFIG_FIELDS:
                print(f"  {name}: {getattr(cfg, name, '(ausente)')}")
    for w in caught:
        print(f"  aviso: {w.category.__name__}: {str(w.message)[:200]}")


def print_readout(backend: Any) -> None:
    """Erro de leitura por qubit (resumo): é o dado que o metadado da coleta vai guardar."""
    sec("3. Erro de leitura por qubit (properties)")
    try:
        props = backend.properties()
        errors = [float(props.readout_error(q)) for q in range(backend.num_qubits)]
        print(f"  qubits lidos: {len(errors)}")
        print(f"  mín / mediana / máx: {min(errors):.5f} / {statistics.median(errors):.5f} / {max(errors):.5f}")
        print(f"  última atualização da calibração: {props.last_update_date}")
    except Exception as exc:  # noqa: BLE001
        fail("properties().readout_error", exc)


def print_full_warning(backend: Any) -> None:
    """Texto completo do aviso de obsolescência, que a primeira sonda cortou em 160 caracteres."""
    sec("4. Aviso do SamplerV2, texto completo")
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        try:
            from qiskit_ibm_runtime import SamplerV2
            SamplerV2(mode=backend)
        except Exception as exc:  # noqa: BLE001
            fail("SamplerV2(mode=backend)", exc)
    for w in caught:
        print(f"  {w.category.__name__}: {str(w.message)[:700]}")
    if not caught:
        print("  nenhum aviso")


def main() -> int:
    """Roda a sonda; sempre termina com código 0 (é só diagnóstico)."""
    parser = argparse.ArgumentParser(description="Complemento só de leitura do reconhecimento IBM.")
    parser.add_argument("--backend", default="ibm_kingston")
    parser.add_argument("--instance", default="open-instance")
    args = parser.parse_args()
    print("Reconhecimento IBM, parte b (só leitura): nenhum job será enviado.")
    service = connect(args.instance)
    if service is not None:
        print_usage_period(service)
        try:
            backend = service.backend(args.backend)
        except Exception as exc:  # noqa: BLE001
            fail("service.backend()", exc)
        else:
            print_config(backend)
            print_readout(backend)
            print_full_warning(backend)
    print("\nFim. Nada foi enviado e nenhum arquivo foi gravado.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
