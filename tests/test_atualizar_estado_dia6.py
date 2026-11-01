"""Testes de scripts/atualizar_estado_dia6.py (Dia 6), com git simulado e CSVs sintéticos."""
from __future__ import annotations

import csv
import importlib.util
import json
import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(_SCRIPTS))
_SPEC = importlib.util.spec_from_file_location("atualizar_estado_dia6", _SCRIPTS / "atualizar_estado_dia6.py")
est = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = est
_SPEC.loader.exec_module(est)

COMMITS = [("aaa1111", "primeiro commit"), ("bbb2222", "segundo | com barra e acento: viés")]
PROJECT = f"# Titulo\nStatus: Dia 5 de 9\n\n{est.ANCHOR}\n"


def fake_git(dirty=False, base_ok=True, commits=COMMITS):
    def git(*args):
        if args[:2] == ("status", "--porcelain"):
            return " M x.py\n" if dirty else ""
        if args[0] == "cat-file":
            if not base_ok:
                raise est.StateError("git cat-file falhou")
            return ""
        if args[:2] == ("rev-parse", "--abbrev-ref"):
            return "master\n"
        if args[:2] == ("rev-parse", "--short"):
            return "ccc3333\n"
        if args[0] == "log":
            return "".join(f"{h}\t{s}\n" for h, s in commits)
        raise AssertionError(args)
    return git


def write(path: Path, cols, rows) -> None:
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(cols)
        for r in rows:
            w.writerow([r.get(c, "") for c in cols])


@pytest.fixture
def results(tmp_path):
    d = tmp_path / "res"
    d.mkdir()
    write(d / "dia6_coleta1_inventario.csv", ("job_id", "n_bits", "uso_qpu_s"),
          [{"job_id": "j1", "n_bits": "1500096", "uso_qpu_s": "5"},
           {"job_id": "j2", "n_bits": "1500096", "uso_qpu_s": "5"}])
    lot = []
    for fonte, ok, h, bits in (("qpu_real", "False", "0.9622541177", "0"), ("simulador", "False", "0.9591528", "0"),
                               ("os", "True", "0.9694924", "1359324")):
        for lote in ("1", "2"):
            lot.append({"fonte": fonte, "lote": lote, "saude_approved": ok, "saude_h_estimated": h,
                        "ext_n_output_bits": bits})
    write(d / "dia6_qpu_vs_sim_lotes.csv",
          ("fonte", "lote", "saude_approved", "saude_h_estimated", "ext_n_output_bits"), lot)
    fixo = [
        {"tipo": "qubit", "grupo": "vies", "id": "14", "lote": "cal_001", "testavel": "True", "replica": "False"},
        {"tipo": "qubit", "grupo": "vies", "id": "14", "lote": "cal_002", "testavel": "True", "replica": "True"},
        {"tipo": "par", "grupo": "par", "id": "130-131", "lote": "cal_001", "testavel": "False", "replica": ""},
        {"tipo": "qubit", "grupo": "vies", "id": "14", "lote": "coleta1_001", "testavel": "", "replica": ""},
    ]
    write(d / "dia6_deriva_dia_conjunto_fixo.csv", ("tipo", "grupo", "id", "lote", "testavel", "replica"), fixo)
    write(d / "dia6_qpu_vs_sim_resumo.csv", ("x",), [{"x": "1"}])
    (d / "outro_arquivo.csv").write_text("a\n1\n", encoding="utf-8")  # não é dia6_*: fica de fora
    return d


def run_main(tmp_path, results, *extra, project=PROJECT, crlf=False, git=None):
    proj = tmp_path / "PROJECT.md"
    if not proj.exists():
        proj.write_bytes((project.replace("\n", "\r\n") if crlf else project).encode("utf-8"))
    js = tmp_path / "estado.json"
    argv = ["--suite", "2500 passed, 1 skipped", "--projeto", str(proj), "--results-dir", str(results),
            "--json", str(js), *extra]
    rc = est.main(argv, git=git or fake_git(), today="2026-11-01")
    return rc, proj, js


# ---- conteúdo

def test_block_has_everything_from_sources(results):
    info = est.git_info(fake_git(), "23d328a")
    facts = est.read_facts(results)
    b = est.build_block(info, facts, "2500 passed, 1 skipped")
    assert b.startswith(est.START) and b.endswith(est.END)
    assert "`ccc3333`" in b and "`master`" in b and "2500 passed, 1 skipped" in b
    assert "| `aaa1111` | primeiro commit |" in b
    assert "segundo \\| com barra e acento: viés" in b
    assert "2 jobs, 3000192 bits, 10 s de QPU" in b
    assert "dia6_coleta1_inventario.csv" in b and "dia6_qpu_vs_sim_resumo.csv" in b
    assert "outro_arquivo.csv" not in b
    for pid in ("T11", "COLETA2", "DEP_SESSAO", "R8", "R11", "R12", "BACKUP_RESULTADOS"):
        assert f"| {pid} |" in b
    assert "Status deste documento não foi alterado" in b
    assert "None" not in b


def test_json_content(results):
    info = est.git_info(fake_git(), "23d328a")
    facts = est.read_facts(results)
    p = est.build_json(info, facts, "2500 passed, 1 skipped", "2026-11-01")
    assert p["data_do_estado"] == "2026-11-01"
    assert p["estado_do_repositorio"]["commits_desde_a_base"][0] == {"hash": "aaa1111", "titulo": "primeiro commit"}
    assert p["resultados_dia6"]["coleta_1"] == {"jobs": ["j1", "j2"], "bits_totais": 3000192, "uso_qpu_s": 10.0}
    saude = p["resultados_dia6"]["e1_parcial"]["saude_por_lote"]
    assert [(s["fonte"], s["lote"], s["aprovado"]) for s in saude] == [
        ("qpu_real", "1", False), ("qpu_real", "2", False), ("simulador", "1", False),
        ("simulador", "2", False), ("os", "1", True), ("os", "2", True)]
    assert saude[0]["h_estimada"] == pytest.approx(0.962254, abs=1e-6)
    cal = {c["item"]: c for c in p["resultados_dia6"]["e1_parcial"]["cal_contra_coleta1"]}
    assert cal["qubit 14"]["replica_em"] == ["cal_002"] and cal["qubit 14"]["nao_replica_em"] == ["cal_001"]
    assert cal["par 130-131"]["nao_testavel_em"] == ["cal_001"]
    assert [x["id"] for x in p["pendencias"]][:2] == ["T11", "COLETA2"]
    assert p["orcamento"]["limite_total_s"] == est.config.QPU_TOTAL_BUDGET_SECONDS
    assert "comando_de_abertura_sugerido" in p and p["modelo_recomendado_para_o_proximo_chat"]["modelo"]


# ---- recusas

def test_dirty_tree_refuses(results):
    with pytest.raises(est.StateError, match="alterações"):
        est.git_info(fake_git(dirty=True), "23d328a")


def test_missing_base_refuses(results):
    with pytest.raises(est.StateError):
        est.git_info(fake_git(base_ok=False), "23d328a")


def test_no_commits_refuses():
    with pytest.raises(est.StateError, match="nenhum commit"):
        est.git_info(fake_git(commits=[]), "23d328a")


@pytest.mark.parametrize("suite", ["", "passou", "2500", "2500 passed, 1 failed", "2500 passed; 1 skipped"])
def test_bad_suite_refuses(tmp_path, results, suite):
    proj = tmp_path / "PROJECT.md"
    proj.write_bytes(PROJECT.encode("utf-8"))
    rc = est.main(["--suite", suite, "--projeto", str(proj), "--results-dir", str(results),
                   "--json", str(tmp_path / "e.json")], git=fake_git())
    assert rc == 1 and not (tmp_path / "e.json").exists()


@pytest.mark.parametrize("text, match", [
    ("sem ancora\n", "âncora"),
    (f"{est.ANCHOR}\nx\n{est.ANCHOR}\n", "âncora"),
    (f"a\r\nb\n{est.ANCHOR}\r\n", "misto"),
    (f"{est.ANCHOR}\n{est.START}\n", "inconsistentes"),
    (f"{est.END}\nx\n{est.START}\n{est.ANCHOR}\n", "inconsistentes"),
])
def test_inspect_refuses_bad_project(text, match):
    with pytest.raises(est.StateError, match=match):
        est.inspect_project(text.encode("utf-8"))


def test_missing_csv_refuses(tmp_path, results):
    (results / "dia6_deriva_dia_conjunto_fixo.csv").unlink()
    rc, proj, js = run_main(tmp_path, results, "--aplicar")
    assert rc == 1 and not js.exists() and proj.read_bytes() == PROJECT.encode("utf-8")


# ---- gravação

def test_default_writes_nothing(tmp_path, results, capsys):
    rc, proj, js = run_main(tmp_path, results)
    assert rc == 0 and not js.exists()
    assert proj.read_bytes() == PROJECT.encode("utf-8")
    assert "nada gravado" in capsys.readouterr().out


def test_aplicar_crlf_keeps_prefix_and_endings(tmp_path, results):
    rc, proj, js = run_main(tmp_path, results, "--aplicar", crlf=True)
    original = PROJECT.replace("\n", "\r\n").encode("utf-8")
    new = proj.read_bytes()
    assert rc == 0 and new.startswith(original.rstrip(b"\r\n"))
    assert b"\n" not in new.replace(b"\r\n", b"")
    text = new.decode("utf-8")
    assert text.index(est.ANCHOR) < text.index(est.START) < text.index(est.END)
    assert "Status: Dia 5 de 9" in text  # o campo Status não é tocado
    data = json.loads(js.read_text(encoding="utf-8"))
    assert data["tipo"] == "estado_para_novo_chat" and "viés" in js.read_text(encoding="utf-8")
    assert not list(tmp_path.glob("*.tmp"))


def test_aplicar_lf_keeps_lf(tmp_path, results):
    rc, proj, _ = run_main(tmp_path, results, "--aplicar")
    assert rc == 0 and b"\r" not in proj.read_bytes()


def test_second_run_is_already_registered_and_changes_nothing(tmp_path, results, capsys):
    rc, proj, js = run_main(tmp_path, results, "--aplicar")
    after_p, after_j = proj.read_bytes(), js.read_bytes()
    rc2, _, _ = run_main(tmp_path, results, "--aplicar", git=fake_git(commits=COMMITS + [("ddd4444", "novo")]))
    assert rc == 0 and rc2 == 0
    assert proj.read_bytes() == after_p and js.read_bytes() == after_j
    assert "já registrado" in capsys.readouterr().out


def test_json_exists_without_block_refuses(tmp_path, results):
    (tmp_path / "estado.json").write_text("{}", encoding="utf-8")
    rc, proj, js = run_main(tmp_path, results, "--aplicar")
    assert rc == 1 and js.read_text(encoding="utf-8") == "{}"
    assert proj.read_bytes() == PROJECT.encode("utf-8")


def test_dirty_tree_main_refuses_and_writes_nothing(tmp_path, results):
    rc, proj, js = run_main(tmp_path, results, "--aplicar", git=fake_git(dirty=True))
    assert rc == 1 and not js.exists() and proj.read_bytes() == PROJECT.encode("utf-8")


def test_stale_tmp_refuses(tmp_path, results):
    (tmp_path / "PROJECT.md.tmp").write_text("x", encoding="utf-8")
    rc, proj, js = run_main(tmp_path, results, "--aplicar")
    assert rc == 1 and not js.exists()
