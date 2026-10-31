"""F12, passo 1: estado do ReplayDetector (to_state, from_state) e histórico em arquivo.

Lotes de TESTE (SHAKE256 determinístico, não é entropia). Tudo em pasta temporária.
"""
from __future__ import annotations

import hashlib
import json
import os
import re

import numpy as np
import pytest

from eal.config import REPLAY_BLOCK_BITS, REPLAY_HISTORY_SCHEMA
from eal.health import replay_store as store
from eal.health.replay import ReplayDetector
from eal.health.replay_store import ReplayHistoryError, load_detector, save_detector

B = REPLAY_BLOCK_BITS
ID_UM = "ID-DO-LOTE-1"


def lot(label: bytes, n_blocks: int = 3) -> np.ndarray:
    raw = hashlib.shake_256(label).digest(n_blocks * B // 8)
    return np.unpackbits(np.frombuffer(raw, dtype=np.uint8)).copy()


def check(det: ReplayDetector, bits: np.ndarray, batch_id: str):
    digest = hashlib.sha3_256(np.packbits(bits).tobytes()).hexdigest()
    return det.check(bits, batch_hash=digest, batch_id=batch_id)


def two_batches() -> ReplayDetector:
    det = ReplayDetector()
    check(det, lot(b"a"), "b1")
    check(det, lot(b"b"), "b2")
    return det


def state_copy() -> dict:
    return json.loads(json.dumps(two_batches().to_state()))


# ---------------------------------------------------------------- to_state / from_state

def test_estado_so_tem_hashes_e_ids():
    state = two_batches().to_state()
    assert state["block_bits"] == B and state["batch_ids"] == ["b1", "b2"]
    assert len(state["blocks"]) == 6 and all(re.fullmatch(r"[0-9a-f]{64}", k) for k in state["blocks"])
    assert all(re.fullmatch(r"b[12]#[0-2]", v) for v in state["blocks"].values())
    assert len(json.dumps(state)) < 3000  # nenhum bit: 6 blocos de 4096 bits não cabem nisso


def test_restaurado_decide_igual_ao_original():
    original = two_batches()
    restored = ReplayDetector.from_state(json.loads(json.dumps(original.to_state())))
    assert restored.history_batches == original.history_batches == 2
    prefixo = np.concatenate([lot(b"a")[: 2 * B], lot(b"novo", 2)])  # 2 blocos repetidos de b1
    r_original, r_restored = check(original, prefixo, "b3"), check(restored, prefixo, "b3")
    assert r_original == r_restored and not r_restored.passed and r_restored.n_repeated_blocks == 2
    novo = lot(b"outro")
    assert check(original, novo, "b4") == check(restored, novo, "b4")


def test_lote_inteiro_repetido_e_visto_apos_restaurar():
    restored = ReplayDetector.from_state(two_batches().to_state())
    r = check(restored, lot(b"b"), "b9")
    assert not r.passed and r.batch_repeated and r.repeated_batch_of == "b2"


def test_batch_id_ja_checado_continua_recusado_apos_restaurar():
    restored = ReplayDetector.from_state(two_batches().to_state())
    with pytest.raises(ValueError):
        check(restored, lot(b"zzz"), "b1")


def test_block_bits_e_exposto():
    assert ReplayDetector().block_bits == B and ReplayDetector(block_bits=64).block_bits == 64


MUTACOES = {
    "campo_ausente": lambda s: s.pop("blocks"),
    "campo_extra": lambda s: s.update(extra=1),
    "block_bits_bool": lambda s: s.update(block_bits=True),
    "block_bits_texto": lambda s: s.update(block_bits="4096"),
    "block_bits_nao_multiplo_de_8": lambda s: s.update(block_bits=7),
    "ids_repetidos": lambda s: s.update(batch_ids=["b1", "b1"]),
    "id_nao_texto": lambda s: s.update(batch_ids=["b1", 2]),
    "id_vazio": lambda s: s.update(batch_ids=[""]),
    "id_longo": lambda s: s.update(batch_ids=["x" * 129]),
    "ids_nao_lista": lambda s: s.update(batch_ids="b1"),
    "hash_de_lote_com_id_desconhecido": lambda s: s["batch_hashes"].update({"h": "nao-existe"}),
    "batch_hashes_nao_objeto": lambda s: s.update(batch_hashes=[]),
    "blocks_nao_objeto": lambda s: s.update(blocks=[]),
    "bloco_hex_curto": lambda s: s["blocks"].update({"abc": "b1#0"}),
    "bloco_hex_maiusculo": lambda s: s["blocks"].update({"A" * 64: "b1#0"}),
    "bloco_ref_desconhecida": lambda s: s["blocks"].update({"a" * 64: "zz#0"}),
    "bloco_ref_sem_cerquilha": lambda s: s["blocks"].update({"a" * 64: "b1"}),
    "bloco_ref_indice_ruim": lambda s: s["blocks"].update({"a" * 64: "b1#x"}),
    "bloco_ref_nao_texto": lambda s: s["blocks"].update({"a" * 64: 3}),
}


@pytest.mark.parametrize("nome", sorted(MUTACOES))
def test_from_state_recusa_estado_ruim(nome):
    state = state_copy()
    MUTACOES[nome](state)
    with pytest.raises(ValueError):
        ReplayDetector.from_state(state)


@pytest.mark.parametrize("state", [None, [], "x", 3])
def test_from_state_recusa_o_que_nao_e_objeto(state):
    with pytest.raises(ValueError):
        ReplayDetector.from_state(state)


# ---------------------------------------------------------------- arquivo

def saved(tmp_path):
    det = ReplayDetector()
    check(det, lot(b"a"), ID_UM)
    path = tmp_path / "logs" / "replay_history.json"
    save_detector(det, path)
    return path


def write_doc(path, doc) -> None:
    path.write_bytes(store._canonical(doc) + b"\n")


def test_arquivo_ausente_vira_detector_vazio(tmp_path):
    det = load_detector(tmp_path / "nao_existe.json")
    assert det.history_batches == 0 and det.block_bits == B


def test_ida_e_volta_pelo_arquivo_detecta_replay(tmp_path):
    path = saved(tmp_path)
    det = load_detector(path)
    assert det.history_batches == 1
    r = check(det, lot(b"a"), "outra-execucao")
    assert not r.passed and r.batch_repeated and r.repeated_batch_of == ID_UM


def test_regravar_acumula_o_historico(tmp_path):
    path = saved(tmp_path)
    det = load_detector(path)
    check(det, lot(b"b"), "b2")
    save_detector(det, path)
    assert load_detector(path).history_batches == 2


def test_arquivo_tem_formato_fixo_e_nenhum_bit(tmp_path):
    path = saved(tmp_path)
    raw = path.read_bytes()
    doc = json.loads(raw)
    assert doc.keys() == {"schema", "state", "state_hash"} and doc["schema"] == REPLAY_HISTORY_SCHEMA
    assert doc["state_hash"] == hashlib.sha3_256(store._canonical(doc["state"])).hexdigest()
    assert raw.endswith(b"\n") and b"\r" not in raw
    assert lot(b"a").tobytes() not in raw and len(raw) < 4000


def test_salvar_cria_a_pasta(tmp_path):
    path = tmp_path / "a" / "b" / "replay_history.json"
    save_detector(ReplayDetector(), path)
    assert path.is_file() and load_detector(path).history_batches == 0


def corrupt_cases(path):
    text = path.read_bytes()
    doc = json.loads(text)
    flip = json.loads(text)
    first = next(iter(flip["state"]["blocks"]))
    flip["state"]["blocks"][("0" if first[0] != "0" else "1") + first[1:]] = flip["state"]["blocks"].pop(first)
    invalid_ok_hash = json.loads(text)
    invalid_ok_hash["state"]["batch_ids"] = [ID_UM, ID_UM]
    invalid_ok_hash["state_hash"] = hashlib.sha3_256(store._canonical(invalid_ok_hash["state"])).hexdigest()
    return {
        "vazio": b"",
        "chave_aberta": b"{",
        "truncado": text[: len(text) // 2],
        "utf8_invalido": b"\xff\xfe\x00",
        "lista": b"[]",
        "nan": b'{"schema": NaN}',
        "chave_repetida": b'{"schema":"a","schema":"b","state":{},"state_hash":"x"}',
        "aninhamento_profundo": b"[" * 200_000,
        "schema_errado": store._canonical({**doc, "schema": "outro"}),
        "campo_extra": store._canonical({**doc, "extra": 1}),
        "campo_ausente": store._canonical({k: v for k, v in doc.items() if k != "state_hash"}),
        "hash_errado": store._canonical({**doc, "state_hash": "0" * 64}),
        "hash_nao_texto": store._canonical({**doc, "state_hash": 5}),
        "bloco_alterado_sem_refazer_hash": store._canonical({**doc, "state": flip["state"]}),
        "estado_invalido_com_hash_refeito": store._canonical(invalid_ok_hash),
    }


CASOS = ["vazio", "chave_aberta", "truncado", "utf8_invalido", "lista", "nan", "chave_repetida",
         "aninhamento_profundo", "schema_errado", "campo_extra", "campo_ausente", "hash_errado",
         "hash_nao_texto", "bloco_alterado_sem_refazer_hash", "estado_invalido_com_hash_refeito"]


@pytest.mark.parametrize("caso", CASOS)
def test_arquivo_corrompido_recusa_sem_alterar_nada(tmp_path, caso):
    path = saved(tmp_path)
    ruim = corrupt_cases(path)[caso]
    path.write_bytes(ruim)
    with pytest.raises(ReplayHistoryError) as exc:
        load_detector(path)
    assert ID_UM not in str(exc.value) and str(path) not in str(exc.value)
    assert path.read_bytes() == ruim  # nada foi apagado nem reparado


def test_outro_tamanho_de_bloco_recusa(tmp_path):
    path = tmp_path / "h.json"
    save_detector(ReplayDetector(block_bits=64), path)
    with pytest.raises(ReplayHistoryError):
        load_detector(path)
    assert load_detector(path, block_bits=64).block_bits == 64


def test_pasta_no_lugar_do_arquivo_recusa(tmp_path):
    (tmp_path / "h.json").mkdir()
    with pytest.raises(ReplayHistoryError):
        load_detector(tmp_path / "h.json")


def test_arquivo_grande_demais_recusa_ler_e_gravar(tmp_path, monkeypatch):
    path = saved(tmp_path)
    antes = path.read_bytes()
    monkeypatch.setattr(store, "REPLAY_HISTORY_MAX_BYTES", 10)
    with pytest.raises(ReplayHistoryError):
        load_detector(path)
    with pytest.raises(ReplayHistoryError):
        save_detector(two_batches(), path)
    assert path.read_bytes() == antes


def test_falha_ao_substituir_mantem_o_arquivo_antigo_e_nao_deixa_temporario(tmp_path, monkeypatch):
    path = saved(tmp_path)
    antes = path.read_bytes()

    def falha(*_args, **_kwargs):
        raise OSError("sem permissão")

    monkeypatch.setattr(os, "replace", falha)
    with pytest.raises(ReplayHistoryError):
        save_detector(two_batches(), path)
    monkeypatch.undo()
    assert path.read_bytes() == antes
    assert sorted(p.name for p in path.parent.iterdir()) == ["replay_history.json"]
