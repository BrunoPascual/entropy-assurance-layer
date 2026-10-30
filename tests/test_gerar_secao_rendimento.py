"""Testes do gerador da documentação de rendimento (Dia 4, etapa 3, passo 5).

Os arquivos de entrada são produzidos pelos próprios scripts (yield_analysis e
estimator_vs_size) sobre dados determinísticos. Valores esperados calculados à mão:
H = 0,954 e 1M bits dão m = 1825, 488 blocos, saída 89,06%, déficit 4,60%,
arredondamento 0,04%, margem 6,25% e resto 0,06%.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from scripts import estimator_vs_size as ev
from scripts import gerar_secao_rendimento as g
from scripts import yield_analysis as ya

HEADER = [
    "label", "source_id", "reading", "extractor", "guarantee", "n_input_bits",
    "h_estimated_input", "h_used", "n", "m", "n_blocks", "discarded_bits",
    "n_output_bits", "epsilon_total_log2", "seconds",
]
GOOD = {
    "n_input_bits": "1000000", "h_estimated_input": "0.954", "h_used": "0.954", "n": "2048",
    "m": "1825", "n_blocks": "488", "discarded_bits": "576", "n_output_bits": "890600",
    "epsilon_total_log2": repr(-64 + math.log2(488)),
}
PROJECT_TEXT = (
    "# Doc\n\n### 6.8 Extrator\n\ntexto 6.8\n\n### 6.9 Mixer\n\ntexto 6.9\n\n"
    "## 17. Limitações conhecidas\n\n- item\n\n## 18. Glossário\n\nfim\n"
)


@dataclass
class FakeBatch:
    bits: np.ndarray
    batch_hash: str


class FakeSource:
    source_id = "fake"

    def __init__(self) -> None:
        self.calls = 0

    def read(self, n_bits: int) -> FakeBatch:
        self.calls += 1
        raw = hashlib.shake_256(f"g-{self.calls}-{n_bits}".encode()).digest((n_bits + 7) // 8)
        bits = np.unpackbits(np.frombuffer(raw, dtype=np.uint8))[:n_bits]
        return FakeBatch(bits, hashlib.sha3_256(np.packbits(bits).tobytes()).hexdigest())


def write_source_csv(directory: Path) -> Path:
    rows = []
    for label in ("os", "qpu_sim_ideal"):
        for extractor in ("toeplitz", "sha3"):
            row = dict.fromkeys(HEADER, "")
            row.update(GOOD, label=label, source_id=label, reading="1", extractor=extractor,
                       guarantee="x", seconds="0.1")
            rows.append(row)
    path = directory / "dia4_extract_test.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=HEADER)
        w.writeheader()
        w.writerows(rows)
    digest = hashlib.sha3_256(path.read_bytes()).hexdigest()
    path.with_suffix(".meta.json").write_text(json.dumps({"csv_sha3_256": digest}), encoding="utf-8")
    return path


@pytest.fixture
def metas(tmp_path: Path) -> tuple[dict[str, Any], dict[str, Any], Path]:
    out = tmp_path / "out"
    ymeta = ya.run(write_source_csv(tmp_path), out)
    emeta = ev.run(FakeSource(), "fake", sizes=(65_536, 1_000_000), reads=3, out_dir=out)
    emeta.pop("summary")
    ymeta["git_dirty"] = False
    emeta["git_dirty"] = False
    return ymeta, emeta, tmp_path


def srow(size: int, mean: float, sd: str = "0.002", frac_byte: str = "1.0", frac_ok: str = "1.0",
         ref: str = "0.996", hbit: str = "0.99", reads: str = "10") -> g.Row:
    return {"size_bits": str(size), "n_reads": reads, "h_est_mean": str(mean), "h_est_sd": sd,
            "h_est_min": str(mean - 0.001), "h_est_max": str(mean + 0.001), "h_bit_mean": hbit,
            "h_byte_mean": str(mean), "h_bit_reference": ref, "frac_limited_by_byte": frac_byte,
            "frac_h_health_ok": frac_ok, "stats_conclusive": "False", "mean_output_bits": "1000",
            "mean_total_yield": "0.9"}


def arow(h: float, label: str = "os") -> g.Row:
    return {"label": label, "reading": "1", "h_used": str(h), "frac_output": "0.89", "n_input_bits": "1000000"}


# ---------------------------------------------------------- formatação


def test_formatting_uses_comma_and_half_up() -> None:
    assert g.dec(0.954) == "0,954"
    assert g.pct(0.0625) == "6,25%"
    assert g.pct(0.03125) == "3,13%"  # 3,125 arredonda para cima, não para o par
    assert g.dec(1024.0, 1) == "1024,0"
    assert g.bits(1_000_000) == "1.000.000" and g.bits(65_536) == "65.536"
    assert g.bits(52_918.5) == "52.919"
    assert g.num("") is None and g.num("0.5") == 0.5


# -------------------------------------------------- frases condicionais


def test_sentence_margin_exact_text() -> None:
    assert g.sentence_margin(2048, -64) == (
        "A margem de segurança é fixa: 128 bits por bloco de 2048 bits (6,25% da entrada), qualquer que seja H.")


def test_trend_monotone_and_not() -> None:
    up = [srow(1000, 0.90), srow(2000, 0.95), srow(3000, 0.97)]
    text = g.sentence_trend(up)
    assert "0,900 com 1.000 bits" in text[0] and "0,970 com 3.000 bits" in text[0]
    assert "cresce com o tamanho" in text[1]
    down = [srow(1000, 0.90), srow(2000, 0.95), srow(3000, 0.94)]
    assert "não cresce estritamente" in g.sentence_trend(down)[1]


def test_trend_uses_size_not_input_order() -> None:
    text = g.sentence_trend([srow(3000, 0.97), srow(1000, 0.90)])
    assert text[0] == "A H estimada média vai de 0,900 com 1.000 bits a 0,970 com 3.000 bits."


def test_health_gate_sentence_both_branches() -> None:
    ok = [srow(1000, 0.95, frac_ok="1.0")]
    assert "Todas as leituras de todos os tamanhos passaram" in g.sentence_health_gate(ok, 0.9)
    mixed = [srow(1000, 0.85, frac_ok="0.0"), srow(2000, 0.92, frac_ok="0.5"), srow(3000, 0.95)]
    text = g.sentence_health_gate(mixed, 0.9)
    assert "1.000 bits (0% das leituras passou)" in text and "2.000 bits (50% das leituras passou)" in text
    assert "3.000" not in text


def test_limiting_branch_both_branches() -> None:
    text, all_byte = g.sentence_limiting_branch([srow(1000, 0.9), srow(2000, 0.95)])
    assert all_byte is True and "em 100% das leituras" in text
    text, all_byte = g.sentence_limiting_branch([srow(1000, 0.9, frac_byte="0.4"), srow(2000, 0.95)])
    assert all_byte is False and "1.000 bits: 40%" in text and "2.000 bits: 100%" in text


def test_reference_sentence_only_blames_byte_when_all_byte() -> None:
    rows = [srow(1000, 0.9), srow(4_000_000, 0.979, ref="0.9982", hbit="0.9975")]
    with_blame = g.sentence_reference(rows, True)
    assert "4.000.000 bits" in with_blame and "0,9982" in with_blame and "por causa do ramo por byte" in with_blame
    assert "por causa do ramo por byte" not in g.sentence_reference(rows, False)


def test_between_reads_sentence_branches() -> None:
    summary = [srow(1_000_000, 0.96, sd="0.003")]
    close = g.sentence_between_reads(summary, [arow(0.953), arow(0.961)])  # amplitude 0,008 <= 4 × 0,003
    assert close is not None and "não distingue uma fonte da outra" in close
    far = g.sentence_between_reads(summary, [arow(0.90), arow(0.96)])  # amplitude 0,06 > 0,012
    assert far is not None and "pode haver diferença entre fontes" in far
    assert g.sentence_between_reads([srow(65_536, 0.87)], [arow(0.95)]) is None  # sem lote de 1M
    assert g.sentence_between_reads([srow(1_000_000, 0.96, sd="")], [arow(0.95)]) is None  # sem desvio


def test_sizes_text_reads_the_data() -> None:
    def a(n: int) -> g.Row:
        return {**arow(0.95), "n_input_bits": str(n)}

    assert g._sizes_text([a(500_000), a(500_000)]) == "lote de 500.000 bits"
    assert g._sizes_text([a(500_000), a(1_000_000)]) == "lotes de tamanhos variados"


# ----------------------------------------------------------- blocos


def test_rendimento_block_has_hand_computed_numbers(metas: Any) -> None:
    ymeta, emeta, _ = metas
    block = g.build_rendimento(ymeta, emeta)
    assert block.startswith(g.RENDIMENTO[0]) and block.endswith(g.RENDIMENTO[1])
    row = next(line for line in block.splitlines() if line.startswith("| `os` | 1 |"))
    cells = [c.strip() for c in row.strip("|").split("|")]
    assert cells[2:] == ["0,954", "1825", "89,06%", "4,60%", "0,04%", "6,25%", "0,06%"]
    assert "| 0,500 | 1024 | 896 | 0,4375 | 1024,0 | 0,000 | 128 |" in block
    assert "| 0,900 | 1843 | 1715 | 0,8374 | 204,8 | 0,200 | 128 |" in block
    assert "| 0,954 | 1953 | 1825 | 0,8911 | 94,2 | 0,792 | 128 |" in block
    assert "| 1,000 | 2048 | 1920 | 0,9375 | 0,0 | 0,000 | 128 |" in block
    assert "| 2048 | 1825 | 488 | 0,8911 | 6,25% | -55,07 |" in block
    assert "| 4096 | 3779 | 244 | 0,9226 | 3,13% | -56,07 |" in block  # k = 3907; 3907 - 128 = 3779
    assert "Primeiro H da grade (passo 0,001) com saída positiva: 0,063." in block
    assert "lote de 1.000.000 bits" in block
    assert "simuladas" in block and "Atenção" not in block


def test_rendimento_block_lists_every_source_hash(metas: Any) -> None:
    ymeta, emeta, _ = metas
    block = g.build_rendimento(ymeta, emeta)
    for meta, keys in ((ymeta, ("analysis", "curve_h", "curve_n")), (emeta, ("readings", "summary"))):
        for key in keys:
            assert meta["outputs"][key]["sha3_256"] in block
    assert ymeta["source_csv_sha3_256"] in block


def test_dirty_git_adds_a_note(metas: Any) -> None:
    ymeta, emeta, _ = metas
    ymeta["git_dirty"] = True
    assert "Atenção: a medição de rendimento foi feita com mudanças sem commit" in g.build_rendimento(ymeta, emeta)
    assert "Atenção: a medição de rendimento" in g.build_limitacoes(ymeta, emeta)


def test_limitacoes_block_states_read_count(metas: Any) -> None:
    ymeta, emeta, _ = metas
    block = g.build_limitacoes(ymeta, emeta)
    assert block.startswith(g.LIMITACOES[0]) and block.endswith(g.LIMITACOES[1])
    assert "A tabela D tem 3 leituras por tamanho" in block


# ------------------------------------------------ verificação dos arquivos


def test_tampered_csv_is_refused(metas: Any) -> None:
    ymeta, emeta, _ = metas
    path = Path(ymeta["outputs"]["curve_h"]["path"])
    path.write_bytes(path.read_bytes().replace(b"1920", b"1921", 1))
    with pytest.raises(ValueError, match="não confere"):
        g.build_rendimento(ymeta, emeta)


def test_tampered_estimator_csv_is_refused(metas: Any) -> None:
    ymeta, emeta, _ = metas
    path = Path(emeta["outputs"]["summary"]["path"])
    path.write_bytes(path.read_bytes() + b"x")
    with pytest.raises(ValueError, match="não confere"):
        g.build_limitacoes(ymeta, emeta)


def test_tampered_source_csv_is_refused(metas: Any) -> None:
    ymeta, emeta, _ = metas
    path = Path(ymeta["source_csv"])
    path.write_bytes(path.read_bytes().replace(b"890600", b"890601", 1))
    with pytest.raises(ValueError, match="não confere"):
        g.build_rendimento(ymeta, emeta)


def test_missing_output_and_missing_file_are_refused(metas: Any) -> None:
    ymeta, emeta, _ = metas
    saved = ymeta["outputs"].pop("curve_n")
    with pytest.raises(ValueError, match="não lista"):
        g.build_rendimento(ymeta, emeta)
    ymeta["outputs"]["curve_n"] = {"path": "nao/existe.csv", "sha3_256": saved["sha3_256"]}
    with pytest.raises(ValueError, match="não consegui ler"):
        g.build_rendimento(ymeta, emeta)


def test_load_meta_errors(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="não consegui ler"):
        g.load_meta(tmp_path / "nao_existe.json")
    bad = tmp_path / "ruim.json"
    bad.write_text("{", encoding="utf-8")
    with pytest.raises(ValueError, match="não consegui ler"):
        g.load_meta(bad)


# ------------------------------------------------------- edição do texto

SPEC = g.RENDIMENTO


def test_upsert_inserts_before_anchor() -> None:
    out = g.upsert_block(PROJECT_TEXT, f"{SPEC[0]}\nB\n{SPEC[1]}", SPEC)
    assert out.index("texto 6.8") < out.index(SPEC[0]) < out.index(SPEC[1]) < out.index("### 6.9 Mixer")
    assert out.count(SPEC[0]) == 1


def test_upsert_replaces_existing_block_and_is_idempotent() -> None:
    once = g.upsert_block(PROJECT_TEXT, f"{SPEC[0]}\nA\n{SPEC[1]}", SPEC)
    twice = g.upsert_block(once, f"{SPEC[0]}\nB\n{SPEC[1]}", SPEC)
    assert "\nB\n" in twice and "\nA\n" not in twice and twice.count(SPEC[0]) == 1
    assert g.upsert_block(twice, f"{SPEC[0]}\nB\n{SPEC[1]}", SPEC) == twice


def test_upsert_refuses_ambiguous_input() -> None:
    block = f"{SPEC[0]}\nB\n{SPEC[1]}"
    with pytest.raises(ValueError, match="encontrada 0"):
        g.upsert_block("sem âncora\n", block, SPEC)
    with pytest.raises(ValueError, match="encontrada 2"):
        g.upsert_block(PROJECT_TEXT + "\n### 6.9 de novo\n", block, SPEC)
    with pytest.raises(ValueError, match="inconsistentes"):
        g.upsert_block(PROJECT_TEXT + SPEC[0], block, SPEC)
    with pytest.raises(ValueError, match="fora de ordem"):
        g.upsert_block(f"{SPEC[1]}\nx\n{SPEC[0]}\n", block, SPEC)


@pytest.mark.parametrize("eol", ["\n", "\r\n"])
def test_update_project_preserves_line_endings(tmp_path: Path, eol: str) -> None:
    project = tmp_path / "PROJECT.md"
    project.write_bytes(PROJECT_TEXT.replace("\n", eol).encode("utf-8"))
    new = g.update_project(project, [("<!-- dia4-rendimento:start -->\nB\n<!-- dia4-rendimento:end -->", g.RENDIMENTO)])
    if eol == "\r\n":
        assert "\n" not in new.replace("\r\n", "")  # nenhum LF solto
        assert new.count("\r") == new.count("\n")
    else:
        assert "\r" not in new


# ------------------------------------------------------------ CLI


def run_main(monkeypatch: pytest.MonkeyPatch, *args: str) -> None:
    monkeypatch.setattr(sys, "argv", ["gerar_secao_rendimento", *args])
    g.main()


def write_metas(ymeta: dict[str, Any], emeta: dict[str, Any], directory: Path) -> tuple[Path, Path]:
    y, e = directory / "y.meta.json", directory / "e.meta.json"
    y.write_text(json.dumps(ymeta), encoding="utf-8")
    e.write_text(json.dumps(emeta), encoding="utf-8")
    return y, e


def test_main_writes_both_blocks_and_rerun_is_stable(metas: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ymeta, emeta, _ = metas
    y, e = write_metas(ymeta, emeta, tmp_path)
    project = tmp_path / "PROJECT.md"
    project.write_bytes(PROJECT_TEXT.replace("\n", "\r\n").encode("utf-8"))
    args = ("--yield-meta", str(y), "--estimator-meta", str(e), "--project", str(project))
    run_main(monkeypatch, *args)
    first = project.read_bytes()
    text = first.decode("utf-8")
    assert text.index("### 6.8.1") < text.index("### 6.9 Mixer") < text.index("Limitações do Dia 4") < text.index("## 18.")
    assert b"\r\n" in first and b"\n" not in first.replace(b"\r\n", b"")
    run_main(monkeypatch, *args)
    assert project.read_bytes() == first  # reexecutar não duplica nem altera


def test_main_dry_run_does_not_write(metas: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                    capsys: pytest.CaptureFixture[str]) -> None:
    ymeta, emeta, _ = metas
    y, e = write_metas(ymeta, emeta, tmp_path)
    project = tmp_path / "PROJECT.md"
    project.write_text(PROJECT_TEXT, encoding="utf-8")
    run_main(monkeypatch, "--yield-meta", str(y), "--estimator-meta", str(e), "--project", str(project), "--dry-run")
    assert project.read_text(encoding="utf-8") == PROJECT_TEXT
    assert "6.8.1 Rendimento do extrator" in capsys.readouterr().out


def test_main_refuses_and_leaves_project_untouched(metas: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                                   capsys: pytest.CaptureFixture[str]) -> None:
    ymeta, emeta, _ = metas
    y, e = write_metas(ymeta, emeta, tmp_path)
    project = tmp_path / "PROJECT.md"
    project.write_text(PROJECT_TEXT, encoding="utf-8")
    path = Path(ymeta["outputs"]["analysis"]["path"])
    path.write_bytes(path.read_bytes() + b"x")
    with pytest.raises(SystemExit) as exc:
        run_main(monkeypatch, "--yield-meta", str(y), "--estimator-meta", str(e), "--project", str(project))
    assert exc.value.code == 1 and "não confere" in capsys.readouterr().err
    assert project.read_text(encoding="utf-8") == PROJECT_TEXT


def test_main_refuses_when_anchor_is_missing(metas: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ymeta, emeta, _ = metas
    y, e = write_metas(ymeta, emeta, tmp_path)
    project = tmp_path / "PROJECT.md"
    project.write_text("# sem âncoras\n", encoding="utf-8")
    with pytest.raises(SystemExit):
        run_main(monkeypatch, "--yield-meta", str(y), "--estimator-meta", str(e), "--project", str(project))
    assert project.read_text(encoding="utf-8") == "# sem âncoras\n"
