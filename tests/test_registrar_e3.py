"""Testes de scripts/registrar_e3.py (registro do E3 no PROJECT.md, Dia 7), com os valores reais."""
from __future__ import annotations

import hashlib
import importlib.util
import math
import re
import sys
from decimal import Decimal
from fractions import Fraction
from pathlib import Path

import pytest

_RAIZ = Path(__file__).resolve().parent.parent / "scripts"


def _carregar(nome: str, arquivo: str):
    spec = importlib.util.spec_from_file_location(nome, _RAIZ / arquivo)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[nome] = mod
    spec.loader.exec_module(mod)
    return mod


reg = _carregar("_registrar_e3", "registrar_e3.py")
e3 = _carregar("_e3_para_teste_registro", "e3_vazao_custo.py")

COMMIT = reg.COMMIT_CURTO + "0" * 33
PROJECT = (b"# Projeto\r\n\r\ntexto antigo\r\n"
           b"<!-- dia7-e4:start -->\r\nx\r\n<!-- dia7-e4:end -->\r\n")

# job, sessão, arquivo, shots, segundos, H estimado (None na calibração)
JOBS = [
    ("dbji1pgnceqs73ak2c8g", "cal", "2026-11-01_ibm_kingston_cal_001.npy", 1000, "2.0", None),
    ("dbjlaghkdqps7390qbq0", "cal", "2026-11-01_ibm_kingston_cal_002.npy", 4000, "3.0", None),
    ("dbjlg80nceqs73ak89g0", "coleta1", "2026-11-01_ibm_kingston_coleta1_001.npy", 9616, "5.0", "0.962254117749"),
    ("dbjlkahffo6c73b9t1u0", "coleta1", "2026-11-01_ibm_kingston_coleta1_002.npy", 9616, "5.0", "0.955501817198"),
    ("dbjq01pffo6c73ba4lo0", "coleta2", "2026-11-01_ibm_kingston_coleta2_001.npy", 9616, "5.0", "0.959768728725"),
    ("dbjq4ehkdqps73912u30", "coleta2", "2026-11-01_ibm_kingston_coleta2_002.npy", 9616, "5.0", "0.955301182366"),
    ("dbkf24d6p51s73cmg7ng", "coleta3", "2026-11-02_ibm_kingston_coleta3_001.npy", 9616, "5.0", "0.960593306672"),
    ("dbkf4f1ffo6c73bbc8m0", "coleta3", "2026-11-02_ibm_kingston_coleta3_002.npy", 9616, "5.0", "0.955903772587"),
]
TEMPOS = ["0.082213", "0.074158", "0.074319", "0.095391", "0.106602", "0.079099", "0.283410",
          "0.332715", "0.325059", "0.312211", "0.317399", "0.325880", "0.324388", "0.359362",
          "0.340648", "0.336673", "0.353267", "0.333450", "0.384965", "0.328416"]
EXTRAIDOS = [1352004, 1353468, 1356396, 1357128, 1347612, 1354932, 1354200, 1356396, 1357860,
             1351272, 1357128, 1359324, 1354200, 1354932, 1354932, 1354932, 1356396, 1356396,
             1354932, 1352736]


def hip_ref(n_input: int, h: float) -> int:
    return (n_input // 2048) * max(math.floor(Fraction(h) * 2048) - 128, 0)


def linhas_qpu(aprovar=()):
    out = []
    for jid, sess, arq, shots, seg, h in JOBS:
        n = shots * 156
        custo = Decimal(seg) * Decimal(96) / 60
        aprovada = "" if h is None else ("True" if jid in aprovar else "False")
        out.append({
            "schema": e3.SCHEMA_QPU, "sessao": sess, "job_id": jid, "arquivo": arq,
            "shots": str(shots), "qubits": "156", "n_bits": str(n), "quantum_seconds": seg,
            "bits_por_s": e3.dec(Decimal(n) / Decimal(seg)), "custo_usd_payg": e3.dec(custo),
            "custo_usd_por_mbit_payg": e3.dec(custo / (Decimal(n) / 1000000)),
            "circuito": "hadamard_all_measure", "rep_delay_s": "0.00025", "json_sha256": "a" * 64,
            "saude_aprovada": aprovada, "h_estimada": h or "",
            "bits_uteis": "" if h is None else ("555" if jid in aprovar else "0"),
            "bits_uteis_hipoteticos": "" if h is None else str(hip_ref(n, float(h))),
        })
    return out


def linhas_local(tempos=TEMPOS, commit=COMMIT, n_bits="1500096"):
    return [{"schema": e3.SCHEMA_LOCAL, "commit": commit, "repeticao": str(i), "n_bits": n_bits,
             "t_s": t, "semente_gerada": "True", "bits_extraidos": str(EXTRAIDOS[i % 20]),
             "status_os": "mixed", "python": "3.12.0", "plataforma": "Windows-11", "cpus": "8"}
            for i, t in enumerate(tempos)]


def gravar_dados(raiz: Path, qpu=None, local=None, resumo=None):
    qpu = linhas_qpu() if qpu is None else qpu
    local = linhas_local() if local is None else local
    pasta = raiz / "data" / "results"
    pasta.mkdir(parents=True, exist_ok=True)
    (pasta / "e3_qpu.csv").write_bytes(e3.csv_bytes(e3.CAMPOS_QPU, qpu))
    (pasta / "e3_local.csv").write_bytes(e3.csv_bytes(e3.CAMPOS_LOCAL, local))
    res = e3.resumir(qpu, local) if resumo is None else resumo
    (pasta / "e3_resumo.csv").write_bytes(e3.csv_bytes(e3.CAMPOS_RESUMO, res))


@pytest.fixture
def ambiente(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "PROJECT.md").write_bytes(PROJECT)
    monkeypatch.setattr(reg, "HASH_ANTES", hashlib.sha256(PROJECT).hexdigest())
    gravar_dados(tmp_path)
    return tmp_path


def rodar():
    saida: list[str] = []
    return reg.main(saida.append), saida


def bloco(raiz: Path) -> list[str]:
    t = (raiz / "PROJECT.md").read_bytes().decode("utf-8")
    return t[t.index(reg.START):].split("\r\n")


# ---------------------------------------------------------------- o resumo reproduz a saída real
def test_resumo_reproduz_a_saida_real():
    r = {x["metrica"]: x["valor"] for x in e3.resumir(linhas_qpu(), linhas_local())}
    esperado = {
        "qpu_jobs": "8", "qpu_segundos": "35.0", "qpu_bits_brutos": "9780576",
        "qpu_custo_pay_as_you_go": "56.00", "qpu_custo_flex": "42.00", "qpu_custo_premium": "28.00",
        "coleta_jobs": "6", "coleta_segundos": "30.0", "coleta_bits_brutos": "9000576",
        "coleta_bits_por_s": "300019.2000", "coleta_s_por_mbit_bruto": "3.3331",
        "coleta_custo_por_mbit_bruto_pay_as_you_go": "5.3330",
        "coleta_custo_por_mbit_bruto_flex": "3.9997", "coleta_custo_por_mbit_bruto_premium": "2.6665",
        "ajuste_fixo_s": "1.6296", "ajuste_por_shot_s": "0.00035031",
        "ajuste_custo_marginal_por_mbit_pay_as_you_go": "3.5930",
        "coleta_lotes_aprovados": "0", "coleta_bits_uteis": "0",
        "coleta_custo_por_mbit_util_pay_as_you_go": "indefinido",
        "coleta_bits_uteis_hipoteticos": "8054196",
        "coleta_custo_por_mbit_util_hipotetico_pay_as_you_go": "5.9596",
        "local_execucoes": "20", "local_t_mediana_s": "0.324724", "local_t_min_s": "0.074158",
        "local_t_max_s": "0.384965", "local_s_por_mbit_bruto": "0.216468",
        "local_bits_por_s": "4619610.2222", "local_bits_extraidos_mediana": "1354932",
        "razao_s_por_mbit_qpu_sobre_os": "15.40", "criterio_limiar": "10",
        "criterio_muito_mais_caro": "True",
    }
    for k, v in esperado.items():
        assert r[k] == v, (k, r[k], v)


# ---------------------------------------------------------------- formatação e contas
def test_formatacao():
    assert reg.n_pt("9000576") == "9.000.576" and reg.d_pt("3.3331") == "3,3331" and reg.d_pt("") == "-"
    assert reg.valor_pt("9000576", "bits") == "9.000.576"
    assert reg.valor_pt("15.40", "vezes") == "15,40" and reg.valor_pt("8", "jobs") == "8"
    assert reg.valor_pt("indefinido", "USD/Mbit") == "indefinido"
    assert reg.valor_pt("https://www.ibm.com/quantum/pricing", "url").startswith("https://")
    assert reg.dec4(Decimal("12.98812")) == "12,9881"


def test_separacao():
    t = [Decimal(x) for x in TEMPOS]
    k, gap = reg.separacao(t)
    assert k == 6 and gap == Decimal("0.283410") / Decimal("0.106602")
    assert reg.separacao([Decimal(x) for x in ("1", "1.1", "0.9", "1.05")]) is None
    assert reg.separacao([Decimal(x) for x in ("1", "1.5", "1.6")]) is None      # separa, mas < 2x
    assert reg.separacao([Decimal(x) for x in ("1", "5", "6")])[0] == 1
    assert reg.separacao([Decimal("1")]) is None
    assert reg.separacao([Decimal(x) for x in ("1", "5", "1")]) is None           # não é monotônico


def test_separacao_no_limiar_exato():
    assert reg.separacao([Decimal(1), Decimal(2)]) == (1, Decimal(2))          # razão == 2 conta


def test_razao_no_limiar_exato_conta_como_igual_ou_acima(monkeypatch):
    qpu, local = linhas_qpu(), linhas_local()
    r = {x["metrica"]: x["valor"] for x in e3.resumir(qpu, local)}
    c_seg, c_mbit, l_mbit = reg.base_coleta(e3, qpu, local)
    rl = reg.razao(c_seg, c_mbit, Decimal("0.384965"), l_mbit)
    monkeypatch.setattr(e3, "RAZAO_MUITO", rl)
    frases = reg.frases_calculadas(e3, qpu, local, r)
    assert "com a mais lenta, igual ou acima do limiar" in frases[1]


def test_razao():
    assert reg.razao(Decimal(30), Decimal("9.000576"), Decimal("0.324724"), Decimal("1.500096")
                     ).quantize(Decimal("0.01")) == Decimal("15.40")


# ---------------------------------------------------------------- aplicação
def test_aplica_e_preserva_o_resto(ambiente):
    codigo, saida = rodar()
    assert codigo == 0 and saida[0].startswith("aplicado")
    dados = (ambiente / "PROJECT.md").read_bytes()
    assert dados.startswith(PROJECT + b"\r\n" + reg.START.encode())
    assert dados.endswith(reg.END.encode() + b"\r\n")
    assert dados.count(b"\n") == dados.count(b"\r\n")
    assert saida[0] == f"aplicado; PROJECT.md: {hashlib.sha256(dados).hexdigest()}"
    assert not list(ambiente.glob("*.tmp"))


def test_idempotente(ambiente):
    assert rodar()[0] == 0
    antes = (ambiente / "PROJECT.md").read_bytes()
    codigo, saida = rodar()
    assert codigo == 0 and saida[0].startswith("já aplicado")
    assert (ambiente / "PROJECT.md").read_bytes() == antes


def test_protocolo_e_hashes(ambiente):
    rodar()
    t = "\n".join(bloco(ambiente))
    assert (f"nenhum job foi enviado; foram usados os 8 jobs já executados no Open Plan") in t
    assert "pay-as-you-go US$ 96/min, flex US$ 72/min, premium US$ 48/min" in t
    assert "fonte https://www.ibm.com/quantum/pricing, consultada em 2026-11-03" in t
    assert f"lotes de 1.500.096 bits, 1 execução de aquecimento descartada e 20 medidas, sobre o commit `{COMMIT}`" in t
    assert "Critério: razão de pelo menos 10." in t
    for nome in ("e3_qpu.csv", "e3_local.csv", "e3_resumo.csv"):
        h = hashlib.sha256((ambiente / "data" / "results" / nome).read_bytes()).hexdigest()
        assert f"- `{nome}`: `{h}`" in t


def test_tabela_de_jobs(ambiente):
    rodar()
    b = bloco(ambiente)
    assert ("| cal | dbji1pgnceqs73ak2c8g | 1.000 | 156.000 | 2,0 | 78000,0000 | 3,2000 | 20,5128 "
            "| - | - | - |") in b
    c3 = [l for l in b if l.startswith("| coleta3 | dbkf4f1ffo6c73bbc8m0")][0]
    assert c3.startswith("| coleta3 | dbkf4f1ffo6c73bbc8m0 | 9.616 | 1.500.096 | 5,0 | 300019,2000 | 8,0000 | 5,3330 | reprovada | 0 | ")
    assert c3.endswith(f"| {reg.n_pt(hip_ref(1500096, 0.955903772587))} |")
    assert len([l for l in b if re.match(r"\| (cal|coleta\d) \| db", l)]) == 8


def test_tabela_do_resumo_e_tempos(ambiente):
    rodar()
    b = bloco(ambiente)
    assert "| `coleta_bits_brutos` | 9.000.576 | bits |" in b
    assert "| `razao_s_por_mbit_qpu_sobre_os` | 15,40 | vezes |" in b
    assert "| `coleta_custo_por_mbit_util_pay_as_you_go` | indefinido | USD/Mbit |" in b
    assert "| `preco_fonte` | https://www.ibm.com/quantum/pricing | url |" in b
    assert "| `criterio_muito_mais_caro` | True | booleano |" in b
    linha = [l for l in b if l.startswith("**Tempos locais por execução, em ordem (s):**")][0]
    assert "0,082213; 0,074158" in linha and linha.endswith("0,328416.")


def test_frases_calculadas(ambiente):
    rodar()
    t = "\n".join(bloco(ambiente))
    assert ("razão 15,40; hipótese \"muito mais caro que a `os`\" confirmada sob esta definição.") in t
    assert "A razão nos extremos dos tempos locais: 67,4" in t and "com a mais lenta, igual ou acima do limiar" in t
    assert "execuções 0 a 5 (6 execuções, de 0,074158 a 0,106602 s) e 6 a 19 (14 execuções, de 0,283410 a 0,384965 s)" in t
    assert "A mediana pré-registrada cai no grupo lento." in t
    assert "A causa da diferença não foi investigada." in t
    c_seg, c_mbit, l_mbit = Decimal(30), Decimal("9.000576"), Decimal("1.500096")
    assert f"{reg.dec4(reg.razao(c_seg, c_mbit, Decimal('0.384965'), l_mbit))} com a mais lenta" in t
    assert f"{reg.dec4(reg.razao(c_seg, c_mbit, Decimal('0.074158'), l_mbit))} com a execução mais rápida" in t


def test_frases_estruturais(ambiente):
    rodar()
    t = "\n".join(bloco(ambiente))
    assert "Nenhum dos jobs de coleta teve lote aprovado pela saúde" in t
    assert "custo fixo por job positivo" in t and "custo por megabit útil hipotético seria maior" in t
    assert "**Ressalvas:**" in t and "O custo é teórico." in t and "IBM_RU" in t
    assert t.count("\n- ") == 3 + 3 + 8 + 3


def test_veredito_nao_confirmado_quando_a_os_e_lenta(ambiente):
    gravar_dados_novos = lambda: None  # noqa: E731
    (ambiente / "data" / "results" / "e3_local.csv").unlink()
    (ambiente / "data" / "results" / "e3_resumo.csv").unlink()
    (ambiente / "data" / "results" / "e3_qpu.csv").unlink()
    gravar_dados(ambiente, local=linhas_local(tempos=["1.000000"] * 20))
    codigo, saida = rodar()
    t = "\n".join(bloco(ambiente))
    assert codigo == 0, saida
    assert "não confirmada sob esta definição" in t and "abaixo do limiar" in t
    assert "sem separação em dois grupos" in t and "cai no grupo" not in t


def test_mediana_igual_ao_menor_do_grupo_lento_conta_como_lento(ambiente):
    for n in ("e3_local.csv", "e3_resumo.csv", "e3_qpu.csv"):
        (ambiente / "data" / "results" / n).unlink()
    gravar_dados(ambiente, local=linhas_local(tempos=["0.080000"] * 8 + ["0.400000"] * 12))
    assert rodar()[0] == 0
    assert "A mediana pré-registrada cai no grupo lento." in "\n".join(bloco(ambiente))


def test_hashes_na_ordem(ambiente):
    rodar()
    b = bloco(ambiente)
    nomes = [re.match(r"- `(e3_\w+\.csv)`", l).group(1) for l in b if re.match(r"- `e3_\w+\.csv`", l)]
    assert nomes == ["e3_qpu.csv", "e3_local.csv", "e3_resumo.csv"]


@pytest.mark.parametrize("nome,campos", [("e3_qpu.csv", e3.CAMPOS_QPU), ("e3_local.csv", e3.CAMPOS_LOCAL),
                                         ("e3_resumo.csv", e3.CAMPOS_RESUMO)])
def test_recusa_csv_sem_linhas(ambiente, nome, campos):
    (ambiente / "data" / "results" / nome).write_bytes(e3.csv_bytes(campos, []))
    recusa(ambiente, f"{re.escape(nome)}: sem linhas")


def test_mediana_no_grupo_rapido(ambiente):
    (ambiente / "data" / "results" / "e3_local.csv").unlink()
    (ambiente / "data" / "results" / "e3_resumo.csv").unlink()
    (ambiente / "data" / "results" / "e3_qpu.csv").unlink()
    tempos = ["0.080000"] * 12 + ["0.400000"] * 8
    gravar_dados(ambiente, local=linhas_local(tempos=tempos))
    assert rodar()[0] == 0
    assert "A mediana pré-registrada cai no grupo rápido." in "\n".join(bloco(ambiente))


# ---------------------------------------------------------------- recusas
def estado(raiz: Path) -> dict[str, bytes]:
    return {str(p.relative_to(raiz)): p.read_bytes() for p in sorted(raiz.rglob("*")) if p.is_file()}


def recusa(raiz: Path, trecho: str):
    antes = estado(raiz)
    codigo, saida = rodar()
    assert codigo == 1 and saida[-1].startswith("RECUSADO") and re.search(trecho, saida[-1]), saida
    assert estado(raiz) == antes


def test_recusa_hash_marcador_crlf(ambiente, monkeypatch):
    monkeypatch.setattr(reg, "HASH_ANTES", "0" * 64)
    recusa(ambiente, "difere de HASH_ANTES")
    novo = PROJECT + reg.START.encode() + b"\r\n"
    (ambiente / "PROJECT.md").write_bytes(novo)
    monkeypatch.setattr(reg, "HASH_ANTES", hashlib.sha256(novo).hexdigest())
    recusa(ambiente, "marcador")
    for dados in (PROJECT.replace(b"\r\n", b"\n"), PROJECT.rstrip(b"\r\n")):
        (ambiente / "PROJECT.md").write_bytes(dados)
        monkeypatch.setattr(reg, "HASH_ANTES", hashlib.sha256(dados).hexdigest())
        recusa(ambiente, "CRLF puro")


def test_recusa_project_ausente(ambiente):
    (ambiente / "PROJECT.md").unlink()
    codigo, saida = rodar()
    assert codigo == 1 and "arquivo ausente" in saida[-1]


@pytest.mark.parametrize("nome", ["e3_qpu.csv", "e3_local.csv", "e3_resumo.csv"])
def test_recusa_csv_ausente(ambiente, nome):
    (ambiente / "data" / "results" / nome).unlink()
    codigo, saida = rodar()
    assert codigo == 1 and "não existe" in saida[-1]


@pytest.mark.parametrize("nome,campo", [("e3_qpu.csv", b"bits_por_s"), ("e3_local.csv", b"t_s"),
                                        ("e3_resumo.csv", b"unidade")])
def test_recusa_cabecalho(ambiente, nome, campo):
    p = ambiente / "data" / "results" / nome
    p.write_bytes(p.read_bytes().replace(campo, b"outro", 1))
    recusa(ambiente, "cabeçalho")


def test_recusa_resumo_adulterado(ambiente):
    p = ambiente / "data" / "results" / "e3_resumo.csv"
    p.write_bytes(p.read_bytes().replace(b"15.40", b"25.40", 1))
    recusa(ambiente, "derivação exata")


@pytest.mark.parametrize("commit", ["a" * 40, reg.COMMIT_CURTO + "X" * 33, reg.COMMIT_CURTO])
def test_recusa_commit(ambiente, commit):
    gravar_dados_forcado(ambiente, local=linhas_local(commit=commit))
    recusa(ambiente, "pré-registrada")


def gravar_dados_forcado(raiz, **kw):
    for n in ("e3_qpu.csv", "e3_local.csv", "e3_resumo.csv"):
        (raiz / "data" / "results" / n).unlink()
    gravar_dados(raiz, **kw)


def test_recusa_dois_commits(ambiente):
    ls = linhas_local()
    ls[0]["commit"] = reg.COMMIT_CURTO + "1" * 33
    gravar_dados_forcado(ambiente, local=ls)
    recusa(ambiente, "mais de um commit")


def test_recusa_tamanho_local_diferente(ambiente):
    gravar_dados_forcado(ambiente, local=linhas_local(n_bits="1000000"))
    recusa(ambiente, "tamanho do lote local")


def test_recusa_lote_aprovado(ambiente):
    gravar_dados_forcado(ambiente, qpu=linhas_qpu(aprovar=("dbkf24d6p51s73cmg7ng",)))
    recusa(ambiente, "Nenhum dos jobs de coleta teve lote aprovado")


def test_estruturais_recusam_formas_invalidas():
    r = {x["metrica"]: x["valor"] for x in e3.resumir(linhas_qpu(), linhas_local())}
    qpu = linhas_qpu()
    assert len(reg.verificar_estruturais(qpu, r)) == 3
    with pytest.raises(reg.Refused, match="aprovado"):
        reg.verificar_estruturais(qpu, {**r, "coleta_bits_uteis": "5"})
    with pytest.raises(reg.Refused, match="aprovado"):
        reg.verificar_estruturais(qpu, {**r, "coleta_lotes_aprovados": "1"})
    with pytest.raises(reg.Refused, match="aprovado"):
        reg.verificar_estruturais(qpu, {**r, "coleta_custo_por_mbit_util_pay_as_you_go": "9.0"})
    with pytest.raises(reg.Refused, match="aprovado"):
        reg.verificar_estruturais([l for l in qpu if l["sessao"] == "cal"], r)
    with pytest.raises(reg.Refused, match="aprovado"):                       # linhas dizem aprovada
        reg.verificar_estruturais(linhas_qpu(aprovar=("dbkf24d6p51s73cmg7ng",)), r)
    with pytest.raises(reg.Refused, match="ajuste"):
        reg.verificar_estruturais(qpu, {**r, "ajuste_fixo_s": "0.0000"})
    with pytest.raises(reg.Refused, match="ajuste"):
        reg.verificar_estruturais(qpu, {**r, "ajuste_fixo_s": "-1.0000"})
    with pytest.raises(reg.Refused, match="ajuste"):
        reg.verificar_estruturais(qpu, {**r, "ajuste_custo_marginal_por_mbit_pay_as_you_go": "6.0000"})
    with pytest.raises(reg.Refused, match="hipotético"):
        reg.verificar_estruturais(qpu, {**r, "coleta_custo_por_mbit_util_hipotetico_pay_as_you_go": "5.0000"})
    with pytest.raises(reg.Refused, match="ajuste de segundos"):          # chave ausente na checagem
        reg.verificar_estruturais(qpu, {k: v for k, v in r.items() if k != "ajuste_fixo_s"})
    with pytest.raises(reg.Refused, match="estrutura inesperada"):         # coluna ausente nas linhas
        reg.verificar_estruturais([{"job_id": "x"}], r)


def test_frases_recusam_resumo_inconsistente():
    qpu, local = linhas_qpu(), linhas_local()
    r = {x["metrica"]: x["valor"] for x in e3.resumir(qpu, local)}
    with pytest.raises(reg.Refused, match="razão recalculada"):
        reg.frases_calculadas(e3, qpu, local, {**r, "razao_s_por_mbit_qpu_sobre_os": "16.40"})
    with pytest.raises(reg.Refused, match="veredito"):
        reg.frases_calculadas(e3, qpu, local, {**r, "criterio_muito_mais_caro": "False"})


def test_ja_aplicado_exige_prefixo_original():
    ins = b"\r\nBLOCO\r\n"
    antigo, reg.HASH_ANTES = reg.HASH_ANTES, hashlib.sha256(PROJECT).hexdigest()
    try:
        assert reg.aplicar(PROJECT, ins) == PROJECT + ins
        assert reg.aplicar(PROJECT + ins, ins) is None
        with pytest.raises(reg.Refused):
            reg.aplicar(PROJECT + b"extra\r\n" + ins, ins)
    finally:
        reg.HASH_ANTES = antigo


def test_insercao_sem_cr():
    with pytest.raises(reg.Refused):
        reg.preparar_insercao("a\rb")
    assert reg.preparar_insercao("a\nb") == b"\r\na\r\nb\r\n"


def test_hash_antes_e_commit_fixos():
    fonte = (_RAIZ / "registrar_e3.py").read_text(encoding="utf-8")
    assert 'HASH_ANTES = "93266df50f08941f3a5ff6714b022343e890d1a2be696776dd10ec3722511033"' in fonte
    assert 'COMMIT_CURTO = "af1f1c4"' in fonte
    assert reg.START == "<!-- dia7-e3:start -->" and reg.END == "<!-- dia7-e3:end -->"
