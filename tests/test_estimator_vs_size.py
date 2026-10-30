"""Testes da medição do estimador x tamanho do lote (Dia 4, etapa 3, passo 4).

Usa uma fonte falsa determinística (SHAKE256) e o estimador real do projeto. Os
asserts são estruturais ou calculados à mão: nenhum depende de um valor de H
que só a medição na máquina pode dizer.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from eal.extract.blocks import block_output_bits
from eal.health.min_entropy import entropy_health_ok
from scripts import estimator_vs_size as ev


@dataclass
class FakeBatch:
    bits: np.ndarray
    batch_hash: str


class FakeSource:
    """Fonte determinística: cada leitura deriva de um contador, sem aleatoriedade."""

    source_id = "fake"

    def __init__(self) -> None:
        self.calls = 0

    def read(self, n_bits: int) -> FakeBatch:
        self.calls += 1
        raw = hashlib.shake_256(f"fake-{self.calls}-{n_bits}".encode()).digest((n_bits + 7) // 8)
        bits = np.unpackbits(np.frombuffer(raw, dtype=np.uint8))[:n_bits]
        return FakeBatch(bits, hashlib.sha3_256(np.packbits(bits).tobytes()).hexdigest())


class ExplodingSource:
    def read(self, n_bits: int) -> Any:
        raise RuntimeError("falha de leitura")


def row(size: int, h_bit: float, h_byte: float, out: int = 1000, yld: float = 0.9) -> dict[str, Any]:
    h_est = min(h_bit, h_byte)
    return {"size_bits": size, "reading": 1, "h_bit": h_bit, "h_byte": h_byte, "h_estimated": h_est,
            "limited_by": ev.limited_by(h_bit, h_byte), "h_health_ok": h_est >= 0.9,
            "output_bits": out, "total_yield": yld}


# ----------------------------------------------------------- referência


def test_h_bit_reference_known_value() -> None:
    # p_u = 0,5 + 2,576 * 0,5 / sqrt(999999) = 0,501288...; H = -log2(p_u) = 0,99629
    assert ev.h_bit_reference(1_000_000) == pytest.approx(0.99629, abs=2e-5)


def test_h_bit_reference_grows_with_size() -> None:
    values = [ev.h_bit_reference(n) for n in (2**16, 2**18, 2**20, 2**22)]
    assert all(a < b for a, b in zip(values, values[1:], strict=False))
    assert all(v < 1.0 for v in values)


def test_h_bit_reference_is_zero_when_bound_reaches_one() -> None:
    assert ev.h_bit_reference(2) == 0.0  # 0,5 + 1,288 / 1 > 1
    assert ev.h_bit_reference(7) == 0.0  # 0,5 + 1,288 / sqrt(6) = 1,026
    assert ev.h_bit_reference(9) > 0.0  # 0,5 + 1,288 / sqrt(8) = 0,955


def test_h_bit_reference_refuses_tiny_input() -> None:
    with pytest.raises(ValueError):
        ev.h_bit_reference(1)


def test_limited_by() -> None:
    assert ev.limited_by(0.99, 0.95) == "byte"
    assert ev.limited_by(0.95, 0.99) == "bit"
    assert ev.limited_by(0.97, 0.97) == "bit"  # empate: "bit", como o estimador


# ------------------------------------------------------- medição de lote


@pytest.mark.parametrize("size", [2**16, 1_000_000])
def test_measure_batch_structure(size: int) -> None:
    r = ev.measure_batch(FakeSource().read(size), reading=3)
    assert r["size_bits"] == size and r["reading"] == 3
    assert r["h_estimated"] == min(r["h_bit"], r["h_byte"])
    assert r["limited_by"] == ("byte" if r["h_byte"] < r["h_bit"] else "bit")
    assert r["h_used"] == min(1.0, r["h_estimated"])
    assert r["m"] == block_output_bits(r["h_used"])
    assert r["n_blocks"] == size // 2048
    assert r["output_bits"] == r["n_blocks"] * r["m"]
    assert r["total_yield"] == pytest.approx(r["output_bits"] / size)
    assert r["h_health_ok"] is entropy_health_ok(r["h_estimated"])
    assert len(r["batch_hash"]) == 64


def test_stats_conclusive_boundary() -> None:
    assert ev.measure_batch(FakeSource().read(1_000_000), 1)["stats_conclusive"] is True
    assert ev.measure_batch(FakeSource().read(999_999), 1)["stats_conclusive"] is False


def test_inconsistent_estimator_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    class Bad:
        class _H:
            h = 0.9

        bit, byte, h_estimated = _H(), _H(), 0.5  # h_estimated != min(0,9; 0,9)

    monkeypatch.setattr(ev, "estimate_min_entropy", lambda bits: Bad())
    with pytest.raises(ValueError, match="inconsistente"):
        ev.measure_batch(FakeSource().read(4096), 1)


def test_measure_counts_and_order() -> None:
    src = FakeSource()
    rows = ev.measure(src, sizes=(4096, 8192), reads=3)
    assert [(r["size_bits"], r["reading"]) for r in rows] == [(4096, 1), (4096, 2), (4096, 3),
                                                              (8192, 1), (8192, 2), (8192, 3)]
    assert src.calls == 6
    assert len({r["batch_hash"] for r in rows}) == 6  # nenhuma leitura repetida


@pytest.mark.parametrize("sizes", [(), (15,), (4096, True), (4096.0,), ("4096",)])
def test_measure_refuses_bad_sizes(sizes: tuple[Any, ...]) -> None:
    with pytest.raises(ValueError, match="sizes"):
        ev.measure(FakeSource(), sizes=sizes)


def test_measure_refuses_zero_reads() -> None:
    with pytest.raises(ValueError, match="reads"):
        ev.measure(FakeSource(), sizes=(4096,), reads=0)


# -------------------------------------------------------------- resumo


def test_summarize_hand_computed() -> None:
    rows = [
        row(100, 0.99, 0.90, out=1000, yld=0.8),   # h_est 0,90 (byte); passa o limiar (>= 0,9)
        row(100, 0.95, 0.99, out=2000, yld=0.9),   # h_est 0,95 (bit)
        row(200, 0.99, 0.80, out=500, yld=0.5),    # h_est 0,80 (byte); reprovado
    ]
    s100, s200 = ev.summarize(rows)
    assert (s100["size_bits"], s100["n_reads"]) == (100, 2)
    assert s100["h_est_mean"] == pytest.approx(0.925)
    assert s100["h_est_sd"] == pytest.approx(0.0353553391)
    assert (s100["h_est_min"], s100["h_est_max"]) == (0.90, 0.95)
    assert s100["h_bit_mean"] == pytest.approx(0.97) and s100["h_byte_mean"] == pytest.approx(0.945)
    assert s100["frac_limited_by_byte"] == 0.5 and s100["frac_h_health_ok"] == 1.0
    assert s100["mean_output_bits"] == 1500 and s100["mean_total_yield"] == pytest.approx(0.85)
    assert s100["h_bit_reference"] == pytest.approx(ev.h_bit_reference(100))
    assert s200["h_est_sd"] is None  # uma leitura só
    assert s200["frac_limited_by_byte"] == 1.0 and s200["frac_h_health_ok"] == 0.0


def test_summarize_keeps_size_order_and_flags_stats() -> None:
    rows = [row(1_000_000, 0.99, 0.96), row(65_536, 0.98, 0.87), row(1_000_000, 0.99, 0.96)]
    out = ev.summarize(rows)
    assert [s["size_bits"] for s in out] == [1_000_000, 65_536]
    assert out[0]["stats_conclusive"] is True and out[1]["stats_conclusive"] is False
    assert out[0]["n_reads"] == 2


# ------------------------------------------------------ execução e arquivos


def test_run_end_to_end(tmp_path: Path) -> None:
    result = ev.run(FakeSource(), "fake", sizes=(4096, 8192), reads=2, out_dir=tmp_path)
    assert set(result["outputs"]) == {"readings", "summary"}
    for info in result["outputs"].values():
        assert hashlib.sha3_256(Path(info["path"]).read_bytes()).hexdigest() == info["sha3_256"]
    saved = json.loads(Path(result["meta_path"]).read_text(encoding="utf-8"))
    assert saved["source_id"] == "fake" and saved["params"]["sizes"] == [4096, 8192]
    assert "summary" not in saved  # o resumo em memória não vai duplicado no meta
    assert len(result["summary"]) == 2
    assert len(list(tmp_path.glob("*.csv"))) == 2 and len(list(tmp_path.glob("*.meta.json"))) == 1


def test_csv_has_no_bits_only_estimates_and_hashes(tmp_path: Path) -> None:
    result = ev.run(FakeSource(), "fake", sizes=(4096,), reads=1, out_dir=tmp_path)
    header = Path(result["outputs"]["readings"]["path"]).read_text(encoding="utf-8").splitlines()[0]
    assert "bits" not in header.replace("size_bits", "").replace("output_bits", "")
    assert "batch_hash" in header


def test_two_runs_do_not_overwrite(tmp_path: Path) -> None:
    a = ev.run(FakeSource(), "fake", sizes=(4096,), reads=1, out_dir=tmp_path)
    b = ev.run(FakeSource(), "fake", sizes=(4096,), reads=1, out_dir=tmp_path)
    assert a["meta_path"] != b["meta_path"]
    assert len(list(tmp_path.glob("*.csv"))) == 4


def test_failed_measurement_writes_nothing(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError):
        ev.run(ExplodingSource(), "x", sizes=(4096,), reads=1, out_dir=tmp_path)  # type: ignore[arg-type]
    assert not list(tmp_path.iterdir())


def test_unique_tag_never_collides(tmp_path: Path) -> None:
    assert ev.unique_tag(tmp_path, "S") == "S"
    for name in ev.output_names("S").values():
        (tmp_path / name).write_text("x")
        assert ev.unique_tag(tmp_path, "S") == "S_2"
    (tmp_path / ev.output_names("S_2")["summary"]).write_text("x")
    assert ev.unique_tag(tmp_path, "S") == "S_3"


def test_write_csv_refuses_existing_file(tmp_path: Path) -> None:
    path = tmp_path / "existente.csv"
    path.write_text("original", encoding="utf-8")
    with pytest.raises(FileExistsError):
        ev._write_csv(path, [{"a": 1}])
    assert path.read_text(encoding="utf-8") == "original"
