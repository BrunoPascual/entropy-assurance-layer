"""F12, passo 2: a CLI guarda o histórico do detector de replay entre execuções.

Fontes de TESTE (SHAKE256 determinístico, não é entropia). Os bits são os mesmos da CLI nos testes
(rótulo conhecido, que já passa na saúde), girados `shift` posições: shift 0 repete o mesmo lote
de propósito (replay); shifts diferentes dão lotes novos. A semente do extrator vem da fonte `os`
real, como nos outros testes da CLI. Tudo em pasta temporária.
"""
from __future__ import annotations

import contextlib
import hashlib
import io
import json
from types import SimpleNamespace

import numpy as np
import pytest

from eal import cli
from eal.cli import main
from eal.config import DEFAULT_N_BITS, RECEIPT_CHAIN_NAME, REPLAY_HISTORY_NAME
from eal.health.replay_store import ReplayHistoryError, load_detector
from eal.sources.base import RawBatch, Source

BASE_LABEL = b"EAL-v1|test-standin|1"


def _bits(shift: int, n_bits: int = DEFAULT_N_BITS) -> np.ndarray:
    raw = hashlib.shake_256(BASE_LABEL).digest((n_bits + 7) // 8)
    bits = np.unpackbits(np.frombuffer(raw, dtype=np.uint8))[:n_bits].copy()
    return np.roll(bits, shift).copy()


class Shifted(Source):
    """Fonte local de TESTE: os bits conhecidos, girados `shift` posições. Conta as leituras."""

    source_id = "shifted_standin"
    source_type = "os"
    is_local = True
    is_simulated = False

    def __init__(self, shift: int) -> None:
        self.shift = shift
        self.reads = 0

    def read(self, n_bits: int) -> RawBatch:
        n_bits = self.validate_n_bits(n_bits)
        self.reads += 1
        return self._build_batch(_bits(self.shift, n_bits), {})


class FailingRead(Source):
    """Fonte local de TESTE cuja leitura falha; nenhum lote chega ao detector."""

    source_id = "failing_read"
    source_type = "os"
    is_local = True
    is_simulated = False

    def read(self, n_bits: int) -> RawBatch:
        raise TimeoutError("provedor fora do ar")


@pytest.fixture(autouse=True)
def _nunca_gravar_no_log_real(tmp_path, monkeypatch):
    """Barreira: nenhum teste grava em data/logs do diretório atual."""
    monkeypatch.setattr(cli, "LOGS_DIR", tmp_path / "_logs_padrao")


def _call(argv, **kw):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(argv, **kw)
    return code, out.getvalue(), err.getvalue()


def _dirs(tmp_path):
    return SimpleNamespace(keys=tmp_path / "keys", receipts=tmp_path / "receipts",
                           pubs=tmp_path / "pubs", logs=tmp_path / "logs")


def _init(d, source):
    return _call(["init-issuer", "--keys-dir", str(d.keys), "--logs-dir", str(d.logs)], _sources=[source])


def _run(d, source):
    return _call(["run", "--keys-dir", str(d.keys), "--receipts-dir", str(d.receipts),
                  "--public-keys-dir", str(d.pubs), "--logs-dir", str(d.logs)], _sources=[source])


def _history(d):
    return d.logs / REPLAY_HISTORY_NAME


def _chain_len(d) -> int:
    path = d.receipts / RECEIPT_CHAIN_NAME
    return path.read_bytes().count(b"\n") if path.exists() else 0


def _log(d) -> list[dict]:
    path = d.logs / cli.RUN_LOG_NAME
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_init_issuer_e_run_gravam_o_historico_na_pasta_de_logs(tmp_path):
    d = _dirs(tmp_path)
    assert _init(d, Shifted(1))[0] == 0
    assert _history(d).is_file() and load_detector(_history(d)).history_batches == 1
    code, _, err = _run(d, Shifted(0))
    assert code == 0, err
    assert load_detector(_history(d)).history_batches == 2


def test_replay_de_uma_execucao_anterior_e_reprovado(tmp_path):
    d = _dirs(tmp_path)
    assert _init(d, Shifted(1))[0] == 0
    assert _run(d, Shifted(0))[0] == 0
    code, _, err = _run(d, Shifted(0))  # o mesmo lote da execução anterior
    assert code == 1 and "fail-closed" in err
    assert _chain_len(d) == 1  # nenhum recibo novo
    entry = _log(d)[-1]
    assert entry["stage"] == "pipeline" and entry["pipeline"]["outcomes"][0]["status"] == "excluded"
    assert load_detector(_history(d)).history_batches == 3  # o lote repetido também foi registrado


def test_controle_sem_o_historico_o_mesmo_lote_passa(tmp_path):
    d = _dirs(tmp_path)
    assert _init(d, Shifted(1))[0] == 0
    assert _run(d, Shifted(0))[0] == 0
    _history(d).unlink()  # é o histórico que barra o replay, não o lote em si
    code, _, err = _run(d, Shifted(0))
    assert code == 0, err
    assert _chain_len(d) == 2


def test_historico_corrompido_recusa_antes_de_ler_qualquer_fonte(tmp_path):
    d = _dirs(tmp_path)
    assert _init(d, Shifted(1))[0] == 0
    _history(d).write_bytes(b"{lixo")
    src = Shifted(0)
    code, _, err = _run(d, src)
    assert code == 1 and "histórico de replay" in err and "fail-closed" in err
    assert src.reads == 0 and _chain_len(d) == 0
    assert _history(d).read_bytes() == b"{lixo"  # nada foi apagado nem reparado
    assert _log(d)[-1]["stage"] == "replay_history"


def test_init_issuer_com_historico_corrompido_nao_cria_chaves(tmp_path):
    d = _dirs(tmp_path)
    d.logs.mkdir()
    _history(d).write_bytes(b"{lixo")
    code, _, err = _init(d, Shifted(1))
    assert code == 1 and "histórico de replay" in err and not d.keys.exists()


def test_falha_ao_gravar_o_historico_nao_emite_recibo(tmp_path, monkeypatch):
    d = _dirs(tmp_path)
    assert _init(d, Shifted(1))[0] == 0

    def boom(detector, path):
        raise ReplayHistoryError("histórico de replay não pôde ser gravado")

    monkeypatch.setattr(cli, "save_detector", boom)
    code, _, err = _run(d, Shifted(0))
    assert code == 1 and "nenhum recibo foi emitido" in err
    assert not d.receipts.exists() and _log(d)[-1]["stage"] == "replay_history"


def test_sem_lote_lido_nao_cria_o_arquivo_do_historico(tmp_path):
    d = _dirs(tmp_path)
    code, _, err = _init(d, FailingRead())
    assert code == 1 and "fail-closed" in err
    assert not _history(d).exists()


def test_arquivo_do_historico_nao_guarda_bits(tmp_path):
    d = _dirs(tmp_path)
    assert _init(d, Shifted(1))[0] == 0
    raw = _history(d).read_bytes()
    assert len(raw) < 200_000
    assert _bits(1)[:4096].tobytes() not in raw
