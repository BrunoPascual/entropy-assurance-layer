"""Testes do log encadeado dos recibos (Dia 5, etapa 3).

Tudo roda em pasta temporária (tmp_path): nunca toca em data/receipts real.
Os recibos aqui são montados à mão (corpo válido da seção 6.11, assinado com
uma chave de teste). O teste com recibos vindos do pipeline real fica em
tests/test_receipt_chain_pipeline.py.

Frases fixas das mensagens (os testes usam ``match=`` nelas):
  ChainError: "cadeia existente inválida", "recibo inválido", "prev_receipt_hash",
              "receipt_id repetido", "receipt_id não corresponde", "já existe" (só por corrida).
  verify_chain: "linha N: ..." com "vazia", "JSON inválido", "não canônico",
              "elo", "receipt_id repetido", "receipt_id não corresponde",
              "arquivo individual ausente", "arquivo individual diferente",
              "sem quebra de linha", "sem linha no log", "cabeça".
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from eal.config import GENESIS_PREV_HASH, RECEIPT_CHAIN_NAME, RECEIPT_REQUIRED_LIMITATIONS
from eal.receipt import chain
from eal.receipt.builder import receipt_id_for
from eal.receipt.chain import ChainError, append_receipt, chain_head, verify_chain
from eal.receipt.schema import canonical_bytes, receipt_body, receipt_hash
from eal.receipt.sign import issuer_key_from_seed, sign_receipt

ISSUER_XI = bytes(range(100, 132))
OTHER_XI = bytes(range(200, 232))
H = "ab" * 32  # um SHA3-256 qualquer em hex
FOREIGN_ID = "3f2b1c9e-1111-4222-8333-444455556666"  # UUID válido que NÃO é o uuid5 do seed_hash


# ---------------------------------------------------------------- helpers

def _seed_hash(i: int) -> str:
    return hashlib.sha3_256(b"chain-test-%d" % i).hexdigest()


def _source(sid, *, status="mixed", local=True, sim=False, approved=True):
    return {"source_id": sid, "status": status, "is_local": local,
            "is_simulated": sim, "approved": approved}


def _body(i: int, prev: str, receipt_id: str | None = None) -> dict:
    """Corpo válido (copia o de test_receipt_core), com id e semente próprios do índice i."""
    seed_hash = _seed_hash(i)
    return {
        "eal_version": "0.1.0",
        "receipt_id": receipt_id or receipt_id_for(seed_hash),
        "created_at": "2026-10-30T18:00:00+00:00",
        "mode": "keygen",
        "prev_receipt_hash": prev,
        "software": {"python": "3.12.10", "kyber-py": "1.2.0", "dilithium-py": "1.5.1"},
        "sources": [
            _source("ibm_kingston", local=False, status="mixed"),
            _source("os"),
            {**_source("faulty_x", status="excluded", approved=False), "reasons": ["APT"]},
        ],
        "extractor": {"type": "toeplitz", "n": 2048, "epsilon_log2": -64, "seed_hash": H},
        "mixer": {"type": "sha3-512", "inputs": ["ibm_kingston", "os"]},
        "seed_hash": seed_hash,
        "keys": {"ml_kem_768_pk_hash": H, "ml_dsa_65_pk_hash": H},
        "limitations": list(RECEIPT_REQUIRED_LIMITATIONS),
    }


_CACHE: dict = {}


def _signed(i: int, prev: str, key, receipt_id: str | None = None) -> dict:
    """Recibo assinado (com cache: a assinatura em Python puro é lenta)."""
    k = (i, prev, key.pk_hash, receipt_id)
    if k not in _CACHE:
        _CACHE[k] = sign_receipt(_body(i, prev, receipt_id), key)
    return json.loads(json.dumps(_CACHE[k]))  # cópia profunda: o teste pode mexer à vontade


def _line(r: dict) -> bytes:
    return canonical_bytes(r) + b"\n"


def _write_chain(d, receipts, *, files: bool = True) -> None:
    """Grava o log e os arquivos individuais à mão, sem passar por append_receipt."""
    (d / RECEIPT_CHAIN_NAME).write_bytes(b"".join(_line(r) for r in receipts))
    if files:
        for r in receipts:
            (d / f"{r['receipt_id']}.json").write_bytes(_line(r))


def _snapshot(d) -> dict:
    return {p.name: p.read_bytes() for p in sorted(d.iterdir())}


def _refused(d, pk, receipt, match: str) -> None:
    """append_receipt recusa com ChainError e não altera NADA na pasta."""
    before = _snapshot(d)
    with pytest.raises(ChainError, match=match):
        append_receipt(receipt, pk, d)
    assert _snapshot(d) == before


@pytest.fixture(scope="module")
def issuer():
    return issuer_key_from_seed(ISSUER_XI)


@pytest.fixture(scope="module")
def other_issuer():
    return issuer_key_from_seed(OTHER_XI)


@pytest.fixture(scope="module")
def chain3(issuer):
    """Três recibos válidos e encadeados: r0 (gênese) -> r1 -> r2."""
    r0 = _signed(0, GENESIS_PREV_HASH, issuer)
    r1 = _signed(1, receipt_hash(r0), issuer)
    r2 = _signed(2, receipt_hash(r1), issuer)
    return [r0, r1, r2]


# ---------------------------------------------------------------- A. começo da cadeia

def test_pasta_vazia_e_cadeia_valida_de_tamanho_zero(tmp_path, issuer):
    # Prova: sem log, a cadeia é válida, vazia e a cabeça é o hash gênese.
    res = verify_chain(tmp_path, issuer.pk)
    assert res.ok and res.reasons == ()
    assert res.length == 0 and res.head == GENESIS_PREV_HASH


def test_primeiro_recibo_com_genesis_e_aceito(tmp_path, issuer, chain3):
    # Prova: o primeiro recibo entra, o caminho devolvido é <id>.json e a cabeça passa a ser o hash dele.
    r0 = chain3[0]
    path = append_receipt(r0, issuer.pk, tmp_path)
    assert path == tmp_path / f"{r0['receipt_id']}.json"
    res = verify_chain(tmp_path, issuer.pk)
    assert res.ok and res.length == 1 and res.head == receipt_hash(r0)


def test_primeiro_recibo_com_outro_prev_e_recusado(tmp_path, issuer):
    # Prova: o primeiro recibo só vale com prev = gênese (e a recusa não deixa rastro).
    _refused(tmp_path, issuer.pk, _signed(0, H, issuer), "prev_receipt_hash")


# ---------------------------------------------------------------- B. encadeamento

def test_segundo_recibo_encadeado_e_aceito(tmp_path, issuer, chain3):
    # Prova: o segundo recibo, com prev = hash do primeiro (com assinatura), entra.
    append_receipt(chain3[0], issuer.pk, tmp_path)
    append_receipt(chain3[1], issuer.pk, tmp_path)
    res = verify_chain(tmp_path, issuer.pk)
    assert res.ok and res.length == 2 and res.head == receipt_hash(chain3[1])


def test_prev_errado_e_recusado(tmp_path, issuer, chain3):
    # Prova: prev que não é o hash da cabeça é recusado, mesmo com assinatura válida.
    append_receipt(chain3[0], issuer.pk, tmp_path)
    _refused(tmp_path, issuer.pk, _signed(1, H, issuer), "prev_receipt_hash")


def test_prev_igual_ao_hash_sem_assinatura_e_recusado(tmp_path, issuer, chain3):
    # Prova: o elo usa o hash do recibo COMPLETO; o hash só do corpo não serve.
    r0 = chain3[0]
    body_only = hashlib.sha3_256(canonical_bytes(receipt_body(r0))).hexdigest()
    assert body_only != receipt_hash(r0)
    append_receipt(r0, issuer.pk, tmp_path)
    _refused(tmp_path, issuer.pk, _signed(1, body_only, issuer), "prev_receipt_hash")


def test_receipt_id_repetido_e_recusado(tmp_path, issuer, chain3):
    # Prova: mesmo com o prev certo, um id já presente no log é recusado.
    append_receipt(chain3[0], issuer.pk, tmp_path)
    again = _signed(0, receipt_hash(chain3[0]), issuer)  # mesmo seed_hash => mesmo receipt_id
    assert again["receipt_id"] == chain3[0]["receipt_id"]
    _refused(tmp_path, issuer.pk, again, "receipt_id repetido")


@pytest.mark.parametrize("bad", [None, [], "x", 5], ids=["None", "lista", "str", "int"])
def test_entrada_que_nao_e_recibo_e_recusada(tmp_path, issuer, bad):
    # Prova: lixo no lugar do recibo vira ChainError, não TypeError nem gravação.
    _refused(tmp_path, issuer.pk, bad, "recibo inválido")


@pytest.mark.parametrize("pk", [b"", b"x" * 1951, b"x" * 1953, None, "ab"],
                         ids=["vazia", "curta", "longa", "None", "str"])
def test_chave_do_emissor_invalida_recusa_a_gravacao(tmp_path, chain3, pk):
    # Prova: sem chave pública válida nada é gravado, e a recusa já nasce na checagem da chave.
    with pytest.raises(ChainError, match="chave pública do emissor inválida"):
        append_receipt(chain3[0], pk, tmp_path)
    assert _snapshot(tmp_path) == {}


# ---------------------------------------------------------------- C. assinatura e emissor

def _bad_value(r):
    v = r["signature"]["value"]
    r["signature"]["value"] = ("A" if v[0] != "A" else "B") + v[1:]


def _no_signature(r):
    del r["signature"]


def _other_hash(r):
    r["signature"]["issuer_pk_hash"] = H


@pytest.mark.parametrize("fn", [_bad_value, _no_signature, _other_hash],
                         ids=["assinatura adulterada", "assinatura ausente", "hash do emissor trocado"])
def test_assinatura_defeituosa_e_recusada(tmp_path, issuer, fn):
    # Prova: assinatura adulterada, ausente ou com emissor trocado não entra no log.
    r = _signed(0, GENESIS_PREV_HASH, issuer)
    fn(r)
    _refused(tmp_path, issuer.pk, r, "recibo inválido")


def test_recibo_de_outro_emissor_e_recusado(tmp_path, issuer, other_issuer):
    # Prova: recibo assinado por outra chave não entra (uma chave por cadeia).
    _refused(tmp_path, issuer.pk, _signed(0, GENESIS_PREV_HASH, other_issuer), "recibo inválido")


def test_cadeia_com_recibo_de_outro_emissor_nao_verifica(tmp_path, issuer, other_issuer, chain3):
    # Prova: verify_chain acusa a linha assinada por emissor diferente do resto.
    r1_other = _signed(1, receipt_hash(chain3[0]), other_issuer)
    _write_chain(tmp_path, [chain3[0], r1_other])
    res = verify_chain(tmp_path, issuer.pk)
    assert not res.ok and any("linha 2" in r for r in res.reasons)


# ---------------------------------------------------------------- D. gravação

def test_linha_e_o_json_canonico_do_recibo_completo(tmp_path, issuer, chain3):
    # Prova: o log é exatamente canonical_bytes(recibo completo) + \n, uma linha por recibo.
    append_receipt(chain3[0], issuer.pk, tmp_path)
    append_receipt(chain3[1], issuer.pk, tmp_path)
    assert (tmp_path / RECEIPT_CHAIN_NAME).read_bytes() == _line(chain3[0]) + _line(chain3[1])


def test_nao_ha_crlf_no_log_nem_nos_arquivos(tmp_path, issuer, chain3):
    # Prova: gravação binária; o Windows não troca \n por \r\n (o hash do arquivo não muda).
    append_receipt(chain3[0], issuer.pk, tmp_path)
    for p in tmp_path.iterdir():
        assert b"\r" not in p.read_bytes(), p.name


def test_arquivo_individual_e_igual_a_linha(tmp_path, issuer, chain3):
    # Prova: <id>.json tem os mesmos bytes da linha do log.
    path = append_receipt(chain3[0], issuer.pk, tmp_path)
    assert path.read_bytes() == _line(chain3[0])


def test_arquivo_individual_solto_recusa_a_gravacao(tmp_path, issuer, chain3):
    # Prova: um <id>.json solto na pasta nunca é sobrescrito; a pasta já conta como inválida e o log nem é criado.
    path = tmp_path / f"{chain3[0]['receipt_id']}.json"
    path.write_bytes(b"lixo")
    _refused(tmp_path, issuer.pk, chain3[0], "cadeia existente inválida")
    assert path.read_bytes() == b"lixo" and not (tmp_path / RECEIPT_CHAIN_NAME).exists()


def test_arquivo_individual_que_aparece_depois_da_varredura_recusa_antes_da_linha(
    tmp_path, issuer, chain3, monkeypatch
):
    # Prova: defesa em profundidade contra corrida. Se <id>.json existir mesmo com a varredura limpa,
    # a recusa vem ANTES de gravar a linha (senão o log ficaria com uma linha sem arquivo).
    ok = chain.ChainResult(True, (), 0, GENESIS_PREV_HASH)
    monkeypatch.setattr(chain, "verify_chain", lambda *a, **k: ok)
    path = tmp_path / f"{chain3[0]['receipt_id']}.json"
    path.write_bytes(b"lixo")
    _refused(tmp_path, issuer.pk, chain3[0], "já existe")
    assert path.read_bytes() == b"lixo" and not (tmp_path / RECEIPT_CHAIN_NAME).exists()


def test_fsync_depois_da_linha_e_antes_do_arquivo_individual(tmp_path, issuer, chain3, monkeypatch):
    # Prova: a linha é gravada e sincronizada primeiro; só depois nasce <id>.json (linha vence arquivo).
    r0 = chain3[0]
    log, ind = tmp_path / RECEIPT_CHAIN_NAME, tmp_path / f"{r0['receipt_id']}.json"
    seen: list[tuple[int, bool]] = []
    real = chain.os.fsync

    def spy(fd):
        seen.append((log.stat().st_size, ind.exists()))
        return real(fd)

    monkeypatch.setattr(chain.os, "fsync", spy)
    append_receipt(r0, issuer.pk, tmp_path)
    assert len(seen) >= 2
    assert seen[0] == (len(_line(r0)), False)  # 1ª sincronização: linha completa no disco, arquivo ainda não
    assert seen[-1][1] is True                  # última: o arquivo individual já existe


def test_escrita_esvazia_o_buffer_antes_do_fsync(tmp_path, monkeypatch):
    # Prova: o fsync só vale se o conteúdo já saiu do buffer do Python (conteúdo pequeno, sem depender do tamanho do buffer).
    target = tmp_path / "a.bin"
    seen: list[int] = []
    real = chain.os.fsync

    def spy(fd):
        seen.append(target.stat().st_size)
        return real(fd)

    monkeypatch.setattr(chain.os, "fsync", spy)
    chain._fsynced_write(target, "ab", b"0123456789")
    assert seen == [10]


def test_gravacao_individual_nunca_sobrescreve_mesmo_se_a_checagem_previa_falhar(tmp_path, issuer, chain3, monkeypatch):
    # Prova: o modo exclusivo ('xb') protege o <id>.json sozinho, numa corrida em que exists() mente.
    ok = chain.ChainResult(True, (), 0, GENESIS_PREV_HASH)
    monkeypatch.setattr(chain, "verify_chain", lambda *a, **k: ok)
    path = tmp_path / f"{chain3[0]['receipt_id']}.json"
    path.write_bytes(b"lixo")
    real_exists = Path.exists
    monkeypatch.setattr(Path, "exists", lambda self, **kw: False if self.suffix == ".json" else real_exists(self, **kw))
    with pytest.raises(ChainError, match="arquivo individual falhou"):
        append_receipt(chain3[0], issuer.pk, tmp_path)
    assert path.read_bytes() == b"lixo"


def test_falha_no_arquivo_individual_deixa_a_linha_e_o_verify_acusa(tmp_path, issuer, chain3, monkeypatch):
    # Prova: se o <id>.json falhar depois da linha, o erro sobe, a linha fica e verify_chain acusa.
    def boom(path, data):
        raise OSError("disco cheio")

    monkeypatch.setattr(chain, "_write_individual", boom)
    with pytest.raises(ChainError):
        append_receipt(chain3[0], issuer.pk, tmp_path)
    assert (tmp_path / RECEIPT_CHAIN_NAME).read_bytes() == _line(chain3[0])
    res = verify_chain(tmp_path, issuer.pk)
    assert not res.ok and any("arquivo individual ausente" in r for r in res.reasons)


@pytest.mark.parametrize("bad_id", ["../x", "..\\x", "con", ""], ids=["sobe pasta", "barra invertida", "nome do Windows", "vazio"])
def test_receipt_id_com_cara_de_caminho_e_recusado(tmp_path, issuer, bad_id):
    # Prova: id fora do UUID canônico é recusado e nada é criado dentro nem fora da pasta.
    d = tmp_path / "receipts"
    d.mkdir()
    r = _signed(0, GENESIS_PREV_HASH, issuer)
    r["receipt_id"] = bad_id
    _refused(d, issuer.pk, r, "recibo inválido")
    assert sorted(p.name for p in tmp_path.iterdir()) == ["receipts"]


def test_append_cria_a_pasta_que_nao_existe(tmp_path, issuer, chain3):
    # Prova: a pasta do log é criada só quando há um recibo válido para gravar.
    d = tmp_path / "novo" / "receipts"
    append_receipt(chain3[0], issuer.pk, d)
    assert verify_chain(d, issuer.pk).length == 1


def test_recusa_em_pasta_inexistente_nao_cria_a_pasta(tmp_path, issuer):
    # Prova: recusar um recibo não deixa pasta criada para trás.
    d = tmp_path / "novo"
    with pytest.raises(ChainError):
        append_receipt(_signed(0, H, issuer), issuer.pk, d)
    assert not d.exists()


# ---------------------------------------------------------------- E. verify_chain pega adulteração

def test_controle_cadeia_de_tres_e_valida(tmp_path, issuer, chain3):
    # Prova (controle): a cadeia de 3 recibos montada à mão é válida; sem isso os testes de adulteração não valem.
    _write_chain(tmp_path, chain3)
    res = verify_chain(tmp_path, issuer.pk)
    assert res.ok and res.reasons == ()
    assert res.length == 3 and res.head == receipt_hash(chain3[2])


def test_pasta_com_gitkeep_e_outros_arquivos_nao_json_continua_valida(tmp_path, issuer, chain3):
    # Prova: .gitkeep e notas não contam como arquivo sobrando (data/receipts real tem um .gitkeep).
    _write_chain(tmp_path, chain3)
    (tmp_path / ".gitkeep").write_bytes(b"")
    (tmp_path / "notas.txt").write_bytes(b"x")
    assert verify_chain(tmp_path, issuer.pk).ok


@pytest.mark.parametrize("idx", [0, 1, 2])
def test_byte_alterado_em_qualquer_linha(tmp_path, issuer, chain3, idx):
    # Prova: um byte mudado em qualquer linha reprova, e o motivo aponta a linha certa.
    _write_chain(tmp_path, chain3)
    lines = [_line(r) for r in chain3]
    assert lines[idx].count(b'"mode":"keygen"') == 1
    lines[idx] = lines[idx].replace(b'"mode":"keygen"', b'"mode":"keygex"')
    (tmp_path / RECEIPT_CHAIN_NAME).write_bytes(b"".join(lines))
    res = verify_chain(tmp_path, issuer.pk)
    assert not res.ok and any(f"linha {idx + 1}:" in r for r in res.reasons)


def test_linha_do_meio_apagada_quebra_o_elo(tmp_path, issuer, chain3):
    # Prova: apagar o recibo do meio deixa um elo quebrado entre o 1º e o 3º.
    _write_chain(tmp_path, chain3)
    (tmp_path / RECEIPT_CHAIN_NAME).write_bytes(_line(chain3[0]) + _line(chain3[2]))
    res = verify_chain(tmp_path, issuer.pk)
    assert not res.ok and any("linha 2:" in r and "elo" in r for r in res.reasons)


def test_linhas_trocadas_de_ordem(tmp_path, issuer, chain3):
    # Prova: trocar a ordem das linhas reprova.
    _write_chain(tmp_path, [chain3[1], chain3[0], chain3[2]])
    res = verify_chain(tmp_path, issuer.pk)
    assert not res.ok and any("elo" in r for r in res.reasons)


def test_linha_duplicada_reprova_por_id_repetido(tmp_path, issuer, chain3):
    # Prova: o mesmo recibo duas vezes no log é acusado como receipt_id repetido.
    _write_chain(tmp_path, [chain3[0], chain3[0]])
    res = verify_chain(tmp_path, issuer.pk)
    assert not res.ok and any("receipt_id repetido" in r for r in res.reasons)


def test_linha_em_branco_reprova(tmp_path, issuer, chain3):
    # Prova: linha vazia no meio do log não é tolerada.
    _write_chain(tmp_path, chain3[:2])
    (tmp_path / RECEIPT_CHAIN_NAME).write_bytes(_line(chain3[0]) + b"\n" + _line(chain3[1]))
    res = verify_chain(tmp_path, issuer.pk)
    assert not res.ok and any("linha 2:" in r and "vazia" in r for r in res.reasons)


JUNK = {
    "json incompleto": b"{",
    "chave repetida": b'{"a":1,"a":2}',
    "NaN": b'{"a":NaN}',
    "nao e objeto": b"[]",
    "utf8 invalido": b"\xff\xfe\xfd",
}


@pytest.mark.parametrize("junk", JUNK.values(), ids=JUNK.keys())
def test_linha_ilegivel_reprova_sem_excecao(tmp_path, issuer, chain3, junk):
    # Prova: lixo no log vira motivo na linha certa; verify_chain nunca levanta por causa do conteúdo.
    _write_chain(tmp_path, chain3[:1])
    (tmp_path / RECEIPT_CHAIN_NAME).write_bytes(_line(chain3[0]) + junk + b"\n")
    res = verify_chain(tmp_path, issuer.pk)
    assert not res.ok and any("linha 2:" in r for r in res.reasons)
    assert res.length == 2  # length = linhas do log, inclusive a ilegível


def test_linha_ruim_no_meio_nao_gera_elo_falso_na_linha_seguinte(tmp_path, issuer, chain3):
    # Prova: depois de uma linha ilegível o elo seguinte é inverificável e não vira acusação extra (sem cascata).
    _write_chain(tmp_path, chain3)
    (tmp_path / RECEIPT_CHAIN_NAME).write_bytes(_line(chain3[0]) + b"{\n" + _line(chain3[2]))
    res = verify_chain(tmp_path, issuer.pk)
    assert not res.ok and any("linha 2:" in r for r in res.reasons)
    assert not any("linha 3:" in r and "elo" in r for r in res.reasons)


def test_receipt_id_de_caminho_na_linha_nao_faz_o_verify_tocar_fora_da_pasta(tmp_path, issuer, monkeypatch):
    # Prova: um receipt_id como "../fora" dentro do log não leva verify_chain a abrir arquivos fora da pasta.
    d = tmp_path / "receipts"
    d.mkdir()
    (tmp_path / "fora.json").write_bytes(b"x")
    r = _signed(0, GENESIS_PREV_HASH, issuer)
    r["receipt_id"] = "../fora"
    (d / RECEIPT_CHAIN_NAME).write_bytes(_line(r))
    touched: list[Path] = []

    def spied(orig):
        def inner(self, *a, **k):
            touched.append(self)
            return orig(self, *a, **k)
        return inner

    for name in ("is_file", "read_bytes", "exists"):
        monkeypatch.setattr(Path, name, spied(getattr(Path, name)))
    res = verify_chain(d, issuer.pk)
    assert not res.ok
    assert touched and all(p.resolve().parent == d.resolve() for p in touched)


def test_linha_nao_canonica_reprova(tmp_path, issuer, chain3):
    # Prova: o mesmo recibo com espaços ou ordem diferente não é aceito (o log é canônico).
    _write_chain(tmp_path, chain3[:1])
    loose = json.dumps(chain3[0]).encode("utf-8")
    assert loose != canonical_bytes(chain3[0])
    (tmp_path / RECEIPT_CHAIN_NAME).write_bytes(loose + b"\n")
    res = verify_chain(tmp_path, issuer.pk)
    assert not res.ok and any("não canônico" in r for r in res.reasons)


def test_ultima_linha_sem_quebra_de_linha_reprova(tmp_path, issuer, chain3):
    # Prova: gravação interrompida (sem \n final) conta como log corrompido.
    _write_chain(tmp_path, chain3[:2])
    (tmp_path / RECEIPT_CHAIN_NAME).write_bytes(_line(chain3[0]) + _line(chain3[1]).rstrip(b"\n"))
    res = verify_chain(tmp_path, issuer.pk)
    assert not res.ok and any("sem quebra de linha" in r for r in res.reasons)
    assert res.length == 2  # length = linhas do log, inclusive a que ficou sem \n


def test_arquivo_individual_alterado_reprova(tmp_path, issuer, chain3):
    # Prova: <id>.json diferente da linha do log é acusado.
    _write_chain(tmp_path, chain3)
    path = tmp_path / f"{chain3[1]['receipt_id']}.json"
    path.write_bytes(b" " + path.read_bytes())
    res = verify_chain(tmp_path, issuer.pk)
    assert not res.ok and any("linha 2:" in r and "arquivo individual diferente" in r for r in res.reasons)


def test_arquivo_individual_faltando_reprova(tmp_path, issuer, chain3):
    # Prova: linha sem o <id>.json correspondente é acusada.
    _write_chain(tmp_path, chain3)
    (tmp_path / f"{chain3[2]['receipt_id']}.json").unlink()
    res = verify_chain(tmp_path, issuer.pk)
    assert not res.ok and any("linha 3:" in r and "arquivo individual ausente" in r for r in res.reasons)


def test_arquivo_individual_sobrando_reprova(tmp_path, issuer, chain3):
    # Prova: um <id>.json sem linha no log (recibo fora da cadeia) é acusado.
    _write_chain(tmp_path, chain3)
    stray = _signed(9, receipt_hash(chain3[2]), issuer)
    (tmp_path / f"{stray['receipt_id']}.json").write_bytes(_line(stray))
    res = verify_chain(tmp_path, issuer.pk)
    assert not res.ok and any("sem linha no log" in r for r in res.reasons)


def test_receipt_id_diferente_do_uuid5_da_semente_reprova(tmp_path, issuer):
    # Prova: o id do recibo tem de ser o uuid5 do seed_hash (hoje ninguém mais confere isso).
    bad = _signed(0, GENESIS_PREV_HASH, issuer, receipt_id=FOREIGN_ID)
    assert bad["receipt_id"] != receipt_id_for(bad["seed_hash"])
    _write_chain(tmp_path, [bad])
    res = verify_chain(tmp_path, issuer.pk)
    assert not res.ok and any("receipt_id não corresponde" in r for r in res.reasons)
    _refused(_fresh(tmp_path), issuer.pk, bad, "receipt_id não corresponde")


def _fresh(base):
    d = base / "limpa"
    d.mkdir()
    return d


# ---------------------------------------------------------------- expected_head, chain_head e entradas estranhas

def test_expected_head_correta_passa(tmp_path, issuer, chain3):
    # Prova: com a cabeça esperada certa a cadeia continua válida.
    _write_chain(tmp_path, chain3)
    assert verify_chain(tmp_path, issuer.pk, expected_head=receipt_hash(chain3[2])).ok


def test_expected_head_errada_reprova(tmp_path, issuer, chain3):
    # Prova: cabeça diferente da esperada reprova.
    _write_chain(tmp_path, chain3)
    res = verify_chain(tmp_path, issuer.pk, expected_head=receipt_hash(chain3[1]))
    assert not res.ok and any("cabeça" in r for r in res.reasons)


def test_ultimo_recibo_apagado_so_aparece_com_expected_head(tmp_path, issuer, chain3):
    # Prova: apagar o ÚLTIMO recibo deixa uma cadeia válida; só a cabeça guardada fora do log denuncia.
    _write_chain(tmp_path, chain3[:2])
    assert verify_chain(tmp_path, issuer.pk).ok
    res = verify_chain(tmp_path, issuer.pk, expected_head=receipt_hash(chain3[2]))
    assert not res.ok and any("cabeça" in r for r in res.reasons)


@pytest.mark.parametrize("bad", [5, "", "curta", "G" * 64, b"x"], ids=["int", "vazia", "curta", "nao hex", "bytes"])
def test_expected_head_invalida_reprova_sem_excecao(tmp_path, issuer, chain3, bad):
    # Prova: expected_head fora do formato reprova sem levantar.
    _write_chain(tmp_path, chain3)
    assert not verify_chain(tmp_path, issuer.pk, expected_head=bad).ok


@pytest.mark.parametrize("pk", [b"", b"x" * 1951, b"x" * 1953, None, "ab"],
                         ids=["vazia", "curta", "longa", "None", "str"])
def test_verify_chain_com_chave_invalida_reprova_mesmo_com_log_vazio(tmp_path, pk):
    # Prova: chave pública inválida reprova sempre, inclusive com a pasta vazia.
    assert not verify_chain(tmp_path, pk).ok


def test_pasta_inexistente_reprova_sem_excecao(tmp_path, issuer):
    # Prova: pasta que não existe é motivo, não exceção.
    assert not verify_chain(tmp_path / "nao_existe", issuer.pk).ok


def test_log_que_e_uma_pasta_reprova_sem_excecao(tmp_path, issuer):
    # Prova: chain.jsonl sendo uma pasta (erro de leitura do sistema) vira motivo, não exceção.
    (tmp_path / RECEIPT_CHAIN_NAME).mkdir()
    assert not verify_chain(tmp_path, issuer.pk).ok


def test_chain_head_vazio_e_apos_gravacoes(tmp_path, issuer, chain3):
    # Prova: cabeça = gênese com log vazio; depois = hash do último recibo gravado.
    assert chain_head(tmp_path, issuer.pk) == GENESIS_PREV_HASH
    append_receipt(chain3[0], issuer.pk, tmp_path)
    append_receipt(chain3[1], issuer.pk, tmp_path)
    assert chain_head(tmp_path, issuer.pk) == receipt_hash(chain3[1])


# ---------------------------------------------------------------- F. fail-closed

def _corrupt_line(d, chain3):
    lines = [_line(r) for r in chain3[:2]]
    lines[1] = lines[1].replace(b'"mode":"keygen"', b'"mode":"keygex"')
    (d / RECEIPT_CHAIN_NAME).write_bytes(b"".join(lines))


def _corrupt_no_newline(d, chain3):
    (d / RECEIPT_CHAIN_NAME).write_bytes(_line(chain3[0]) + _line(chain3[1]).rstrip(b"\n"))


def _corrupt_missing_file(d, chain3):
    (d / f"{chain3[1]['receipt_id']}.json").unlink()


CORRUPTIONS = {
    "linha alterada": _corrupt_line,
    "sem quebra de linha final": _corrupt_no_newline,
    "arquivo individual ausente": _corrupt_missing_file,
}


@pytest.mark.parametrize("corrupt", CORRUPTIONS.values(), ids=CORRUPTIONS.keys())
def test_log_corrompido_recusa_novas_gravacoes_e_chain_head(tmp_path, issuer, chain3, corrupt):
    # Prova: fail-closed. Com o log corrompido, nem um recibo válido entra, e chain_head também recusa.
    _write_chain(tmp_path, chain3[:2])
    corrupt(tmp_path, chain3)
    assert not verify_chain(tmp_path, issuer.pk).ok
    nxt = _signed(2, receipt_hash(chain3[1]), issuer)
    _refused(tmp_path, issuer.pk, nxt, "cadeia existente inválida")
    with pytest.raises(ChainError, match="cadeia existente inválida"):
        chain_head(tmp_path, issuer.pk)


# ---------------------------------------------------------------- G. sigilo

MARK = b"SEGREDO-123"


def test_motivos_do_verify_nao_ecoam_o_conteudo_das_linhas(tmp_path, issuer, chain3):
    # Prova: nenhum motivo repete o conteúdo da linha (um provedor pode ter posto qualquer coisa ali).
    junk = b'{"x":"' + MARK + b'", "x":1}'
    _write_chain(tmp_path, chain3[:1])
    (tmp_path / RECEIPT_CHAIN_NAME).write_bytes(_line(chain3[0]) + junk + b"\n" + MARK + b"\n")
    res = verify_chain(tmp_path, issuer.pk)
    assert not res.ok
    assert all(MARK.decode() not in r for r in res.reasons)


def test_mensagem_de_recusa_nao_ecoa_assinatura_semente_nem_prev(tmp_path, issuer, chain3):
    # Prova: o texto do ChainError não contém a assinatura, o seed_hash nem o prev do recibo recusado.
    r = _signed(0, H, issuer)
    with pytest.raises(ChainError) as exc:
        append_receipt(r, issuer.pk, tmp_path)
    text = str(exc.value)
    assert r["signature"]["value"] not in text
    assert r["seed_hash"] not in text
    assert r["receipt_id"] not in text
