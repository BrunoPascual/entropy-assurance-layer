"""Gráfico de viés por qubit: simulador com ruído vs previsão da calibração.

Uso (na raiz do projeto):
    py -3.12 -m scripts.plot_bias
    py -3.12 -m scripts.plot_bias --bits 2000000 --qubits 20

Compara, para cada qubit, a frequência de uns medida no `qpu_sim` (FakeKingston)
com a previsão feita só pelo erro de leitura da calibração. A fonte `os` entra
como controle. NÃO diz nada sobre a QPU real: essa comparação é o E1.
"""
from __future__ import annotations

import argparse
import io
from datetime import date
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # sem janela: só grava arquivo
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from eal.sources import noise  # noqa: E402
from eal.sources.os_source import OsSource  # noqa: E402
from eal.sources.qpu_sim import QpuSim  # noqa: E402

RESULTS_DIR = Path("data/results")


def bias_per_qubit(bits: np.ndarray, n_qubits: int) -> np.ndarray:
    """Frequência de uns por coluna (qubit), com bits em ordem shot a shot."""
    shots = bits.size // n_qubits
    return bits[: shots * n_qubits].reshape(shots, n_qubits).mean(axis=0)


def sampling_sd(shots: int) -> float:
    """Desvio-padrão da frequência de uns de uma moeda justa em `shots` lançamentos."""
    return float(np.sqrt(0.25 / shots))


def make_figure(freq: np.ndarray, expected: np.ndarray, control: np.ndarray,
                qubits: list[int], shots: int, title: str):
    """Barras de desvio em relação a 0,5, com a previsão e o controle `os`."""
    x = np.arange(len(qubits))
    ci = 1.96 * sampling_sd(shots)
    fig, ax = plt.subplots(figsize=(11, 5))
    ax.bar(x, freq - 0.5, bottom=0.5, color="#4c78a8", label="qpu_sim (medido)",
           yerr=ci, capsize=2, ecolor="#333333")
    ax.scatter(x, expected, marker="D", color="#e45756", zorder=3,
               label="previsto pela calibração (só leitura)")
    ax.scatter(x, control, marker="o", color="#888888", zorder=3, s=22,
               label="os (controle)")
    ax.axhline(0.5, color="black", linestyle="--", linewidth=1)
    ax.set_xticks(x, [str(q) for q in qubits])
    ax.set_xlabel("qubit físico")
    ax.set_ylabel("frequência de uns")
    ax.set_title(title)
    ax.legend(loc="upper right")
    ax.text(0.99, 0.02, "eixo y recortado; barras partem de 0,5; barra de erro = IC 95% de amostragem",
            transform=ax.transAxes, ha="right", fontsize=8, color="#555555")
    fig.tight_layout()
    return fig


def run(n_bits: int = 1_000_000, n_qubits: int = 20, seed: int = 1,
        backend_name: str = "FakeKingston", out_dir: Path = RESULTS_DIR) -> Path:
    """Gera os bits, calcula o viés e grava o PNG. Retorna o caminho do arquivo."""
    sim = QpuSim(n_qubits=n_qubits, seed=seed, noise_backend=backend_name)
    batch = sim.read(n_bits)
    qubits = batch.params["physical_qubits"]
    backend = noise.load_fake_backend(backend_name)
    freq = bias_per_qubit(batch.bits, n_qubits)
    expected = np.array([noise.expected_p1_readout_only(backend, q) for q in qubits])
    control = bias_per_qubit(OsSource().read(n_bits).bits, n_qubits)
    shots = batch.params["shots"]
    title = (f"Viés por qubit: simulador com ruído do {backend_name} "
             f"(calibração de {batch.params['calibration_date'][:10]}), {shots} shots/qubit")
    fig = make_figure(freq, expected, control, qubits, shots, title)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{date.today().isoformat()}_bias_por_qubit.png"
    buf = io.BytesIO()  # grava na memória e depois escreve o arquivo de uma vez
    fig.savefig(buf, format="png", dpi=150)
    plt.close(fig)
    path.write_bytes(buf.getvalue())
    return path


def main() -> None:
    """Ponto de entrada da linha de comando."""
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--bits", type=int, default=1_000_000)
    ap.add_argument("--qubits", type=int, default=20)
    ap.add_argument("--seed", type=int, default=1)
    args = ap.parse_args()
    print(f"Gráfico salvo em {run(args.bits, args.qubits, args.seed)}")


if __name__ == "__main__":
    main()
