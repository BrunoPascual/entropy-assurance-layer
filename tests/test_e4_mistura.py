"""Testes de scripts/e4_mistura.py com um motor falso que segue a especificação do mixer."""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import math
import sys
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

_CAMINHO = Path(__file__).resolve().parents[1] / "scripts" / "e4_mistura.py"
_spec = importlib.util.spec_from_file_location("e4_mistura", _CAMINHO)
e4 = importlib.util.module_from_spec(_spec)
sys.modules["e4_mistura"] = e4
_spec.loader.exec_module(e4)


# ---------------------------------------------------------------- motor falso
class FakePolicyError(ValueError):
    pass


@dataclass
class FakeExtraction:
    extractor_type: str
    guarantee: str
    n: int
    m: int
    h_used: float
    epsilon_log2: int
    n_input_bits: int
    n_blocks: int
    discarded_bits: int
    bits: np.ndarray = field(repr=False)
    seed_hash: str | None = None
    notes: tuple = ()
    input_hash: str | None = None


@dataclass
class FakeMixInput:
    source_id: str
    batch_id: str
    input_hash: str
    is_local: object
    is_simulated: object
    report: object
    extraction: FakeExtraction


def fake_hash_bits(bits: np.ndarray) -> str:
    return hashlib.sha3_256(int(bits.size).to_bytes(8, "big") + np.packbits(bits).tobytes()).hexdigest()


CHAMADAS: list[tuple] = []


def fake_mix(inputs, mode="keygen"):
    """Codificação do docstring de eal/mix/mixer.py e a recusa de input_hash repetido."""
    CHAMADAS.append((mode, tuple(m.source_id for m in inputs),
                     tuple(m.is_local for m in inputs), tuple(m.is_simulated for m in inputs)))
    hs = [m.input_hash for m in inputs]
    if len(set(hs)) != len(hs):
        raise FakePolicyError("input_hash repetido")
    for m in inputs:
        assert m.report.approved is True and m.report.n_bits == m.extraction.n_input_bits
        assert m.extraction.input_hash == m.input_hash
    h = hashlib.sha3_512(b"EAL-v1-mix")
    for m in sorted(inputs, key=lambda x: x.source_id):
        sid = m.source_id.encode()
        b = m.extraction.bits
        h.update(len(sid).to_bytes(8, "big") + sid + b.size.to_bytes(8, "big") + np.packbits(b).tobytes())
    return SimpleNamespace(seed=h.digest())


def fake_stats(bits: np.ndarray):
    n = bits.size
    s = abs(2 * int(bits.sum()) - n) / math.sqrt(n)
    p = math.erfc(s / math.sqrt(2))
    t = lambda v: SimpleNamespace(p_value=v)  # noqa: E731
    return SimpleNamespace(passed=p >= 0.01, inconclusive=False, monobit=t(p),
                           block_frequency=t(0.5), runs=t(0.5))


MOTOR = e4.Motor(mix=fake_mix, MixInput=FakeMixInput, ExtractionResult=FakeExtraction,
                 MixPolicyError=FakePolicyError, hash_bits=fake_hash_bits,
                 run_stats_tests=fake_stats, mix_domain=b"EAL-v1-mix")


@pytest.fixture(autouse=True)
def pequeno(monkeypatch):
    """Grade reduzida para os testes rodarem rápido (a grade real é travada à parte)."""
    CHAMADAS.clear()
    monkeypatch.setattr(e4, "N_SEMENTES", 40)
    monkeypatch.setattr(e4, "REPS", 2)
    monkeypatch.setattr(e4, "REPS_FORCA", 1)
    monkeypatch.setattr(e4, "KS_FORCA", (1, 4))
    monkeypatch.setattr(e4, "REPS_MEDIR_TEMPO", 1)


def rng(x=7):
    return np.random.default_rng(x)


# ---------------------------------------------------------------- pré-registro
def test_grade_pre_registrada():
    fonte = _CAMINHO.read_text(encoding="utf-8")
    for trecho in (
        "N_SEMENTES = 2000", "L_BITS = 2048", "SEED_BITS = 512", "P_ENVIESADA = 0.55",
        "TRAVA_RUN, TRAVA_JANELA = 64, 1024", 'ID_HONESTA, ID_SEGUNDA = "os", "qpu_remota"',
        'MODO = "keygen"', "KS_FORCA = (1, 4, 8, 12)", "REPS = 100", "REPS_FORCA = 10",
        "LIMITE_TENTATIVAS = 64", "Z_POSICAO = 5.0",
        'CENARIOS = ("base_boa", "enviesada", "travada", "constante", "copia", "adv_alvo", "sem_fonte_boa")',
        'COMBINADORES = ("hash", "xor")',
    ):
        assert trecho in fonte, trecho


def test_esperado_pre_registrado():
    assert e4.ESPERADO[("copia", "hash")] == "sem_semente"
    assert e4.ESPERADO[("copia", "xor")] == "insegura"
    assert e4.ESPERADO[("adv_alvo", "hash")] == "segura"
    assert e4.ESPERADO[("adv_alvo", "xor")] == "insegura"
    assert e4.ESPERADO[("sem_fonte_boa", "hash")] == "insegura"
    assert e4.ESPERADO[("adv_forca", "hash")] == "k_bits"
    for c in ("base_boa", "enviesada", "travada", "constante"):
        assert e4.ESPERADO[(c, "hash")] == e4.ESPERADO[(c, "xor")] == "segura"
    assert len(e4.ESPERADO) == 15


def test_celulas_da_grade_real(monkeypatch):
    monkeypatch.setattr(e4, "REPS", 100)
    monkeypatch.setattr(e4, "REPS_FORCA", 10)
    monkeypatch.setattr(e4, "KS_FORCA", (1, 4, 8, 12))
    cs = e4.celulas()
    assert len(cs) == 18
    assert sum(c.reps for c in cs) == 14 * 100 + 4 * 10
    assert [c.k for c in cs if c.cenario == "adv_forca"] == [1, 4, 8, 12]
    assert all(c.combinador == "hash" for c in cs if c.cenario == "adv_forca")


def test_semente_pareada_e_distinta():
    assert e4.semente("adv_alvo", None, 3) == e4.semente("adv_alvo", None, 3)
    todas = {e4.semente(c, None, r) for c in e4.CENARIOS for r in range(100)}
    todas |= {e4.semente("adv_forca", k, r) for k in (1, 4, 8, 12) for r in range(10)}
    assert len(todas) == 7 * 100 + 4 * 10
    assert e4.semente("adv_forca", 4, 0) != e4.semente("adv_forca", 8, 0)


# ---------------------------------------------------------------- entradas
def test_entradas_formas_e_valores():
    for c in e4.CENARIOS:
        H, S, alvos = e4.gerar_entradas(c, rng(), 30)
        assert H.shape == S.shape == (30, e4.L_BITS) and H.dtype == S.dtype == np.uint8
        assert set(np.unique(H)) <= {0, 1} and set(np.unique(S)) <= {0, 1}
        assert (alvos is not None) == (c == "adv_alvo")


def test_entradas_por_cenario():
    H, S, _ = e4.gerar_entradas("constante", rng(), 5)
    assert not S.any() and H.any()
    H, S, _ = e4.gerar_entradas("copia", rng(), 5)
    assert np.array_equal(H, S)
    H, S, a = e4.gerar_entradas("adv_alvo", rng(), 5)
    assert np.array_equal(H[:, :512] ^ S[:, :512], a)
    assert np.array_equal(H[:, 512:], S[:, 512:])
    H, S, _ = e4.gerar_entradas("sem_fonte_boa", rng(), 5)
    assert not H.any() and S.all()
    _, S, _ = e4.gerar_entradas("enviesada", rng(), 400)
    assert 0.54 < S.mean() < 0.56
    H, S, _ = e4.gerar_entradas("adv_forca", rng(), 5)
    assert S is None and H.shape == (5, e4.L_BITS)
    with pytest.raises(e4.E4Erro):
        e4.gerar_entradas("outro", rng(), 5)


def _maior_corrida(v: np.ndarray) -> int:
    melhor = atual = 1
    for a, b in zip(v[:-1], v[1:]):
        atual = atual + 1 if a == b else 1
        melhor = max(melhor, atual)
    return melhor


def test_travada_tem_trecho_de_64_em_cada_janela():
    _, S, _ = e4.gerar_entradas("travada", rng(), 20)
    for linha in S:
        for w in range(0, e4.L_BITS, e4.TRAVA_JANELA):
            assert _maior_corrida(linha[w:w + e4.TRAVA_JANELA]) >= e4.TRAVA_RUN


def test_mesmas_entradas_para_hash_e_xor():
    a = e4.gerar_entradas("base_boa", np.random.default_rng(e4.semente("base_boa", None, 0)), 8)
    b = e4.gerar_entradas("base_boa", np.random.default_rng(e4.semente("base_boa", None, 0)), 8)
    assert np.array_equal(a[0], b[0]) and np.array_equal(a[1], b[1])


# ---------------------------------------------------------------- combinadores
def test_xor_cancela_copia_e_entrega_o_alvo():
    H, S, _ = e4.gerar_entradas("copia", rng(), 10)
    assert not e4.combinar_xor(H, S).any()
    H, S, a = e4.gerar_entradas("adv_alvo", rng(), 10)
    assert np.array_equal(e4.combinar_xor(H, S), np.packbits(a, axis=1))
    H, S, _ = e4.gerar_entradas("base_boa", rng(), 10)
    assert np.array_equal(e4.combinar_xor(H, S), np.packbits(H[:, :512] ^ S[:, :512], axis=1))


def test_hash_usa_o_mix_com_politica_e_ids():
    H, S, _ = e4.gerar_entradas("base_boa", rng(), 6)
    sem, rec = e4.combinar_hash(MOTOR, H, S)
    assert sem.shape == (6, 64) and rec == 0
    assert CHAMADAS[0] == ("keygen", ("os", "qpu_remota"), (True, False), (False, False))
    assert bytes(sem[0]) == fake_mix([e4.contribuicao(MOTOR, "os", H[0], True),
                                      e4.contribuicao(MOTOR, "qpu_remota", S[0], False)]).seed


def test_hash_recusa_copia():
    H, S, _ = e4.gerar_entradas("copia", rng(), 6)
    sem, rec = e4.combinar_hash(MOTOR, H, S)
    assert sem.shape == (0, 64) and rec == 6


@pytest.mark.parametrize("k", [1, 3, 6])
def test_forcar_zera_k_bits_e_confere_com_o_mix(k):
    H, _, _ = e4.gerar_entradas("adv_forca", rng(k), 12)
    sem, falhas = e4.forcar(MOTOR, H, k)
    assert falhas == 0 and sem.shape == (12, 64)
    assert e4.prefixo_zero(sem, k).all()
    assert len(CHAMADAS) == 12


def test_forcar_recusa_se_caminho_rapido_difere():
    def mix_diferente(inputs, mode="keygen"):
        return SimpleNamespace(seed=b"\x00" * 64)

    motor = e4.Motor(**{**MOTOR.__dict__, "mix": mix_diferente})
    H, _, _ = e4.gerar_entradas("adv_forca", rng(), 2)
    with pytest.raises(e4.E4Erro, match="caminho rápido"):
        e4.forcar(motor, H, 1)


def test_forcar_conta_falha_quando_o_limite_acaba(monkeypatch):
    monkeypatch.setattr(e4, "LIMITE_TENTATIVAS", 1 / 4096)   # k = 12: uma única tentativa
    H, _, _ = e4.gerar_entradas("adv_forca", rng(), 3)
    sem, falhas = e4.forcar(MOTOR, H, 12)
    assert sem.shape == (3, 64) and falhas == 3 - int(e4.prefixo_zero(sem, 12).sum())
    assert falhas == 3                 # com 1 tentativa, acertar 12 bits tem chance 1/4096


def test_forcar_faz_ao_menos_uma_tentativa(monkeypatch):
    monkeypatch.setattr(e4, "LIMITE_TENTATIVAS", 1 / 8192)   # 0,5 tentativa: arredonda para 1
    H, _, _ = e4.gerar_entradas("adv_forca", rng(), 2)
    sem, falhas = e4.forcar(MOTOR, H, 12)
    assert sem.shape == (2, 64) and falhas == 2


def test_forcar_valida_k_e_ordem(monkeypatch):
    H, _, _ = e4.gerar_entradas("adv_forca", rng(), 1)
    with pytest.raises(e4.E4Erro):
        e4.forcar(MOTOR, H, 0)
    with pytest.raises(e4.E4Erro):
        e4.forcar(MOTOR, H, 65)
    monkeypatch.setattr(e4, "ID_SEGUNDA", "aaa")
    with pytest.raises(e4.E4Erro, match="ordem"):
        e4.forcar(MOTOR, H, 1)


# ---------------------------------------------------------------- métricas
def test_avaliar_sementes_constantes():
    sem = np.zeros((40, 64), dtype=np.uint8)
    m = e4.avaliar(MOTOR, sem, 40)
    assert m["n_distintas"] == "1" and m["n_pos_z5"] == "512"
    assert m["aprovada"] == "False" and float(m["max_abs_z"]) == pytest.approx(math.sqrt(40), abs=1e-3)


def test_avaliar_incompleta_nao_roda_estatistica():
    sem = np.random.default_rng(1).integers(0, 256, size=(10, 64), dtype=np.uint8)
    m = e4.avaliar(MOTOR, sem, 40)
    assert m["aprovada"] == "" and m["p_monobit"] == "" and m["n_sementes"] == "10"
    vazio = e4.avaliar(MOTOR, np.zeros((0, 64), dtype=np.uint8), 40)
    assert vazio["n_sementes"] == "0" and vazio["max_abs_z"] == "" and vazio["n_distintas"] == "0"


def test_avaliar_recusa_inconclusivo():
    motor = e4.Motor(**{**MOTOR.__dict__, "run_stats_tests":
                        lambda b: SimpleNamespace(passed=False, inconclusive=True)})
    with pytest.raises(e4.E4Erro, match="inconclusivos"):
        e4.avaliar(motor, np.zeros((40, 64), dtype=np.uint8), 40)


def test_prefixo_zero():
    s = np.zeros((3, 64), dtype=np.uint8)
    s[1, 0] = 0b00010000
    s[2, 0] = 0b10000000
    assert list(e4.prefixo_zero(s, 3)) == [True, True, False]
    assert list(e4.prefixo_zero(s, 4)) == [True, False, False]


def seq(c, rep=0):
    return e4.rodar_sequencia(MOTOR, c, rep, "abc")


def test_sequencia_xor_adv_alvo_controla_tudo():
    l = seq(e4.Celula("adv_alvo", "xor", None, 1))
    assert l["n_alvo"] == "40" and l["n_sementes"] == "40" and l["esperado"] == "insegura"
    assert l["aprovada"] in ("True", "False") and l["n_falhas_forca"] == "" and l["k"] == ""


def test_sequencia_hash_adv_alvo_nao_controla():
    l = seq(e4.Celula("adv_alvo", "hash", None, 1))
    assert l["n_alvo"] == "0" and l["n_distintas"] == "40" and l["esperado"] == "segura"


def test_sequencia_copia_hash_sem_semente():
    l = seq(e4.Celula("copia", "hash", None, 1))
    assert (l["n_sementes"], l["n_recusadas"], l["aprovada"]) == ("0", "40", "")


def test_sequencia_forca():
    l = seq(e4.Celula("adv_forca", "hash", 4, 1))
    assert (l["k"], l["n_alvo"], l["n_falhas_forca"], l["n_recusadas"]) == ("4", "40", "0", "0")
    assert l["esperado"] == "k_bits" and int(l["n_pos_z5"]) == 4


def test_sequencia_sem_fonte_boa_repete_a_semente():
    for comb in ("hash", "xor"):
        assert seq(e4.Celula("sem_fonte_boa", comb, None, 1))["n_distintas"] == "1"


def test_sequencia_campos_e_ordem():
    l = seq(e4.Celula("base_boa", "hash", None, 1), rep=1)
    assert tuple(l) == e4.CAMPOS_SEQ
    assert l["semente"] == str(e4.semente("base_boa", None, 1)) and l["repeticao"] == "1"


# ---------------------------------------------------------------- resumo
def test_clopper_pearson():
    assert e4.clopper_pearson(0, 20) == pytest.approx((0.0, 0.168433), abs=1e-6)
    assert e4.clopper_pearson(10, 20) == pytest.approx((0.271958, 0.728042), abs=1e-6)
    with pytest.raises(e4.E4Erro):
        e4.clopper_pearson(3, 2)


def test_resumo_agrega_por_celula():
    ls = [seq(e4.Celula("adv_alvo", "xor", None, 2), r) for r in range(2)]
    ls += [seq(e4.Celula("copia", "hash", None, 2), r) for r in range(2)]
    ls += [seq(e4.Celula("adv_forca", "hash", 1, 1), 0)]
    res = {(r["cenario"], r["combinador"], r["k"]): r for r in e4.resumir(ls)}
    a = res[("adv_alvo", "xor", "")]
    assert (a["n_seq"], a["sementes_total"], a["frac_alvo"], a["esperado"]) == ("2", "80", "1.0000", "insegura")
    c = res[("copia", "hash", "")]
    assert (c["n_seq_completas"], c["taxa_aprovacao"], c["recusadas_total"], c["frac_alvo"]) == ("0", "", "80", "")
    assert c["distintas_max"] == "0" and c["max_abs_z_max"] == "" and c["n_aprovadas"] == "0"
    f = res[("adv_forca", "hash", "1")]
    assert (f["frac_alvo"], f["falhas_forca_total"], f["pos_z5_min"]) == ("1.0000", "0", "1")
    assert list(res) == [("adv_alvo", "xor", ""), ("copia", "hash", ""), ("adv_forca", "hash", "1")]


def test_resumo_taxa_e_ic():
    base = seq(e4.Celula("base_boa", "xor", None, 1))
    ls = [dict(base, aprovada=v, repeticao=str(i)) for i, v in enumerate(["True"] * 9 + ["False"])]
    r = e4.resumir(ls)[0]
    lo, hi = e4.clopper_pearson(9, 10)
    assert (r["n_aprovadas"], r["taxa_aprovacao"]) == ("9", "0.9000")
    assert (r["ic95_inf"], r["ic95_sup"]) == (f"{lo:.4f}", f"{hi:.4f}")


def test_resumo_faixas_e_alvo_sem_sementes():
    base = seq(e4.Celula("adv_alvo", "xor", None, 1))
    ls = [dict(base, repeticao=str(i), n_pos_z5=str(v), n_distintas=str(d), max_abs_z=z,
               n_falhas_forca=f)
          for i, (v, d, z, f) in enumerate([(3, 40, "1.0", "1"), (0, 1, "3.5", "2"), (7, 20, "2.0", "0")])]
    r = e4.resumir(ls)[0]
    assert (r["max_abs_z_max"], r["falhas_forca_total"]) == ("3.5000", "3")
    assert (r["pos_z5_min"], r["pos_z5_max"]) == ("0", "7")
    assert (r["distintas_min"], r["distintas_max"]) == ("1", "40")
    vazio = dict(base, n_sementes="0", n_alvo="0", aprovada="", max_abs_z="", n_pos_z5="",
                 n_distintas="0")
    r = e4.resumir([vazio])[0]
    assert r["frac_alvo"] == "" and r["sementes_total"] == "0" and r["taxa_aprovacao"] == ""


def test_resumo_recusa_dados_invalidos():
    base = seq(e4.Celula("base_boa", "xor", None, 1))
    with pytest.raises(e4.E4Erro, match="aprovada"):
        e4.resumir([dict(base, aprovada="true")])
    with pytest.raises(e4.E4Erro, match="schema"):
        e4.resumir([dict(base, schema="x")])
    with pytest.raises(e4.E4Erro):
        e4.resumir([])


# ---------------------------------------------------------------- main
def _main(tmp_path, *args, limpo=True):
    saida: list[str] = []
    codigo = e4.main(list(args), raiz=tmp_path, motor=MOTOR, git=lambda r: ("f" * 40, limpo),
                     saida=saida.append)
    return codigo, saida


def test_rodar_grava_os_dois_csvs(tmp_path):
    codigo, saida = _main(tmp_path, "--rodar")
    assert codigo == 0, saida
    pasta = tmp_path / "data" / "results"
    linhas = e4.ler_seq(pasta / "e4_sequencias.csv")
    assert len(linhas) == 14 * 2 + 2 * 1
    assert {l["commit"] for l in linhas} == {"f" * 40}
    with (pasta / "e4_resumo.csv").open(encoding="utf-8", newline="") as f:
        res = list(csv.DictReader(f))
    assert len(res) == 16 and tuple(res[0]) == e4.CAMPOS_RESUMO
    for nome in ("e4_sequencias.csv", "e4_resumo.csv"):
        dados = (pasta / nome).read_bytes()
        assert f"{nome}: {hashlib.sha256(dados).hexdigest()}" in saida
        assert b"\r\n" not in dados
    assert not list(pasta.glob("*.tmp"))


def test_rodar_recusa_arvore_suja(tmp_path):
    codigo, saida = _main(tmp_path, "--rodar", limpo=False)
    assert codigo == 1 and "RECUSADO" in saida[-1]
    assert not (tmp_path / "data").exists()


@pytest.mark.parametrize("nome", ["e4_sequencias.csv", "e4_resumo.csv"])
def test_rodar_recusa_se_saida_existe(tmp_path, nome):
    pasta = tmp_path / "data" / "results"
    pasta.mkdir(parents=True)
    (pasta / nome).write_bytes(b"x")
    codigo, saida = _main(tmp_path, "--rodar")
    assert codigo == 1 and "já existe" in saida[-1]
    assert sorted(p.name for p in pasta.iterdir()) == [nome]


def test_gravar_novo_nao_sobrescreve(tmp_path):
    alvo = tmp_path / "a.csv"
    e4.gravar_novo(alvo, b"um")
    with pytest.raises(e4.E4Erro, match="já existe"):
        e4.gravar_novo(alvo, b"dois")
    assert alvo.read_bytes() == b"um"


def test_resumir_idempotente_e_recusa_se_diferente(tmp_path):
    assert _main(tmp_path, "--rodar")[0] == 0
    pasta = tmp_path / "data" / "results"
    codigo, saida = _main(tmp_path, "--resumir")
    assert codigo == 0 and "já existia igual" in saida[-1]
    (pasta / "e4_resumo.csv").write_bytes(b"outro")
    codigo, saida = _main(tmp_path, "--resumir")
    assert codigo == 1 and "difere" in saida[-1]
    (pasta / "e4_resumo.csv").unlink()
    assert _main(tmp_path, "--resumir")[0] == 0


def test_resumir_recusa_sem_seq_e_cabecalho_errado(tmp_path):
    codigo, saida = _main(tmp_path, "--resumir")
    assert codigo == 1 and "não existe" in saida[-1]
    pasta = tmp_path / "data" / "results"
    pasta.mkdir(parents=True)
    (pasta / "e4_sequencias.csv").write_text("a,b\n1,2\n", encoding="utf-8")
    codigo, saida = _main(tmp_path, "--resumir")
    assert codigo == 1 and "cabeçalho" in saida[-1]


def test_medir_tempo_nao_grava_nem_mostra_resultado(tmp_path):
    codigo, saida = _main(tmp_path, "--medir-tempo")
    assert codigo == 0 and not (tmp_path / "data").exists()
    texto = "\n".join(saida).lower()
    assert "30 sequências" in texto
    for proibido in ("aprovad", "true", "false", "taxa", "distint", "recus"):
        assert proibido not in texto


def test_modos_exclusivos(tmp_path):
    with pytest.raises(SystemExit):
        _main(tmp_path, "--rodar", "--resumir")
    with pytest.raises(SystemExit):
        _main(tmp_path)
