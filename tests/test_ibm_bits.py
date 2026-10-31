"""Testes da conversão do resultado do SamplerV2 em bits e dos params do lote da IBM (Dia 6)."""
from __future__ import annotations

import json
import math

import numpy as np
import pytest
from qiskit import ClassicalRegister, QuantumCircuit, QuantumRegister
from qiskit.primitives import BitArray, StatevectorSampler
from qiskit.providers.fake_provider import GenericBackendV2
from qiskit.transpiler.preset_passmanagers import generate_preset_pass_manager

from eal.sources.ibm_bits import (
    BIT_ORDER, CIRCUIT_NAME, bitarray_to_bits, build_ibm_params, physical_qubits_from_isa,
)


def sampler_bits(circuit: QuantumCircuit, shots: int, seed: int = 1) -> BitArray:
    """BitArray de um circuito, pelo StatevectorSampler (mesma classe que a IBM devolve)."""
    return StatevectorSampler(seed=seed).run([circuit], shots=shots).result()[0].data.c


def hadamard(n: int) -> QuantumCircuit:
    qc = QuantumCircuit(n, n)
    qc.h(range(n))
    qc.measure(range(n), range(n))
    return qc


def isa_for(circuit: QuantumCircuit, layout: list[int], backend_qubits: int = 12):
    backend = GenericBackendV2(num_qubits=backend_qubits, seed=1)
    pm = generate_preset_pass_manager(backend=backend, optimization_level=0,
                                      initial_layout=layout)
    return pm.run(circuit)


def good_params(**changes):
    base = dict(
        backend_name="ibm_kingston", job_id="dbgiga4dgr2s73crj1h0", shots=4096,
        physical_qubits=[3, 5, 7], readout_error=[0.01, 0.02, 0.5],
        calibration_date="2026-10-31 19:21:17-03:00", rep_delay_seconds=0.00025,
        max_execution_time_seconds=20.0, primitive="SamplerV2",
        sdk_versions={"qiskit": "2.6.1", "qiskit_ibm_runtime": "0.51.0"})
    base.update(changes)
    return base


# ------------------------------------------------------- ordem dos bits (o ponto crítico)

def test_coluna_i_e_o_clbit_i_alem_da_fronteira_de_8_bits():
    n = 12
    qc = QuantumCircuit(n, n)
    for q in (0, 2, 9, 11):
        qc.x(q)
    qc.measure(range(n), range(n))
    bits = bitarray_to_bits(sampler_bits(qc, 5), n, 5)
    expected = np.array([1, 0, 1, 0, 0, 0, 0, 0, 0, 1, 0, 1], dtype=np.uint8)
    assert np.array_equal(bits.reshape(5, n), np.tile(expected, (5, 1)))


def test_a_ordem_e_a_do_clbit_e_nao_a_do_qubit():
    qc = QuantumCircuit(5, 5)
    qc.x(0)
    qc.measure([0, 1, 2, 3, 4], [3, 0, 1, 2, 4])  # o qubit 0 e medido no clbit 3
    bits = bitarray_to_bits(sampler_bits(qc, 3), 5, 3).reshape(3, 5)
    assert (bits == np.array([0, 0, 0, 1, 0])).all()


def test_canario_a_ordem_big_do_qiskit_sairia_espelhada():
    """Se o Qiskit mudar a convenção de 'big', este teste avisa."""
    qc = QuantumCircuit(5, 5)
    qc.x(0)
    qc.x(2)
    qc.measure(range(5), range(5))
    ba = sampler_bits(qc, 1)
    assert ba.to_bool_array(order="little")[0].astype(int).tolist() == [1, 0, 1, 0, 0]
    assert ba.to_bool_array(order="big")[0].astype(int).tolist() == [0, 0, 1, 0, 1]
    assert ba.get_bitstrings() == ["00101"]


def test_o_achatamento_e_shot_a_shot():
    rows = np.array([[0, 0, 1], [1, 0, 0]], dtype=bool)  # coluna i = clbit i
    ba = BitArray.from_bool_array(rows, order="little")
    bits = bitarray_to_bits(ba, 3, 2)
    assert bits.tolist() == [0, 0, 1, 1, 0, 0]


def test_forma_e_tipo_dos_bits():
    bits = bitarray_to_bits(sampler_bits(hadamard(4), 50), 4, 50)
    assert bits.dtype == np.uint8 and bits.ndim == 1 and bits.size == 200
    assert bits.flags["C_CONTIGUOUS"] and set(np.unique(bits)) <= {0, 1}


def test_hadamard_da_proporcao_proxima_de_meio_por_coluna():
    bits = bitarray_to_bits(sampler_bits(hadamard(4), 4000, seed=7), 4, 4000)
    means = bits.reshape(4000, 4).mean(axis=0)
    assert ((means > 0.45) & (means < 0.55)).all()


# ------------------------------------------------------- recusas da conversão

@pytest.mark.parametrize("bad", [None, [0, 1], np.zeros((2, 3), dtype=np.uint8), "00"])
def test_resultado_que_nao_e_bitarray_e_recusado(bad):
    with pytest.raises(ValueError, match="BitArray"):
        bitarray_to_bits(bad, 3, 2)


def test_num_bits_e_shots_precisam_bater():
    ba = sampler_bits(hadamard(4), 10)
    with pytest.raises(ValueError, match="número de bits"):
        bitarray_to_bits(ba, 5, 10)
    with pytest.raises(ValueError, match="shots"):
        bitarray_to_bits(ba, 4, 11)


def test_varredura_de_parametros_e_recusada():
    ba = BitArray.from_bool_array(np.zeros((2, 5, 3), dtype=bool), order="little")
    assert ba.shape == (2,)
    with pytest.raises(ValueError, match="varredura"):
        bitarray_to_bits(ba, 3, 5)


@pytest.mark.parametrize("n,shots", [(0, 5), (4, 0), (True, 5), (4, True), (4.0, 5), (-1, 5)])
def test_n_e_shots_invalidos_sao_recusados(n, shots):
    with pytest.raises(ValueError):
        bitarray_to_bits(sampler_bits(hadamard(4), 5), n, shots)


# ------------------------------------------------------- mapa clbit -> qubit físico

@pytest.mark.parametrize("layout", [
    [0, 1, 2, 3, 4, 5],
    [3, 5, 7, 1, 0, 2],
    [11, 10, 9, 8, 7, 6],
])
def test_mapa_vem_do_circuito_transpilado(layout):
    isa = isa_for(hadamard(6), layout)
    assert physical_qubits_from_isa(isa, 6) == layout


def test_barrier_e_aceita():
    qc = QuantumCircuit(4, 4)
    qc.h(range(4))
    qc.barrier()
    qc.measure(range(4), range(4))
    assert physical_qubits_from_isa(isa_for(qc, [2, 3, 0, 1]), 4) == [2, 3, 0, 1]


def test_porta_de_dois_qubits_e_recusada():
    qc = QuantumCircuit(2, 2)
    qc.h(0)
    qc.cx(0, 1)
    qc.measure([0, 1], [0, 1])
    with pytest.raises(ValueError, match="mais de um qubit"):
        physical_qubits_from_isa(qc, 2)


def test_clbit_medido_duas_vezes_e_recusado():
    qc = QuantumCircuit(2, 2)
    qc.measure(0, 0)
    qc.measure(1, 0)
    with pytest.raises(ValueError, match="mais de uma vez"):
        physical_qubits_from_isa(qc, 2)


def test_clbit_nao_medido_e_recusado():
    qc = QuantumCircuit(3, 3)
    qc.measure([0, 1], [0, 1])
    with pytest.raises(ValueError, match="0..n-1"):
        physical_qubits_from_isa(qc, 3)


def test_mesmo_qubit_fisico_em_dois_clbits_e_recusado():
    qc = QuantumCircuit(2, 2)
    qc.measure(0, 0)
    qc.measure(0, 1)
    with pytest.raises(ValueError, match="mesmo qubit físico"):
        physical_qubits_from_isa(qc, 2)


def test_registrador_diferente_de_c_e_recusado():
    qc = QuantumCircuit(QuantumRegister(2, "q"), ClassicalRegister(2, "meas"))
    qc.measure([0, 1], [0, 1])
    with pytest.raises(ValueError, match="registrador"):
        physical_qubits_from_isa(qc, 2)


def test_dois_registradores_classicos_sao_recusados():
    qc = QuantumCircuit(QuantumRegister(2, "q"), ClassicalRegister(1, "c"),
                        ClassicalRegister(1, "d"))
    qc.measure([0, 1], [0, 1])
    with pytest.raises(ValueError, match="registrador"):
        physical_qubits_from_isa(qc, 2)


def test_tamanho_do_registrador_precisa_bater_com_n():
    with pytest.raises(ValueError, match="registrador"):
        physical_qubits_from_isa(hadamard(6), 5)


@pytest.mark.parametrize("n", [0, -1, True, 2.0])
def test_n_qubits_invalido_no_mapa(n):
    with pytest.raises(ValueError):
        physical_qubits_from_isa(hadamard(2), n)


# ------------------------------------------------------- params

def test_params_completos_e_coerentes():
    p = build_ibm_params(**good_params())
    assert p["backend"] == "ibm_kingston" and p["job_id"] == "dbgiga4dgr2s73crj1h0"
    assert p["shots"] == 4096 and p["qubits"] == 3 and p["n_qubits"] == 3
    assert p["physical_qubits"] == [3, 5, 7]
    assert p["readout_error_by_position"] == [0.01, 0.02, 0.5]
    assert p["discarded_bits"] == 0 and p["circuit"] == CIRCUIT_NAME
    assert p["primitive"] == "SamplerV2"
    assert p["sdk"] == {"qiskit": "2.6.1", "qiskit_ibm_runtime": "0.51.0"}


def test_bit_order_e_o_mesmo_texto_da_qpu_sim():
    assert BIT_ORDER == "shot-major; posicao i do shot = physical_qubits[i]"
    assert build_ibm_params(**good_params())["bit_order"] == BIT_ORDER


def test_params_vao_e_voltam_por_json():
    p = build_ibm_params(**good_params())
    assert json.loads(json.dumps(p)) == p


def test_params_nao_trazem_chaves_de_segredo():
    p = build_ibm_params(**good_params())
    blob = json.dumps(p).lower()
    for word in ("token", "secret", "password", "crn", "instance"):
        assert word not in blob


def test_params_sem_retrato_de_calibracao():
    p = build_ibm_params(**good_params(readout_error=None, calibration_date=None))
    assert p["readout_error_by_position"] is None and p["calibration_date"] is None


def test_retrato_de_calibracao_vem_junto_ou_nao_vem():
    with pytest.raises(ValueError, match="juntos"):
        build_ibm_params(**good_params(readout_error=None))
    with pytest.raises(ValueError, match="juntos"):
        build_ibm_params(**good_params(calibration_date=None))


def test_float_do_numpy_e_aceito_e_int_do_numpy_e_recusado():
    p = build_ibm_params(**good_params(readout_error=list(np.array([0.1, 0.2, 0.3]))))
    assert json.loads(json.dumps(p)) == p          # np.float64 e subclasse de float
    with pytest.raises(ValueError):                # indice fisico vem de find_bit: int de verdade
        build_ibm_params(**good_params(physical_qubits=[np.int64(3), 5, 7]))


@pytest.mark.parametrize("changes", [
    {"backend_name": "ibm kingston"}, {"backend_name": ""}, {"backend_name": "a/b"},
    {"backend_name": 5}, {"job_id": "a b"}, {"job_id": "x" * 65}, {"job_id": None},
    {"primitive": "Sampler V2"}, {"shots": 0}, {"shots": -1}, {"shots": True},
    {"shots": 1.5}, {"physical_qubits": []}, {"physical_qubits": [1, 1, 7]},
    {"physical_qubits": [-1, 2, 3]}, {"physical_qubits": [True, 2, 3]},
    {"physical_qubits": [1.5, 2, 3]},
    {"readout_error": [0.1, 0.2]}, {"readout_error": [0.1, 0.2, 1.5]},
    {"readout_error": [0.1, 0.2, math.nan]}, {"readout_error": [0.1, 0.2, -0.1]},
    {"readout_error": [0.1, 0.2, True]},
    {"calibration_date": ""}, {"calibration_date": "a\nb"}, {"calibration_date": "x" * 65},
    {"rep_delay_seconds": -1}, {"rep_delay_seconds": 2}, {"rep_delay_seconds": math.nan},
    {"rep_delay_seconds": True},
    {"max_execution_time_seconds": 0}, {"max_execution_time_seconds": -5},
    {"max_execution_time_seconds": math.inf}, {"max_execution_time_seconds": True},
    {"sdk_versions": {}}, {"sdk_versions": None}, {"sdk_versions": {"a b": "1"}},
    {"sdk_versions": {"qiskit": "x" * 65}}, {"sdk_versions": {"qiskit": "1\n2"}},
    {"sdk_versions": {"qiskit": 2}},
])
def test_params_invalidos_sao_recusados(changes):
    with pytest.raises(ValueError):
        build_ibm_params(**good_params(**changes))


def test_valores_nos_limites_sao_aceitos():
    build_ibm_params(**good_params(rep_delay_seconds=0, readout_error=[0.0, 1.0, 0.5],
                                   max_execution_time_seconds=1e-3, shots=1))
    build_ibm_params(**good_params(rep_delay_seconds=1))


# ------------------------------------------------------- integração com o projeto

def test_params_sao_aceitos_pelo_g6_do_recibo():
    builder = pytest.importorskip("eal.receipt.builder")
    clean = builder.clean_batch_params(build_ibm_params(**good_params()))
    assert clean == {"backend": "ibm_kingston", "job_id": "dbgiga4dgr2s73crj1h0",
                     "shots": 4096, "qubits": 3}


def test_lote_da_ibm_vai_e_volta_pelo_storage(tmp_path):
    base = pytest.importorskip("eal.sources.base")
    storage = pytest.importorskip("eal.storage")
    bits = bitarray_to_bits(sampler_bits(hadamard(3), 4), 3, 4)
    params = build_ibm_params(**good_params(shots=4))
    batch = base.RawBatch(source_id="ibm_kingston", source_type="qpu_ibm",
                          source_version="0.1.0", is_local=False, is_simulated=False,
                          bits=bits, params=params)
    path = storage.save_batch(batch, "cal", raw_dir=tmp_path)
    loaded = storage.load_batch(path)
    assert np.array_equal(loaded.bits, bits) and loaded.params == params
    assert loaded.source_type == "qpu_ibm" and loaded.is_local is False
