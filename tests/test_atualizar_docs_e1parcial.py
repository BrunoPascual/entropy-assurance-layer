"""Testes de scripts/atualizar_docs_e1parcial.py (Dia 6), com CSVs e PROJECT.md sintéticos."""
from __future__ import annotations

import csv
import importlib.util
import sys
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "atualizar_docs_e1parcial",
    Path(__file__).resolve().parents[1] / "scripts" / "atualizar_docs_e1parcial.py")
doc = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = doc
_SPEC.loader.exec_module(doc)

NQ = 6
SHOTS = 10000
ANCHOR_TEXT = f"# Titulo\nStatus: Dia 5 de 9\n\n{doc.ANCHOR}\n"


def write(path: Path, cols, rows) -> None:
    cols = list(cols)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(cols)
        for r in rows:
            w.writerow([r.get(c, "") for c in cols])


def make_results(d: Path) -> Path:
    d.mkdir(parents=True, exist_ok=True)
    lotes = []
    for fonte, sid, ok, h in (("qpu_real", "ibm_kingston", "False", "0.9622541177"),
                              ("simulador", "qpu_sim", "False", "0.9591528149"),
                              ("os", "os", "True", "0.9694924432")):
        for lote in ("1", "2"):
            lotes.append({"fonte": fonte, "lote": lote, "source_id": sid, "n_bits": "1500096",
                          "saude_approved": ok, "saude_h_estimated": h, "saude_h_threshold": "0.9",
                          "saude_stats_monobit": "2.9e-18" if ok == "False" else "0.47",
                          "saude_stats_block": "0.36", "saude_stats_runs": "0" if ok == "False" else "0.93",
                          "saude_rct_pass": "True", "saude_apt_pass": "True", "saude_replay_pass": "True",
                          "saude_h_health_pass": "True",
                          "saude_reasons": "monobit: p = 2.91e-18 (< 0.01) | runs: p = 0 (< 0.01)" if ok == "False" else "",
                          "ext_n_output_bits": "0" if ok == "False" else "1359324",
                          "ext_rendimento": "0.0" if ok == "False" else "0.906"})
    write(d / "dia6_qpu_vs_sim_lotes.csv", doc.CSV_COLUMNS["dia6_qpu_vs_sim_lotes.csv"], lotes)
    res = []
    for fonte in doc.FONTES:
        res.append({"fonte": fonte, "n_qubits": str(NQ), "n_shots": str(SHOTS), "frac1_lote1": "0.4964",
                    "frac1_lote2": "0.4979", "zp1_max_abs_lote1": "33.1", "zp1_max_abs_lote2": "36.1",
                    "zp1_n_acima3_lote1": "9", "zp1_n_acima3_lote2": "9",
                    "corr_viz_n_acima3_lote1": "3", "corr_viz_n_acima3_lote2": "2",
                    "corr_shot_n_acima3_lote1": "1", "corr_shot_n_acima3_lote2": "0",
                    "zdiff_dp": "1.1445", "zdiff_n_acima3": "3", "zdiff_max_abs": "4.36", "zdiff_max_pos": "35"})
    write(d / "dia6_qpu_vs_sim_resumo.csv", doc.CSV_COLUMNS["dia6_qpu_vs_sim_resumo.csv"], res)
    exc = []
    for lote, flags in (("1", (1, 3)), ("2", (1, 4))):
        for pos in range(NQ):
            exc.append({"lote": lote, "posicao": str(pos), "n_shots": str(SHOTS), "p1": "0.5",
                        "erro_leitura": "0.01", "excesso": "0.0",
                        "acima_do_limite": "True" if pos in flags else "False"})
    write(d / "dia6_qpu_excesso_leitura.csv", doc.CSV_COLUMNS["dia6_qpu_excesso_leitura.csv"], exc)
    pq = []
    for fonte in doc.FONTES:
        for lote in ("1", "2"):
            for pos in range(NQ):
                strong = fonte == "qpu_real" and pos == 2
                pq.append({"fonte": fonte, "lote": lote, "posicao": str(pos), "n_shots": str(SHOTS),
                           "p1": "0.5" if pos != 5 else "0.56",
                           "corr_vizinho": "" if pos == NQ - 1 else ("-0.067" if strong else "0.001"),
                           "erro_leitura": ("0.49" if pos == 5 else "0.02") if fonte == "qpu_real" else ""})
    write(d / "dia6_qpu_vs_sim_por_qubit.csv", doc.CSV_COLUMNS["dia6_qpu_vs_sim_por_qubit.csv"], pq)
    lotes_cal = [("cal_001", "2026-11-01T14:30:25Z", "2026-11-01 07:36:54-03:00", "1000", "batch_hash"),
                 ("cal_002", "2026-11-01T15:09:16Z", "2026-11-01 11:57:51-03:00", "4000", "batch_hash"),
                 ("coleta1_001", "2026-11-01T15:24:23Z", "2026-11-01 11:57:51-03:00", "9616", "inventario+batch_hash"),
                 ("coleta1_002", "2026-11-01T15:28:12Z", "2026-11-01 11:57:51-03:00", "9616", "inventario+batch_hash")]
    write(d / "dia6_deriva_dia_lotes.csv", doc.CSV_COLUMNS["dia6_deriva_dia_lotes.csv"],
          [{"lote": a, "criado_em": b, "calibracao_no_envio": c, "n_shots": s, "frac1": "0.4970",
            "conferencia": k} for a, b, c, s, k in lotes_cal])
    fixo = []
    for lote, rep in (("cal_001", "False"), ("cal_002", "True")):
        fixo.append({"tipo": "qubit", "grupo": "vies_alem_da_leitura", "id": "14", "lote": lote,
                     "estimativa": "0.507", "z": "0.44", "z_esperado": "9.29", "testavel": "True",
                     "replica": rep, "magnitude_compativel": rep})
    fixo.append({"tipo": "par", "grupo": "par_replicado_coleta1", "id": "130-131", "lote": "cal_001",
                 "estimativa": "-0.07", "z": "-2.25", "z_esperado": "1.07", "testavel": "False",
                 "replica": "", "magnitude_compativel": ""})
    fixo.append({"tipo": "qubit", "grupo": "vies_alem_da_leitura", "id": "14", "lote": "coleta1_001",
                 "estimativa": "0.34", "z": "-30.9", "z_esperado": "", "testavel": "", "replica": "",
                 "magnitude_compativel": ""})
    write(d / "dia6_deriva_dia_conjunto_fixo.csv", doc.CSV_COLUMNS["dia6_deriva_dia_conjunto_fixo.csv"], fixo)
    write(d / "dia6_deriva_dia_estabilidade.csv", doc.CSV_COLUMNS["dia6_deriva_dia_estabilidade.csv"],
          [{"lote_a": "cal_001", "lote_b": "cal_002", "zdiff_media": "-0.0107", "zdiff_dp": "1.4472",
            "zdiff_n_acima3": "6", "zdiff_max_abs": "5.1"}])
    return d


@pytest.fixture
def results(tmp_path):
    return make_results(tmp_path / "res")


def block_of(results):
    data, shas = doc.load_inputs(results)
    return doc.build_block(data, shas)


# ---- o bloco

def test_block_has_numbers_from_the_csvs(results):
    b = block_of(results)
    assert b.startswith(doc.START) and b.endswith(doc.END)
    assert "0,9623" in b and "0,9592" in b and "0,9695" in b      # H estimada
    assert "2,90e-18" in b                                         # p do CSV (2.9e-18), formatado
    assert "1359324" in b
    assert "reprovado: monobit: p = 2.91e-18 (< 0.01); runs: p = 0 (< 0.01)" in b
    assert "None" not in b and "nan" not in b.lower().replace("finan", "")


def test_block_intervals_and_cal_summary(results):
    b = block_of(results)
    assert "cal_001 → cal_002: 39 min" in b
    assert "cal_002 → coleta1_001: 15 min" in b
    assert "cal_001 → coleta1_001: 54 min" in b
    assert "qubit 14: replica em cal_002; não replica em cal_001; não testável em nenhum lote." in b
    assert "par 130-131: replica em nenhum lote; não replica em nenhum lote; não testável em cal_001." in b
    assert "criado_em" in b and "não o da execução" in b


def test_block_excess_and_neighbours(results):
    b = block_of(results)
    assert "Lote 1: 2 de 6 qubits acima do limite (posições: 1, 3)" in b
    assert "Lote 2: 2 de 6 qubits acima do limite (posições: 1, 4)" in b
    assert "Acima do limite em todos os lotes: 1." in b
    # r = -0,067 com 10000 shots: z = -6,7, acima do limite de Bonferroni para 5 pares (|z| > 2,58)
    assert "2-3 (z = -6,70)" in b
    assert "QPU real, acima do limite em todos os lotes: 2-3." in b
    assert "Posição 5: erro de leitura 0,4900" in b


def test_block_is_deterministic(results):
    assert block_of(results) == block_of(results)


@pytest.mark.parametrize("name", list(doc.CSV_COLUMNS))
def test_missing_csv_refuses(results, name):
    (results / name).unlink()
    with pytest.raises(doc.DocError, match="não encontrado"):
        doc.load_inputs(results)


def test_missing_column_refuses(results):
    p = results / "dia6_qpu_vs_sim_resumo.csv"
    p.write_text(p.read_text(encoding="utf-8").replace("zdiff_dp", "outro"), encoding="utf-8")
    with pytest.raises(doc.DocError, match="faltam as colunas"):
        doc.load_inputs(results)


def test_bad_number_refuses(results):
    p = results / "dia6_qpu_vs_sim_lotes.csv"
    p.write_text(p.read_text(encoding="utf-8").replace("0.9622541177", "abc"), encoding="utf-8")
    data, shas = doc.load_inputs(results)
    with pytest.raises(doc.DocError, match="não é número"):
        doc.build_block(data, shas)


# ---- a aplicação no PROJECT.md

def test_apply_crlf_keeps_prefix_and_endings(results):
    b = block_of(results)
    original = ANCHOR_TEXT.replace("\n", "\r\n").encode("utf-8")
    new = doc.apply_block(original, b)
    assert new.startswith(original.rstrip(b"\r\n"))
    assert b"\n" not in new.replace(b"\r\n", b"")
    text = new.decode("utf-8")
    assert text.index(doc.ANCHOR) < text.index(doc.START) < text.index(doc.END)
    assert text.endswith("\r\n")  # o fim de arquivo original foi mantido
    assert doc.apply_block(new, b) is None  # idempotente


def test_apply_lf_keeps_lf(results):
    b = block_of(results)
    new = doc.apply_block(ANCHOR_TEXT.encode("utf-8"), b)
    assert b"\r" not in new
    assert doc.apply_block(new, b) is None


def test_existing_different_block_refuses(results):
    b = block_of(results)
    new = doc.apply_block(ANCHOR_TEXT.encode("utf-8"), b)
    with pytest.raises(doc.DocError, match="diferente"):
        doc.apply_block(new, b.replace("39 min", "38 min"))


@pytest.mark.parametrize("text, match", [
    ("sem ancora\n", "âncora"),
    (f"{doc.ANCHOR}\nx\n{doc.ANCHOR}\n", "âncora"),
    (f"a\r\nb\n{doc.ANCHOR}\r\n", "misto"),
    (f"{doc.ANCHOR}\n{doc.START}\n", "inconsistentes"),
    (f"{doc.END}\nx\n{doc.START}\n{doc.ANCHOR}\n", "inconsistentes"),
])
def test_apply_refuses_bad_project(results, text, match):
    with pytest.raises(doc.DocError, match=match):
        doc.apply_block(text.encode("utf-8"), block_of(results))


def test_main_default_shows_and_writes_nothing(results, tmp_path, capsys):
    proj = tmp_path / "PROJECT.md"
    proj.write_bytes(ANCHOR_TEXT.encode("utf-8"))
    before = proj.read_bytes()
    assert doc.main(["--projeto", str(proj), "--results-dir", str(results)]) == 0
    assert proj.read_bytes() == before
    assert "nada gravado" in capsys.readouterr().out


def test_main_aplicar_then_already_applied(results, tmp_path, capsys):
    proj = tmp_path / "PROJECT.md"
    proj.write_bytes(ANCHOR_TEXT.replace("\n", "\r\n").encode("utf-8"))
    args = ["--projeto", str(proj), "--results-dir", str(results), "--aplicar"]
    assert doc.main(args) == 0
    after = proj.read_bytes()
    assert doc.START.encode() in after and not list(tmp_path.glob("*.tmp"))
    assert doc.main(args) == 0
    assert proj.read_bytes() == after
    assert "já aplicado" in capsys.readouterr().out


def test_main_refuses_without_project(results, tmp_path):
    assert doc.main(["--projeto", str(tmp_path / "nada.md"), "--results-dir", str(results),
                     "--aplicar"]) == 1


def test_main_refuses_when_csv_missing_and_writes_nothing(results, tmp_path):
    proj = tmp_path / "PROJECT.md"
    proj.write_bytes(ANCHOR_TEXT.encode("utf-8"))
    (results / "dia6_deriva_dia_estabilidade.csv").unlink()
    assert doc.main(["--projeto", str(proj), "--results-dir", str(results), "--aplicar"]) == 1
    assert proj.read_bytes() == ANCHOR_TEXT.encode("utf-8")
