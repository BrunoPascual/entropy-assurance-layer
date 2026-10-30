"""Testes do gerador de documentação do Dia 4 (etapa 5).

O CSV de entrada é montado com as colunas reais de resilience_dia4 e gravado por
`write_outputs` (que calcula resumo, gate e contagens do meta), de modo que o
gerador é testado contra o mesmo formato que a execução oficial produz.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import pytest

from eal.config import MIN_LOCAL_OUTPUT_BITS
from scripts import gerar_docs_dia4 as gd
from scripts import resilience_dia4 as rs

PARAMS = {"reps": 5, "n_bits": 1_000_000, "noise_backend": "FakeKingston"}
H64 = "a" * 64


def row(scenario: str, rep: int = 1, **kw: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "scenario": scenario, "rep": rep, "mode": "experiment", "n_bits": 1_000_000, "os_status": "mixed",
        "os_expected_to_fail": False, "seed_generated": True, "usable_for_key": False,
        "statuses": "os:mixed", "mixed": "os", "not_mixed_reasons": "", "must_exclude": "",
        "seed_equals_without_bad": None, "seed_hash": H64, "error": "", "verdict": "ok"}
    base.update(kw)
    return base


def good_rows() -> list[dict[str, Any]]:
    return [
        row("BASE"),
        row("C1_stuck", statuses="os:mixed;faulty_stuck:excluded", must_exclude="faulty_stuck",
            seed_equals_without_bad=True,
            not_mixed_reasons="faulty_stuck: reprovada pelo teste de saúde: RCT | sem saída de extração"),
        row("C6_prng", statuses="os:mixed;faulty_prng:mixed", mixed="faulty_prng;os"),
        row("C5c_os_down_experiment", os_status="read_failed", os_expected_to_fail=True, must_exclude="os",
            statuses="os:read_failed;qpu_sim:mixed", mixed="qpu_sim", verdict="ok_experiment_only"),
        row("K1_keygen_standin", mode="keygen", usable_for_key=True, statuses="os:mixed;ibm_standin:mixed",
            mixed="ibm_standin;os"),
        row("C4_remote_down", mode="keygen", usable_for_key=True, must_exclude="ibm_down",
            statuses="os:mixed;ibm_down:read_failed", seed_equals_without_bad=True),
        row("C5a_os_down", mode="keygen", os_status="read_failed", os_expected_to_fail=True, must_exclude="os",
            seed_generated=False, usable_for_key=None, seed_hash="", statuses="os:read_failed;ibm_standin:not_mixed",
            mixed="", error="política: exige 1 fonte(s)", verdict="ok_fail_closed"),
        row("C5b_os_tampered", mode="keygen", os_status="excluded", os_expected_to_fail=True, must_exclude="os",
            seed_generated=False, usable_for_key=None, seed_hash="", statuses="os:excluded;ibm_standin:not_mixed",
            mixed="", error="política: exige 1 fonte(s)", verdict="ok_fail_closed"),
    ]


def write_source(directory: Path, rows: list[dict[str, Any]] | None = None) -> Path:
    meta = rs.write_outputs(rows if rows is not None else good_rows(), PARAMS, directory)
    return Path(meta["meta_path"])


def edit_meta(meta_path: Path, **changes: Any) -> None:
    data = json.loads(meta_path.read_text(encoding="utf-8"))
    data.update(changes)
    meta_path.write_text(json.dumps(data), encoding="utf-8")


PROJECT_TEXT = (
    "# Doc\n\n- **Status:** Dia 3 de 9 (concluído)\n\n### 6.9 Mixer\n\n1. Só entram fontes com `approved = True`.\n"
    + gd.POLICY_OLD + "\n4. Se a política não for satisfeita, nenhuma semente é gerada.\n\n"
    "### 6.10 Derivação\n\ntexto\n\n---\n\n## 7. Estrutura de pastas\n\n```\n"
    "│   ├── storage.py          # gravação e leitura de lotes em data/raw/\n"
    "│   ├── sources/            # os_source.py\n"
    "│   ├── extract/            # toeplitz.py, sha3.py\n"
    "│   ├── mix/                # mixer.py\n```\n\n"
    "## 17. Limitações conhecidas\n\n- item\n\n## 18. Glossário\n\nfim\n"
)


# ---------------------------------------------------------- leitura


def test_typed_converts_flags() -> None:
    raw = {k: "" for k in rs.CSV_FIELDS} | {"rep": "3", "n_bits": "1000000", "os_expected_to_fail": "False",
                                            "seed_generated": "True", "usable_for_key": "", "seed_equals_without_bad": "True"}
    t = gd.typed(raw)
    assert (t["rep"], t["n_bits"], t["os_expected_to_fail"], t["seed_generated"]) == (3, 1_000_000, False, True)
    assert t["usable_for_key"] is None and t["seed_equals_without_bad"] is True


@pytest.mark.parametrize("field", ["os_expected_to_fail", "seed_generated"])
def test_typed_refuses_bad_required_flag(field: str) -> None:
    raw = {k: "" for k in rs.CSV_FIELDS} | {"rep": "1", "n_bits": "10", "os_expected_to_fail": "False",
                                            "seed_generated": "True"} | {field: "yes"}
    with pytest.raises(ValueError, match=field):
        gd.typed(raw)
    with pytest.raises(ValueError, match="rep ou n_bits"):
        gd.typed({**raw, field: "True", "rep": "x"})


def test_load_resilience_happy_path(tmp_path: Path) -> None:
    meta, rows = gd.load_resilience(write_source(tmp_path))
    assert len(rows) == 8 and meta["gate"]["ok"] is True
    assert rows[0]["rep"] == 1 and rows[6]["seed_generated"] is False and rows[6]["usable_for_key"] is None


def test_tampered_csv_is_refused(tmp_path: Path) -> None:
    meta_path = write_source(tmp_path)
    csv_path = Path(json.loads(meta_path.read_text(encoding="utf-8"))["csv"])
    csv_path.write_bytes(csv_path.read_bytes().replace(b"ok_fail_closed", b"ok", 1))
    with pytest.raises(ValueError, match="não confere"):
        gd.load_resilience(meta_path)


def test_wrong_header_is_refused(tmp_path: Path) -> None:
    meta_path = write_source(tmp_path)
    csv_path = Path(json.loads(meta_path.read_text(encoding="utf-8"))["csv"])
    csv_path.write_bytes(csv_path.read_bytes().replace(b"scenario,", b"cenario,", 1))
    edit_meta(meta_path, csv_sha3_256=hashlib.sha3_256(csv_path.read_bytes()).hexdigest())
    with pytest.raises(ValueError, match="cabeçalho"):
        gd.load_resilience(meta_path)


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"n_rows": 99}, "número de linhas"),
        ({"verdicts_by_scenario": {"BASE": {"ok": 7}}}, "vereditos por cenário"),
        ({"os_false_alarms": 4}, "falsos alarmes"),
        ({"gate": {"ok": False, "problems": ["x"]}}, "gate"),
    ],
)
def test_meta_that_disagrees_with_the_csv_is_refused(tmp_path: Path, change: dict[str, Any], message: str) -> None:
    meta_path = write_source(tmp_path)
    edit_meta(meta_path, **change)
    with pytest.raises(ValueError, match=message):
        gd.load_resilience(meta_path)


def test_missing_csv_is_refused(tmp_path: Path) -> None:
    meta_path = write_source(tmp_path)
    edit_meta(meta_path, csv=str(tmp_path / "nao_existe.csv"))
    with pytest.raises(ValueError, match="não consegui ler"):
        gd.load_resilience(meta_path)


# -------------------------------------------------------- tabelas e frases


def test_needs_attention_truth_table() -> None:
    assert gd.needs_attention(row("X", verdict="ok")) is False
    assert gd.needs_attention(row("X", verdict="ok_fail_closed", os_expected_to_fail=True)) is False
    assert gd.needs_attention(row("X", verdict="ok_experiment_only", os_expected_to_fail=True)) is False
    assert gd.needs_attention(row("X", verdict="ok_fail_closed", os_expected_to_fail=False)) is True  # falso alarme
    assert gd.needs_attention(row("X", verdict="ok_experiment_only")) is True
    for v in ("UNEXPECTED: x", "DETECTION_MISS: y", "VIOLATION: z"):
        assert gd.needs_attention(row("X", verdict=v, os_expected_to_fail=True)) is True


def test_counts_table_numbers() -> None:
    rows = [row("A"), row("A", 2), row("A", 3, verdict="DETECTION_MISS: s"), row("B", mode="keygen", verdict="ok_fail_closed")]
    lines = gd.counts_table(rows)
    assert lines[2] == "| `A` | experiment | 3 | 2 | - | - | 1 | - | - |"
    assert lines[3] == "| `B` | keygen | 1 | - | - | 1 | - | - | - |"


def test_attention_table_escapes_pipes_and_truncates() -> None:
    long_reason = "x" * 200
    rows = [row("K1", verdict="UNEXPECTED: não entrou na mistura: ibm_standin",
                not_mixed_reasons="ibm_standin: reprovada: APT | H abaixo do limiar", statuses="os:mixed;ibm_standin:excluded"),
            row("K1", 2, verdict="UNEXPECTED: z", not_mixed_reasons=long_reason)]
    text = "\n".join(gd.attention_table(rows))
    assert "APT / H abaixo do limiar" in text and "APT | H" not in text
    assert "x" * 110 + "..." in text and "x" * 111 not in text
    assert gd.attention_table([row("A")]) == ["Nenhuma execução fora do esperado."]


def test_sentences_on_good_data() -> None:
    text = "\n".join(gd.sentences(good_rows()))
    assert "não entrou na mistura em 0 de 5 execuções" in text  # BASE, C1, C6, K1, C4
    assert "Em 2 execuções com fontes defeituosas ou indisponíveis e a `os` aprovada (`C1_stuck`, `C4_remote_down`), nenhuma" in text
    assert "A `faulty_prng` entrou na mistura em 1 de 1 execuções" in text
    assert "a semente foi gerada em 0 de 2 execuções (esperado: 0; G2)" in text
    assert "K1: semente utilizável em 1 de 1 execuções; 0 com UNEXPECTED" in text
    assert "marcada como inutilizável em 1 de 1 execuções" in text
    assert "VIOLATION (política ou isolamento do pipeline quebrados): 0." in text


def test_sentences_report_misses_false_alarms_and_violations() -> None:
    rows = good_rows()
    rows[1]["verdict"] = "DETECTION_MISS: faulty_stuck"
    rows += [
        row("BASE", 2, os_status="excluded", verdict="ok_experiment_only"),
        row("K1_keygen_standin", 2, mode="keygen", usable_for_key=True, verdict="UNEXPECTED: não entrou"),
        row("C6_prng", 2, os_status="excluded", verdict="ok_fail_closed"),
        row("C1_stuck", 2, verdict="VIOLATION: x"),
        row("C1_stuck", 3, os_status="excluded", must_exclude="faulty_stuck", seed_generated=False,
            usable_for_key=None, verdict="ok_fail_closed"),  # falso alarme da os: não conta como "com a os aprovada"
        row("K1_keygen_standin", 3, mode="keygen", os_status="excluded", seed_generated=False,
            usable_for_key=None, verdict="ok_fail_closed"),
        row("C5a_os_down", 2, mode="keygen", os_status="read_failed", os_expected_to_fail=True, must_exclude="os",
            seed_generated=True, usable_for_key=True, verdict="VIOLATION: semente gerada sem a fonte local aprovada"),
    ]
    text = "\n".join(gd.sentences(rows))
    assert "não entrou na mistura em 4 de 11 execuções" in text  # BASE 2, C6 2, C1 3, K1 3
    assert "Em 2 execuções com fontes defeituosas ou indisponíveis" in text  # C1 rep 1 e C4; o C1 rep 3 fica de fora
    assert "em 1 delas uma fonte defeituosa entrou na mistura (DETECTION_MISS" in text
    assert "A `faulty_prng` entrou na mistura em 1 de 1 execuções" in text  # a C6 rep 2 tem a os fora
    assert "a semente foi gerada em 1 de 3 execuções (esperado: 0; G2)" in text
    assert "K1: semente utilizável em 2 de 3 execuções; 1 com UNEXPECTED" in text
    assert "VIOLATION (política ou isolamento do pipeline quebrados): 2." in text


def test_sentences_omit_absent_scenarios() -> None:
    text = "\n".join(gd.sentences([row("BASE")]))
    for fragment in ("C6", "(G2)", "K1:", "C5c:", "defeituosas"):
        assert fragment not in text
    assert "Execuções com VIOLATION" in text


# ------------------------------------------------------------------ blocos


def test_gate_block_content(tmp_path: Path) -> None:
    meta, rows = gd.load_resilience(write_source(tmp_path))
    meta["git_dirty"], meta["git_commit"] = False, "abcdef1234567"
    block = gd.build_gate(meta, rows)
    assert block.startswith(gd.GATE[0]) and block.endswith(gd.GATE[1])
    assert "Resultado do gate: CUMPRIDO." in block and "commit `abcdef1`" in block
    assert meta["csv_sha3_256"] in block and "5 repetições por cenário" in block and "lotes de 1.000.000 bits" in block
    assert "medido com mudanças sem commit" not in block and "stand-in" in block


def test_gate_block_not_met_and_dirty_note(tmp_path: Path) -> None:
    rows = good_rows()
    rows[0]["usable_for_key"] = True  # BASE com semente utilizável em experiment
    meta, loaded = gd.load_resilience(write_source(tmp_path, rows))
    meta["git_dirty"] = True
    block = gd.build_gate(meta, loaded)
    assert "Resultado do gate: NÃO CUMPRIDO." in block and "utilizável para chave" in block
    assert "medido com mudanças sem commit" in block


def test_static_blocks_state_the_code_facts() -> None:
    mixer, pipeline, limits = gd.build_mixer(), gd.build_pipeline(), gd.build_limits()
    assert mixer.startswith(gd.MIXER[0]) and mixer.endswith(gd.MIXER[1])
    assert f"{MIN_LOCAL_OUTPUT_BITS} bits" in mixer and "8 bytes, big-endian" in mixer and "BITS, não de bytes" in mixer
    for status in ("mixed", "excluded", "not_mixed", "read_failed", "health_failed", "extraction_failed"):
        assert f"`{status}`" in pipeline
    assert pipeline.startswith(gd.PIPELINE[0]) and pipeline.endswith(gd.PIPELINE[1])
    assert "nome da classe" in pipeline and "KeyboardInterrupt" in pipeline
    assert limits.startswith(gd.LIMITS[0]) and limits.endswith(gd.LIMITS[1])
    assert "stand-in" in limits and "2^k" in limits and "P1" in limits


def test_marker_names_do_not_collide_with_the_other_generator() -> None:
    from scripts import gerar_secao_rendimento as g

    markers = [m for spec in (gd.GATE, gd.MIXER, gd.PIPELINE, gd.LIMITS, g.RENDIMENTO, g.LIMITACOES) for m in spec[:2]]
    assert len(set(markers)) == len(markers)
    for a in markers:
        assert sum(a in b for b in markers) == 1  # nenhum marcador é substring de outro


# ---------------------------------------------------- edições de texto


def test_policy_replacement_and_idempotence() -> None:
    once = gd._replace_once(PROJECT_TEXT, gd.POLICY_OLD, gd.POLICY_NEW, "política")
    assert gd.POLICY_OLD not in once and gd.POLICY_NEW in once
    assert "`usable_for_key = False`" in once and f"{MIN_LOCAL_OUTPUT_BITS} bits" in once
    assert gd._replace_once(once, gd.POLICY_OLD, gd.POLICY_NEW, "política") == once


def test_policy_replacement_refuses_unknown_or_duplicated_text() -> None:
    with pytest.raises(ValueError, match="nem o texto antigo nem o novo"):
        gd._replace_once("outro texto\n", gd.POLICY_OLD, gd.POLICY_NEW, "política")
    with pytest.raises(ValueError, match="2 vezes"):
        gd._replace_once(gd.POLICY_OLD + "\n" + gd.POLICY_OLD, gd.POLICY_OLD, gd.POLICY_NEW, "política")


def test_status_line() -> None:
    ok = gd.update_status(PROJECT_TEXT, True)
    assert "- **Status:** Dia 4 de 9 (concluído; gate do Dia 4 aprovado, ver seção 16.2)" in ok
    assert "Dia 3 de 9" not in ok and gd.update_status(ok, True) == ok
    assert "em andamento; gate do Dia 4 não cumprido" in gd.update_status(PROJECT_TEXT, False)
    with pytest.raises(ValueError, match="Status"):
        gd.update_status("sem status\n", True)
    with pytest.raises(ValueError, match="Status"):
        gd.update_status("- **Status:** a\n- **Status:** b\n", True)


def test_tree_edit_adds_pipeline_aligned_and_is_idempotent() -> None:
    text, warnings = gd.update_tree(PROJECT_TEXT)
    assert warnings == []
    assert "│   ├── extract/            # blocks.py, budget.py, toeplitz.py, sha3.py" in text
    lines = text.splitlines()
    storage = next(ln for ln in lines if "storage.py" in ln)
    pipe = next(ln for ln in lines if "pipeline.py" in ln)
    assert lines.index(pipe) == lines.index(storage) + 1
    assert pipe.index("#") == storage.index("#")  # comentários alinhados
    assert gd.update_tree(text) == (text, [])


def test_tree_edit_warns_instead_of_failing() -> None:
    text, warnings = gd.update_tree("# Doc sem árvore\n")
    assert text == "# Doc sem árvore\n" and len(warnings) == 2


# ----------------------------------------------- integração e CLI


def blocks_for(tmp_path: Path) -> tuple[list[Any], bool]:
    meta, rows = gd.load_resilience(write_source(tmp_path))
    blocks = [(gd.build_gate(meta, rows), gd.GATE), (gd.build_mixer(), gd.MIXER),
              (gd.build_pipeline(), gd.PIPELINE), (gd.build_limits(), gd.LIMITS)]
    return blocks, bool(meta["gate"]["ok"])


@pytest.mark.parametrize("eol", ["\n", "\r\n"])
def test_update_project_places_blocks_and_preserves_eol(tmp_path: Path, eol: str) -> None:
    blocks, ok = blocks_for(tmp_path)
    project = tmp_path / "PROJECT.md"
    project.write_bytes(PROJECT_TEXT.replace("\n", eol).encode("utf-8"))
    new, warnings = gd.update_project(project, blocks, ok)
    plain = new.replace("\r\n", "\n")
    assert warnings == []
    order = [plain.index(m) for m in ("### 6.9 Mixer", gd.MIXER[0], "### 6.10", gd.PIPELINE[0], "## 7. Estrutura",
                                      gd.GATE[0], "## 17.", gd.LIMITS[0], "## 18.")]
    assert order == sorted(order)
    assert plain.index("---\n\n## 7.") > plain.index(gd.PIPELINE[1])  # 6.14 vem antes do separador
    if eol == "\r\n":
        assert "\n" not in new.replace("\r\n", "") and new.count("\r") == new.count("\n")
    else:
        assert "\r" not in new
    project.write_bytes(new.encode("utf-8"))
    again, _ = gd.update_project(project, blocks, ok)
    assert again == new  # reexecutar não duplica


def run_main(monkeypatch: pytest.MonkeyPatch, *args: str) -> None:
    monkeypatch.setattr(sys, "argv", ["gerar_docs_dia4", *args])
    gd.main()


def test_main_writes_and_dry_run_does_not(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                         capsys: pytest.CaptureFixture[str]) -> None:
    meta_path = write_source(tmp_path)
    project = tmp_path / "PROJECT.md"
    project.write_text(PROJECT_TEXT, encoding="utf-8")
    run_main(monkeypatch, "--resilience-meta", str(meta_path), "--project", str(project), "--dry-run")
    assert project.read_text(encoding="utf-8") == PROJECT_TEXT
    assert "16.2 Resultado do gate do Dia 4" in capsys.readouterr().out
    run_main(monkeypatch, "--resilience-meta", str(meta_path), "--project", str(project))
    text = project.read_text(encoding="utf-8")
    assert "### 16.2" in text and "### 6.14" in text and "### 6.9.1" in text and "Dia 4 de 9" in text


def test_main_refuses_and_leaves_project_untouched(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                                   capsys: pytest.CaptureFixture[str]) -> None:
    meta_path = write_source(tmp_path)
    csv_path = Path(json.loads(meta_path.read_text(encoding="utf-8"))["csv"])
    csv_path.write_bytes(csv_path.read_bytes() + b"x")
    project = tmp_path / "PROJECT.md"
    project.write_text(PROJECT_TEXT, encoding="utf-8")
    with pytest.raises(SystemExit) as exc:
        run_main(monkeypatch, "--resilience-meta", str(meta_path), "--project", str(project))
    assert exc.value.code == 1 and "não confere" in capsys.readouterr().err
    assert project.read_text(encoding="utf-8") == PROJECT_TEXT


def test_main_refuses_when_an_anchor_or_the_policy_text_is_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                                                    capsys: pytest.CaptureFixture[str]) -> None:
    meta_path = write_source(tmp_path)
    project = tmp_path / "PROJECT.md"
    for broken, message in ((PROJECT_TEXT.replace("## 17.", "## 17 "), "âncora"),
                            (PROJECT_TEXT.replace(gd.POLICY_OLD, "outra política"), "política do 6.9")):
        project.write_text(broken, encoding="utf-8")
        with pytest.raises(SystemExit):
            run_main(monkeypatch, "--resilience-meta", str(meta_path), "--project", str(project))
        assert message in capsys.readouterr().err
        assert project.read_text(encoding="utf-8") == broken


def test_main_warns_about_missing_tree_but_still_writes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                                        capsys: pytest.CaptureFixture[str]) -> None:
    meta_path = write_source(tmp_path)
    project = tmp_path / "PROJECT.md"
    no_tree = PROJECT_TEXT.replace("│   ├── storage.py          # gravação e leitura de lotes em data/raw/\n", "")
    project.write_text(no_tree, encoding="utf-8")
    run_main(monkeypatch, "--resilience-meta", str(meta_path), "--project", str(project))
    assert "AVISO: árvore de pastas: linha de storage.py" in capsys.readouterr().err
    assert "### 16.2" in project.read_text(encoding="utf-8")
