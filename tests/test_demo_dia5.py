"""Testes da demo ponta a ponta (Dia 5, etapa 5).

Quase tudo aqui roda sem a CLI real: a função ``run_demo`` recebe um ``runner``
falso (``FakeCli``) que imita a CLI em pasta temporária. O falso mostra que a
LÓGICA da demo está certa (ordem dos passos, repetição, conferência de texto,
cópias), não que a CLI real esteja correta. A CLI real só roda no teste
opcional, ligado com ``EAL_E2E=1``.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

from scripts import demo_dia5 as demo

ROOT = Path(__file__).resolve().parents[1]
GUARDED = (
    Path("keys"),
    Path("data") / "receipts",
    Path("data") / "logs",
    Path("data") / "public_keys",
)
EXPECTED_CODES = [0, 0, 0, 0, 0, 1, 1, 0, 1]
SHA3_ABC = "3a985da74fe225b2045c172d6bd390bd855f086e3e9d525b46bfe24511431532"


def _snapshot_real() -> list[tuple[str, int, int]]:
    items: list[tuple[str, int, int]] = []
    for rel in GUARDED:
        base = ROOT / rel
        if base.is_dir():
            for path in sorted(base.rglob("*")):
                if path.is_file():
                    st = path.stat()
                    items.append((str(path.relative_to(ROOT)), st.st_size, st.st_mtime_ns))
    return items


@pytest.fixture(autouse=True)
def _nunca_gravar_nas_pastas_reais():
    """Barreira: nenhum teste deste arquivo pode mexer em keys/ nem em data/ reais."""
    before = _snapshot_real()
    yield
    assert _snapshot_real() == before, "o teste mexeu nas pastas reais do projeto"


def _passo_lines(text: str) -> list[str]:
    """Números dos passos que terminam em OK; aceita CRLF (modo texto do Windows)."""
    return re.findall(r"^passo (\d): .*\| OK$", text.replace("\r\n", "\n"), re.M)


def _project(tmp_path: Path) -> Path:
    project = tmp_path / "proj"
    project.mkdir()
    return project


# ------------------------------------------------------- leitura da saída

def test_passo_lines_aceita_crlf_do_windows():
    text = (
        "passo 1: t | esperado 0 | obtido 0 | OK\r\n"
        "passo 2: t | esperado 1 | obtido 0 | FALHOU\r\n"
        "passo 3: t | esperado 0 | obtido 0 | OK\r\n"
    )
    assert _passo_lines(text) == ["1", "3"]


def test_passo_lines_aceita_lf():
    assert _passo_lines("passo 7: t | esperado 1 | obtido 1 | OK\n") == ["7"]


# ------------------------------------------------------------ constantes

def test_limites_da_demo():
    assert demo.MAX_RUN_ATTEMPTS == 3
    assert demo.STEP_COUNT == 9


def test_constantes_batem_com_a_cli():
    cli = pytest.importorskip("eal.cli")
    config = pytest.importorskip("eal.config")
    assert Path(cli.KEYS_DIR) == demo.KEYS_REL
    assert Path(cli.RECEIPTS_DIR) == demo.RECEIPTS_REL
    assert Path(cli.LOGS_DIR) / cli.RUN_LOG_NAME == demo.LOGS_REL / demo.RUN_LOG_NAME
    assert config.RECEIPT_CHAIN_NAME == demo.CHAIN_NAME


# ------------------------------------------------------------ pasta da demo

def test_check_aceita_pasta_nova_fora_do_projeto(tmp_path):
    project = _project(tmp_path)
    target = tmp_path / "demo"
    assert demo.check_demo_dir(target, project) == target.resolve()
    assert not target.exists()


def test_check_aceita_pasta_irma_com_o_mesmo_prefixo(tmp_path):
    project = _project(tmp_path)
    (tmp_path / "proj2").mkdir()
    target = tmp_path / "proj2" / "demo"
    assert demo.check_demo_dir(target, project) == target.resolve()


def test_check_recusa_pasta_existente_mesmo_vazia(tmp_path):
    project = _project(tmp_path)
    target = tmp_path / "demo"
    target.mkdir()
    with pytest.raises(demo.DemoError):
        demo.check_demo_dir(target, project)
    assert list(target.iterdir()) == []


def test_check_recusa_a_raiz_do_projeto(tmp_path):
    project = _project(tmp_path)
    with pytest.raises(demo.DemoError):
        demo.check_demo_dir(project, project)


@pytest.mark.parametrize("rel", ["data/demo", "keys/demo", "scratch/demo", "data/receipts/demo"])
def test_check_recusa_pasta_nova_dentro_do_projeto(tmp_path, rel):
    project = _project(tmp_path)
    target = project / rel
    with pytest.raises(demo.DemoError):
        demo.check_demo_dir(target, project)
    assert not target.exists()
    assert list(project.iterdir()) == []


def test_check_recusa_caminho_com_ponto_ponto_que_cai_no_projeto(tmp_path):
    project = _project(tmp_path)
    target = project / "data" / ".." / "keys" / "x"
    with pytest.raises(demo.DemoError):
        demo.check_demo_dir(target, project)
    assert list(project.iterdir()) == []


def test_default_demo_dir_fica_no_temp_e_nao_existe(monkeypatch, tmp_path):
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    found = demo.default_demo_dir(datetime(2026, 10, 31, 12, 0, 5, tzinfo=timezone.utc))
    assert found == tmp_path / "eal_demo_20261031_120005"
    assert not found.exists()


def test_default_demo_dir_muda_com_o_horario(monkeypatch, tmp_path):
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    a = demo.default_demo_dir(datetime(2026, 10, 31, 12, 0, 5, tzinfo=timezone.utc))
    b = demo.default_demo_dir(datetime(2026, 10, 31, 12, 0, 6, tzinfo=timezone.utc))
    assert a != b


# ------------------------------------------------------------------- log

def _line(**fields) -> bytes:
    return json.dumps(fields).encode()


def test_read_log_lines_sem_arquivo_devolve_vazio(tmp_path):
    assert demo.read_log_lines(tmp_path / "nada.jsonl") == []


def test_read_log_lines_ignora_linhas_vazias(tmp_path):
    path = tmp_path / "log.jsonl"
    path.write_bytes(b"a\n\nb\n")
    assert demo.read_log_lines(path) == [b"a", b"b"]


def test_new_log_entries_pega_so_as_novas():
    lines = [_line(n=1), _line(n=2), _line(n=3)]
    assert demo.new_log_entries(1, lines) == [{"n": 2}, {"n": 3}]


def test_new_log_entries_json_invalido_ou_nao_objeto_vira_dict_vazio():
    assert demo.new_log_entries(0, [b"{", b"[1]", b'"x"', b"\xff"]) == [{}, {}, {}, {}]


_FAIL = {"command": "run", "stage": "pipeline", "ok": False}


@pytest.mark.parametrize(
    "code,entries,command,attempt,expected",
    [
        (1, [_FAIL], "run", 1, True),
        (1, [_FAIL], "run", 2, True),
        (1, [_FAIL], "run", 3, False),
        (0, [_FAIL], "run", 1, False),
        (2, [_FAIL], "run", 1, False),
        (1, [], "run", 1, False),
        (1, [_FAIL, _FAIL], "run", 1, False),
        (1, [{**_FAIL, "stage": "chain"}], "run", 1, False),
        (1, [{**_FAIL, "stage": "issuer_key"}], "run", 1, False),
        (1, [{**_FAIL, "stage": "public_keys"}], "run", 1, False),
        (1, [{**_FAIL, "stage": "unexpected"}], "run", 1, False),
        (1, [{**_FAIL, "command": "init-issuer"}], "run", 1, False),
        (1, [_FAIL], "init-issuer", 1, False),
        (1, [{**_FAIL, "command": "init-issuer"}], "init-issuer", 1, True),
        (1, [{**_FAIL, "ok": True}], "run", 1, False),
        (1, [{}], "run", 1, False),
    ],
)
def test_should_retry(code, entries, command, attempt, expected):
    assert demo.should_retry(code, entries, command, attempt) is expected


# ----------------------------------------------------------------- cadeia

def _write_chain(directory: Path, count: int) -> list[str]:
    directory.mkdir(parents=True, exist_ok=True)
    ids: list[str] = []
    blob = b""
    for i in range(1, count + 1):
        rid = f"00000000-0000-4000-8000-{i:012d}"
        line = json.dumps(
            {"mode": "keygen", "n": i, "receipt_id": rid}, sort_keys=True, separators=(",", ":")
        ).encode() + b"\n"
        blob += line
        (directory / f"{rid}.json").write_bytes(line)
        ids.append(rid)
    (directory / "chain.jsonl").write_bytes(blob)
    return ids


def test_chain_head_resposta_conhecida(tmp_path):
    path = tmp_path / "chain.jsonl"
    path.write_bytes(b"abc\n")
    assert demo.chain_head_from_file(path) == SHA3_ABC


def test_chain_head_usa_a_ultima_linha(tmp_path):
    path = tmp_path / "chain.jsonl"
    path.write_bytes(b"x\nabc\n")
    assert demo.chain_head_from_file(path) == SHA3_ABC


@pytest.mark.parametrize("content", [b"", b"abc", b"a\n\nb\n"])
def test_chain_head_recusa_arquivo_estranho(tmp_path, content):
    path = tmp_path / "chain.jsonl"
    path.write_bytes(content)
    with pytest.raises(demo.DemoError):
        demo.chain_head_from_file(path)


def test_chain_head_recusa_arquivo_ausente(tmp_path):
    with pytest.raises(demo.DemoError):
        demo.chain_head_from_file(tmp_path / "nada.jsonl")


def test_receipt_ids_na_ordem(tmp_path):
    ids = _write_chain(tmp_path / "r", 3)
    assert demo.receipt_ids(tmp_path / "r" / "chain.jsonl") == ids


@pytest.mark.parametrize(
    "content",
    [b"{\n", b'{"outra":1}\n', b'{"receipt_id":5}\n', b"[1]\n"],
)
def test_receipt_ids_recusa_linha_estranha(tmp_path, content):
    path = tmp_path / "chain.jsonl"
    path.write_bytes(content)
    with pytest.raises(demo.DemoError):
        demo.receipt_ids(path)


def test_tamper_copy_troca_exatamente_um_byte(tmp_path):
    src = tmp_path / "r.json"
    original = b'{"a":1,\r\n"mode":"keygen","z":2}\n'
    src.write_bytes(original)
    dst = tmp_path / "sub" / "r.json"
    demo.tamper_copy(src, dst)
    out = dst.read_bytes()
    assert len(out) == len(original)
    assert sum(1 for a, b in zip(out, original) if a != b) == 1
    assert b'"mode":"keygex"' in out
    assert b"\r\n" in out
    assert src.read_bytes() == original


def test_tamper_copy_troca_so_a_primeira_ocorrencia(tmp_path):
    src = tmp_path / "r.json"
    src.write_bytes(b'{"mixer":{"mode":"keygen"},"mode":"keygen"}\n')
    dst = tmp_path / "c.json"
    demo.tamper_copy(src, dst)
    assert dst.read_bytes().count(b'"mode":"keygen"') == 1
    assert dst.read_bytes().count(b'"mode":"keygex"') == 1


def test_tamper_copy_recusa_recibo_sem_o_trecho_e_nao_cria_nada(tmp_path):
    src = tmp_path / "r.json"
    src.write_bytes(b'{"a":1}\n')
    dst = tmp_path / "sub" / "c.json"
    with pytest.raises(demo.DemoError):
        demo.tamper_copy(src, dst)
    assert not dst.parent.exists()


def test_tamper_copy_nunca_sobrescreve(tmp_path):
    src = tmp_path / "r.json"
    src.write_bytes(b'{"mode":"keygen"}\n')
    dst = tmp_path / "c.json"
    dst.write_bytes(b"antigo")
    with pytest.raises(demo.DemoError):
        demo.tamper_copy(src, dst)
    assert dst.read_bytes() == b"antigo"


def test_truncate_chain_copy_tira_o_ultimo_recibo(tmp_path):
    src = tmp_path / "r"
    ids = _write_chain(src, 3)
    (src / ".gitkeep").write_bytes(b"")
    before = {p.name: p.read_bytes() for p in src.iterdir()}
    kept, removed = demo.truncate_chain_copy(src, tmp_path / "t")
    assert (kept, removed) == (ids[1], ids[2])
    chain = (tmp_path / "t" / "chain.jsonl").read_bytes()
    assert chain == before["chain.jsonl"].split(b"\n", 2)[0] + b"\n" + \
        before["chain.jsonl"].split(b"\n", 2)[1] + b"\n"
    assert sorted(p.name for p in (tmp_path / "t").iterdir()) == sorted(
        ["chain.jsonl", f"{ids[0]}.json", f"{ids[1]}.json"]
    )
    assert {p.name: p.read_bytes() for p in src.iterdir()} == before


def test_truncate_chain_copy_recusa_cadeia_curta_e_nao_cria_nada(tmp_path):
    _write_chain(tmp_path / "r", 1)
    with pytest.raises(demo.DemoError):
        demo.truncate_chain_copy(tmp_path / "r", tmp_path / "t")
    assert not (tmp_path / "t").exists()


def test_truncate_chain_copy_recusa_destino_existente(tmp_path):
    _write_chain(tmp_path / "r", 2)
    (tmp_path / "t").mkdir()
    with pytest.raises(demo.DemoError):
        demo.truncate_chain_copy(tmp_path / "r", tmp_path / "t")
    assert list((tmp_path / "t").iterdir()) == []


def test_truncate_chain_copy_recusa_arquivo_individual_ausente(tmp_path):
    ids = _write_chain(tmp_path / "r", 2)
    (tmp_path / "r" / f"{ids[0]}.json").unlink()
    with pytest.raises(demo.DemoError):
        demo.truncate_chain_copy(tmp_path / "r", tmp_path / "t")
    assert not (tmp_path / "t").exists()


# ------------------------------------------------------------------- CLI

def test_cli_command_usa_o_mesmo_python_e_o_modulo_eal():
    assert demo.cli_command(["verify", "x"]) == [sys.executable, "-m", "eal", "verify", "x"]


def test_build_cli_env_define_utf8_e_pythonpath(tmp_path):
    base = {"PATH": "p", "PYTHONPATH": "velho"}
    env = demo.build_cli_env(tmp_path, base)
    assert env["PYTHONIOENCODING"] == "utf-8"
    assert env["PYTHONPATH"].split(os.pathsep) == [str(tmp_path), "velho"]
    assert env["PATH"] == "p"
    assert base == {"PATH": "p", "PYTHONPATH": "velho"}


def test_build_cli_env_sem_pythonpath_previo(tmp_path):
    assert demo.build_cli_env(tmp_path, {})["PYTHONPATH"] == str(tmp_path)


class _Proc:
    def __init__(self, code, out, err):
        self.returncode, self.stdout, self.stderr = code, out, err


def test_run_cli_chama_o_subprocesso_e_decodifica_utf8(monkeypatch, tmp_path):
    seen = {}

    def fake_run(cmd, **kwargs):
        seen["cmd"], seen["kwargs"] = cmd, kwargs
        return _Proc(1, "válido".encode(), "cabeça".encode())

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = demo.run_cli(["verify", "x"], tmp_path / "w", tmp_path / "root")
    assert result == demo.CliResult(1, "válido", "cabeça")
    assert seen["cmd"] == demo.cli_command(["verify", "x"])
    assert seen["kwargs"]["cwd"] == str(tmp_path / "w")
    assert seen["kwargs"]["capture_output"] is True
    assert seen["kwargs"]["timeout"] == demo.CLI_TIMEOUT_SECONDS
    assert seen["kwargs"]["env"]["PYTHONIOENCODING"] == "utf-8"
    assert seen["kwargs"]["env"]["PYTHONPATH"].split(os.pathsep)[0] == str(tmp_path / "root")


def test_run_cli_estouro_de_tempo_vira_erro_da_demo(monkeypatch, tmp_path):
    def fake_run(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd, 1)

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(demo.DemoError):
        demo.run_cli(["run"], tmp_path)


def test_cli_result_text_junta_stdout_e_stderr():
    assert "saida" in demo.CliResult(0, "saida", "erro").text
    assert "erro" in demo.CliResult(0, "saida", "erro").text


# ----------------------------------------------------------- CLI falsa

class FakeCli:
    """Imita a CLI em pasta temporária. Mostra a lógica da demo, não a CLI real."""

    def __init__(self, *, init_stages=(), run_stages=(), tamper_passes=False,
                 hide_head_text=False, skip_chain=False):
        self.calls: list[tuple[list[str], Path]] = []
        self.init_stages = list(init_stages)
        self.run_stages = list(run_stages)
        self.tamper_passes = tamper_passes
        self.hide_head_text = hide_head_text
        self.skip_chain = skip_chain
        self.ok_runs = 0
        self.reason = "motivo-falso-do-pipeline"
        self.expected_chain = b""
        self.lines: list[bytes] = []

    def __call__(self, args, cwd):
        cwd = Path(cwd)
        self.calls.append((list(args), cwd))
        if args[0] == "init-issuer":
            stage = self.init_stages.pop(0) if self.init_stages else None
            return self._fail(cwd, "init-issuer", stage) if stage else demo.CliResult(0, "ok\n", "")
        if args[0] == "run":
            stage = self.run_stages.pop(0) if self.run_stages else None
            return self._fail(cwd, "run", stage) if stage else self._run_ok(cwd)
        return self._verify(args, cwd)

    def _fail(self, cwd, command, stage):
        log = cwd / "data" / "logs" / "eal_runs.jsonl"
        log.parent.mkdir(parents=True, exist_ok=True)
        entry = {"ts": "t", "command": command, "stage": stage, "ok": False,
                 "reason": self.reason, "pipeline": None}
        with open(log, "ab") as fh:
            fh.write(json.dumps(entry).encode() + b"\n")
        return demo.CliResult(1, "", f"erro: {stage}")

    def _run_ok(self, cwd):
        self.ok_runs += 1
        rid = f"00000000-0000-4000-8000-{self.ok_runs:012d}"
        line = json.dumps({"mode": "keygen", "n": self.ok_runs, "receipt_id": rid},
                          sort_keys=True, separators=(",", ":")).encode() + b"\n"
        if not self.skip_chain:
            folder = cwd / "data" / "receipts"
            folder.mkdir(parents=True, exist_ok=True)
            with open(folder / "chain.jsonl", "ab") as fh:
                fh.write(line)
            (folder / f"{rid}.json").write_bytes(line)
            self.expected_chain += line
            self.lines.append(line)
        return demo.CliResult(0, f"receipt_id: {rid}\n", "")

    def _verify(self, args, cwd):
        target = cwd / args[1]
        opts = dict(zip(args[2:], args[3:]))
        content = target.read_bytes()
        if b"keygex" in content and not self.tamper_passes:
            return demo.CliResult(1, "", "recibo reprovado: assinatura\n")
        chain_dir = cwd / opts["--chain-dir"] if "--chain-dir" in opts else target.parent
        chain = chain_dir / "chain.jsonl"
        if not chain.exists():
            return demo.CliResult(1, "", "erro: use --chain-dir ou --sem-cadeia\n")
        lines = chain.read_bytes().split(b"\n")[:-1]
        rid = target.stem
        ids = [json.loads(ln)["receipt_id"] for ln in lines]
        if rid not in ids:
            return demo.CliResult(1, "", "cadeia reprovada: recibo fora do log\n")
        if "--expected-head" in opts and opts["--expected-head"] != hashlib.sha3_256(lines[-1]).hexdigest():
            return demo.CliResult(1, "", "cadeia reprovada: cabeça diferente\n")
        text = f"recibo válido: {rid}\ncadeia: posição {ids.index(rid) + 1} de {len(ids)}\n"
        if "--expected-head" in opts and not self.hide_head_text:
            text += "cabeça conferida\n"
        return demo.CliResult(0, text, "")


def _kinds(fake: FakeCli) -> list[str]:
    return [args[0] for args, _ in fake.calls]


# --------------------------------------------------------------- run_demo

def test_run_demo_caminho_feliz(tmp_path):
    fake, demo_dir = FakeCli(), tmp_path / "demo"
    report = demo.run_demo(demo_dir, fake)
    assert report.aborted is None
    assert [s.number for s in report.steps] == list(range(1, 10))
    assert [s.expected_code for s in report.steps] == EXPECTED_CODES
    assert [s.got_code for s in report.steps] == EXPECTED_CODES
    assert all(s.ok for s in report.steps)
    assert report.ok is True
    assert all(cwd == demo_dir for _, cwd in fake.calls)
    assert _kinds(fake) == ["init-issuer", "run", "run"] + ["verify"] * 6


def test_run_demo_usa_caminhos_e_cabecas_certos(tmp_path):
    fake, demo_dir = FakeCli(), tmp_path / "demo"
    demo.run_demo(demo_dir, fake)
    chain = demo_dir / "data" / "receipts" / "chain.jsonl"
    ids = demo.receipt_ids(chain)
    head2 = hashlib.sha3_256(fake.lines[-1].rstrip(b"\n")).hexdigest()
    rec = Path("data") / "receipts"
    verifies = [args for args, _ in fake.calls if args[0] == "verify"]
    assert verifies == [
        ["verify", str(rec / f"{ids[1]}.json"), "--expected-head", head2],
        ["verify", str(rec / f"{ids[0]}.json")],
        ["verify", str(Path("tamper") / f"{ids[1]}.json"), "--chain-dir", str(rec)],
        ["verify", str(rec / f"{ids[1]}.json"), "--expected-head", "a" * 64],
        ["verify", str(Path("truncated") / f"{ids[0]}.json")],
        ["verify", str(Path("truncated") / f"{ids[0]}.json"), "--expected-head", head2],
    ]


def test_run_demo_nao_mexe_na_cadeia_da_demo_e_faz_as_copias(tmp_path):
    fake, demo_dir = FakeCli(), tmp_path / "demo"
    demo.run_demo(demo_dir, fake)
    rec = demo_dir / "data" / "receipts"
    assert (rec / "chain.jsonl").read_bytes() == fake.expected_chain
    for line in fake.lines:
        rid = json.loads(line)["receipt_id"]
        assert (rec / f"{rid}.json").read_bytes() == line
    ids = demo.receipt_ids(rec / "chain.jsonl")
    tampered = (demo_dir / "tamper" / f"{ids[1]}.json").read_bytes()
    assert tampered != fake.lines[1]
    assert len(tampered) == len(fake.lines[1])
    assert (demo_dir / "truncated" / "chain.jsonl").read_bytes() == fake.lines[0]


def test_run_demo_repete_run_com_falha_de_pipeline(tmp_path):
    fake = FakeCli(run_stages=["pipeline"])
    report = demo.run_demo(tmp_path / "demo", fake)
    assert report.ok
    assert _kinds(fake).count("run") == 3
    assert "tentativas: 2" in report.steps[1].detail
    assert fake.reason in report.steps[1].detail
    assert "tentativas" not in report.steps[2].detail


def test_run_demo_repete_init_issuer_com_falha_de_pipeline(tmp_path):
    fake = FakeCli(init_stages=["pipeline"])
    report = demo.run_demo(tmp_path / "demo", fake)
    assert report.ok
    assert _kinds(fake).count("init-issuer") == 2
    assert "tentativas: 2" in report.steps[0].detail


def test_run_demo_desiste_depois_de_tres_tentativas(tmp_path):
    fake = FakeCli(run_stages=["pipeline"] * 3)
    report = demo.run_demo(tmp_path / "demo", fake)
    assert report.aborted is not None
    assert report.ok is False
    assert [s.number for s in report.steps] == [1, 2]
    assert report.steps[1].ok is False and report.steps[1].got_code == 1
    assert _kinds(fake) == ["init-issuer", "run", "run", "run"]


def test_run_demo_nao_repete_falha_que_nao_e_de_pipeline(tmp_path):
    fake = FakeCli(run_stages=["chain"])
    report = demo.run_demo(tmp_path / "demo", fake)
    assert report.aborted is not None
    assert _kinds(fake) == ["init-issuer", "run"]


def test_run_demo_falha_do_init_issuer_aborta_sem_rodar_o_resto(tmp_path):
    fake = FakeCli(init_stages=["issuer_key"])
    report = demo.run_demo(tmp_path / "demo", fake)
    assert report.aborted is not None
    assert [s.number for s in report.steps] == [1]
    assert _kinds(fake) == ["init-issuer"]


def test_run_demo_adulterado_que_passa_marca_falha_e_continua(tmp_path):
    report = demo.run_demo(tmp_path / "demo", FakeCli(tamper_passes=True))
    assert [s.ok for s in report.steps] == [True] * 5 + [False] + [True] * 3
    assert (report.steps[5].expected_code, report.steps[5].got_code) == (1, 0)
    assert report.ok is False and report.aborted is None


def test_run_demo_exige_o_texto_esperado_alem_do_codigo(tmp_path):
    report = demo.run_demo(tmp_path / "demo", FakeCli(hide_head_text=True))
    assert [s.ok for s in report.steps] == [True] * 3 + [False] + [True] * 5
    assert report.steps[3].got_code == 0
    assert "texto esperado ausente" in report.steps[3].detail


def test_run_demo_exige_que_o_run_acrescente_um_recibo(tmp_path):
    report = demo.run_demo(tmp_path / "demo", FakeCli(skip_chain=True))
    assert report.steps[1].ok is False and report.steps[1].got_code == 0
    assert report.aborted is not None


def test_run_demo_recusa_pasta_existente_sem_chamar_a_cli(tmp_path):
    fake, demo_dir = FakeCli(), tmp_path / "demo"
    demo_dir.mkdir()
    with pytest.raises(demo.DemoError):
        demo.run_demo(demo_dir, fake)
    assert fake.calls == []


# ----------------------------------------------------------- relatório

def _steps(count=9, bad=()):
    return tuple(
        demo.StepResult(n, f"titulo {n}", 0, 0 if n not in bad else 1, n not in bad,
                        "" if n not in bad else "texto esperado ausente: abc")
        for n in range(1, count + 1)
    )


def test_report_ok_exige_nove_passos_ok_e_sem_aborto():
    assert demo.DemoReport(_steps(9), None).ok is True
    assert demo.DemoReport(_steps(8), None).ok is False
    assert demo.DemoReport(_steps(9, bad=(4,)), None).ok is False
    assert demo.DemoReport(_steps(9), "abortado").ok is False


def test_format_report_uma_linha_por_passo_e_resultado_ok():
    text = demo.format_report(demo.DemoReport(_steps(9), None))
    found = re.findall(r"^passo (\d): titulo \d \| esperado 0 \| obtido 0 \| OK$", text, re.M)
    assert found == [str(n) for n in range(1, 10)]
    assert text.splitlines()[-1] == "RESULTADO: OK (9 de 9 passos)"


def test_format_report_falha_mostra_detalhe_e_contagem():
    text = demo.format_report(demo.DemoReport(_steps(9, bad=(6,)), None))
    assert "passo 6: titulo 6 | esperado 0 | obtido 1 | FALHOU" in text
    assert "    texto esperado ausente: abc" in text
    assert text.splitlines()[-1] == "RESULTADO: FALHOU (8 de 9 passos ok)"


def test_format_report_aborto_lista_o_motivo():
    steps = (_steps(2)[0], _steps(2, bad=(2,))[1])
    text = demo.format_report(demo.DemoReport(steps, "passo 2 falhou"))
    assert "ABORTADO: passo 2 falhou" in text
    assert text.splitlines()[-1] == "RESULTADO: FALHOU (1 de 9 passos ok)"


def test_format_report_mostra_a_saida_da_cli_indentada():
    step = demo.StepResult(1, "t", 0, 0, True, "", ("linha a", "linha b"))
    text = demo.format_report(demo.DemoReport((step,), None))
    assert "    > linha a" in text and "    > linha b" in text


# ------------------------------------------------------------------ main

def test_main_recusa_pasta_existente_com_codigo_2(tmp_path, capsys):
    project, target = _project(tmp_path), tmp_path / "demo"
    target.mkdir()
    code = demo.main(["--pasta", str(target)], _runner=FakeCli(), _project_root=project)
    assert code == 2
    assert "erro:" in capsys.readouterr().err
    assert list(target.iterdir()) == []


def test_main_recusa_pasta_dentro_do_projeto_com_codigo_2(tmp_path):
    project = _project(tmp_path)
    target = project / "data" / "demo"
    code = demo.main(["--pasta", str(target)], _runner=FakeCli(), _project_root=project)
    assert code == 2
    assert not target.exists()
    assert list(project.iterdir()) == []


def test_main_caminho_feliz(tmp_path, capsys):
    project, target = _project(tmp_path), tmp_path / "demo"
    code = demo.main(["--pasta", str(target)], _runner=FakeCli(), _project_root=project)
    out = capsys.readouterr().out
    assert code == 0
    assert re.findall(r"^passo (\d):", out, re.M) == [str(n) for n in range(1, 10)]
    assert "RESULTADO: OK (9 de 9 passos)" in out
    assert "pasta da demo:" in out
    assert "não é apagada" in out


def test_main_falha_de_passo_devolve_1(tmp_path, capsys):
    code = demo.main(["--pasta", str(tmp_path / "demo")], _runner=FakeCli(tamper_passes=True),
                     _project_root=_project(tmp_path))
    assert code == 1
    assert "RESULTADO: FALHOU" in capsys.readouterr().out


def test_main_aborto_devolve_1(tmp_path, capsys):
    code = demo.main(["--pasta", str(tmp_path / "demo")], _runner=FakeCli(run_stages=["chain"]),
                     _project_root=_project(tmp_path))
    assert code == 1
    assert "ABORTADO" in capsys.readouterr().out


def test_main_sem_pasta_usa_o_diretorio_temporario(monkeypatch, tmp_path):
    temp = tmp_path / "tmp"
    temp.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(temp))
    code = demo.main([], _runner=FakeCli(), _project_root=_project(tmp_path))
    assert code == 0
    assert [p.name for p in temp.iterdir() if p.name.startswith("eal_demo_")] != []


def test_main_erro_inesperado_nao_vaza_a_mensagem(tmp_path, capsys):
    def boom(args, cwd):
        raise RuntimeError("SEGREDO123")

    code = demo.main(["--pasta", str(tmp_path / "demo")], _runner=boom,
                     _project_root=_project(tmp_path))
    captured = capsys.readouterr()
    assert code == 1
    assert "RuntimeError" in captured.err
    assert "SEGREDO123" not in captured.out + captured.err


def test_main_erro_da_demo_durante_a_execucao_devolve_1(tmp_path, capsys):
    def slow(args, cwd):
        raise demo.DemoError("passou do tempo")

    code = demo.main(["--pasta", str(tmp_path / "demo")], _runner=slow,
                     _project_root=_project(tmp_path))
    assert code == 1
    assert "passou do tempo" in capsys.readouterr().err


def test_main_opcao_invalida_sai_com_2():
    with pytest.raises(SystemExit) as info:
        demo.main(["--nao-existe"])
    assert info.value.code == 2


# ----------------------------------------------- ponta a ponta (opcional)

@pytest.mark.skipif(os.environ.get("EAL_E2E") != "1",
                    reason="teste lento com a fonte os real; ligue com EAL_E2E=1")
def test_demo_ponta_a_ponta_com_a_os_real(tmp_path):
    demo_dir = tmp_path / "demo"
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    proc = subprocess.run(
        [sys.executable, "-m", "scripts.demo_dia5", "--pasta", str(demo_dir)],
        cwd=str(ROOT), env=env, capture_output=True, timeout=1800, check=False,
    )
    out = proc.stdout.decode("utf-8", "replace") + proc.stderr.decode("utf-8", "replace")
    assert proc.returncode == 0, out
    assert _passo_lines(out) == [str(n) for n in range(1, 10)]
    assert "RESULTADO: OK (9 de 9 passos)" in out
    sk_hex = (demo_dir / "keys" / "issuer_ml_dsa_65.sk").read_text().strip()
    secret = sk_hex[64:128]  # K do ML-DSA; os 32 primeiros bytes (rho) são públicos
    assert len(secret) == 64
    assert secret not in out
    ids = demo.receipt_ids(demo_dir / "data" / "receipts" / "chain.jsonl")
    assert ids[-1] in out  # controle: um dado público aparece na saída
