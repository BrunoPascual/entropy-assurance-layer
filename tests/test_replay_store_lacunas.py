"""F12, revisão de mutações: testes que isolam os três casos que sobreviveram às mutações.

1) chave repetida num documento válido por outros critérios; 2) fsync chamado antes do replace;
3) arquivo ilegível (OSError na leitura) vira ReplayHistoryError sem vazar o caminho.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest

from eal.health import replay_store as store
from eal.health.replay import ReplayDetector
from eal.health.replay_store import ReplayHistoryError, load_detector, save_detector


def _documento_valido_com_chave_repetida(path: Path) -> bytes:
    """Documento com schema, state e state_hash corretos, mas com a chave "schema" repetida."""
    save_detector(ReplayDetector(), path)
    doc = json.loads(path.read_bytes())
    state_hash = doc["state_hash"]
    body = (
        '{"schema":"eal-replay-history-v1","schema":"eal-replay-history-v1",'
        f'"state":{store._canonical(doc["state"]).decode()},"state_hash":"{state_hash}"}}\n'
    )
    return body.encode("utf-8")


def test_chave_repetida_recusada_mesmo_com_o_resto_valido(tmp_path):
    path = tmp_path / "h.json"
    save_detector(ReplayDetector(), path)
    path.write_bytes(_documento_valido_com_chave_repetida(path))
    with pytest.raises(ReplayHistoryError):
        load_detector(path)


def test_gravacao_chama_fsync_antes_de_substituir(tmp_path, monkeypatch):
    ordem: list[str] = []
    real_fsync, real_replace = os.fsync, os.replace
    monkeypatch.setattr(os, "fsync", lambda fd: (ordem.append("fsync"), real_fsync(fd)))
    monkeypatch.setattr(os, "replace", lambda a, b: (ordem.append("replace"), real_replace(a, b)))
    save_detector(ReplayDetector(), tmp_path / "h.json")
    assert ordem == ["fsync", "replace"]


def test_arquivo_ilegivel_vira_erro_sem_vazar_o_caminho(tmp_path, monkeypatch):
    path = tmp_path / "segredo-do-caminho.json"
    save_detector(ReplayDetector(), path)

    def sem_permissao(self, *a, **k):
        raise PermissionError(f"negado: {self}")

    monkeypatch.setattr(Path, "read_bytes", sem_permissao)
    with pytest.raises(ReplayHistoryError) as exc:
        load_detector(path)
    assert "segredo-do-caminho" not in str(exc.value) and str(tmp_path) not in str(exc.value)
