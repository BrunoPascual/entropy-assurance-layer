"""Testes de scripts/e2_ataques.py com fontes e avaliação falsas (sem eal real)."""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import itertools
import json
import sys
from pathlib import Path

import numpy as np
import pytest

_CAMINHO = Path(__file__).resolve().parents[1] / "scripts" / "e2_ataques.py"
_spec = importlib.util.spec_from_file_location("e2_ataques", _CAMINHO)
e2 = importlib.util.module_from_spec(_spec)
sys.modules["e2_ataques"] = e2
_spec.loader.exec_module(e2)


# ---------------------------------------------------------------- falsos
class FakeBatch:
    _ids = itertools.count()

    def __init__(self, source_id, bits, params, n_bits):
        self.n_bits = n_bits
        self.source_id = source_id
        self.bits = bits
        self.params = params
        self.batch_id = f"b{next(self._ids)}"
        self.batch_hash = hashlib.sha256(bits.tobytes() + self.batch_id.encode()).hexdigest()


class FakeSource:
    criadas: list = []

    def __init__(self, source_id, valor, seed):
        self.source_id, self.valor, self.seed = source_id, valor, seed
        self.leituras = 0
        FakeSource.criadas.append(self)

    def read(self, n_bits):
        self.leituras += 1
        params = {"seed": self.seed}
        if self.source_id == "faulty_replay":
            params["replayed"] = self.leituras > 1
        return FakeBatch(self.source_id, np.zeros(8, dtype=np.uint8), params, n_bits)


class FakeDetector:
    criados = 0

    def __init__(self):
        FakeDetector.criados += 1
        self.vistos = []


class FakeReport:
    def __init__(self, d):
        self._d = d

    def to_dict(self):
        return dict(self._d)


def fake_avaliar(batch, detector):
    repetido = batch.params.get("replayed", False)
    detector.vistos.append(batch.batch_id)
    sid = batch.source_id
    reprovado = repetido or sid in ("faulty_biased", "faulty_correlated", "faulty_stuck")
    return FakeReport({
        "n_bits": batch.n_bits,
        "approved": np.bool_(not reprovado),
        "rct_pass": sid != "faulty_stuck", "apt_pass": sid != "faulty_biased",
        "apt_inconclusive": False, "replay_pass": not repetido,
        "h_health_pass": sid not in ("faulty_correlated", "faulty_biased"), "stats_pass": sid != "faulty_correlated",
        "stats_inconclusive": sid == "faulty_correlated",
        "h_estimated": 0.96, "rct_max_run": 20, "apt_max_count": 540,
        "stats": {"monobit": 0.5}, "reasons": ["replay: lote repetido"] if repetido else [],
    })


def fabricas_falsas():
    return {f: (lambda v, s, f=f: FakeSource(f, v, s))
            for f in ("faulty_biased", "faulty_correlated", "faulty_stuck",
                      "faulty_prng", "faulty_replay", "os")}


def rodar(c):
    return e2.rodar_celula(c, fabricas_falsas(), FakeDetector, fake_avaliar, "abc123")


@pytest.fixture(autouse=True)
def _limpa():
    FakeSource.criadas = []
    FakeDetector.criados = 0


# ---------------------------------------------------------------- pré-registro
def test_grade_pre_registrada():
    assert e2.GRADE == (
        ("faulty_biased", "p", (0.501, 0.502, 0.505, 0.51, 0.55)),
        ("faulty_correlated", "rho", (0.501, 0.502, 0.505, 0.51, 0.6)),
        ("faulty_stuck", "run_length", (8, 16, 24, 32, 64)),
        ("faulty_prng", "", (None,)),
        ("faulty_replay", "", (None,)),
    )
    assert e2.STUCK_EVERY == 1024
    assert e2.TAMANHOS == (1_000_000, 4_000_000)
    assert e2.REPS == {1_000_000: 20, 4_000_000: 10}
    assert e2.REPS_OS == {1_000_000: 200, 4_000_000: 50}


def test_total_de_lotes_790():
    assert sum(c.n_lotes for c in e2.celulas()) == 790
    por_n = {}
    for c in e2.celulas():
        por_n[c.n_bits] = por_n.get(c.n_bits, 0) + c.n_lotes
    assert por_n == {1_000_000: 560, 4_000_000: 230}


def test_medir_tempo_usa_2_por_celula_e_mesmas_celulas():
    mt = e2.celulas_medir_tempo()
    assert all(c.reps == 2 for c in mt)
    assert [(c.fonte, c.valor, c.n_bits) for c in mt] == \
        [(c.fonte, c.valor, c.n_bits) for c in e2.celulas()]


# ---------------------------------------------------------------- sementes
def test_semente_deterministica_e_distinta_na_grade():
    sementes = [e2.semente(c.fonte, c.valor, c.n_bits, r)
                for c in e2.celulas() if c.fonte != "os" for r in range(c.reps)]
    assert len(sementes) == len(set(sementes))
    assert all(0 <= s < 2**64 for s in sementes)
    assert e2.semente("faulty_biased", 0.501, 1_000_000, 3) == \
        e2.semente("faulty_biased", 0.501, 1_000_000, 3)


@pytest.mark.parametrize("args", [
    ("faulty_correlated", 0.501, 1_000_000, 3),
    ("faulty_biased", 0.502, 1_000_000, 3),
    ("faulty_biased", 0.501, 4_000_000, 3),
    ("faulty_biased", 0.501, 1_000_000, 4),
])
def test_semente_muda_com_cada_argumento(args):
    assert e2.semente(*args) != e2.semente("faulty_biased", 0.501, 1_000_000, 3)


def test_texto_valor():
    assert e2.texto_valor(None) == ""
    assert e2.texto_valor(0.51) == "0.51"
    assert e2.texto_valor(24) == "24"
    with pytest.raises(e2.E2Erro):
        e2.texto_valor(True)
    with pytest.raises(e2.E2Erro):
        e2.texto_valor("0.5")


# ---------------------------------------------------------------- células
def test_celula_comum_instancia_e_detector_novos_por_lote():
    c = e2.Celula("faulty_biased", "p", 0.55, 1_000_000, 5)
    linhas = rodar(c)
    assert len(linhas) == 5
    assert len(FakeSource.criadas) == 5 and FakeDetector.criados == 5
    assert [l["repeticao"] for l in linhas] == ["0", "1", "2", "3", "4"]
    assert all(l["leitura"] == "1" for l in linhas)
    for r, (fonte, l) in enumerate(zip(FakeSource.criadas, linhas)):
        s = e2.semente("faulty_biased", 0.55, 1_000_000, r)
        assert fonte.seed == s and l["semente"] == str(s) and fonte.valor == 0.55


def test_replay_um_detector_por_par_duas_leituras():
    c = e2.Celula("faulty_replay", "", None, 1_000_000, 3)
    linhas = rodar(c)
    assert len(linhas) == 6
    assert len(FakeSource.criadas) == 3 and FakeDetector.criados == 3
    assert [l["leitura"] for l in linhas] == ["1", "2"] * 3
    assert [l["approved"] for l in linhas] == ["True", "False"] * 3


def test_os_sem_semente():
    linhas = rodar(e2.Celula("os", "", None, 1_000_000, 3))
    assert all(l["semente"] == "" for l in linhas)
    assert all(f.seed is None for f in FakeSource.criadas)


def test_recusa_fonte_errada():
    fab = fabricas_falsas()
    fab["faulty_biased"] = lambda v, s: FakeSource("os", v, s)
    with pytest.raises(e2.E2Erro, match="lote de"):
        e2.rodar_celula(e2.Celula("faulty_biased", "p", 0.55, 1_000_000, 1),
                        fab, FakeDetector, fake_avaliar, "x")


def test_recusa_semente_diferente():
    fab = fabricas_falsas()
    fab["faulty_biased"] = lambda v, s: FakeSource("faulty_biased", v, 2026)
    with pytest.raises(e2.E2Erro, match="semente"):
        e2.rodar_celula(e2.Celula("faulty_biased", "p", 0.55, 1_000_000, 1),
                        fab, FakeDetector, fake_avaliar, "x")


def test_recusa_replay_que_nao_repete():
    class SemReplay(FakeSource):
        def read(self, n_bits):
            b = super().read(n_bits)
            b.params["replayed"] = False
            return b

    fab = fabricas_falsas()
    fab["faulty_replay"] = lambda v, s: SemReplay("faulty_replay", v, s)
    with pytest.raises(e2.E2Erro, match="replay"):
        e2.rodar_celula(e2.Celula("faulty_replay", "", None, 1_000_000, 1),
                        fab, FakeDetector, fake_avaliar, "x")


def test_recusa_n_bits_do_relatorio_diferente():
    def avaliar_errado(batch, detector):
        batch.n_bits = 999
        return fake_avaliar(batch, detector)

    with pytest.raises(e2.E2Erro, match="n_bits"):
        e2.rodar_celula(e2.Celula("os", "", None, 1_000_000, 1),
                        fabricas_falsas(), FakeDetector, avaliar_errado, "x")


def test_flag_nao_booleana_recusa():
    with pytest.raises(e2.E2Erro):
        e2._flag("approved", None)
    with pytest.raises(e2.E2Erro):
        e2._flag("approved", 1)
    assert e2._flag("approved", np.bool_(False)) == "False"


def test_linha_reasons_e_stats_em_json():
    linhas = rodar(e2.Celula("faulty_replay", "", None, 1_000_000, 1))
    assert json.loads(linhas[1]["reasons"]) == ["replay: lote repetido"]
    assert json.loads(linhas[0]["stats_json"]) == {"monobit": 0.5}
    assert linhas[0]["commit"] == "abc123" and linhas[0]["schema"] == e2.SCHEMA


# ---------------------------------------------------------------- resumo
def test_clopper_pearson_valores_conhecidos():
    assert e2.clopper_pearson(0, 20) == pytest.approx((0.0, 0.168433), abs=1e-6)
    assert e2.clopper_pearson(20, 20) == pytest.approx((0.831567, 1.0), abs=1e-6)
    inf, sup = e2.clopper_pearson(10, 20)
    # referência: soma binomial resolvida por bissecção, sem scipy
    assert inf == pytest.approx(0.271958, abs=1e-6) and sup == pytest.approx(0.728042, abs=1e-6)
    with pytest.raises(e2.E2Erro):
        e2.clopper_pearson(3, 2)
    with pytest.raises(e2.E2Erro):
        e2.clopper_pearson(0, 0)


def test_tipo_grupo():
    assert e2.tipo_grupo("os", "1") == "falso_positivo"
    assert e2.tipo_grupo("faulty_replay", "1") == "referencia"
    assert e2.tipo_grupo("faulty_replay", "2") == "deteccao"
    assert e2.tipo_grupo("faulty_prng", "1") == "deteccao"


def test_resumo_conta_e_separa_grupos():
    linhas = (rodar(e2.Celula("faulty_biased", "p", 0.55, 1_000_000, 4))
              + rodar(e2.Celula("faulty_replay", "", None, 1_000_000, 3))
              + rodar(e2.Celula("os", "", None, 1_000_000, 5)))
    res = e2.resumir(linhas)
    chaves = [(r["fonte"], r["leitura"], r["tipo"]) for r in res]
    assert chaves == [("faulty_biased", "1", "deteccao"), ("faulty_replay", "1", "referencia"),
                      ("faulty_replay", "2", "deteccao"), ("os", "1", "falso_positivo")]
    b, r1, r2, o = res
    assert (b["n_lotes"], b["n_reprovados"], b["taxa"], b["n_apt_falhou"]) == ("4", "4", "1.0000", "4")
    assert (r1["n_reprovados"], r2["n_reprovados"], r2["n_replay_falhou"]) == ("0", "3", "3")
    assert (o["n_lotes"], o["n_reprovados"], o["ic95_inf"]) == ("5", "0", "0.0000")
    assert o["h_estimada_min"] == "0.960000"


def test_resumo_contagem_por_teste():
    linhas = (rodar(e2.Celula("faulty_correlated", "rho", 0.6, 1_000_000, 3))
              + rodar(e2.Celula("faulty_stuck", "run_length", 64, 1_000_000, 2))
              + rodar(e2.Celula("faulty_biased", "p", 0.55, 1_000_000, 4)))
    c, st, b = e2.resumir(linhas)
    contagens = ("n_rct_falhou", "n_apt_falhou", "n_replay_falhou", "n_h_falhou",
                 "n_stats_falhou", "n_stats_inconclusivo")
    assert [c[k] for k in contagens] == ["0", "0", "0", "3", "3", "3"]
    assert [st[k] for k in contagens] == ["2", "0", "0", "0", "0", "0"]
    assert [b[k] for k in contagens] == ["0", "4", "0", "4", "0", "0"]
    assert (c["n_reprovados"], st["n_reprovados"]) == ("3", "2")


def test_resumo_recusa_flag_invalida_e_schema():
    linhas = rodar(e2.Celula("os", "", None, 1_000_000, 2))
    ruim = [dict(linhas[0], approved="true")]
    with pytest.raises(e2.E2Erro, match="approved"):
        e2.resumir(ruim)
    with pytest.raises(e2.E2Erro, match="schema"):
        e2.resumir([dict(linhas[0], schema="outro")])
    with pytest.raises(e2.E2Erro):
        e2.resumir([])


# ---------------------------------------------------------------- main
def _main(tmp_path, *args, limpo=True):
    saida = []
    codigo = e2.main(list(args), raiz=tmp_path, fabricas=fabricas_falsas(),
                     saude=(FakeDetector, fake_avaliar),
                     git=lambda r: ("f" * 40, limpo), saida=saida.append)
    return codigo, saida


def test_rodar_grava_os_dois_csvs(tmp_path):
    codigo, saida = _main(tmp_path, "--rodar")
    assert codigo == 0, saida
    pasta = tmp_path / "data" / "results"
    lotes = e2.ler_lotes(pasta / "e2_lotes.csv")
    assert len(lotes) == 790
    with (pasta / "e2_resumo.csv").open(encoding="utf-8", newline="") as f:
        resumo = list(csv.DictReader(f))
    assert sum(int(r["n_lotes"]) for r in resumo) == 790
    assert len(resumo) == 2 * (5 + 5 + 5 + 1 + 2 + 1)
    for nome in ("e2_lotes.csv", "e2_resumo.csv"):
        dados = (pasta / nome).read_bytes()
        assert f"{nome}: {hashlib.sha256(dados).hexdigest()}" in saida
        assert b"\r\n" not in dados
    assert not list(pasta.glob("*.tmp"))


def test_rodar_recusa_arvore_suja(tmp_path):
    codigo, saida = _main(tmp_path, "--rodar", limpo=False)
    assert codigo == 1 and "RECUSADO" in saida[-1]
    assert not (tmp_path / "data" / "results" / "e2_lotes.csv").exists()


@pytest.mark.parametrize("nome", ["e2_lotes.csv", "e2_resumo.csv"])
def test_rodar_recusa_se_saida_existe(tmp_path, nome):
    pasta = tmp_path / "data" / "results"
    pasta.mkdir(parents=True)
    (pasta / nome).write_bytes(b"x")
    codigo, saida = _main(tmp_path, "--rodar")
    assert codigo == 1 and "já existe" in saida[-1]
    assert (pasta / nome).read_bytes() == b"x"
    assert sorted(p.name for p in pasta.iterdir()) == [nome]


def test_resumir_idempotente_e_recusa_se_diferente(tmp_path):
    assert _main(tmp_path, "--rodar")[0] == 0
    pasta = tmp_path / "data" / "results"
    codigo, saida = _main(tmp_path, "--resumir")
    assert codigo == 0 and "já existia igual" in saida[-1]
    (pasta / "e2_resumo.csv").write_bytes(b"outro")
    codigo, saida = _main(tmp_path, "--resumir")
    assert codigo == 1 and "difere" in saida[-1]
    assert (pasta / "e2_resumo.csv").read_bytes() == b"outro"
    (pasta / "e2_resumo.csv").unlink()
    codigo, _ = _main(tmp_path, "--resumir")
    assert codigo == 0 and (pasta / "e2_resumo.csv").exists()


def test_gravar_novo_nao_sobrescreve(tmp_path):
    alvo = tmp_path / "a.csv"
    e2.gravar_novo(alvo, b"um")
    with pytest.raises(e2.E2Erro, match="já existe"):
        e2.gravar_novo(alvo, b"dois")
    assert alvo.read_bytes() == b"um"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["a.csv"]


def test_resumir_sem_lotes_recusa(tmp_path):
    codigo, saida = _main(tmp_path, "--resumir")
    assert codigo == 1 and "não existe" in saida[-1]


def test_resumir_recusa_cabecalho_errado(tmp_path):
    pasta = tmp_path / "data" / "results"
    pasta.mkdir(parents=True)
    (pasta / "e2_lotes.csv").write_text("a,b\n1,2\n", encoding="utf-8")
    codigo, saida = _main(tmp_path, "--resumir")
    assert codigo == 1 and "cabeçalho" in saida[-1]


def test_medir_tempo_nao_grava_nem_mostra_veredito(tmp_path):
    codigo, saida = _main(tmp_path, "--medir-tempo")
    assert codigo == 0
    assert not (tmp_path / "data").exists()
    texto = "\n".join(saida).lower()
    assert "790 lotes" in texto
    for proibido in ("approved", "reprov", "aprov", "true", "false", "taxa"):
        assert proibido not in texto
    assert len(FakeSource.criadas) == sum(c.reps for c in e2.celulas_medir_tempo())


def test_modos_exclusivos(tmp_path):
    with pytest.raises(SystemExit):
        _main(tmp_path, "--rodar", "--resumir")
    with pytest.raises(SystemExit):
        _main(tmp_path)
