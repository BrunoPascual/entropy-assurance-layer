"""Testes da demo ao vivo: sem rede e sem QPU (coletor falso e lotes sintéticos)."""
import json
import re
from types import SimpleNamespace

import numpy as np
import pytest

from eal.sources.base import RawBatch
from eal.storage import save_batch
from scripts import demo_ao_vivo as demo

NQ, SHOTS = 156, 400


def _batch(p1: float = 0.5, seed: int = 1, job_id: str = "jobfalso123") -> RawBatch:
    rng = np.random.default_rng(seed)
    bits = (rng.random(NQ * SHOTS) < p1).astype(np.uint8)
    params = {"n_qubits": NQ, "shots": SHOTS, "physical_qubits": list(range(NQ)), "job_id": job_id,
              "backend": "ibm_kingston", "calibration_date_run": "2026-11-06 10:00:00-03:00"}
    return RawBatch(source_id="ibm_kingston", source_type="qpu_ibm", source_version="0.1.0", is_local=False,
                    is_simulated=False, bits=bits, params=params)


def _os_reader(n):
    rng = np.random.default_rng(99)
    return RawBatch(source_id="os", source_type="os", source_version="0.1.0", is_local=True, is_simulated=False,
                    bits=rng.integers(0, 2, n, dtype=np.uint8), params={})


def _heavy_hex_edges():
    e = [(i, i + 1) for i in range(156 - 1) if i % 20 < 15]
    for r in range(7):
        for k, c in enumerate((3, 7, 11, 15) if r % 2 == 0 else (1, 5, 9, 13)):
            b = 20 * r + 16 + k
            e += [(20 * r + c, b), (b, 20 * (r + 1) + c)]
    return e


def test_chip_layout_heavy_hex():
    pos = demo.chip_layout(156, _heavy_hex_edges())
    assert pos[0] == (0.0, 0.0) and pos[15] == (15.0, 0.0) and pos[20] == (0.0, 1.0)
    assert pos[16] == (3.0, 0.5) and pos[36] == (1.0, 1.5)


def test_chip_layout_cai_na_grade_se_o_mapa_nao_for_heavy_hex():
    pos = demo.chip_layout(40, [(16, 17)])  # ponte sem vizinho de fileira
    assert pos[14] == (1.0, 1.0) and len(pos) == 40


def test_page_data_e_html(tmp_path):
    b = _batch(p1=0.53)
    npy = save_batch(b, "t", tmp_path)
    d = demo.analyze(npy, mode="gravado", quantum_seconds=5.0, wait_seconds=None,
                     os_reader=_os_reader, edges=_heavy_hex_edges())
    assert d["n_bits"] == NQ * SHOTS and len(d["qubits"]) == NQ and d["mosaico"]["colunas"] == NQ
    assert d["mosaico"]["linhas"] == min(demo.MOSAIC_SHOTS, SHOTS)
    assert not d["qpu"]["aprovado"] and d["frac1"] > 0.52  # viés de 3% reprova no monobit
    assert [t["nome"] for t in d["qpu"]["testes"]][4] == "Frequência (monobit)"
    assert d["duplicado_verificado"] is False  # no ensaio a comparação com lotes anteriores não roda
    html = demo.render_html(d)
    payload = re.search(r'<script id="dados" type="application/json">(.*?)</script>', html, re.S).group(1)
    assert json.loads(payload)["job_id"] == "jobfalso123"
    assert "__DADOS__" not in html and "__TITULO__" not in html


def test_render_html_escapa_fechamento_de_script():
    d = {"job_id": "x</script><b>", "backend": "b"}
    html = demo.render_html(d)
    assert "x</script><b>" not in html and "x<\\/script><b>" in html


class FakeCollector:
    def __init__(self, states):
        self.states = list(states)

    def retrieve(self, job_id):
        return self.states.pop(0)


def R(state, **kw):
    base = dict(state=state, job_id="j", status=None, output_file="", quantum_seconds=None, duplicate_of="")
    base.update(kw)
    return SimpleNamespace(**base)


def _clock(step=4.0):
    t = {"v": 0.0}

    def c():
        t["v"] += step
        return t["v"]
    return c


def test_wait_for_espera_a_fila_e_devolve_o_lote():
    col = FakeCollector([R("pending", status="QUEUED"), R("pending", status="RUNNING"),
                         R("final", output_file="a.npy", quantum_seconds=5.0)])
    out = []
    w = demo.wait_for(col, "j", out.append, sleep=lambda s: None, clock=_clock())
    assert w.output_file == "a.npy" and w.quantum_seconds == 5.0 and w.duplicate_of == ""
    assert any("QUEUED" in o for o in out) and any("RUNNING" in o for o in out)


def test_wait_for_job_ja_fechado_nao_afirma_comparacao():
    col = FakeCollector([R("already_final", output_file="a.npy", quantum_seconds=5.0)])
    w = demo.wait_for(col, "j", lambda s: None, sleep=lambda s: None, clock=_clock())
    assert w.duplicate_of is None


def test_wait_for_uso_pendente_desiste_do_uso_mas_mostra_os_bits():
    col = FakeCollector([R("usage_pending", output_file="a.npy")] * 100)
    w = demo.wait_for(col, "j", lambda s: None, sleep=lambda s: None, clock=_clock(step=10.0))
    assert w.output_file == "a.npy" and w.quantum_seconds is None and w.duplicate_of is None


def test_wait_for_job_falho():
    col = FakeCollector([R("failed", status="ERROR")])
    assert demo.wait_for(col, "j", lambda s: None, sleep=lambda s: None, clock=_clock()) is None


def test_run_ensaio_grava_pagina_sem_abrir(tmp_path, monkeypatch):
    npy = save_batch(_batch(), "t", tmp_path / "raw")
    monkeypatch.setattr(demo, "kingston_edges", lambda: _heavy_hex_edges())
    from eal.sources import os_source
    monkeypatch.setattr(os_source.OsSource, "read", lambda self, n: _os_reader(n))
    opened = []
    monkeypatch.setattr(demo.webbrowser, "open", opened.append)
    args = demo.build_parser().parse_args(["--arquivo", str(npy), "--out-dir", str(tmp_path / "out"),
                                           "--logs-dir", str(tmp_path / "logs"), "--nao-abrir"])
    out = []
    assert demo.run(args, out.append) == 0
    pages = list((tmp_path / "out").glob("*.html"))
    assert len(pages) == 1 and not opened
    assert '"modo": "gravado"' in pages[0].read_text(encoding="utf-8")


def test_run_ctrl_c_na_espera_explica_como_retomar(tmp_path, monkeypatch):
    class Boom:
        def retrieve(self, job_id):
            raise KeyboardInterrupt
    monkeypatch.setattr(demo, "_ctx_and_collector", lambda args, out: (None, None, Boom()))
    args = demo.build_parser().parse_args(["--job", "abc123", "--nao-abrir"])
    out = []
    assert demo.run(args, out.append) == demo.EXIT_ERROR
    assert any("--job abc123" in o for o in out)


def test_main_recusa_job_e_arquivo_juntos(capsys):
    assert demo.main(["--job", "x", "--arquivo", "y"]) == 2


def _analisa(tmp_path, p1, seed=1):
    npy = save_batch(_batch(p1=p1, seed=seed), "t", tmp_path)
    return demo.analyze(npy, mode="gravado", quantum_seconds=5.0, wait_seconds=None,
                        os_reader=_os_reader, edges=_heavy_hex_edges())


def test_veredito_so_chama_de_visivel_quando_o_z_justifica(tmp_path):
    d = _analisa(tmp_path, 0.53)
    assert abs(d["z_total"]) >= demo.Z_VISIVEL
    texto = " ".join(d["veredito"])
    assert "estatisticamente visível" in texto and "Frequência (monobit)" in texto


def test_veredito_reprovado_sem_desvio_nao_alega_visibilidade(tmp_path):
    d = _analisa(tmp_path, 0.5)
    d["qpu"] = {"aprovado": False, "testes": [
        {"nome": "Repetição (RCT)", "ok": False}, {"nome": "Frequência (monobit)", "ok": True}]}
    d["frac1"], d["z_total"] = 0.5002, 0.3
    texto = " ".join(demo.verdict_paragraphs(d))
    assert "estatisticamente visível" not in texto and "Falhou em: Repetição (RCT)." in texto
    assert "não vem da frequência" in texto


def test_veredito_aprovado_usa_a_contagem_real_de_testes(tmp_path):
    d = _analisa(tmp_path, 0.5)
    d["qpu"]["aprovado"] = True
    texto = demo.verdict_paragraphs(d)[0]
    assert f"nos {len(d['qpu']['testes'])} testes" in texto and "Falhou" not in texto
