"""Dia 6, passo 2: do resultado do SamplerV2 aos bits do lote e aos params (sem rede).

Só usa o Qiskit de núcleo (circuitos e ``BitArray``); nada aqui fala com a IBM. Fixa os
contratos que o E1 usa para comparar a QPU real com a ``qpu_sim``:

- coluna ``i`` de cada shot = clbit ``i`` = ``physical_qubits[i]`` (a mesma frase de
  ``bit_order`` da ``qpu_sim``). O ``BitArray`` é lido com ``order="little"``, o único que
  entrega a coluna ``i`` igual ao clbit ``i`` (conferido com circuitos de resposta conhecida,
  inclusive além de 8 bits); a ordem padrão (``"big"``) sairia espelhada;
- o mapa clbit -> qubit físico é lido do circuito JÁ transpilado (as instruções ``measure``),
  e não do layout pedido;
- o circuito enviado só tem portas de um qubit. Sem isso os bits não seriam independentes por
  construção e o estudo passaria a responder outra pergunta.

Limite: a conversão foi testada com ``BitArray`` produzidos pelo ``StatevectorSampler`` do
Qiskit; o ``BitArray`` que a IBM devolve vem da mesma classe, mas isso só se confirma com um
job real (a calibração do Dia 6).
"""
from __future__ import annotations

import math
import re
from collections.abc import Sequence
from typing import Any

import numpy as np
from qiskit import QuantumCircuit
from qiskit.primitives import BitArray

BIT_ORDER = "shot-major; posicao i do shot = physical_qubits[i]"
CLASSICAL_REGISTER = "c"
CIRCUIT_NAME = "hadamard_all_measure"
_TEXT_RE = re.compile(r"[A-Za-z0-9._-]{1,64}")
_SHORT_MAX = 64


def _is_int(value: Any) -> bool:
    """Inteiro de verdade (bool não vale)."""
    return isinstance(value, int) and not isinstance(value, bool)


def _check_register(isa: QuantumCircuit, n_qubits: int) -> None:
    """O circuito precisa ter um único registrador clássico ``c`` com ``n_qubits`` bits."""
    registers = [(reg.name, reg.size) for reg in isa.cregs]
    if registers != [(CLASSICAL_REGISTER, n_qubits)]:
        raise ValueError("o circuito precisa de um único registrador clássico 'c' com n bits")


def _check_single_qubit_only(isa: QuantumCircuit) -> None:
    """Nenhuma instrução (fora ``barrier``) pode envolver mais de um qubit."""
    for inst in isa.data:
        if inst.operation.name != "barrier" and len(inst.qubits) > 1:
            raise ValueError("o circuito tem instrução com mais de um qubit")


def physical_qubits_from_isa(isa: QuantumCircuit, n_qubits: int) -> list[int]:
    """Qubit físico de cada clbit, lido das ``measure`` do circuito transpilado.

    Devolve ``physical[i]`` = qubit físico medido no clbit ``i``. Recusa circuito com
    registrador diferente de ``c`` com ``n_qubits`` bits, com porta de mais de um qubit, com
    clbit medido duas vezes ou não medido, ou com o mesmo qubit físico em dois clbits.
    """
    if not _is_int(n_qubits) or n_qubits < 1:
        raise ValueError("n_qubits deve ser inteiro positivo")
    _check_register(isa, n_qubits)
    _check_single_qubit_only(isa)
    mapping: dict[int, int] = {}
    for inst in isa.data:
        if inst.operation.name != "measure":
            continue
        clbit = isa.find_bit(inst.clbits[0]).index
        if clbit in mapping:
            raise ValueError("clbit medido mais de uma vez")
        mapping[clbit] = isa.find_bit(inst.qubits[0]).index
    if sorted(mapping) != list(range(n_qubits)):
        raise ValueError("os clbits medidos não são 0..n-1")
    physical = [mapping[i] for i in range(n_qubits)]
    if len(set(physical)) != n_qubits:
        raise ValueError("o mesmo qubit físico alimenta dois clbits")
    return physical


def bitarray_to_bits(bitarray: Any, n_qubits: int, shots: int) -> np.ndarray:
    """Bits do lote: uint8, uma dimensão, shot a shot; posição ``i`` do shot = clbit ``i``."""
    if not _is_int(n_qubits) or n_qubits < 1 or not _is_int(shots) or shots < 1:
        raise ValueError("n_qubits e shots devem ser inteiros positivos")
    if not isinstance(bitarray, BitArray):
        raise ValueError("o resultado não é um BitArray")
    if bitarray.shape != ():
        raise ValueError("o resultado tem varredura de parâmetros (shape diferente de ())")
    if bitarray.num_bits != n_qubits:
        raise ValueError("o número de bits do resultado não bate com n_qubits")
    if bitarray.num_shots != shots:
        raise ValueError("o número de shots do resultado não bate com o pedido")
    matrix = bitarray.to_bool_array(order="little")
    if matrix.shape != (shots, n_qubits):
        raise ValueError("forma inesperada da matriz de bits")
    return np.ascontiguousarray(matrix.astype(np.uint8).reshape(-1))


def _check_text(name: str, value: Any) -> str:
    """Texto curto sem espaço nem barra (o mesmo padrão dos params do recibo)."""
    if not isinstance(value, str) or not _TEXT_RE.fullmatch(value):
        raise ValueError(f"{name} inválido")
    return value


def _check_short(name: str, value: Any) -> str:
    """Texto curto imprimível, sem quebra de linha."""
    if (not isinstance(value, str) or not value or len(value) > _SHORT_MAX
            or not value.isprintable()):
        raise ValueError(f"{name} inválido")
    return value


def _check_float(name: str, value: Any, low: float, high: float) -> float:
    """Número real finito entre ``low`` e ``high`` (inclusive); bool não vale."""
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or not math.isfinite(value) or not low <= value <= high):
        raise ValueError(f"{name} inválido")
    return float(value)


def _check_physical(physical_qubits: Sequence[int]) -> list[int]:
    """Lista não vazia de índices físicos inteiros, não negativos e distintos."""
    physical = list(physical_qubits)
    if (not physical or any(not _is_int(q) or q < 0 for q in physical)
            or len(set(physical)) != len(physical)):
        raise ValueError("physical_qubits inválido")
    return [int(q) for q in physical]


def _check_snapshot(readout_error: Sequence[float] | None, calibration_date: str | None,
                    n_qubits: int) -> tuple[list[float] | None, str | None]:
    """Retrato da calibração: os dois campos juntos ou nenhum (fica ``None`` no registro)."""
    if readout_error is None and calibration_date is None:
        return None, None
    if readout_error is None or calibration_date is None:
        raise ValueError("readout_error e calibration_date vêm juntos ou nenhum")
    errors = [_check_float("readout_error", e, 0.0, 1.0) for e in readout_error]
    if len(errors) != n_qubits:
        raise ValueError("readout_error precisa ter um valor por qubit")
    return errors, _check_short("calibration_date", calibration_date)


def _check_versions(sdk_versions: dict[str, str]) -> dict[str, str]:
    """Versões dos pacotes: nomes e valores curtos; nada além disso entra no registro."""
    if not isinstance(sdk_versions, dict) or not sdk_versions:
        raise ValueError("sdk_versions inválido")
    return {_check_text("nome de pacote", k): _check_short("versão", v)
            for k, v in sorted(sdk_versions.items())}


def build_ibm_params(*, backend_name: str, job_id: str, shots: int,
                     physical_qubits: Sequence[int],
                     readout_error: Sequence[float] | None,
                     calibration_date: str | None, rep_delay_seconds: float,
                     max_execution_time_seconds: float, primitive: str,
                     sdk_versions: dict[str, str]) -> dict[str, Any]:
    """``params`` do ``RawBatch`` de um job da IBM.

    Traz as quatro chaves do G6 (``backend``, ``job_id``, ``shots``, ``qubits``) e os nomes
    da ``qpu_sim`` (``n_qubits``, ``physical_qubits``, ``bit_order``, ``discarded_bits``,
    ``calibration_date``). Um lote da IBM nunca descarta bits: cada shot entra inteiro.
    ``readout_error_by_position[i]`` é o erro de leitura do qubit ``physical_qubits[i]``.
    """
    if not _is_int(shots) or shots < 1:
        raise ValueError("shots deve ser inteiro positivo")
    physical = _check_physical(physical_qubits)
    errors, cal_date = _check_snapshot(readout_error, calibration_date, len(physical))
    max_time = _check_float("max_execution_time_seconds", max_execution_time_seconds,
                            0.0, 1e7)
    if max_time <= 0:
        raise ValueError("max_execution_time_seconds inválido")
    return {
        "backend": _check_text("backend_name", backend_name),
        "job_id": _check_text("job_id", job_id),
        "shots": shots,
        "qubits": len(physical),
        "n_qubits": len(physical),
        "primitive": _check_text("primitive", primitive),
        "circuit": CIRCUIT_NAME,
        "physical_qubits": physical,
        "bit_order": BIT_ORDER,
        "discarded_bits": 0,
        "calibration_date": cal_date,
        "readout_error_by_position": errors,
        "rep_delay_seconds": _check_float("rep_delay_seconds", rep_delay_seconds, 0.0, 1.0),
        "max_execution_time_seconds": max_time,
        "sdk": _check_versions(sdk_versions),
    }
