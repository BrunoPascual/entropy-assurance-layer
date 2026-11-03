"""Testes de scripts/consolidar_dia7.py (pastas temporárias; um teste lê o data/results real se existir)."""
from __future__ import annotations

import csv
import hashlib
import importlib.util
import io
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("consolidar_dia7", ROOT / "scripts" / "consolidar_dia7.py")
cd = importlib.util.module_from_spec(_spec)
sys.modules["consolidar_dia7"] = cd
_spec.loader.exec_module(cd)

COMMIT = "a" * 40
LIMPA = lambda: (True, COMMIT)  # noqa: E731
SUJA = lambda: (False, COMMIT)  # noqa: E731

E3_REAL = ("metrica,valor,unidade\npreco_fonte,https://www.ibm.com/quantum/pricing,url\n"
           "coleta_bits_uteis,0,bits\ncoleta_custo_por_mbit_util_pay_as_you_go,indefinido,USD/Mbit\n"
           "razao_s_por_mbit_qpu_sobre_os,15.40,vezes\nlocal_execucoes,20,execuções\n")
E5_REAL = ("configuracao,esperado,n_reps,s_media,s_dp,se_media,s_min,s_max,frac_s_maior_2,margem,criterio_ok\n"
           "ideal_exato,S = 2*raiz(2) (exato),1,2.828427,0.000000,0.000000,2.828427,2.828427,1.0000,0.000000,True\n"
           "ideal_amostrado,compatível com 2*raiz(2),100,2.828795,0.024325,0.022354,2.770000,2.884500,1.0000,0.007297,True\n")


def escrever(path: Path, campos: list[str], linhas: list[dict]) -> None:
    buf = io.StringIO(newline="")
    w = csv.DictWriter(buf, fieldnames=campos, lineterminator="\r\n")
    w.writeheader()
    w.writerows(linhas)
    path.write_bytes(buf.getvalue().encode("utf-8"))


def popular(pasta: Path, pular: str = "") -> Path:
    """Um CSV sintético por fonte: 2 linhas, colunas exigidas mais uma extra."""
    for f in cd.FONTES:
        if f.arquivo == pular:
            continue
        if f.arquivo == "e3_resumo.csv":
            (pasta / f.arquivo).write_bytes(E3_REAL.encode("utf-8"))
            continue
        if f.arquivo == "e5_resumo.csv":
            (pasta / f.arquivo).write_bytes(E5_REAL.encode("utf-8"))
            continue
        campos = [*f.chave, *f.valores, "extra_ignorada"]
        linhas = []
        for i in range(2):
            l = {c: f"k{i}" for c in f.chave}
            l.update({c: f"{j}.{i}0" for j, c in enumerate(f.valores)})
            l["extra_ignorada"] = "nao_copiar"
            linhas.append(l)
        escrever(pasta / f.arquivo, campos, linhas)
    return pasta


@pytest.fixture
def pasta(tmp_path: Path) -> Path:
    return popular(tmp_path)


def ler(path: Path) -> list[dict]:
    return list(csv.DictReader(io.StringIO(path.read_bytes().decode("utf-8"), newline="")))


# --- especificação fixa ---

def test_toda_coluna_copiada_tem_unidade():
    for f in cd.FONTES:
        for c in f.valores:
            assert c in cd.UNIDADES, (f.arquivo, c)


def test_unidades_sem_entradas_orfas():
    usadas = {c for f in cd.FONTES for c in f.valores}
    assert set(cd.UNIDADES) == usadas


def test_cinco_experimentos_cobertos():
    assert {f.experimento for f in cd.FONTES} == set(cd.EXPERIMENTOS) == set(cd.ESTADOS)


def test_estados_fixados():
    assert {e: s for e, (s, _) in cd.ESTADOS.items()} == {
        "E1": "parcial", "E2": "completo", "E3": "completo", "E4": "completo", "E5": "parcial"}
    assert "coleta 1" in cd.ESTADOS["E1"][1]
    assert "QPU real não feito" in cd.ESTADOS["E5"][1]


def test_ressalvas_sem_digitos():
    for _, ressalva in cd.ESTADOS.values():
        texto = ressalva.replace("coleta 1", "").replace("coleta 2", "").replace("coleta 3", "")
        assert not any(ch.isdigit() for ch in texto)


def test_arquivos_de_origem_mapeados():
    arquivos = {f.arquivo for f in cd.FONTES}
    assert arquivos == {
        "dia6_qpu_vs_sim_resumo.csv", "dia6_coleta2_qpu_vs_sim_resumo.csv",
        "dia6_coleta3_qpu_vs_sim_resumo.csv", "dia6_qpu_vs_sim_lotes.csv",
        "dia6_coleta2_qpu_vs_sim_lotes.csv", "dia6_coleta3_qpu_vs_sim_lotes.csv",
        "dia6_deriva_dia_estabilidade.csv", "dia6_deriva_coleta2_estabilidade.csv",
        "dia6_deriva_coleta3_estabilidade.csv", "dia6_deriva_dia_conjunto_fixo.csv",
        "dia6_deriva_coleta2_conjunto_fixo.csv", "dia6_deriva_coleta3_conjunto_fixo.csv",
        "e2_resumo.csv", "e3_resumo.csv", "e4_resumo.csv", "e5_resumo.csv"}
    assert len(arquivos) == len(cd.FONTES)


def test_grupos_distintos():
    assert len({f.grupo for f in cd.FONTES}) == len(cd.FONTES)


def test_colunas_reais_do_lote_coleta3():
    cab = ("fonte,lote,source_id,is_simulated,n_bits,batch_hash,saude_schema,saude_batch_id,"
           "saude_source_id,saude_n_bits,saude_h_declared,saude_rct_pass,saude_rct_cutoff,"
           "saude_rct_max_run,saude_rct_max_run_start,saude_rct_alpha_neg_log2,saude_apt_pass,"
           "saude_apt_inconclusive,saude_apt_cutoff,saude_apt_max_count,saude_apt_n_windows,"
           "saude_apt_n_failed_windows,saude_apt_discarded_bits,saude_apt_alpha_neg_log2,"
           "saude_replay_pass,saude_replay_history_batches,saude_replay_n_blocks,"
           "saude_replay_repeated_blocks,saude_replay_batch_repeated,saude_h_bit,saude_h_byte,"
           "saude_h_estimated,saude_h_limited_by,saude_h_threshold,saude_h_health_pass,"
           "saude_stats_monobit,saude_stats_block,saude_stats_runs,saude_stats_pass,"
           "saude_stats_inconclusive,saude_approved,saude_reasons,saude_notes,pipe_status,"
           "pipe_reasons,pipe_error,pipe_seed_generated,ext_extractor_type,ext_guarantee,ext_n,"
           "ext_m,ext_h_used,ext_epsilon_log2,ext_epsilon_total_log2,ext_n_input_bits,"
           "ext_n_blocks,ext_n_output_bits,ext_discarded_bits,ext_input_hash,ext_notes,"
           "ext_rendimento").split(",")
    assert set(cd.LOTES + ("fonte", "lote")) <= set(cab)


# --- montagem ---

def test_montar_gate(pasta: Path):
    longo, gate = cd.montar(pasta, COMMIT)
    assert [g["experimento"] for g in gate] == list(cd.EXPERIMENTOS)
    for g in gate:
        assert int(g["n_metricas"]) == sum(1 for l in longo if l["experimento"] == g["experimento"])
        assert g["estado"] == cd.ESTADOS[g["experimento"]][0]
        assert g["commit"] == COMMIT
    e1 = gate[0]
    assert e1["n_arquivos"] == "12" and e1["arquivos"].count(";") == 11


def test_n_metricas_por_fonte_sintetica(pasta: Path):
    longo, gate = cd.montar(pasta, COMMIT)
    for f in cd.FONTES:
        n = sum(1 for l in longo if l["arquivo_origem"] == f.arquivo)
        if f.longo:
            assert n == 5
        elif f.arquivo == "e5_resumo.csv":
            assert n == 2 * len(f.valores)
        else:
            assert n == 2 * len(f.valores)


def test_valor_copiado_como_texto(pasta: Path):
    longo, _ = cd.montar(pasta, COMMIT)
    e5 = {(l["chave"], l["metrica"]): l["valor"] for l in longo if l["experimento"] == "E5"}
    assert e5[("tabela=e5_resumo;configuracao=ideal_exato", "s_dp")] == "0.000000"
    assert e5[("tabela=e5_resumo;configuracao=ideal_amostrado", "frac_s_maior_2")] == "1.0000"
    assert e5[("tabela=e5_resumo;configuracao=ideal_amostrado", "esperado")] == "compatível com 2*raiz(2)"
    assert e5[("tabela=e5_resumo;configuracao=ideal_exato", "criterio_ok")] == "True"


def test_e3_longo_com_unidade_da_origem(pasta: Path):
    longo, _ = cd.montar(pasta, COMMIT)
    e3 = {l["metrica"]: (l["valor"], l["unidade"], l["chave"]) for l in longo if l["experimento"] == "E3"}
    assert e3["coleta_custo_por_mbit_util_pay_as_you_go"] == ("indefinido", "USD/Mbit", "tabela=e3_resumo")
    assert e3["razao_s_por_mbit_qpu_sobre_os"][:2] == ("15.40", "vezes")
    assert e3["local_execucoes"][1] == "execuções"
    assert e3["preco_fonte"][0] == "https://www.ibm.com/quantum/pricing"


def test_chave_formato(pasta: Path):
    longo, _ = cd.montar(pasta, COMMIT)
    chaves = {l["chave"] for l in longo}
    assert "tabela=qpu_vs_sim_lotes;coleta=3;fonte=k1;lote=k1" in chaves
    assert "tabela=deriva_conjunto_fixo;deriva=mesmo_dia;tipo=k0;grupo=k0;id=k0;lote=k0" in chaves
    assert "tabela=e2_resumo;fonte=k0;parametro=k0;valor=k0;n_bits=k0;leitura=k0;tipo=k0" in chaves


def test_unidade_e_estado_por_linha(pasta: Path):
    longo, _ = cd.montar(pasta, COMMIT)
    for l in longo:
        assert l["estado"] == cd.ESTADOS[l["experimento"]][0]
        if l["experimento"] != "E3":
            assert l["unidade"] == cd.UNIDADES[l["metrica"]]


def test_sha256_da_origem(pasta: Path):
    longo, _ = cd.montar(pasta, COMMIT)
    for l in longo:
        assert l["sha256_origem"] == hashlib.sha256((pasta / l["arquivo_origem"]).read_bytes()).hexdigest()


def test_coluna_extra_nao_copiada(pasta: Path):
    longo, _ = cd.montar(pasta, COMMIT)
    assert not any(l["valor"] == "nao_copiar" or l["metrica"] == "extra_ignorada" for l in longo)


def test_celula_vazia_nao_vira_linha(pasta: Path):
    p = pasta / "e4_resumo.csv"
    linhas = ler(p)
    linhas[0]["frac_alvo"] = ""
    escrever(p, list(linhas[0]), linhas)
    longo, _ = cd.montar(pasta, COMMIT)
    e4 = [l for l in longo if l["experimento"] == "E4"]
    assert len(e4) == 2 * 17 - 1
    assert all(l["valor"] != "" for l in longo)


def test_chave_com_coluna_vazia_mantida(pasta: Path):
    p = pasta / "e4_resumo.csv"
    linhas = ler(p)
    linhas[0]["k"] = ""
    escrever(p, list(linhas[0]), linhas)
    longo, _ = cd.montar(pasta, COMMIT)
    assert any(l["chave"] == "tabela=e4_resumo;cenario=k0;combinador=k0;k=" for l in longo)


def test_deterministico(pasta: Path):
    a = cd.csv_bytes(cd.CAMPOS_LONG, cd.montar(pasta, COMMIT)[0])
    b = cd.csv_bytes(cd.CAMPOS_LONG, cd.montar(pasta, COMMIT)[0])
    assert a == b


def test_ordem_segue_fontes(pasta: Path):
    longo, _ = cd.montar(pasta, COMMIT)
    ordem = []
    for l in longo:
        if not ordem or ordem[-1] != l["arquivo_origem"]:
            ordem.append(l["arquivo_origem"])
    assert ordem == [f.arquivo for f in cd.FONTES]


# --- recusas ---

@pytest.mark.parametrize("arquivo", [f.arquivo for f in cd.FONTES])
def test_recusa_arquivo_ausente(tmp_path: Path, arquivo: str):
    popular(tmp_path, pular=arquivo)
    with pytest.raises(cd.Recusa, match="arquivo ausente"):
        cd.montar(tmp_path, COMMIT)


def test_recusa_coluna_ausente(pasta: Path):
    p = pasta / "e2_resumo.csv"
    linhas = ler(p)
    for l in linhas:
        del l["taxa"]
    escrever(p, list(linhas[0]), linhas)
    with pytest.raises(cd.Recusa, match="colunas ausentes: taxa"):
        cd.montar(pasta, COMMIT)


def test_recusa_coluna_de_chave_ausente(pasta: Path):
    p = pasta / "e5_resumo.csv"
    p.write_bytes(E5_REAL.replace("configuracao,", "config,").encode("utf-8"))
    with pytest.raises(cd.Recusa, match="configuracao"):
        cd.montar(pasta, COMMIT)


def test_recusa_e3_sem_unidade(pasta: Path):
    (pasta / "e3_resumo.csv").write_bytes(b"metrica,valor\nx,1\n")
    with pytest.raises(cd.Recusa, match="unidade"):
        cd.montar(pasta, COMMIT)


def test_recusa_chave_repetida(pasta: Path):
    p = pasta / "e4_resumo.csv"
    linhas = ler(p)
    escrever(p, list(linhas[0]), [linhas[0], linhas[0]])
    with pytest.raises(cd.Recusa, match="chave repetida"):
        cd.montar(pasta, COMMIT)


def test_recusa_sem_linhas(pasta: Path):
    (pasta / "e5_resumo.csv").write_bytes(E5_REAL.splitlines()[0].encode("utf-8") + b"\n")
    with pytest.raises(cd.Recusa, match="sem linhas"):
        cd.montar(pasta, COMMIT)


def test_recusa_nao_utf8(pasta: Path):
    (pasta / "e5_resumo.csv").write_bytes(E5_REAL.encode("cp1252"))
    with pytest.raises(cd.Recusa, match="UTF-8"):
        cd.montar(pasta, COMMIT)


def test_recusa_campos_a_mais(pasta: Path):
    (pasta / "e5_resumo.csv").write_bytes((E5_REAL + "x,y,1,2,3,4,5,6,7,8,9,10\n").encode("utf-8"))
    with pytest.raises(cd.Recusa, match="número de campos"):
        cd.montar(pasta, COMMIT)


def test_recusa_campos_a_menos(pasta: Path):
    (pasta / "e5_resumo.csv").write_bytes((E5_REAL + "x,y,1\n").encode("utf-8"))
    with pytest.raises(cd.Recusa, match="número de campos"):
        cd.montar(pasta, COMMIT)


def test_recusa_experimento_sem_metrica(pasta: Path):
    p = pasta / "e2_resumo.csv"
    linhas = ler(p)
    for l in linhas:
        for c in cd.FONTES[-4].valores:
            l[c] = ""
    escrever(p, list(linhas[0]), linhas)
    with pytest.raises(cd.Recusa, match="E2 sem nenhuma métrica"):
        cd.montar(pasta, COMMIT)


# --- saída e main ---

def test_csv_bytes_lf_utf8_sem_bom(pasta: Path):
    longo, _ = cd.montar(pasta, COMMIT)
    b = cd.csv_bytes(cd.CAMPOS_LONG, longo)
    assert not b.startswith(b"\xef\xbb\xbf") and b"\r\n" not in b
    assert b.decode("utf-8").splitlines()[0] == ",".join(cd.CAMPOS_LONG)
    assert "compatível" in b.decode("utf-8")


def test_conferir_nao_grava(pasta: Path, capsys):
    assert cd.main(["--conferir"], results=pasta, git=SUJA) == 0
    assert not (pasta / cd.OUT_LONG).exists() and not (pasta / cd.OUT_GATE).exists()
    out = capsys.readouterr().out
    assert "nada gravado" in out and "E1  parcial" in out and "E5  parcial" in out


def test_gravar_recusa_arvore_suja(pasta: Path, capsys):
    assert cd.main(["--gravar"], results=pasta, git=SUJA) == 1
    assert not (pasta / cd.OUT_LONG).exists() and not (pasta / cd.OUT_GATE).exists()
    assert "árvore suja" in capsys.readouterr().out


def test_gravar_ok(pasta: Path, capsys):
    assert cd.main(["--gravar"], results=pasta, git=LIMPA) == 0
    longo, gate = cd.montar(pasta, COMMIT)
    assert (pasta / cd.OUT_LONG).read_bytes() == cd.csv_bytes(cd.CAMPOS_LONG, longo)
    assert (pasta / cd.OUT_GATE).read_bytes() == cd.csv_bytes(cd.CAMPOS_GATE, gate)
    out = capsys.readouterr().out
    assert cd.sha256((pasta / cd.OUT_LONG).read_bytes()) in out
    assert cd.sha256((pasta / cd.OUT_GATE).read_bytes()) in out


def test_gravar_lido_de_volta(pasta: Path):
    cd.main(["--gravar"], results=pasta, git=LIMPA)
    gate = ler(pasta / cd.OUT_GATE)
    assert [g["estado"] for g in gate] == ["parcial", "completo", "completo", "completo", "parcial"]
    assert len(ler(pasta / cd.OUT_LONG)) == sum(int(g["n_metricas"]) for g in gate)


@pytest.mark.parametrize("existente", [cd.OUT_LONG, cd.OUT_GATE])
def test_gravar_recusa_se_existe(pasta: Path, existente: str):
    (pasta / existente).write_bytes(b"antigo")
    assert cd.main(["--gravar"], results=pasta, git=LIMPA) == 1
    assert (pasta / existente).read_bytes() == b"antigo"
    outro = cd.OUT_GATE if existente == cd.OUT_LONG else cd.OUT_LONG
    assert not (pasta / outro).exists()


def test_gravar_tudo_ou_nada(pasta: Path, monkeypatch):
    real = open
    def falso(path, mode="r", *a, **k):
        if str(path).endswith(cd.OUT_GATE):
            raise OSError("disco cheio")
        return real(path, mode, *a, **k)
    monkeypatch.setattr("builtins.open", falso)
    with pytest.raises(OSError):
        cd.gravar(pasta, b"a", b"b")
    assert not (pasta / cd.OUT_LONG).exists()


def test_recusa_nao_grava_nada(tmp_path: Path, capsys):
    popular(tmp_path, pular="e5_resumo.csv")
    assert cd.main(["--gravar"], results=tmp_path, git=LIMPA) == 1
    assert not (tmp_path / cd.OUT_LONG).exists()
    assert "RECUSADO" in capsys.readouterr().out


def test_git_falha_vira_recusa(pasta: Path, capsys):
    def quebrado():
        raise cd.Recusa("git indisponível ou pasta fora do repositório")
    assert cd.main(["--conferir"], results=pasta, git=quebrado) == 1
    assert "git indisponível" in capsys.readouterr().out


def test_estado_git_fora_do_repo(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))
    with pytest.raises(cd.Recusa, match="git"):
        cd.estado_git()


def test_modo_obrigatorio(pasta: Path):
    with pytest.raises(SystemExit):
        cd.main([], results=pasta, git=LIMPA)


# --- dados reais (só leitura; pulado se data/results não estiver presente) ---

def test_dados_reais_montam(capsys):
    real = ROOT / "data" / "results"
    if not (real / "e5_resumo.csv").is_file():
        pytest.skip("data/results real ausente")
    longo, gate = cd.montar(real, COMMIT)
    assert [g["experimento"] for g in gate] == list(cd.EXPERIMENTOS)
    assert all(int(g["n_metricas"]) > 0 for g in gate)
    e3 = {l["metrica"]: l["valor"] for l in longo if l["experimento"] == "E3"}
    assert e3["criterio_muito_mais_caro"] in ("True", "False")


# --- testes vindos de mutantes sobreviventes ---

def test_unidades_por_familia():
    for c, u in cd.UNIDADES.items():
        if c.endswith(("_pass", "_approved", "_ok")) or c in (
                "replica", "sinal_igual", "testavel", "magnitude_compativel"):
            assert u == "booleano", c
        if c.startswith(("frac", "taxa", "ic95")) or c == "ext_rendimento":
            assert u == "fração", c
        if c.startswith("s_") or c in ("se_media", "margem"):
            assert u == "S", c
        if c.startswith(("n_", "saude_stats_m")) and c != "n_bits":
            assert u in ("contagem", "p"), c
    assert cd.UNIDADES["saude_approved"] == "booleano"
    assert cd.UNIDADES["saude_h_estimated"] == "bits/bit"


def test_recusa_chave_repetida_com_valores_diferentes(pasta: Path):
    p = pasta / "e4_resumo.csv"
    linhas = ler(p)
    outra = dict(linhas[1])
    outra.update({c: linhas[0][c] for c in ("cenario", "combinador", "k")})
    escrever(p, list(linhas[0]), [linhas[0], outra])
    with pytest.raises(cd.Recusa, match="chave repetida"):
        cd.montar(pasta, COMMIT)


def _repo(tmp_path: Path) -> Path:
    import subprocess
    r = tmp_path / "repo"
    r.mkdir()
    g = ["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false"]
    subprocess.run(["git", "init", "-q"], cwd=r, check=True)
    (r / "a.txt").write_text("a")
    subprocess.run([*g, "add", "a.txt"], cwd=r, check=True)
    subprocess.run([*g, "commit", "-q", "-m", "x"], cwd=r, check=True)
    return r


def test_estado_git_limpo_e_sujo(tmp_path: Path, monkeypatch):
    if not __import__("shutil").which("git"):
        pytest.skip("git ausente")
    r = _repo(tmp_path)
    monkeypatch.chdir(r)
    limpa, head = cd.estado_git()
    assert limpa is True and len(head) == 40
    (r / "novo.txt").write_text("b")
    assert cd.estado_git() == (False, head)


def test_gravar_nao_sobrescreve_em_corrida(pasta: Path, monkeypatch):
    (pasta / cd.OUT_LONG).write_bytes(b"antigo")
    monkeypatch.setattr(cd.Path, "exists", lambda self: False)
    with pytest.raises(FileExistsError):
        cd.gravar(pasta, b"novo", b"b")
    assert (pasta / cd.OUT_LONG).read_bytes() == b"antigo"
