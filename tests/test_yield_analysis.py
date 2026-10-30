"""Testes do script de rendimento (Dia 4, etapa 3, passos 2 e 3).

O CSV de entrada é montado com o cabeçalho real do compare_extractors e valores
calculados à mão (ver comentários). Nenhum bit é lido ou gravado.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
from pathlib import Path

import pytest

from scripts import yield_analysis as ya

HEADER = [
    "label", "source_id", "reading", "extractor", "guarantee", "n_input_bits",
    "h_estimated_input", "h_used", "n", "m", "n_blocks", "discarded_bits",
    "n_output_bits", "epsilon_total_log2", "seconds", "frac_ones_out",
    "h_estimated_out", "monobit_p_out", "block_p_out", "runs_p_out",
    "seed_hash", "input_batch_hash",
]

# H = 0,954, 1M bits: k = floor(1953,792) = 1953; m = 1825; 488 blocos; resto 576; saída 890600
GOOD = {
    "n_input_bits": "1000000", "h_estimated_input": "0.954", "h_used": "0.954", "n": "2048",
    "m": "1825", "n_blocks": "488", "discarded_bits": "576", "n_output_bits": "890600",
    "epsilon_total_log2": repr(-64 + math.log2(488)),
}
# H = 0,05: k = 102 < 128, m = 0, lote inteiro descartado
LOW = {
    "n_input_bits": "1000000", "h_estimated_input": "0.05", "h_used": "0.05", "n": "2048",
    "m": "0", "n_blocks": "0", "discarded_bits": "1000000", "n_output_bits": "0",
    "epsilon_total_log2": "",
}


def make_row(label: str, reading: int, extractor: str, values: dict[str, str]) -> dict[str, str]:
    row = dict.fromkeys(HEADER, "")
    row.update(values)
    row.update(label=label, source_id=label, reading=str(reading), extractor=extractor,
               guarantee="x", seconds="0.1")
    return row


def pair(label: str, reading: int, values: dict[str, str]) -> list[dict[str, str]]:
    return [make_row(label, reading, "toeplitz", values), make_row(label, reading, "sha3", values)]


def write_source(directory: Path, rows: list[dict[str, str]], *, meta_hash: str | None = None,
                 name: str = "dia4_extract_test") -> Path:
    csv_path = directory / f"{name}.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=HEADER)
        w.writeheader()
        w.writerows(rows)
    digest = meta_hash or hashlib.sha3_256(csv_path.read_bytes()).hexdigest()
    csv_path.with_suffix(".meta.json").write_text(json.dumps({"csv_sha3_256": digest}), encoding="utf-8")
    return csv_path


@pytest.fixture
def good_rows() -> list[dict[str, str]]:
    return pair("os", 1, GOOD) + pair("os", 2, GOOD) + pair("faulty_low", 1, LOW)


# ------------------------------------------------------------ leitura segura


def test_reads_when_hash_matches(tmp_path: Path, good_rows: list[dict[str, str]]) -> None:
    assert len(ya.read_verified_csv(write_source(tmp_path, good_rows))) == 6


def test_tampered_csv_is_refused(tmp_path: Path, good_rows: list[dict[str, str]]) -> None:
    path = write_source(tmp_path, good_rows)
    path.write_bytes(path.read_bytes().replace(b"890600", b"890601", 1))
    with pytest.raises(ValueError, match="não confere"):
        ya.read_verified_csv(path)


def test_missing_meta_is_refused(tmp_path: Path, good_rows: list[dict[str, str]]) -> None:
    path = write_source(tmp_path, good_rows)
    path.with_suffix(".meta.json").unlink()
    with pytest.raises(ValueError, match="não consegui ler"):
        ya.read_verified_csv(path)


def test_meta_without_hash_is_refused(tmp_path: Path, good_rows: list[dict[str, str]]) -> None:
    path = write_source(tmp_path, good_rows)
    path.with_suffix(".meta.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="csv_sha3_256"):
        ya.read_verified_csv(path)


def test_missing_column_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "x.csv"
    path.write_text("label,reading\r\nos,1\r\n", encoding="utf-8")
    path.with_suffix(".meta.json").write_text(
        json.dumps({"csv_sha3_256": hashlib.sha3_256(path.read_bytes()).hexdigest()}), encoding="utf-8")
    with pytest.raises(ValueError, match="colunas ausentes"):
        ya.read_verified_csv(path)


# ------------------------------------------------- conferência linha a linha


def test_only_toeplitz_rows_are_analyzed(good_rows: list[dict[str, str]]) -> None:
    out = ya.analyze(good_rows)
    assert len(out) == 3  # 3 leituras, não 6 linhas


def test_known_values_for_h_0954(good_rows: list[dict[str, str]]) -> None:
    r = ya.analyze(good_rows)[0]
    assert (r["m"], r["n_blocks"], r["output_bits"], r["tail_bits"], r["margin_bits"]) == (
        1825, 488, 890_600, 576, 62_464)
    assert r["deficit_bits"] == pytest.approx(488 * 94.208, rel=1e-9)
    assert r["yield_block"] == 1825 / 2048
    assert r["total_yield"] == pytest.approx(0.8906)
    assert r["frac_margin"] == pytest.approx(0.062464)
    assert r["frac_tail"] == pytest.approx(0.000576)


def test_fractions_sum_to_one(good_rows: list[dict[str, str]]) -> None:
    for r in ya.analyze(good_rows):
        total = sum(r[k] for k in ("frac_deficit", "frac_rounding", "frac_margin", "frac_output",
                                   "frac_tail", "frac_low_entropy_discard"))
        assert total == pytest.approx(1.0, abs=1e-12)


def test_low_entropy_row_goes_to_discard(good_rows: list[dict[str, str]]) -> None:
    r = ya.analyze(good_rows)[2]
    assert (r["m"], r["output_bits"], r["low_entropy_discard_bits"]) == (0, 0, 1_000_000)
    assert r["frac_low_entropy_discard"] == 1.0 and r["frac_output"] == 0.0


@pytest.mark.parametrize(
    ("column", "bad", "message"),
    [
        ("m", "1826", "m gravado"),
        ("n_blocks", "487", "n_blocks gravado"),
        ("n_output_bits", "890601", "n_output_bits gravado"),
        ("discarded_bits", "577", "discarded_bits gravado"),
        ("epsilon_total_log2", "-60.0", "epsilon_total_log2"),
        ("h_used", "0.9", "gravado"),  # m e saída gravados são de H = 0,954
    ],
)
def test_inconsistent_row_stops_the_analysis(column: str, bad: str, message: str) -> None:
    values = {**GOOD, column: bad}
    with pytest.raises(ValueError, match=message):
        ya.analyze(pair("os", 1, values))


def test_epsilon_given_without_blocks_is_refused() -> None:
    with pytest.raises(ValueError, match="sem blocos"):
        ya.analyze(pair("x", 1, {**LOW, "epsilon_total_log2": "-60.0"}))


def test_invalid_value_in_row_is_refused() -> None:
    with pytest.raises(ValueError, match="inválido"):
        ya.analyze(pair("x", 1, {**GOOD, "h_used": "abc"}))
    with pytest.raises(ValueError):
        ya.analyze(pair("x", 1, {**GOOD, "h_used": "1.5"}))


def test_sha3_row_that_diverges_is_refused() -> None:
    rows = [make_row("os", 1, "toeplitz", GOOD), make_row("os", 1, "sha3", {**GOOD, "n_output_bits": "1"})]
    with pytest.raises(ValueError, match="divergem"):
        ya.analyze(rows)


def test_missing_sha3_partner_is_refused() -> None:
    with pytest.raises(ValueError, match="mesmas leituras"):
        ya.analyze([make_row("os", 1, "toeplitz", GOOD)])


def test_duplicate_and_unknown_extractor_refused() -> None:
    with pytest.raises(ValueError, match="repetida"):
        ya.analyze(pair("os", 1, GOOD) + [make_row("os", 1, "toeplitz", GOOD)])
    with pytest.raises(ValueError, match="desconhecido"):
        ya.analyze([make_row("os", 1, "outro", GOOD)])


# ------------------------------------------------------------------ curvas


def test_curve_h_known_points() -> None:
    rows = ya.curve_h()
    assert len(rows) == 1000
    by_h = {r["h"]: r for r in rows}
    assert by_h[1.0]["m"] == 1920 and by_h[1.0]["yield_block"] == 0.9375
    assert by_h[0.5]["m"] == 896 and by_h[0.5]["deficit_per_block"] == 1024
    assert by_h[0.001]["m"] == 0 and by_h[0.001]["low_entropy_discard"] == 2048
    assert by_h[0.954]["m"] == 1825
    first_positive = next(r for r in rows if r["m"] > 0)
    assert first_positive["h"] == 0.063 and first_positive["m"] == 1  # k = floor(129,02) = 129


def test_curve_h_is_monotone() -> None:
    ys = [r["yield_block"] for r in ya.curve_h()]
    assert all(a <= b for a, b in zip(ys, ys[1:], strict=False))


def test_curve_n_known_points() -> None:
    rows = {(r["n"], r["h"]): r for r in ya.curve_n()}
    assert len(rows) == 15
    assert rows[(2048, 1.0)]["m"] == 1920 and rows[(2048, 1.0)]["n_blocks"] == 488
    assert rows[(512, 0.9)]["m"] == 332 and rows[(512, 0.9)]["n_blocks"] == 1953  # k = floor(460,8) = 460
    assert rows[(512, 0.9)]["tail_bits"] == 64
    assert rows[(8192, 1.0)]["m"] == 8064 and rows[(8192, 1.0)]["n_blocks"] == 122
    assert rows[(2048, 0.954)]["batch_epsilon_log2"] == pytest.approx(-64 + math.log2(488))
    assert rows[(2048, 0.954)]["margin_frac_of_block"] == 0.0625


def test_curve_n_bigger_blocks_waste_less_margin() -> None:
    rows = {(r["n"], r["h"]): r for r in ya.curve_n()}
    ys = [rows[(n, 0.954)]["yield_block"] for n in ya.CURVE_N_VALUES]
    assert all(a < b for a, b in zip(ys, ys[1:], strict=False))


# ------------------------------------------------- execução e arquivos


def test_unique_tag_never_collides(tmp_path: Path) -> None:
    assert ya.unique_tag(tmp_path, "S") == "S"
    for name in ya.output_names("S").values():
        (tmp_path / name).write_text("x")
        assert ya.unique_tag(tmp_path, "S") == "S_2"
    (tmp_path / ya.output_names("S_2")["curve_n"]).write_text("x")
    assert ya.unique_tag(tmp_path, "S") == "S_3"


def test_run_end_to_end_and_hashes(tmp_path: Path, good_rows: list[dict[str, str]]) -> None:
    src = write_source(tmp_path, good_rows)
    out = tmp_path / "out"
    meta = ya.run(src, out)
    assert set(meta["outputs"]) == {"analysis", "curve_h", "curve_n"}
    for info in meta["outputs"].values():
        assert hashlib.sha3_256(Path(info["path"]).read_bytes()).hexdigest() == info["sha3_256"]
    saved = json.loads(Path(meta["meta_path"]).read_text(encoding="utf-8"))
    assert saved["source_csv_sha3_256"] == hashlib.sha3_256(src.read_bytes()).hexdigest()
    assert "não medidas" in " ".join(saved["notes"])
    assert len(list(out.glob("*.csv"))) == 3 and len(list(out.glob("*.meta.json"))) == 1


def test_two_runs_do_not_overwrite(tmp_path: Path, good_rows: list[dict[str, str]]) -> None:
    src = write_source(tmp_path, good_rows)
    first, second = ya.run(src, tmp_path / "out"), ya.run(src, tmp_path / "out")
    assert first["meta_path"] != second["meta_path"]
    assert len(list((tmp_path / "out").glob("*.csv"))) == 6


def test_run_refuses_tampered_source_and_writes_nothing(tmp_path: Path, good_rows: list[dict[str, str]]) -> None:
    src = write_source(tmp_path, good_rows)
    src.write_bytes(src.read_bytes().replace(b"1825", b"1826", 1))
    with pytest.raises(ValueError):
        ya.run(src, tmp_path / "out")
    assert not (tmp_path / "out").exists() or not list((tmp_path / "out").iterdir())


def test_run_refuses_inconsistent_source_and_writes_nothing(tmp_path: Path) -> None:
    rows = pair("os", 1, {**GOOD, "m": "1826"})
    src = write_source(tmp_path, rows)  # hash confere, mas o m não
    with pytest.raises(ValueError, match="m gravado"):
        ya.run(src, tmp_path / "out")
    assert not (tmp_path / "out").exists() or not list((tmp_path / "out").iterdir())


def test_write_csv_refuses_existing_file(tmp_path: Path) -> None:
    path = tmp_path / "existente.csv"
    path.write_text("original", encoding="utf-8")
    with pytest.raises(FileExistsError):
        ya._write_csv(path, [{"a": 1}])
    assert path.read_text(encoding="utf-8") == "original"
