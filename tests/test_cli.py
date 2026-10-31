"""Testes da linha de comando (Dia 5, etapa 4): init-issuer, run e verify.

Tudo roda em pasta temporária (nunca em keys/ nem data/ reais). As fontes de dados
são fontes de TESTE injetadas por ``main(..., _sources=[...])``: nenhum teste depende
de sorteio. A ShakeStandin (SHAKE256 determinístico) não é entropia.

Frases fixas (os testes usam ``in`` nelas):
  stdout: "chave do emissor criada", "recibo gravado", "receipt_id:", "cabeça da cadeia:",
          "recibo válido", "posição X de N", "AVISO: cadeia não conferida".
  stderr: "já existe", "init-issuer", "simulada", "fail-closed", "cadeia existente inválida",
          "recibo gravado" (quando só as chaves públicas falham), "erro inesperado (Classe)",
          "recibo reprovado", "cadeia reprovada", "não está na cadeia", "chain.jsonl" (pasta sem log),
          "não encontrado", "ilegível", "recibo recusado", "aviso: não foi possível gravar o log".
  log (data/logs/eal_runs.jsonl): command, stage ("issuer_key", "chain", "pipeline",
          "unexpected"), ok=false, reason, pipeline (PipelineResult.to_dict() ou null).
"""
from __future__ import annotations

import contextlib
import hashlib
import io
import itertools
import json
import os
import re
import shutil
import subprocess
import sys
import types
from pathlib import Path

import numpy as np
import pytest

from eal import cli
from eal.cli import main
from eal.config import DEFAULT_N_BITS, GENESIS_PREV_HASH, ISSUER_PK_NAME, ISSUER_SK_NAME, RECEIPT_CHAIN_NAME, RECEIPT_REQUIRED_LIMITATIONS
from eal.receipt.builder import issuer_seed_from_mix, receipt_id_for
from eal.receipt.chain import ChainError, verify_chain
from eal.receipt.schema import canonical_bytes, receipt_hash
from eal.receipt.sign import issuer_key_from_seed, load_issuer_key, load_issuer_public_key, save_issuer_key, sign_receipt
from eal.sources.base import RawBatch, Source

ROOT = Path(__file__).resolve().parents[1]
_LOGS_PADRAO = cli.LOGS_DIR  # valor original, antes da barreira autouse trocar o nome em uso
MARK = "SEGREDO-123"
OTHER_XI = bytes(range(200, 232))
H = "ab" * 32
STANDIN_LABEL = b"EAL-v1|test-standin|1"
_READS = itertools.count(1)  # F12: cada leitura do ShakeStandin gira os bits por mais 1 posição


# ---------------------------------------------------------------- fontes de teste

class ShakeStandin(Source):
    """Fonte de TESTE: bits determinísticos do SHAKE256. Nunca usar fora dos testes."""

    source_id = "shake_standin"
    source_type = "os"
    is_local = True
    is_simulated = False

    def read(self, n_bits: int) -> RawBatch:
        n_bits = self.validate_n_bits(n_bits)
        raw = hashlib.shake_256(STANDIN_LABEL).digest((n_bits + 7) // 8)
        bits = np.unpackbits(np.frombuffer(raw, dtype=np.uint8))[:n_bits].copy()
        # F12: com o histórico de replay guardado entre execuções, cada leitura precisa de bits novos.
        # Girar a sequência conhecida por mais 1 posição a cada leitura dá bits novos (os blocos de
        # 4096 bits mudam; replay deslocado não é detectado, ver replay.py) com as mesmas propriedades.
        bits = np.roll(bits, next(_READS)).copy()
        return self._build_batch(bits, {"label": STANDIN_LABEL.decode()})


class RemoteDown(Source):
    """Fonte remota que falha na leitura; a mensagem da exceção não pode vazar."""

    source_id = "remote_down"
    source_type = "qpu_ibm"
    is_local = False
    is_simulated = False

    def read(self, n_bits: int) -> RawBatch:
        raise TimeoutError(f"provedor fora do ar: {MARK}")


class StuckZeros(Source):
    """Fonte local defeituosa: só zeros (o teste de saúde tem de reprová-la)."""

    source_id = "stuck_zeros"
    source_type = "os"
    is_local = True
    is_simulated = False

    def read(self, n_bits: int) -> RawBatch:
        n_bits = self.validate_n_bits(n_bits)
        return self._build_batch(np.zeros(n_bits, dtype=np.uint8), {})


# ---------------------------------------------------------------- helpers

class World:
    """Pastas de uma 'instalação' de teste."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.keys = self.root / "keys"
        self.receipts = self.root / "receipts"
        self.pubs = self.root / "public_keys"
        self.logs = self.root / "logs"


def _call(argv, **kw):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(argv, **kw)
    return code, out.getvalue(), err.getvalue()


def _run_args(w: World, *extra: str) -> list[str]:
    return ["run", "--keys-dir", str(w.keys), "--receipts-dir", str(w.receipts),
            "--public-keys-dir", str(w.pubs), "--logs-dir", str(w.logs), *extra]


def _verify_args(path, keys: Path, *extra: str) -> list[str]:
    return ["verify", str(path), "--keys-dir", str(keys), *extra]


def _tree(root: Path) -> dict:
    if not root.exists():
        return {}
    return {str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def _chain_receipts(w: World) -> list[dict]:
    text = (w.receipts / RECEIPT_CHAIN_NAME).read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines()]


def _read_log(logs: Path) -> list[dict]:
    path = logs / cli.RUN_LOG_NAME
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _clone(world: World, tmp_path: Path) -> World:
    shutil.copytree(world.root, tmp_path / "w")
    return World(tmp_path / "w")


@pytest.fixture(autouse=True)
def _nunca_gravar_no_log_real(tmp_path, monkeypatch):
    """Barreira: nenhum teste grava em data/logs do diretório atual (o padrão é relativo ao cwd).

    Sem isto, uma mutação que faz o 'verify' registrar falhas (ou qualquer caminho que caia no
    padrão) escreve no data/logs real do projeto, como aconteceu na rodada de mutações.
    """
    monkeypatch.setattr(cli, "LOGS_DIR", tmp_path / "_logs_padrao")


@pytest.fixture(scope="module")
def world(tmp_path_factory) -> World:
    """init-issuer + dois 'run' pelo CLI, uma vez só; os testes copiam esta pasta para mexer."""
    w = World(tmp_path_factory.mktemp("world"))
    code, out, err = _call(["init-issuer", "--keys-dir", str(w.keys), "--logs-dir", str(w.logs)],
                           _sources=[ShakeStandin()])
    assert code == 0, err
    w.init_out, w.init_err = out, err
    outs = []
    for _ in range(2):
        code, out, err = _call(_run_args(w), _sources=[ShakeStandin()])
        assert code == 0, err
        outs.append((out, err))
    w.run_outs = outs
    w.issuer_pk = load_issuer_public_key(w.keys / ISSUER_PK_NAME)
    return w


def _signed_outside_chain(w: World, tmp_path: Path) -> Path:
    """Recibo válido e bem assinado pelo emissor do mundo, mas que NÃO está no log."""
    key = load_issuer_key(w.keys / ISSUER_SK_NAME, w.keys / ISSUER_PK_NAME)
    seed_hash = hashlib.sha3_256(b"recibo-solto").hexdigest()
    body = {
        "eal_version": "0.1.0", "receipt_id": receipt_id_for(seed_hash),
        "created_at": "2026-10-30T18:00:00+00:00", "mode": "keygen", "prev_receipt_hash": GENESIS_PREV_HASH,
        "software": {"python": "3.12.10", "kyber-py": "1.2.0", "dilithium-py": "1.5.1"},
        "sources": [
            {"source_id": "ibm_kingston", "status": "mixed", "is_local": False, "is_simulated": False, "approved": True},
            {"source_id": "os", "status": "mixed", "is_local": True, "is_simulated": False, "approved": True},
        ],
        "extractor": {"type": "toeplitz", "n": 2048, "epsilon_log2": -64, "seed_hash": H},
        "mixer": {"type": "sha3-512", "inputs": ["ibm_kingston", "os"]},
        "seed_hash": seed_hash, "keys": {"ml_kem_768_pk_hash": H, "ml_dsa_65_pk_hash": H},
        "limitations": list(RECEIPT_REQUIRED_LIMITATIONS),
    }
    receipt = sign_receipt(body, key)
    folder = tmp_path / "solto"
    folder.mkdir()
    path = folder / "recibo.json"
    path.write_bytes(canonical_bytes(receipt) + b"\n")
    return path


# ---------------------------------------------------------------- uso

def test_help_sai_com_zero_e_lista_os_comandos():
    # Prova: --help funciona e mostra os três comandos.
    code, out, _ = _call(["--help"])
    assert code == 0 and all(c in out for c in ("init-issuer", "run", "verify"))


def test_sem_comando_sai_com_2():
    # Prova: sem comando é erro de uso (código 2), sem traceback.
    code, _, err = _call([])
    assert code == 2 and "Traceback" not in err


def test_comando_desconhecido_sai_com_2():
    # Prova: comando que não existe é erro de uso.
    assert _call(["collect-ibm"])[0] == 2


@pytest.mark.parametrize("source, word", [("qpu_sim", "simulada"), ("ibm_kingston", "ainda não existe")],
                         ids=["simulada", "ibm"])
def test_run_so_aceita_a_fonte_os(tmp_path, source, word):
    # Prova: fonte simulada (T13) ou ainda inexistente sai com 2, explica o motivo e não cria nada.
    w = World(tmp_path / "w")
    code, out, err = _call(_run_args(w, "--sources", source))
    assert code == 2 and word in err
    assert not w.root.exists()


@pytest.mark.parametrize("bits", ["0", "-5", "abc", "1.5"], ids=["zero", "negativo", "texto", "decimal"])
def test_run_com_bits_invalido_sai_com_2(tmp_path, bits):
    # Prova: --bits precisa ser inteiro positivo.
    w = World(tmp_path / "w")
    assert _call(_run_args(w, "--bits", bits))[0] == 2
    assert not w.root.exists()


def test_python_m_eal_funciona():
    # Prova: o __main__ existe e `py -3.12 -m eal --help` roda como processo de verdade.
    proc = subprocess.run([sys.executable, "-m", "eal", "--help"], cwd=ROOT, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=120,
                          env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    assert proc.returncode == 0, proc.stderr
    assert "init-issuer" in proc.stdout


# ---------------------------------------------------------------- init-issuer

def test_init_issuer_cria_o_par_e_mostra_so_o_hash_da_publica(world):
    # Prova: .sk e .pk criados e coerentes; a saída traz o hash da pública e nada da privada.
    key = load_issuer_key(world.keys / ISSUER_SK_NAME, world.keys / ISSUER_PK_NAME)
    assert "chave do emissor criada" in world.init_out and key.pk_hash in world.init_out
    assert key.sk[32:64].hex() not in world.init_out + world.init_err
    assert world.init_err == ""


def test_init_issuer_recusa_sobrescrever(tmp_path, world):
    # Prova: com a chave já criada, o comando recusa e não mexe em nenhum byte.
    w = _clone(world, tmp_path)
    before = _tree(w.keys)
    code, _, err = _call(["init-issuer", "--keys-dir", str(w.keys), "--logs-dir", str(w.logs)],
                         _sources=[ShakeStandin()])
    assert code == 1 and "já existe" in err
    assert _tree(w.keys) == before


def test_init_issuer_fail_closed_nao_cria_chave_e_registra(tmp_path):
    # Prova: sem fonte local aprovada não nasce chave do emissor, e a falha fica registrada.
    w = World(tmp_path / "w")
    code, _, err = _call(["init-issuer", "--keys-dir", str(w.keys), "--logs-dir", str(w.logs)],
                         _sources=[RemoteDown()])
    assert code == 1 and "fail-closed" in err
    assert not w.keys.exists()
    log = _read_log(w.logs)
    assert len(log) == 1 and log[0]["ok"] is False and log[0]["command"] == "init-issuer"


# ---------------------------------------------------------------- run

def test_run_sem_chave_do_emissor_sai_com_1_sem_gravar(tmp_path):
    # Prova: sem keys/ o run manda rodar init-issuer e não grava recibo nem chaves.
    w = World(tmp_path / "w")
    code, _, err = _call(_run_args(w), _sources=[ShakeStandin()])
    assert code == 1 and "init-issuer" in err
    assert not w.receipts.exists() and not w.pubs.exists()
    log = _read_log(w.logs)
    assert len(log) == 1 and log[0]["stage"] == "issuer_key" and log[0]["ok"] is False


def test_primeiro_recibo_usa_genesis_e_o_segundo_encadeia(world):
    # Prova: o CLI encadeia de verdade; a cadeia gravada verifica com a chave do emissor.
    r0, r1 = _chain_receipts(world)
    assert r0["prev_receipt_hash"] == GENESIS_PREV_HASH
    assert r1["prev_receipt_hash"] == receipt_hash(r0)
    res = verify_chain(world.receipts, world.issuer_pk)
    assert res.ok and res.length == 2 and res.head == receipt_hash(r1)


def test_run_imprime_id_caminho_e_cabeca_da_cadeia(world):
    # Prova: a saída do run diz o que foi gravado e dá a cabeça para guardar fora do log.
    r1 = _chain_receipts(world)[1]
    out, err = world.run_outs[1]
    assert "recibo gravado" in out and r1["receipt_id"] in out and f"{r1['receipt_id']}.json" in out
    assert f"cabeça da cadeia: {receipt_hash(r1)}" in out
    assert err == ""


def test_chaves_publicas_gravadas_e_conferem_com_os_hashes_do_recibo(world):
    # Prova: só as públicas vão para disco, em hex, com o hash SHA3-256 que o recibo registra.
    r1 = _chain_receipts(world)[1]
    folder = world.pubs / r1["receipt_id"]
    assert sorted(p.name for p in folder.iterdir()) == sorted([cli.PUBLIC_DSA_NAME, cli.PUBLIC_KEM_NAME])
    sizes = {cli.PUBLIC_KEM_NAME: 1184, cli.PUBLIC_DSA_NAME: 1952}
    fields = {cli.PUBLIC_KEM_NAME: "ml_kem_768_pk_hash", cli.PUBLIC_DSA_NAME: "ml_dsa_65_pk_hash"}
    for name in sizes:
        raw = bytes.fromhex((folder / name).read_text(encoding="ascii").strip())
        assert len(raw) == sizes[name]
        assert hashlib.sha3_256(raw).hexdigest() == r1["keys"][fields[name]]


def test_nada_secreto_em_arquivos_saidas_nem_log(tmp_path, world, monkeypatch):
    # Prova (T10): semente e chaves privadas (derivadas e do emissor) não aparecem em arquivo, saída nem log.
    # Controle: o seed_hash (dado público) tem de aparecer, para o teste não passar vazio.
    w = _clone(world, tmp_path)
    caught: dict = {}
    real_pipe, real_derive = cli.run_pipeline, cli.derive_keys_from_mix

    def pipe(*a, **k):
        result = real_pipe(*a, **k)
        caught["mix"] = result.mix
        return result

    def derive(mix):
        keys = real_derive(mix)
        caught["keys"] = keys
        return keys

    monkeypatch.setattr(cli, "run_pipeline", pipe)
    monkeypatch.setattr(cli, "derive_keys_from_mix", derive)
    code, out, err = _call(_run_args(w), _sources=[ShakeStandin()])
    assert code == 0, err
    issuer = load_issuer_key(w.keys / ISSUER_SK_NAME, w.keys / ISSUER_PK_NAME)
    secrets = {"semente": caught["mix"].seed, "ML-KEM dk (início)": caught["keys"].kem_dk[:32],
               "ML-KEM dk (fim)": caught["keys"].kem_dk[-32:], "ML-DSA K": caught["keys"].dsa_sk[32:64],
               "emissor K": issuer.sk[32:64]}
    files = [p for p in sorted(w.root.rglob("*")) if p.is_file() and p.name != ISSUER_SK_NAME]
    blob = b"".join(p.read_bytes() for p in files) + (out + err).encode("utf-8")
    assert caught["mix"].seed_hash.encode() in blob, "controle: o seed_hash público deveria aparecer"
    for name, value in secrets.items():
        assert value.hex().encode() not in blob, name


def test_fonte_reprovada_da_fail_closed_sem_gravar_nada(tmp_path, world):
    # Prova: fonte local defeituosa -> código 1, nenhum recibo nem chave pública nova, falha registrada.
    w = _clone(world, tmp_path)
    before = (_tree(w.receipts), _tree(w.pubs))
    code, _, err = _call(_run_args(w), _sources=[StuckZeros()])
    assert code == 1 and "fail-closed" in err and "stuck_zeros" in err
    assert (_tree(w.receipts), _tree(w.pubs)) == before
    last = _read_log(w.logs)[-1]
    assert last["ok"] is False and last["stage"] == "pipeline" and last["command"] == "run"
    assert last["pipeline"] is not None


def test_run_nao_repete_sozinho_quando_a_fonte_falha(tmp_path, world, monkeypatch):
    # Prova: o pipeline roda uma única vez; repetir até passar esvaziaria o sentido dos testes de saúde.
    w = _clone(world, tmp_path)
    calls: list[int] = []
    real = cli.run_pipeline

    def spy(*a, **k):
        calls.append(1)
        return real(*a, **k)

    monkeypatch.setattr(cli, "run_pipeline", spy)
    assert _call(_run_args(w), _sources=[StuckZeros()])[0] == 1
    assert len(calls) == 1


def test_mensagem_da_excecao_da_fonte_nao_vai_ao_log_nem_a_saida(tmp_path, world):
    # Prova: o texto da exceção de uma fonte (pode ter dados do provedor) não chega ao log nem ao console.
    w = _clone(world, tmp_path)
    code, out, err = _call(_run_args(w), _sources=[RemoteDown()])
    log_text = (w.logs / cli.RUN_LOG_NAME).read_text(encoding="utf-8")
    assert code == 1 and "remote_down" in log_text
    assert MARK not in out + err + log_text


def test_cadeia_corrompida_recusa_antes_de_rodar_o_pipeline(tmp_path, world, monkeypatch):
    # Prova: log corrompido -> código 1, nada gravado, e o pipeline nem chega a rodar (não gasta entropia à toa).
    w = _clone(world, tmp_path)
    log = w.receipts / RECEIPT_CHAIN_NAME
    log.write_bytes(log.read_bytes().replace(b'"mode":"keygen"', b'"mode":"keygex"', 1))
    before = _tree(w.receipts)
    monkeypatch.setattr(cli, "run_pipeline", lambda *a, **k: pytest.fail("pipeline não deveria rodar"))
    code, _, err = _call(_run_args(w), _sources=[ShakeStandin()])
    assert code == 1 and "cadeia existente inválida" in err
    assert _tree(w.receipts) == before
    assert _read_log(w.logs)[-1]["stage"] == "chain"


def test_chave_do_emissor_diferente_da_da_cadeia_recusa(tmp_path, world):
    # Prova: uma chave por cadeia; com outra chave do emissor o run recusa e não grava.
    w = _clone(world, tmp_path)
    other = tmp_path / "outras_chaves"
    other.mkdir()
    save_issuer_key(issuer_key_from_seed(OTHER_XI), other)
    args = _run_args(w)
    args[args.index("--keys-dir") + 1] = str(other)
    before = _tree(w.receipts)
    code, _, err = _call(args, _sources=[ShakeStandin()])
    assert code == 1 and "cadeia" in err
    assert _tree(w.receipts) == before


def test_bits_vai_para_o_pipeline(tmp_path, world, monkeypatch):
    # Prova: --bits chega ao run_pipeline como inteiro (e modo keygen).
    w = _clone(world, tmp_path)
    seen: dict = {}
    real = cli.run_pipeline

    def spy(*a, **k):
        seen.update(k)
        return real(*a, **k)

    monkeypatch.setattr(cli, "run_pipeline", spy)
    _call(_run_args(w, "--bits", "4096"), _sources=[ShakeStandin()])
    assert seen["n_bits"] == 4096 and seen["mode"] == "keygen"


def test_erro_inesperado_vira_codigo_1_sem_traceback_e_sem_a_mensagem(tmp_path, world, monkeypatch):
    # Prova: exceção inesperada -> código 1, só o nome da classe aparece (a mensagem pode ter segredo), e vai ao log.
    w = _clone(world, tmp_path)

    def boom(*a, **k):
        raise RuntimeError(MARK)

    monkeypatch.setattr(cli, "run_pipeline", boom)
    code, out, err = _call(_run_args(w), _sources=[ShakeStandin()])
    log_text = (w.logs / cli.RUN_LOG_NAME).read_text(encoding="utf-8")
    assert code == 1 and "erro inesperado (RuntimeError)" in err and "Traceback" not in err
    assert MARK not in out + err + log_text
    assert _read_log(w.logs)[-1]["stage"] == "unexpected"


def test_falha_nas_chaves_publicas_depois_do_recibo_avisa_que_o_recibo_ficou(tmp_path, world, monkeypatch):
    # Prova: se só as chaves públicas falharem, o recibo já está no log (linha vence arquivo) e o aviso diz isso.
    w = _clone(world, tmp_path)

    def boom(*a, **k):
        raise OSError("disco cheio")

    monkeypatch.setattr(cli, "_write_public_keys", boom)
    code, _, err = _call(_run_args(w), _sources=[ShakeStandin()])
    assert code == 1 and "recibo gravado" in err
    assert verify_chain(w.receipts, world.issuer_pk).length == 3


# ---------------------------------------------------------------- verify

def test_verify_recibo_valido_sai_com_zero(world):
    # Prova: o último recibo da cadeia verifica e a saída diz a posição dele.
    r1 = _chain_receipts(world)[1]
    path = world.receipts / f"{r1['receipt_id']}.json"
    code, out, err = _call(_verify_args(path, world.keys))
    assert code == 0 and "recibo válido" in out and "posição 2 de 2" in out and err == ""


def test_verify_recibo_do_meio_da_cadeia(world):
    # Prova: recibo que não é o último também verifica, e a posição é a dele.
    r0 = _chain_receipts(world)[0]
    path = world.receipts / f"{r0['receipt_id']}.json"
    code, out, _ = _call(_verify_args(path, world.keys))
    assert code == 0 and "posição 1 de 2" in out


def test_verify_nao_depende_do_nome_do_arquivo(tmp_path, world):
    # Prova: uma cópia com outro nome, com --chain-dir, é reconhecida pelo conteúdo e não pelo nome.
    r1 = _chain_receipts(world)[1]
    copy = tmp_path / "copia_qualquer.json"
    shutil.copyfile(world.receipts / f"{r1['receipt_id']}.json", copy)
    code, out, _ = _call(_verify_args(copy, world.keys, "--chain-dir", str(world.receipts)))
    assert code == 0 and "posição 2 de 2" in out


def test_verify_byte_alterado_sai_com_1(tmp_path, world):
    # Prova: um byte mudado no arquivo do recibo reprova.
    w = _clone(world, tmp_path)
    r1 = _chain_receipts(w)[1]
    path = w.receipts / f"{r1['receipt_id']}.json"
    path.write_bytes(path.read_bytes().replace(b'"mode":"keygen"', b'"mode":"keygex"', 1))
    code, _, err = _call(_verify_args(path, w.keys))
    assert code == 1 and "recibo reprovado" in err


def test_verify_com_outra_chave_do_emissor_sai_com_1(tmp_path, world):
    # Prova: a assinatura só vale para a chave pública do emissor certa.
    other = tmp_path / "outras_chaves"
    other.mkdir()
    save_issuer_key(issuer_key_from_seed(OTHER_XI), other)
    r1 = _chain_receipts(world)[1]
    code, _, err = _call(_verify_args(world.receipts / f"{r1['receipt_id']}.json", other))
    assert code == 1 and "recibo reprovado" in err


def test_verify_arquivo_inexistente_sai_com_1(tmp_path, world):
    # Prova: arquivo que não existe vira mensagem, não traceback.
    code, _, err = _call(_verify_args(tmp_path / "nao_existe.json", world.keys))
    assert code == 1 and "não encontrado" in err and "Traceback" not in err


def test_verify_arquivo_que_nao_e_json_sai_com_1(tmp_path, world):
    # Prova: lixo no lugar do recibo reprova sem exceção.
    path = tmp_path / "lixo.json"
    path.write_bytes(b"isto nao e json")
    code, _, err = _call(_verify_args(path, world.keys))
    assert code == 1 and "recibo reprovado" in err and "Traceback" not in err


def test_verify_sem_chave_publica_do_emissor_sai_com_1(tmp_path, world):
    # Prova: sem keys/<pk> o verify diz o que falta em vez de quebrar.
    r1 = _chain_receipts(world)[1]
    empty = tmp_path / "vazia"
    empty.mkdir()
    code, _, err = _call(_verify_args(world.receipts / f"{r1['receipt_id']}.json", empty))
    assert code == 1 and "chave pública do emissor" in err and "Traceback" not in err


def test_verify_em_pasta_sem_log_diz_o_que_fazer(tmp_path, world):
    # Prova: recibo copiado para uma pasta sem chain.jsonl não vira "cadeia reprovada" confusa:
    # a mensagem aponta --chain-dir e --sem-cadeia.
    path = _signed_outside_chain(world, tmp_path)
    code, _, err = _call(_verify_args(path, world.keys))
    assert code == 1 and "chain.jsonl" in err and "--chain-dir" in err and "--sem-cadeia" in err


def test_verify_recibo_valido_que_nao_esta_no_log_sai_com_1(tmp_path, world):
    # Prova: assinatura válida não basta; com o log certo à vista, o recibo precisa estar nele.
    path = _signed_outside_chain(world, tmp_path)
    code, _, err = _call(_verify_args(path, world.keys, "--chain-dir", str(world.receipts)))
    assert code == 1 and "não está na cadeia" in err


def test_verify_sem_cadeia_aceita_o_recibo_solto_mas_avisa(tmp_path, world):
    # Prova: --sem-cadeia verifica só a assinatura e diz, em alto e bom som, que a cadeia não foi conferida.
    path = _signed_outside_chain(world, tmp_path)
    code, out, _ = _call(_verify_args(path, world.keys, "--sem-cadeia"))
    assert code == 0 and "recibo válido" in out and "AVISO: cadeia não conferida" in out


def test_verify_sem_cadeia_continua_reprovando_recibo_adulterado(tmp_path, world):
    # Prova: --sem-cadeia não afrouxa a verificação da assinatura.
    path = _signed_outside_chain(world, tmp_path)
    path.write_bytes(path.read_bytes().replace(b'"mode":"keygen"', b'"mode":"keygex"', 1))
    assert _call(_verify_args(path, world.keys, "--sem-cadeia"))[0] == 1


def test_verify_cadeia_corrompida_em_outra_linha_sai_com_1(tmp_path, world):
    # Prova: o recibo verificado está intacto, mas a cadeia ao redor está corrompida: reprova.
    w = _clone(world, tmp_path)
    r1 = _chain_receipts(w)[1]
    log = w.receipts / RECEIPT_CHAIN_NAME
    log.write_bytes(log.read_bytes().replace(b'"mode":"keygen"', b'"mode":"keygex"', 1))  # só a 1ª linha
    code, _, err = _call(_verify_args(w.receipts / f"{r1['receipt_id']}.json", w.keys))
    assert code == 1 and "cadeia reprovada" in err


def test_verify_ignora_gitkeep_na_pasta(tmp_path, world):
    # Prova: o .gitkeep de data/receipts não atrapalha a verificação.
    w = _clone(world, tmp_path)
    (w.receipts / ".gitkeep").write_bytes(b"")
    r1 = _chain_receipts(w)[1]
    assert _call(_verify_args(w.receipts / f"{r1['receipt_id']}.json", w.keys))[0] == 0


def test_verify_expected_head_certa_e_errada(world):
    # Prova: --expected-head certa passa; errada (ou mal formada) reprova, o que denuncia o último recibo apagado.
    r0, r1 = _chain_receipts(world)
    path = world.receipts / f"{r1['receipt_id']}.json"
    ok, out, _ = _call(_verify_args(path, world.keys, "--expected-head", receipt_hash(r1)))
    assert ok == 0 and "cabeça conferida" in out
    for bad in (receipt_hash(r0), "zz"):
        code, _, err = _call(_verify_args(path, world.keys, "--expected-head", bad))
        assert code == 1 and "cadeia reprovada" in err


@pytest.mark.parametrize("tamper", [False, True], ids=["recibo valido", "recibo adulterado"])
def test_verify_nao_ecoa_assinatura_nem_semente(tmp_path, world, tamper):
    # Prova: nem no sucesso nem na falha o verify imprime a assinatura ou o seed_hash do recibo.
    w = _clone(world, tmp_path)
    r1 = _chain_receipts(w)[1]
    path = w.receipts / f"{r1['receipt_id']}.json"
    if tamper:
        path.write_bytes(path.read_bytes().replace(b'"mode":"keygen"', b'"mode":"keygex"', 1))
    _, out, err = _call(_verify_args(path, w.keys))
    assert r1["signature"]["value"] not in out + err
    assert r1["seed_hash"] not in out + err


# ---------------------------------------------------------------- acrescentados após as mutações

class _BadResult:
    """Resultado de pipeline sem semente cujo to_dict() não serializa em JSON."""

    mode, outcomes, mix, error, inputs = "keygen", (), None, "política", ()

    def to_dict(self):
        return {"ruim": {1, 2}}


def test_saida_nao_quebra_em_console_sem_acentos(tmp_path):
    # Prova: console que não escreve acentos (ibm850/ASCII) recebe '?' em vez de UnicodeEncodeError.
    out = io.TextIOWrapper(io.BytesIO(), encoding="ascii", errors="strict", write_through=True)
    err = io.TextIOWrapper(io.BytesIO(), encoding="ascii", errors="strict", write_through=True)
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(_verify_args(tmp_path / "x.json", tmp_path / "sem_chaves"))
    assert code == 1
    assert b"?" in err.buffer.getvalue()


def test_duas_falhas_acumulam_no_log(tmp_path):
    # Prova: o log de falhas é acrescentado (T14), não sobrescrito.
    w = World(tmp_path / "w")
    for _ in range(2):
        assert _call(["init-issuer", "--keys-dir", str(w.keys), "--logs-dir", str(w.logs)], _sources=[RemoteDown()])[0] == 1
    assert len(_read_log(w.logs)) == 2


def test_log_com_pipeline_nao_serializavel_ainda_registra(tmp_path, monkeypatch):
    # Prova: se o to_dict() do pipeline não serializar, a falha é registrada mesmo assim (com pipeline nulo).
    w = World(tmp_path / "w")
    monkeypatch.setattr(cli, "run_pipeline", lambda *a, **k: _BadResult())
    code, _, _ = _call(["init-issuer", "--keys-dir", str(w.keys), "--logs-dir", str(w.logs)], _sources=[ShakeStandin()])
    log = _read_log(w.logs)
    assert code == 1 and len(log) == 1 and log[0]["pipeline"] is None and log[0]["stage"] == "pipeline"


def test_pasta_de_logs_invalida_so_avisa(tmp_path):
    # Prova: se o log de falhas não puder ser gravado, o comando ainda sai com 1 e avisa, sem exceção.
    blocker = tmp_path / "logs_e_um_arquivo"
    blocker.write_bytes(b"x")
    code, _, err = _call(["init-issuer", "--keys-dir", str(tmp_path / "k"), "--logs-dir", str(blocker)],
                         _sources=[RemoteDown()])
    assert code == 1 and "aviso: não foi possível gravar o log" in err and "Traceback" not in err


def test_lista_de_fontes_vazia_da_fail_closed(tmp_path, world):
    # Prova: lista vazia NÃO vira 'use a os por padrão'; sem fonte local aprovada não há semente.
    w = _clone(world, tmp_path)
    code, _, err = _call(_run_args(w), _sources=[])
    assert code == 1 and "fail-closed" in err


@pytest.mark.parametrize("missing", [ISSUER_SK_NAME, ISSUER_PK_NAME], ids=["sem .sk", "sem .pk"])
def test_init_issuer_recusa_com_so_uma_das_chaves(tmp_path, world, missing):
    # Prova: com só um dos arquivos da chave, o init-issuer recusa, diz qual falta (F7) e não recria por cima.
    w = _clone(world, tmp_path)
    (w.keys / missing).unlink()
    before = _tree(w.keys)
    code, _, err = _call(["init-issuer", "--keys-dir", str(w.keys), "--logs-dir", str(w.logs)], _sources=[ShakeStandin()])
    assert code == 1 and "incompleta" in err and f"falta {missing}" in err and _tree(w.keys) == before


def test_init_issuer_cria_a_pasta_das_chaves_sem_depender_do_save_issuer_key(tmp_path, monkeypatch):
    # Prova: a pasta das chaves é criada pelo próprio init-issuer. O save_issuer_key de hoje também cria,
    # então aqui ele é trocado por uma versão que EXIGE a pasta já existente; a defesa fica verificada
    # e não vira código morto se o save_issuer_key mudar.
    real = cli.save_issuer_key

    def needs_folder(key, directory):
        if not Path(directory).is_dir():
            raise FileNotFoundError("a pasta das chaves deveria existir")
        return real(key, directory)

    monkeypatch.setattr(cli, "save_issuer_key", needs_folder)
    w = World(tmp_path / "w")
    code, _, err = _call(["init-issuer", "--keys-dir", str(w.keys), "--logs-dir", str(w.logs)], _sources=[ShakeStandin()])
    assert code == 0, err
    assert (w.keys / ISSUER_SK_NAME).is_file() and (w.keys / ISSUER_PK_NAME).is_file()


def test_init_issuer_deriva_a_chave_do_mix_keygen(tmp_path, monkeypatch):
    # Prova: o par do emissor vem do mix keygen daquela execução, com o domínio do emissor (issuer_seed_from_mix).
    w = World(tmp_path / "w")
    caught: dict = {}
    real = cli.run_pipeline

    def spy(*a, **k):
        result = real(*a, **k)
        caught["mix"] = result.mix
        return result

    monkeypatch.setattr(cli, "run_pipeline", spy)
    assert _call(["init-issuer", "--keys-dir", str(w.keys), "--logs-dir", str(w.logs)], _sources=[ShakeStandin()])[0] == 0
    saved = load_issuer_key(w.keys / ISSUER_SK_NAME, w.keys / ISSUER_PK_NAME)
    assert saved.pk == issuer_key_from_seed(issuer_seed_from_mix(caught["mix"])).pk


def test_run_com_so_uma_das_chaves_do_emissor_manda_rodar_init_issuer(tmp_path, world):
    # Prova: .pk sem .sk (ou o contrário) conta como 'chave não encontrada', não como chave ilegível.
    w = _clone(world, tmp_path)
    (w.keys / ISSUER_PK_NAME).unlink()
    code, _, err = _call(_run_args(w), _sources=[ShakeStandin()])
    assert code == 1 and "init-issuer" in err


def test_run_com_chave_do_emissor_corrompida_ou_trocada(tmp_path, world):
    # Prova: .pk ilegível ou par que não combina -> mensagem clara, código 1, sem traceback e sem gravar.
    for bad in ("zz", issuer_key_from_seed(OTHER_XI).pk.hex()):
        w = _clone(world, tmp_path / bad[:2])
        (w.keys / ISSUER_PK_NAME).write_text(bad, encoding="ascii")
        before = _tree(w.receipts)
        code, _, err = _call(_run_args(w), _sources=[ShakeStandin()])
        assert code == 1 and "ilegível ou inconsistente" in err and "Traceback" not in err
        assert _tree(w.receipts) == before


def test_chaves_publicas_formato_e_nunca_sobrescreve(tmp_path):
    # Prova: <pasta>/<id>/ tem só as duas públicas, em hex com \n final, e uma segunda gravação do mesmo id falha.
    keys = types.SimpleNamespace(kem_ek=b"\x01\x02", dsa_pk=b"\x03\x04")
    rid = "3f2b1c9e-1111-4222-8333-444455556666"
    folder = cli._write_public_keys(tmp_path, rid, keys)
    assert folder == tmp_path / rid
    assert (folder / cli.PUBLIC_KEM_NAME).read_bytes() == b"0102\n"
    assert (folder / cli.PUBLIC_DSA_NAME).read_bytes() == b"0304\n"
    before = _tree(tmp_path)
    with pytest.raises(FileExistsError):
        cli._write_public_keys(tmp_path, rid, types.SimpleNamespace(kem_ek=b"\x09", dsa_pk=b"\x09"))
    assert _tree(tmp_path) == before


def test_chaves_publicas_sao_gravadas_em_modo_binario(tmp_path, monkeypatch):
    # Prova: independente do sistema, as chaves públicas vão em modo binário (no Windows, o modo texto
    # trocaria \n por \r\n e os bytes do arquivo mudariam de um sistema para outro).
    import builtins

    modes: list[str] = []

    def spy(file, mode="r", *a, **k):
        modes.append(mode)
        return builtins.open(file, mode, *a, **k)

    monkeypatch.setattr(cli, "open", spy, raising=False)
    cli._write_public_keys(tmp_path, "3f2b1c9e-1111-4222-8333-444455556666",
                           types.SimpleNamespace(kem_ek=b"\x01", dsa_pk=b"\x02"))
    assert len(modes) == 2 and all("b" in m for m in modes)


def test_recusa_do_append_vira_falha_registrada(tmp_path, world, monkeypatch):
    # Prova: se append_receipt recusar (ChainError), o run sai com 1, diz 'recibo recusado' e não grava chaves públicas.
    w = _clone(world, tmp_path)

    def refuse(*a, **k):
        raise ChainError("recusa de teste")

    monkeypatch.setattr(cli, "append_receipt", refuse)
    before = _tree(w.pubs)
    code, _, err = _call(_run_args(w), _sources=[ShakeStandin()])
    assert code == 1 and "recibo recusado" in err
    assert _tree(w.pubs) == before and _read_log(w.logs)[-1]["stage"] == "chain"


def test_run_imprime_semente_chaves_publicas_e_fontes(world):
    # Prova: a saída do run traz o hash da semente, os hashes das duas chaves públicas e o estado de cada fonte.
    r1 = _chain_receipts(world)[1]
    out, _ = world.run_outs[1]
    assert f"semente (hash): {r1['seed_hash']}" in out
    assert f"ML-KEM-768 {r1['keys']['ml_kem_768_pk_hash']}" in out
    assert f"ML-DSA-65 {r1['keys']['ml_dsa_65_pk_hash']}" in out
    assert "shake_standin=mixed" in out


@pytest.mark.parametrize("kind", ["pasta", "utf8 invalido"])
def test_verify_arquivo_ilegivel_sai_com_1(tmp_path, world, kind):
    # Prova: pasta no lugar do arquivo, ou bytes que não são UTF-8, viram 'ilegível' (código 1, sem traceback).
    path = tmp_path / "alvo.json"
    if kind == "pasta":
        path.mkdir()
    else:
        path.write_bytes(b"\xff\xfe\xfd")
    code, _, err = _call(_verify_args(path, world.keys))
    assert code == 1 and "ilegível" in err and "Traceback" not in err


def test_verify_que_falha_nao_cria_log_em_lugar_nenhum(tmp_path, world, monkeypatch):
    # Prova: só init-issuer e run registram falhas; verify reprovado não cria data/logs no diretório atual.
    monkeypatch.chdir(tmp_path)
    assert _call(_verify_args(tmp_path / "nao_existe.json", world.keys))[0] == 1
    assert not (tmp_path / "data").exists()
    assert not cli.LOGS_DIR.exists()  # a pasta de log em uso (a da barreira autouse)


def test_bits_padrao_vem_do_config(tmp_path, world, monkeypatch):
    # Prova: sem --bits, init-issuer e run usam DEFAULT_N_BITS.
    seen: list[int] = []

    def spy(*a, **k):
        seen.append(k["n_bits"])
        raise RuntimeError("parar aqui")

    monkeypatch.setattr(cli, "run_pipeline", spy)
    w = _clone(world, tmp_path)
    _call(_run_args(w))
    _call(["init-issuer", "--keys-dir", str(tmp_path / "outras"), "--logs-dir", str(w.logs)])
    assert seen == [DEFAULT_N_BITS, DEFAULT_N_BITS]


def test_caminhos_padrao_da_secao_7(tmp_path, monkeypatch):
    # Prova: sem opções de pasta, tudo cai onde a seção 7 do PROJECT.md diz (relativo ao diretório atual).
    monkeypatch.chdir(tmp_path)
    assert _LOGS_PADRAO == Path("data/logs")  # o valor real do padrão, não o da barreira
    monkeypatch.setattr(cli, "LOGS_DIR", _LOGS_PADRAO)  # aqui o padrão relativo é o que se testa
    assert _call(["init-issuer"], _sources=[ShakeStandin()])[0] == 0
    assert (tmp_path / "keys" / ISSUER_SK_NAME).is_file() and (tmp_path / "keys" / ISSUER_PK_NAME).is_file()
    code, out, err = _call(["run"], _sources=[ShakeStandin()])
    assert code == 0, err
    receipts = tmp_path / "data" / "receipts"
    rid = re.search(r"receipt_id: ([0-9a-f-]{36})", out).group(1)
    assert (receipts / "chain.jsonl").is_file() and (receipts / f"{rid}.json").is_file()
    pubs = tmp_path / "data" / "public_keys" / rid
    assert sorted(p.name for p in pubs.iterdir()) == ["ml_dsa_65.pk.hex", "ml_kem_768.ek.hex"]
    assert _call(["run"], _sources=[RemoteDown()])[0] == 1
    assert (tmp_path / "data" / "logs" / "eal_runs.jsonl").is_file()
