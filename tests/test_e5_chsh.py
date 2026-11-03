"""Testes de scripts/e5_chsh.py. A conta exata usa o Qiskit real; o ruído real usa o FakeKingston."""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import math
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

_CAMINHO = Path(__file__).resolve().parents[1] / "scripts" / "e5_chsh.py"
_spec = importlib.util.spec_from_file_location("e5_chsh", _CAMINHO)
e5 = importlib.util.module_from_spec(_spec)
sys.modules["e5_chsh"] = e5
_spec.loader.exec_module(e5)

R2 = 1 / math.sqrt(2)


class RuidoFalso:
    """Mistura 90% das probabilidades exatas com 10% uniforme, amostrada pela semente."""

    info = {"par_fisico": "1-2", "erro_cz": "0.01", "erro_leitura_q0": "0.02",
            "erro_leitura_q1": "0.03", "calibracao_backend": "2026-04-15T09:15:15+02:00",
            "n_2q_por_circuito": "1"}

    def __init__(self):
        self.probs = [0.9 * e5.probs_exatas(e5.ANGULOS_A[i], e5.ANGULOS_B[j]) + 0.025
                      for i, j in e5.AJUSTES]
        self.sementes = []

    def contagens(self, seed):
        self.sementes.append(seed)
        rng = np.random.default_rng(seed)
        return [e5.amostrar(rng, p, e5.N_SHOTS) for p in self.probs]


def motor_falso():
    return e5.Motor(probs_exatas=e5.probs_exatas, preparar_ruido=RuidoFalso)


@pytest.fixture
def pequeno(monkeypatch):
    monkeypatch.setattr(e5, "N_SHOTS", 400)
    monkeypatch.setattr(e5, "REPS", 5)
    monkeypatch.setattr(e5, "REPS_MEDIR_TEMPO", 1)


# ---------------------------------------------------------------- pré-registro
def test_pre_registro():
    fonte = _CAMINHO.read_text(encoding="utf-8")
    for trecho in (
        "ANGULOS_A = (0.0, math.pi / 2)", "ANGULOS_B = (math.pi / 4, -math.pi / 4)",
        "AJUSTES = ((0, 0), (0, 1), (1, 0), (1, 1))", "SINAIS = (1, 1, 1, -1)",
        "N_SHOTS = 4000", "REPS = 100", 'BACKEND_RUIDO = "FakeKingston"', "OPT_LEVEL = 1",
        "SEED_TRANSPILER = 2026", "K_SIGMA = 3", "TOL_EXATO = 1e-12", "LIMITE_CLASSICO = 2.0",
        "TSIRELSON = 2 * math.sqrt(2)",
    ):
        assert trecho in fonte, trecho
    assert e5.CONFIGS == ("ideal_exato", "ideal_amostrado", "ruido_fake_kingston",
                          "classico_aleatorio", "classico_otimo")


# ---------------------------------------------------------------- física
def test_circuito():
    qc = e5.circuito(0.3, -0.7)
    nomes = [ins.operation.name for ins in qc.data]
    assert nomes == ["h", "cx", "ry", "ry", "measure", "measure"]
    assert float(qc.data[2].operation.params[0]) == pytest.approx(-0.3)
    assert float(qc.data[3].operation.params[0]) == pytest.approx(0.7)
    assert [qc.find_bit(q).index for q in qc.data[1].qubits] == [0, 1]
    assert [ins.operation.name for ins in e5.circuito(0, 0, medir=False).data] == ["h", "cx", "ry", "ry"]


@pytest.mark.parametrize("ta,tb", [(0.0, 0.0), (0.0, math.pi / 4), (math.pi / 2, -math.pi / 4),
                                   (1.1, 0.2), (-0.5, 2.0)])
def test_correlacao_exata_e_cos_da_diferenca(ta, tb):
    p = e5.probs_exatas(ta, tb)
    assert p.sum() == pytest.approx(1.0) and (p >= -1e-15).all()
    assert e5.correlacao_exata(p) == pytest.approx(math.cos(ta - tb), abs=1e-12)


def test_s_exato_e_tsirelson():
    es = [e5.correlacao_exata(e5.probs_exatas(e5.ANGULOS_A[i], e5.ANGULOS_B[j])) for i, j in e5.AJUSTES]
    assert es == pytest.approx([R2, R2, R2, -R2], abs=1e-12)
    assert abs(e5.s_de(es) - 2 * math.sqrt(2)) <= 1e-12


# ---------------------------------------------------------------- contas
def test_correlacao_de_contagens():
    assert e5.correlacao({"00": 30, "11": 50, "01": 10, "10": 10}, 100) == pytest.approx(0.6)
    assert e5.correlacao({"01": 4}, 4) == -1.0
    with pytest.raises(e5.E5Erro, match="somam"):
        e5.correlacao({"00": 3}, 4)
    with pytest.raises(e5.E5Erro, match="chaves"):
        e5.correlacao({"00": 3, "2": 1}, 4)


def test_s_e_erro_padrao():
    assert e5.s_de([0.5, 0.5, 0.5, -0.5]) == 2.0
    assert e5.s_de([1, 1, 1, 1]) == 2
    assert e5.se_de([0.0, 0.0, 0.0, 0.0], 100) == pytest.approx(math.sqrt(4 / 100))
    assert e5.se_de([1, -1, 1, -1], 100) == 0.0


def test_classico_otimo_da_exatamente_2():
    es = [e5.correlacao(c, 1000) for c in e5.contagens_otimo(1000)]
    assert es == [1.0, -1.0, 1.0, -1.0] and e5.s_de(es) == 2.0 and e5.se_de(es, 1000) == 0.0


def test_semente_distinta_e_32_bits():
    ss = {e5.semente(c, r) for c in e5.CONFIGS for r in range(100)}
    assert len(ss) == 500 and all(0 <= s < 2 ** 32 for s in ss)
    assert e5.semente("ideal_amostrado", 3) == e5.semente("ideal_amostrado", 3)


# ---------------------------------------------------------------- escolha do par
class Alvo:
    def __init__(self, erros, nomes=("cz", "rz")):
        self.operation_names = set(nomes)
        self._cz = {qs: (None if e is None else SimpleNamespace(error=e)) for qs, e in erros.items()}

    def __getitem__(self, k):
        assert k == "cz"
        return self._cz


def test_escolher_par_pela_regra():
    leitura = {0: (0.01, 0.01), 1: (0.02, 0.02), 2: (0.001, 0.003), 3: (0.05, 0.05)}.__getitem__
    alvo = Alvo({(1, 0): 0.010, (0, 1): 0.012, (1, 2): 0.009, (2, 3): 0.001, (5, 6): None})
    p = e5.escolher_par(alvo, leitura)
    # custos: (0,1) 0.010+0.01+0.02 = 0.040; (1,2) 0.009+0.02+0.002 = 0.031; (2,3) 0.001+0.002+0.05 = 0.053
    assert (p["q0"], p["q1"]) == (1, 2) and p["erro_cz"] == 0.009
    assert p["ro0"] == pytest.approx(0.02) and p["ro1"] == pytest.approx(0.002)


def test_escolher_par_usa_o_menor_erro_das_duas_direcoes_e_desempata():
    leitura = lambda q: (0.0, 0.0)  # noqa: E731
    p = e5.escolher_par(Alvo({(0, 1): 0.01, (1, 0): 0.02, (3, 2): 0.01}), leitura)
    assert (p["q0"], p["q1"], p["erro_cz"]) == (0, 1, 0.01)        # menor das direções; empate: menor par


def test_escolher_par_recusa():
    with pytest.raises(e5.E5Erro, match="não tem a porta cz"):
        e5.escolher_par(Alvo({}, nomes=("ecr",)), lambda q: (0, 0))
    alvo = Alvo({(0, 1): 0.01})
    alvo._cz[(2, 3)] = SimpleNamespace(error=None)                  # erro desconhecido: ignorado
    assert (e5.escolher_par(alvo, lambda q: (0, 0))["q0"]) == 0
    with pytest.raises(e5.E5Erro, match="nenhum par"):
        e5.escolher_par(Alvo({(0, 1): None}), lambda q: (0, 0))


# ---------------------------------------------------------------- ruído real (FakeKingston)
def test_ruido_real_fake_kingston(monkeypatch):
    pytest.importorskip("qiskit_aer")
    pytest.importorskip("qiskit_ibm_runtime")
    pytest.importorskip("eal.sources.noise")
    monkeypatch.setattr(e5, "N_SHOTS", 64)
    r = e5.RuidoReal()
    assert r.info["par_fisico"] == "147-148" and r.info["n_2q_por_circuito"] == "1"
    assert r.info["calibracao_backend"].startswith("2026-04-15")
    conts = r.contagens(123)
    assert len(conts) == 4 and all(sum(c.values()) == 64 for c in conts)
    assert conts == r.contagens(123)                        # mesma semente, mesmas contagens
    s = e5.s_de([e5.correlacao(c, 64) for c in conts])
    assert -4 <= s <= 4                                     # o valor não é conferido aqui
    for c in r.circuitos:                                   # lado de Alice (bit 0) no qubit 147
        med = {c.find_bit(ins.clbits[0]).index: c.find_bit(ins.qubits[0]).index
               for ins in c.data if ins.operation.name == "measure"}
        assert med == {0: 147, 1: 148}
    ro = [e for e in r.sim.options.noise_model.to_dict()["errors"] if e["type"] == "roerror"]
    assert sorted(q for e in ro for qs in e["gate_qubits"] for q in qs) == [147, 148]


def test_exigir_uma_porta_2q():
    from qiskit import QuantumCircuit
    um = QuantumCircuit(2)
    um.cx(0, 1)
    dois = QuantumCircuit(2)
    dois.cx(0, 1)
    dois.cz(0, 1)
    e5.exigir_uma_porta_2q([um, um])
    with pytest.raises(e5.E5Erro, match="portas de 2 qubits"):
        e5.exigir_uma_porta_2q([um, dois])
    with pytest.raises(e5.E5Erro, match="portas de 2 qubits"):
        e5.exigir_uma_porta_2q([um, QuantumCircuit(2)])


# ---------------------------------------------------------------- rodadas
def test_ideal_exato_uma_linha(pequeno):
    ls = e5.rodar_config(motor_falso(), "ideal_exato", 5, "c")
    assert len(ls) == 1 and ls[0]["n_shots"] == "" and ls[0]["semente"] == ""
    assert abs(float(ls[0]["s"]) - 2 * math.sqrt(2)) <= 1e-12 and ls[0]["se_s"] == "0.0"
    assert tuple(ls[0]) == e5.CAMPOS


def test_ideal_exato_recusa_circuito_errado(pequeno):
    m = e5.Motor(probs_exatas=lambda a, b: np.array([0.25] * 4), preparar_ruido=RuidoFalso)
    with pytest.raises(e5.E5Erro, match="S exato"):
        e5.rodar_config(m, "ideal_exato", 1, "c")


def test_ideal_amostrado_perto_de_tsirelson(pequeno):
    ls = e5.rodar_config(motor_falso(), "ideal_amostrado", 5, "c")
    assert len(ls) == 5 and len({l["semente"] for l in ls}) == 5
    for l in ls:
        assert abs(float(l["s"]) - 2 * math.sqrt(2)) < 5 * float(l["se_s"])


def test_reprodutivel(pequeno):
    a = e5.rodar_config(motor_falso(), "ideal_amostrado", 3, "c")
    b = e5.rodar_config(motor_falso(), "ideal_amostrado", 3, "c")
    assert [l["s"] for l in a] == [l["s"] for l in b]


def test_classicos(pequeno):
    al = e5.rodar_config(motor_falso(), "classico_aleatorio", 5, "c")
    assert all(abs(float(l["s"])) < 5 * float(l["se_s"]) for l in al)
    ot = e5.rodar_config(motor_falso(), "classico_otimo", 5, "c")
    assert {l["s"] for l in ot} == {"2.0"} and {l["se_s"] for l in ot} == {"0.0"}


def test_ruido_usa_a_semente_e_grava_o_par(pequeno):
    ruido = RuidoFalso()
    ls = e5.rodar_config(motor_falso(), "ruido_fake_kingston", 3, "c", ruido)
    assert ruido.sementes == [e5.semente("ruido_fake_kingston", r) for r in range(3)]
    assert {l["par_fisico"] for l in ls} == {"1-2"} and {l["n_2q_por_circuito"] for l in ls} == {"1"}
    with pytest.raises(e5.E5Erro, match="não preparado"):
        e5.rodar_config(motor_falso(), "ruido_fake_kingston", 1, "c", None)
    with pytest.raises(e5.E5Erro, match="desconhecida"):
        e5.rodar_config(motor_falso(), "outra", 1, "c", ruido)


def test_campos_e_info_vazia_fora_do_ruido(pequeno):
    l = e5.rodar_config(motor_falso(), "classico_aleatorio", 1, "abc")[0]
    assert tuple(l) == e5.CAMPOS and l["commit"] == "abc" and l["par_fisico"] == ""


# ---------------------------------------------------------------- resumo
def rodadas(config, ss, se="0.01"):
    base = dict.fromkeys(e5.CAMPOS, "")
    return [dict(base, schema=e5.SCHEMA, configuracao=config, repeticao=str(i), s=repr(s), se_s=se,
                 t_s="0.1") for i, s in enumerate(ss)]


def completo(**trocas):
    t = 2 * math.sqrt(2)
    cfg = {"ideal_exato": [t], "ideal_amostrado": [t - 0.01, t + 0.01, t],
           "ruido_fake_kingston": [2.5, 2.52, 2.48], "classico_aleatorio": [0.01, -0.02, 0.0],
           "classico_otimo": [2.0, 2.0, 2.0]}
    cfg.update(trocas)
    return [l for c in e5.CONFIGS for l in rodadas(c, cfg[c])]


def resumo_dict(ls):
    return {r["configuracao"]: r for r in e5.resumir(ls)}


def test_resumo_criterios_ok():
    r = resumo_dict(completo())
    assert all(r[c]["criterio_ok"] == "True" for c in e5.CONFIGS)
    assert r["classico_otimo"]["s_dp"] == "0.000000" and r["classico_otimo"]["margem"] == "0.000000"
    assert r["ruido_fake_kingston"]["frac_s_maior_2"] == "1.0000"
    assert r["classico_aleatorio"]["frac_s_maior_2"] == "0.0000"
    assert r["classico_otimo"]["frac_s_maior_2"] == "0.0000"          # S = 2 não é maior que 2
    assert r["ideal_exato"]["n_reps"] == "1" and r["ideal_exato"]["s_dp"] == "0.000000"
    m = 3 * statistics_stdev([2.5, 2.52, 2.48]) / math.sqrt(3)
    assert r["ruido_fake_kingston"]["margem"] == f"{m:.6f}"
    assert list(r) == list(e5.CONFIGS) and tuple(e5.resumir(completo())[0]) == e5.CAMPOS_RESUMO


def statistics_stdev(xs):
    import statistics
    return statistics.stdev(xs)


@pytest.mark.parametrize("trocas,config", [
    ({"ideal_exato": [2.8]}, "ideal_exato"),
    ({"ideal_amostrado": [2.7, 2.71, 2.69]}, "ideal_amostrado"),
    ({"ruido_fake_kingston": [1.9, 1.95, 2.0]}, "ruido_fake_kingston"),
    ({"ruido_fake_kingston": [2.0, 2.01, 2.02]}, "ruido_fake_kingston"),
    ({"ruido_fake_kingston": [2.83, 2.84, 2.85]}, "ruido_fake_kingston"),
    ({"classico_aleatorio": [2.1, 2.1, 2.1]}, "classico_aleatorio"),
    ({"classico_otimo": [2.0001, 2.0001, 2.0001]}, "classico_otimo"),
])
def test_resumo_criterio_falha(trocas, config):
    r = resumo_dict(completo(**trocas))
    assert r[config]["criterio_ok"] == "False"
    assert all(r[c]["criterio_ok"] == "True" for c in e5.CONFIGS if c != config)


def test_avaliar_limites():
    t = 2 * math.sqrt(2)
    assert e5.avaliar("ideal_amostrado", t + 0.5, 0.5) is True       # na borda exata conta
    assert e5.avaliar("ideal_amostrado", t + 0.0101, 0.01) is False
    assert e5.avaliar("classico_otimo", 2.0, 0.0) is True
    assert e5.avaliar("ruido_fake_kingston", 2.1, 0.1) is False      # 2,1 - 0,1 não é > 2
    assert e5.avaliar("ruido_fake_kingston", t - 0.1, 0.1) is False  # S + m não é < 2*raiz(2)
    with pytest.raises(e5.E5Erro):
        e5.avaliar("outra", 2.0, 0.0)


def test_resumo_recusa():
    with pytest.raises(e5.E5Erro, match="sem linhas"):
        e5.resumir([])
    ls = completo()
    with pytest.raises(e5.E5Erro, match="schema"):
        e5.resumir([dict(ls[0], schema="x")] + ls[1:])
    with pytest.raises(e5.E5Erro, match="configuração"):
        e5.resumir([dict(ls[0], configuracao="x")] + ls[1:])
    with pytest.raises(e5.E5Erro, match="faltam"):
        e5.resumir([l for l in ls if l["configuracao"] != "classico_otimo"])


# ---------------------------------------------------------------- main
def _main(tmp_path, *args, limpo=True):
    saida: list[str] = []
    codigo = e5.main(list(args), raiz=tmp_path, motor=motor_falso(), git=lambda r: ("f" * 40, limpo),
                     saida=saida.append)
    return codigo, saida


def test_rodar_grava_os_dois(tmp_path, pequeno):
    codigo, saida = _main(tmp_path, "--rodar")
    assert codigo == 0, saida
    pasta = tmp_path / "data" / "results"
    ls = e5.ler_rodadas(pasta / "e5_rodadas.csv")
    assert len(ls) == 1 + 4 * 5 and {l["commit"] for l in ls} == {"f" * 40}
    with (pasta / "e5_resumo.csv").open(encoding="utf-8", newline="") as f:
        assert len(list(csv.DictReader(f))) == 5
    for nome in ("e5_rodadas.csv", "e5_resumo.csv"):
        dados = (pasta / nome).read_bytes()
        assert f"{nome}: {hashlib.sha256(dados).hexdigest()}" in saida and b"\r\n" not in dados
    assert not list(pasta.glob("*.tmp"))


def test_rodar_recusa_arvore_suja(tmp_path, pequeno):
    codigo, saida = _main(tmp_path, "--rodar", limpo=False)
    assert codigo == 1 and "RECUSADO" in saida[-1] and not (tmp_path / "data").exists()


@pytest.mark.parametrize("nome", ["e5_rodadas.csv", "e5_resumo.csv"])
def test_rodar_recusa_se_saida_existe(tmp_path, pequeno, nome):
    pasta = tmp_path / "data" / "results"
    pasta.mkdir(parents=True)
    (pasta / nome).write_bytes(b"x")
    codigo, saida = _main(tmp_path, "--rodar")
    assert codigo == 1 and "já existe" in saida[-1]
    assert sorted(p.name for p in pasta.iterdir()) == [nome]


def test_gravar_novo_nao_sobrescreve(tmp_path):
    alvo = tmp_path / "a.csv"
    e5.gravar_novo(alvo, b"um")
    with pytest.raises(e5.E5Erro, match="já existe"):
        e5.gravar_novo(alvo, b"dois")
    assert alvo.read_bytes() == b"um"


def test_resumir_idempotente_e_recusa(tmp_path, pequeno):
    assert _main(tmp_path, "--rodar")[0] == 0
    p = tmp_path / "data" / "results" / "e5_resumo.csv"
    codigo, saida = _main(tmp_path, "--resumir")
    assert codigo == 0 and "já existia igual" in saida[-1]
    p.write_bytes(b"outro")
    codigo, saida = _main(tmp_path, "--resumir")
    assert codigo == 1 and "difere" in saida[-1] and p.read_bytes() == b"outro"
    p.unlink()
    assert _main(tmp_path, "--resumir")[0] == 0


def test_resumir_recusa_cabecalho_e_ausente(tmp_path):
    codigo, saida = _main(tmp_path, "--resumir")
    assert codigo == 1 and "não existe" in saida[-1]
    pasta = tmp_path / "data" / "results"
    pasta.mkdir(parents=True)
    (pasta / "e5_rodadas.csv").write_text("a,b\n1,2\n", encoding="utf-8")
    codigo, saida = _main(tmp_path, "--resumir")
    assert codigo == 1 and "cabeçalho" in saida[-1]


def test_medir_tempo_nao_grava_nem_mostra_s(tmp_path, pequeno):
    codigo, saida = _main(tmp_path, "--medir-tempo")
    assert codigo == 0 and not (tmp_path / "data").exists()
    texto = "\n".join(saida).lower()
    assert "preparo do ruído" in texto and "estimativa da rodada" in texto
    for proibido in ("true", "false", "criterio", "s_media", "s =", "tsirelson"):
        assert proibido not in texto


def test_modos_exclusivos(tmp_path):
    with pytest.raises(SystemExit):
        _main(tmp_path, "--rodar", "--resumir")
    with pytest.raises(SystemExit):
        _main(tmp_path)
