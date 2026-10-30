"""Testes da derivação PQC a partir da semente (Dia 5, etapa 1)."""
from __future__ import annotations

import hashlib
from types import SimpleNamespace

import numpy as np
import pytest
from dilithium_py.ml_dsa import ML_DSA_65
from kyber_py.ml_kem import ML_KEM_768

from eal.config import DSA_DOMAIN, KEM_DOMAIN
from eal.pqc.keygen import DerivedKeys, derive_keys, derive_keys_from_mix

SEED = bytes(range(64))
SEED_1BIT = bytes([SEED[0] ^ 0x01]) + SEED[1:]


def _frag(data: bytes, n: int = 40) -> str:
    """Primeiros n caracteres da forma escapada que repr() imprime para estes bytes.

    Usa o mesmo repr(bytes) que o dataclass e o dict usariam, então a busca
    em texto funciona mesmo com escapes (\\x..) e aspas.
    """
    return repr(data)[2:-1][:n]


def _sha3_hex(data: bytes) -> str:
    return hashlib.sha3_256(data).hexdigest()


def _fake_mix(*, mode="keygen", usable=True, seed=SEED, seed_hash=None):
    """Objeto com os atributos que derive_keys_from_mix lê.

    seed_hash, se não for passado, é o SHA3-256 da semente (como o mixer faz).
    Para semente que não é bytes, usa um hash dummy: o teste espera erro de
    qualquer forma.
    """
    if seed_hash is None:
        seed_hash = _sha3_hex(seed) if isinstance(seed, bytes) else "0" * 64
    return SimpleNamespace(
        mode=mode, usable_for_key=usable, seed=seed, seed_hash=seed_hash
    )


@pytest.fixture(scope="module")
def keys() -> DerivedKeys:
    return derive_keys(SEED)


# --- 1. Validação de entrada ---------------------------------------------

@pytest.mark.parametrize("bad", [SEED[:63], SEED + b"\x00"], ids=["63 bytes", "65 bytes"])
def test_semente_com_tamanho_errado_e_recusada(bad):
    with pytest.raises(ValueError):
        derive_keys(bad)


@pytest.mark.parametrize(
    "bad", [SEED.hex(), bytearray(SEED), None], ids=["str", "bytearray", "None"]
)
def test_semente_com_tipo_errado_e_recusada(bad):
    with pytest.raises(TypeError):
        derive_keys(bad)


def test_mensagem_de_erro_nao_ecoa_a_semente():
    with pytest.raises(ValueError) as exc:
        derive_keys(SEED[:63])
    texto = str(exc.value)
    assert _frag(SEED, 32) not in texto
    assert SEED[:8].hex() not in texto


def test_mix_ausente_e_recusado():
    with pytest.raises(ValueError):
        derive_keys_from_mix(None)


@pytest.mark.parametrize("flag", [False, None, 1, "True"], ids=["False", "None", "1", "str"])
def test_usable_for_key_precisa_ser_booleano_verdadeiro(flag):
    with pytest.raises(ValueError):
        derive_keys_from_mix(_fake_mix(usable=flag))


def test_usable_for_key_aceita_numpy_bool():
    derive_keys_from_mix(_fake_mix(usable=np.True_))


def test_modo_experiment_e_recusado_mesmo_com_flag_verdadeira():
    with pytest.raises(ValueError):
        derive_keys_from_mix(_fake_mix(mode="experiment", usable=True))


@pytest.mark.parametrize("mode", [None, "KEYGEN", "keygen ", 1], ids=["None", "caixa", "espaço", "int"])
def test_modo_diferente_de_keygen_e_recusado(mode):
    with pytest.raises(ValueError):
        derive_keys_from_mix(_fake_mix(mode=mode))


@pytest.mark.parametrize(
    "bad_seed", [SEED[:63], SEED.hex(), None], ids=["curta", "str", "None"]
)
def test_semente_invalida_dentro_do_mix_e_recusada(bad_seed):
    with pytest.raises((TypeError, ValueError)):
        derive_keys_from_mix(_fake_mix(seed=bad_seed))


def test_seed_hash_que_nao_bate_e_recusado():
    with pytest.raises(ValueError):
        derive_keys_from_mix(_fake_mix(seed_hash="0" * 64))


def test_semente_trocada_com_hash_antigo_e_recusada():
    """Semente adulterada mantendo o seed_hash original: a checagem deve pegar."""
    with pytest.raises(ValueError):
        derive_keys_from_mix(_fake_mix(seed=SEED_1BIT, seed_hash=_sha3_hex(SEED)))


def test_mix_valido_gera_as_mesmas_chaves_que_a_semente():
    assert derive_keys_from_mix(_fake_mix()).kem_dk == derive_keys(SEED).kem_dk


# --- 2. Tamanhos FIPS 203 e 204 ------------------------------------------

def test_tamanhos_das_chaves(keys):
    assert len(keys.kem_ek) == 1184
    assert len(keys.kem_dk) == 2400
    assert len(keys.dsa_pk) == 1952
    assert len(keys.dsa_sk) == 4032


# --- 3. Ida e volta -------------------------------------------------------

def test_kem_encapsula_e_decapsula(keys):
    ss, ct = ML_KEM_768.encaps(keys.kem_ek)
    assert len(ss) == 32
    assert len(ct) == 1088
    assert ML_KEM_768.decaps(keys.kem_dk, ct) == ss


@pytest.mark.parametrize("deterministic", [True, False], ids=["determinístico", "hedged"])
def test_dsa_assina_e_verifica(keys, deterministic):
    msg = b"EAL teste"
    sig = ML_DSA_65.sign(keys.dsa_sk, msg, deterministic=deterministic)
    assert len(sig) == 3309
    assert ML_DSA_65.verify(keys.dsa_pk, msg, sig)


# --- 4. Determinismo ------------------------------------------------------

def test_mesma_semente_mesmas_chaves(keys):
    again = derive_keys(SEED)
    assert again.kem_ek == keys.kem_ek
    assert again.kem_dk == keys.kem_dk
    assert again.dsa_pk == keys.dsa_pk
    assert again.dsa_sk == keys.dsa_sk


def test_um_bit_de_diferenca_muda_as_chaves(keys):
    other = derive_keys(SEED_1BIT)
    assert other.kem_ek != keys.kem_ek
    assert other.dsa_pk != keys.dsa_pk


# --- 5. Resposta conhecida: a derivação segue a especificação -------------

def test_derivacao_segue_a_especificacao(keys):
    kem_material = hashlib.shake_256(KEM_DOMAIN + SEED).digest(64)  # d || z
    dsa_material = hashlib.shake_256(DSA_DOMAIN + SEED).digest(32)  # xi
    ek, dk = ML_KEM_768.key_derive(kem_material)
    pk, sk = ML_DSA_65.key_derive(dsa_material)
    assert keys.kem_ek == ek
    assert keys.kem_dk == dk
    assert keys.dsa_pk == pk
    assert keys.dsa_sk == sk


# --- 6. Separação de domínio ----------------------------------------------

def test_sem_prefixo_de_dominio_gera_chaves_diferentes(keys):
    kem_sem_prefixo = ML_KEM_768.key_derive(hashlib.shake_256(SEED).digest(64))[0]
    dsa_sem_prefixo = ML_DSA_65.key_derive(hashlib.shake_256(SEED).digest(32))[0]
    assert keys.kem_ek != kem_sem_prefixo
    assert keys.dsa_pk != dsa_sem_prefixo


def test_prefixos_trocados_entre_algoritmos_geram_chaves_diferentes(keys):
    kem_com_prefixo_dsa = ML_KEM_768.key_derive(
        hashlib.shake_256(DSA_DOMAIN + SEED).digest(64)
    )[0]
    assert keys.kem_ek != kem_com_prefixo_dsa


# --- 7. Adulteração -------------------------------------------------------

def test_ciphertext_alterado_gera_segredo_diferente_sem_excecao(keys):
    """ML-KEM usa rejeição implícita: não há exceção, o segredo muda."""
    ss, ct = ML_KEM_768.encaps(keys.kem_ek)
    ct_alterado = bytes([ct[0] ^ 0x01]) + ct[1:]
    assert ML_KEM_768.decaps(keys.kem_dk, ct_alterado) != ss


def test_assinatura_alterada_e_recusada(keys):
    msg = b"recibo"
    sig = ML_DSA_65.sign(keys.dsa_sk, msg, deterministic=True)
    assert ML_DSA_65.verify(keys.dsa_pk, msg, sig)
    assert not ML_DSA_65.verify(keys.dsa_pk, b"recibo!", sig)
    assert not ML_DSA_65.verify(keys.dsa_pk, msg, bytes([sig[0] ^ 0x01]) + sig[1:])
    assert not ML_DSA_65.verify(keys.dsa_pk, msg, sig, ctx=b"outro")


def test_chave_publica_de_outra_semente_e_recusada(keys):
    msg = b"recibo"
    sig = ML_DSA_65.sign(keys.dsa_sk, msg, deterministic=True)
    outra_pk = derive_keys(SEED_1BIT).dsa_pk
    assert not ML_DSA_65.verify(outra_pk, msg, sig)


# --- 8. Sigilo ------------------------------------------------------------

def test_sk_do_ml_dsa_comeca_com_rho_publico(keys):
    """FIPS 204: pk = rho || t1 e sk = rho || K || tr || ...

    Os primeiros 32 bytes da sk são públicos. Por isso os testes de sigilo
    procuram trechos secretos de verdade (K), e não o início da sk.
    """
    assert keys.dsa_sk[:32] == keys.dsa_pk[:32]


def _secret_parts(keys: DerivedKeys) -> dict[str, bytes]:
    """Trechos que são segredo de verdade em cada chave privada.

    ML-KEM (FIPS 203): dk = dk_pke || ek || H(ek) || z. Início e z são secretos.
    ML-DSA (FIPS 204): sk = rho || K || tr || ...; K = sk[32:64] é secreto.
    """
    return {
        "kem_dk_inicio": keys.kem_dk[:32],
        "kem_dk_z": keys.kem_dk[-32:],
        "dsa_sk_K": keys.dsa_sk[32:64],
        "semente": SEED,
    }


def test_repr_nao_vaza_segredos(keys):
    texto = repr(keys)
    # Controle: a chave pública aparece no repr. Sem isso, a busca não provaria nada.
    assert _frag(keys.kem_ek) in texto
    for nome, parte in _secret_parts(keys).items():
        assert _frag(parte) not in texto, nome
        assert parte.hex()[:32] not in texto, nome


def test_resumo_publico_so_tem_hashes_das_chaves_publicas(keys):
    resumo = keys.public_summary()
    assert set(resumo) == {"ml_kem_768_pk_hash", "ml_dsa_65_pk_hash"}
    assert resumo["ml_kem_768_pk_hash"] == _sha3_hex(keys.kem_ek)
    assert resumo["ml_dsa_65_pk_hash"] == _sha3_hex(keys.dsa_pk)
    for valor in resumo.values():
        assert len(valor) == 64
        int(valor, 16)  # só hexadecimal
    texto = repr(resumo)
    for nome, parte in _secret_parts(keys).items():
        assert _frag(parte) not in texto, nome
        assert parte.hex()[:32] not in texto, nome
