import numpy as np
import pytest

from scripts import plot_bias


def test_bias_per_qubit_known_answer():
    # 3 shots x 2 qubits: coluna 0 = [1,1,0], coluna 1 = [0,0,0]
    bits = np.array([1, 0, 1, 0, 0, 0], dtype=np.uint8)
    assert plot_bias.bias_per_qubit(bits, 2).tolist() == pytest.approx([2 / 3, 0.0])


def test_bias_per_qubit_ignores_partial_shot():
    bits = np.array([1, 1, 1, 1, 1], dtype=np.uint8)  # 2 shots de 2 + 1 bit sobrando
    assert plot_bias.bias_per_qubit(bits, 2).tolist() == [1.0, 1.0]


def test_sampling_sd():
    assert plot_bias.sampling_sd(10_000) == pytest.approx(0.005)


def test_run_creates_png(tmp_path):
    path = plot_bias.run(n_bits=20_000, n_qubits=4, seed=2, out_dir=tmp_path)
    assert path.exists() and path.suffix == ".png"
    assert path.stat().st_size > 5_000
    assert path.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


def test_gate_chart_path_uses_today_and_bias_name():
    from scripts.gate_dia2 import bias_chart_path
    p = bias_chart_path("2026-10-28")
    assert p.name == "2026-10-28_bias_por_qubit.png"
    assert p.parent.as_posix() == "data/results"
