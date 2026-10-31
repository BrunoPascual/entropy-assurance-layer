"""Testes das correções da revisão adversarial do Dia 5, partes 2 e 3.

F7  chave do emissor incompleta (só .pk ou só .sk): mensagem que explica, nos
    dois comandos, antes de qualquer pipeline.
F8  --expected-head em maiúsculas (como o Get-FileHash imprime) é aceito.
F9  objetos aninhados do recibo: o construtor só emite campos previstos e recusa
    texto hexadecimal longo e listas longas de bits.
F10 o pipeline só grava a mensagem de erro do extrator, nunca a da leitura da semente.
F11 a checagem da semente do Toeplitz exige booleano estrito.

Tudo roda em pasta temporária com fontes falsas; a única fonte de dados aqui são
arrays fixos de teste, que NÃO são fonte de entropia do projeto.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from eal import cli
from eal.config import GENESIS_PREV_HASH, ISSUER_PK_NAME, ISSUER_SK_NAME
from eal.extract.toeplitz import extract_toeplitz
from eal.health.report import HealthReport
from eal.pipeline import _extract, run_pipeline
from eal.pqc.keygen import derive_keys_from_mix
from eal.receipt import builder
from eal.receipt.builder import build_receipt_body
from eal.receipt.chain import append_receipt
from eal.receipt.schema import receipt_hash
from eal.receipt.sign import issuer_key_from_seed, save_issuer_key, sign_receipt

ROOT = Path(__file__).resolve().parents[1]
GUARDED = (Path("keys"), Path("data") / "receipts", Path("data") / "logs", Path("data") / "public_keys")
N_BITS = 4096


def _snapshot() -> list[tuple[str, int, int]]:
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
    before = _snapshot()
    yield
    assert _snapshot() == before, "o teste mexeu nas pastas reais do projeto"


# ------------------------------------------------------------ fontes e execução falsas

def make_health_report(batch, *, approved: bool = True) -> HealthReport:
    return HealthReport(
        schema="eal-healthreport-v1", batch_id=batch.batch_id, source_id=batch.source_id,
        n_bits=int(batch.bits.size), h_declared=1.0,
        rct_pass=True, rct_cutoff=41, rct_max_run=12, rct_max_run_start=100, rct_alpha_neg_log2=40,
        apt_pass=True, apt_inconclusive=False, apt_cutoff=600, apt_max_count=530,
        apt_n_windows=4, apt_n_failed_windows=0, apt_discarded_bits=0, apt_alpha_neg_log2=20,
        replay_pass=True, replay_history_batches=0, replay_n_blocks=1,
        replay_repeated_blocks=0, replay_batch_repeated=False,
        h_bit=0.99, h_byte=0.98, h_estimated=1.0, h_limited_by="byte", h_threshold=0.9,
        h_health_pass=True, stats={"monobit": 0.5}, stats_pass=True, stats_inconclusive=False,
        approved=approved,
        reasons=() if approved else ("RCT: 99 bits iguais seguidos em 5 (limite 41)",),
        notes=("replay: primeiro lote da execução; não há histórico para comparar",),
    )


class FakeSource:
    source_type = "fake"
    source_version = "teste-1"
    is_local = True
    is_simulated = False

    def __init__(self, source_id: str, seed: int) -> None:
        self.source_id = source_id
        rng = np.random.default_rng(seed)
        self._batch = SimpleNamespace(
            source_id=source_id, batch_id=f"batch-{source_id}",
            bits=rng.integers(0, 2, N_BITS, dtype=np.uint8),
            is_local=True, is_simulated=False, batch_hash="0" * 64,
        )

    def read(self, n_bits: int):
        return self._batch


class FakeSeedSource:
    def read(self, n_bits: int):
        rng = np.random.default_rng(999)
        return SimpleNamespace(
            bits=rng.integers(0, 2, n_bits, dtype=np.uint8),
            is_local=True, is_simulated=False, batch_id="seed-batch",
        )


def fake_health(batch, detector, h_declared):
    return make_health_report(batch, approved=batch.source_id != "os_ruim")


def make_run(*, with_excluded: bool = False):
    sources = [FakeSource("os", 1)]
    if with_excluded:
        sources.append(FakeSource("os_ruim", 2))
    result = run_pipeline(sources, FakeSeedSource(), mode="keygen", n_bits=N_BITS,
                          health_fn=fake_health, detector=object())
    assert result.mix is not None, result.error
    return result, sources


def make_body(*, with_excluded: bool = False) -> dict:
    result, sources = make_run(with_excluded=with_excluded)
    keys = derive_keys_from_mix(result.mix)
    return build_receipt_body(result, keys, sources, prev_receipt_hash=GENESIS_PREV_HASH,
                              created_at="2026-10-31T12:00:00+00:00",
                              software={"python": "teste"})


# ===================================================================== F11

BOOL_CASES = [
    (True, False, True),
    (np.True_, np.False_, True),
    (True, True, False),
    (False, False, False),
    (1, 0, False),
    (True, None, False),
    (True, "", False),
    ("não", False, False),
    (True, "False", False),
]


@pytest.mark.parametrize("is_local,is_simulated,accepted", BOOL_CASES)
def test_f11_semente_exige_booleano_estrito(is_local, is_simulated, accepted):
    rng = np.random.default_rng(1)
    bits = rng.integers(0, 2, 20_000, dtype=np.uint8)
    seed = SimpleNamespace(bits=rng.integers(0, 2, 4096, dtype=np.uint8),
                           is_local=is_local, is_simulated=is_simulated, batch_id="semente")
    if accepted:
        assert extract_toeplitz(bits, 1.0, seed, input_batch_id="entrada").n_output_bits > 0
    else:
        with pytest.raises(ValueError, match="local e não simulada"):
            extract_toeplitz(bits, 1.0, seed, input_batch_id="entrada")


# ===================================================================== F10

def _approved_report_and_batch():
    batch = FakeSource("os", 1)._batch
    return batch, make_health_report(batch)


def test_f10_valueerror_da_leitura_da_semente_nao_e_gravado():
    batch, report = _approved_report_and_batch()

    class Seed:
        def read(self, n_bits):
            raise ValueError("SEGREDO-DO-PROVEDOR")

    extraction, problem = _extract(batch, report, Seed())
    assert extraction is None
    assert problem == "extração falhou: ValueError"
    assert "SEGREDO" not in problem


def test_f10_outras_excecoes_da_leitura_continuam_so_com_o_nome():
    batch, report = _approved_report_and_batch()

    class Seed:
        def read(self, n_bits):
            raise RuntimeError("SEGREDO-DO-PROVEDOR")

    _, problem = _extract(batch, report, Seed())
    assert problem == "extração falhou: RuntimeError"


def test_f10_mensagem_do_extrator_continua_gravada():
    batch, report = _approved_report_and_batch()

    class ShortSeed:
        def read(self, n_bits):
            return SimpleNamespace(bits=np.zeros(100, dtype=np.uint8), is_local=True,
                                   is_simulated=False, batch_id="curta")

    extraction, problem = _extract(batch, report, ShortSeed())
    assert extraction is None
    assert problem.startswith("extração recusada: semente curta")


def test_f10_caminho_feliz_continua_extraindo():
    batch, report = _approved_report_and_batch()
    extraction, problem = _extract(batch, report, FakeSeedSource())
    assert problem is None and extraction.n_output_bits > 0


def test_f10_no_pipeline_completo_o_motivo_fica_so_com_o_nome_da_classe():
    class Boom:
        def read(self, n_bits):
            raise ValueError("SEGREDO-DO-PROVEDOR")

    result = run_pipeline([FakeSource("os", 1)], Boom(), mode="keygen", n_bits=N_BITS,
                          health_fn=fake_health, detector=object())
    assert result.mix is None
    texto = json.dumps(result.to_dict(), ensure_ascii=False)
    assert "SEGREDO" not in texto
    assert "extração falhou: ValueError" in texto


# ===================================================================== F9

def test_f9_recibo_real_tem_so_campos_previstos():
    body = make_body(with_excluded=True)
    assert set(body["extractor"]) <= builder.EXTRACTOR_KEYS
    assert set(body["mixer"]) <= builder.MIXER_KEYS
    for entry in body["mixer"]["included"]:
        assert set(entry) <= builder.MIXER_INCLUDED_KEYS
    for entry in body["mixer"]["excluded"]:
        assert set(entry) <= builder.MIXER_EXCLUDED_KEYS
    for entry in body["sources"]:
        assert set(entry) <= builder.SOURCE_ENTRY_KEYS
        assert set(entry["health"]) <= builder.HEALTH_KEYS
        assert set(entry["extraction"]) <= builder.EXTRACTION_KEYS


def test_f9_as_listas_do_construtor_batem_exatamente_com_o_que_as_classes_produzem():
    body = make_body(with_excluded=True)
    assert set(body["extractor"]) == builder.EXTRACTOR_KEYS
    assert set(body["mixer"]) == builder.MIXER_KEYS
    assert all(set(e) == builder.MIXER_INCLUDED_KEYS for e in body["mixer"]["included"])
    assert body["mixer"]["excluded"], "o teste precisa de uma fonte excluída"
    assert all(set(e) == builder.MIXER_EXCLUDED_KEYS for e in body["mixer"]["excluded"])
    assert all(set(e) == builder.SOURCE_ENTRY_KEYS for e in body["sources"])
    assert all(set(e["health"]) == builder.HEALTH_KEYS for e in body["sources"])
    assert all(set(e["extraction"]) == builder.EXTRACTION_KEYS for e in body["sources"])


def test_f9_campos_do_healthreport_estao_travados():
    # Se este teste falhar, um campo entrou ou saiu do HealthReport: decida de propósito
    # se ele vai para o recibo assinado e atualize HEALTH_KEYS no builder.
    assert {f.name for f in dataclasses.fields(HealthReport)} == builder.HEALTH_KEYS
    assert len(builder.HEALTH_KEYS) == 35


def test_f9_healthreport_com_campo_novo_nao_chega_ao_recibo(monkeypatch):
    original = HealthReport.to_dict

    def com_extra(self):
        d = original(self)
        d["bits_do_lote"] = "novo campo"
        return d

    monkeypatch.setattr(HealthReport, "to_dict", com_extra)
    with pytest.raises(ValueError, match=r"campos não previstos em sources\[0\]\.health"):
        make_body()


def test_f9_extraction_mixer_e_extractor_com_campo_novo_sao_recusados(monkeypatch):
    from eal.extract.blocks import ExtractionResult
    from eal.mix.mixer import MixResult

    original_ext = ExtractionResult.to_dict
    monkeypatch.setattr(ExtractionResult, "to_dict", lambda self: {**original_ext(self), "x": 1})
    with pytest.raises(ValueError, match=r"sources\[0\]\.extraction"):
        make_body()
    monkeypatch.setattr(ExtractionResult, "to_dict", original_ext)

    original_mix = MixResult.to_dict
    monkeypatch.setattr(MixResult, "to_dict", lambda self: {**original_mix(self), "x": 1})
    with pytest.raises(ValueError, match=r"campos não previstos em mixer"):
        make_body()


def test_f9_mixer_included_e_excluded_com_campo_novo_sao_recusados(monkeypatch):
    from eal.mix.mixer import MixResult

    original = MixResult.to_dict

    def com_extra_incluida(self):
        d = original(self)
        d["included"] = [{**e, "x": 1} for e in d["included"]]
        return d

    monkeypatch.setattr(MixResult, "to_dict", com_extra_incluida)
    with pytest.raises(ValueError, match=r"mixer\.included\[0\]"):
        make_body()

    def com_extra_excluida(self):
        d = original(self)
        d["excluded"] = [{**e, "x": 1} for e in d["excluded"]]
        return d

    monkeypatch.setattr(MixResult, "to_dict", com_extra_excluida)
    with pytest.raises(ValueError, match=r"mixer\.excluded\[0\]"):
        make_body(with_excluded=True)


def test_f9_entrada_de_fonte_com_campo_novo_e_recusada(monkeypatch):
    original = builder._source_entry
    monkeypatch.setattr(builder, "_source_entry", lambda *a: {**original(*a), "x": 1})
    with pytest.raises(ValueError, match=r"campos não previstos em sources\[0\]"):
        make_body()


def test_f9_mensagem_cita_o_nome_do_campo_e_nunca_o_valor(monkeypatch):
    original = HealthReport.to_dict
    monkeypatch.setattr(HealthReport, "to_dict", lambda self: {**original(self), "campo_novo": "VALOR-SECRETO-123"})
    with pytest.raises(ValueError) as info:
        make_body()
    assert "campo_novo" in str(info.value)
    assert "VALOR-SECRETO-123" not in str(info.value)


def test_f9_texto_hexadecimal_longo_em_campo_permitido_e_recusado(monkeypatch):
    original = HealthReport.to_dict
    semente_em_hex = "ab" * 64  # 64 bytes em hexadecimal (128 caracteres)

    def com_hex(self):
        d = original(self)
        d["notes"] = list(d["notes"]) + [semente_em_hex]
        return d

    monkeypatch.setattr(HealthReport, "to_dict", com_hex)
    with pytest.raises(ValueError, match="hexadecimal longo") as info:
        make_body()
    assert semente_em_hex not in str(info.value)


def test_f9_hash_de_64_caracteres_continua_permitido():
    body = make_body()
    assert len(body["seed_hash"]) == 64
    assert len(body["keys"]["ml_kem_768_pk_hash"]) == 64


def test_f9_lista_longa_de_bits_em_campo_permitido_e_recusada(monkeypatch):
    original = HealthReport.to_dict

    def com_bits(self):
        d = original(self)
        d["stats"] = {**d["stats"], "bits": [0, 1] * 40}
        return d

    monkeypatch.setattr(HealthReport, "to_dict", com_bits)
    with pytest.raises(ValueError, match="lista longa de bits"):
        make_body()


def test_f9_lista_curta_de_inteiros_nao_e_confundida_com_bits(monkeypatch):
    original = HealthReport.to_dict

    def com_lista_curta(self):
        d = original(self)
        d["stats"] = {**d["stats"], "contagens": [0, 1, 1, 0]}
        return d

    monkeypatch.setattr(HealthReport, "to_dict", com_lista_curta)
    assert make_body()["sources"][0]["health"]["stats"]["contagens"] == [0, 1, 1, 0]


def test_f9_bytes_no_recibo_continuam_recusados(monkeypatch):
    original = HealthReport.to_dict
    monkeypatch.setattr(HealthReport, "to_dict", lambda self: {**original(self), "notes": [b"bytes"]})
    with pytest.raises(TypeError):
        make_body()


def test_f9_extractor_com_campo_novo_e_recusado():
    ok = {"type": "toeplitz", "n": 2048, "epsilon_log2": -64}
    builder.check_nested_fields({"extractor": ok})
    with pytest.raises(ValueError, match="campos não previstos em extractor"):
        builder.check_nested_fields({"extractor": {**ok, "x": 1}})


def test_f9_funcao_isolada_aceita_corpo_sem_os_objetos_aninhados():
    builder.check_nested_fields({})
    builder.check_nested_fields({"sources": "nao e lista", "mixer": 3, "extractor": None})


# ============================================================ F8 e F7 (CLI)

def _signed_receipt_in_chain(tmp_path: Path):
    keys_dir, receipts_dir = tmp_path / "keys", tmp_path / "receipts"
    key = issuer_key_from_seed(b"\x03" * 32)
    save_issuer_key(key, keys_dir)
    result, sources = make_run()
    body = build_receipt_body(result, derive_keys_from_mix(result.mix), sources,
                              prev_receipt_hash=GENESIS_PREV_HASH)
    receipt = sign_receipt(body, key)
    path = append_receipt(receipt, key.pk, receipts_dir)
    return keys_dir, path, receipt_hash(receipt)


def test_f8_parser_normaliza_a_cabeca_para_minusculas_e_tira_espacos():
    args = cli._build_parser().parse_args(["verify", "x.json", "--expected-head", "  ABCDEF" + "0" * 58 + " "])
    assert args.expected_head == "abcdef" + "0" * 58


def test_f8_cabeca_em_maiusculas_e_aceita(tmp_path, capsys):
    keys_dir, path, head = _signed_receipt_in_chain(tmp_path)
    code = cli.main(["verify", str(path), "--keys-dir", str(keys_dir), "--expected-head", head.upper()])
    out = capsys.readouterr().out
    assert code == 0
    assert "cabeça conferida" in out


def test_f8_cabeca_em_minusculas_continua_aceita(tmp_path, capsys):
    keys_dir, path, head = _signed_receipt_in_chain(tmp_path)
    assert cli.main(["verify", str(path), "--keys-dir", str(keys_dir), "--expected-head", head]) == 0
    assert "cabeça conferida" in capsys.readouterr().out


def test_f8_cabeca_errada_continua_recusada_mesmo_em_maiusculas(tmp_path, capsys):
    keys_dir, path, head = _signed_receipt_in_chain(tmp_path)
    wrong = ("f" if head[0] != "f" else "e") + head[1:]
    code = cli.main(["verify", str(path), "--keys-dir", str(keys_dir), "--expected-head", wrong.upper()])
    assert code == 1
    assert "diferente da esperada" in capsys.readouterr().err


def test_f8_texto_que_nao_e_hash_continua_recusado(tmp_path, capsys):
    keys_dir, path, _ = _signed_receipt_in_chain(tmp_path)
    assert cli.main(["verify", str(path), "--keys-dir", str(keys_dir), "--expected-head", "abc"]) == 1
    assert "diferente da esperada" in capsys.readouterr().err


class _PipelineNaoDevia:
    def read(self, n_bits):
        raise AssertionError("o pipeline não devia rodar")


def _issuer_args(command: str, tmp_path: Path) -> list[str]:
    base = [command, "--keys-dir", str(tmp_path / "keys"), "--logs-dir", str(tmp_path / "logs")]
    if command == "run":
        base += ["--receipts-dir", str(tmp_path / "receipts"), "--public-keys-dir", str(tmp_path / "pk")]
    return base


def _only(tmp_path: Path, name: str, content: str = "00\n") -> Path:
    keys = tmp_path / "keys"
    keys.mkdir(parents=True, exist_ok=True)
    (keys / name).write_text(content, encoding="ascii")
    return keys / name


def _last_log(tmp_path: Path) -> dict:
    lines = (tmp_path / "logs" / cli.RUN_LOG_NAME).read_text(encoding="utf-8").strip().split("\n")
    return json.loads(lines[-1])


@pytest.mark.parametrize("command", ["init-issuer", "run"])
@pytest.mark.parametrize("present,missing", [(ISSUER_PK_NAME, ISSUER_SK_NAME), (ISSUER_SK_NAME, ISSUER_PK_NAME)])
def test_f7_chave_incompleta_explica_qual_arquivo_falta(tmp_path, capsys, monkeypatch, command, present, missing):
    monkeypatch.setattr(cli, "_run_keygen", lambda *a, **k: pytest.fail("o pipeline não devia rodar"))
    _only(tmp_path, present)
    code = cli.main(_issuer_args(command, tmp_path), _sources=[_PipelineNaoDevia()], _seed_source=_PipelineNaoDevia())
    err = capsys.readouterr().err
    assert code == 1
    assert "incompleta" in err
    assert f"falta {missing}" in err
    assert f"existe só {present}" in err
    assert _last_log(tmp_path)["stage"] == "issuer_key"


@pytest.mark.parametrize("command", ["init-issuer", "run"])
def test_f7_mensagem_orienta_os_dois_caminhos(tmp_path, capsys, command):
    _only(tmp_path, ISSUER_PK_NAME)
    cli.main(_issuer_args(command, tmp_path))
    err = capsys.readouterr().err
    assert "apague o arquivo que sobrou" in err
    assert "restaure o arquivo que falta" in err
    assert "init-issuer" in err


@pytest.mark.parametrize("command", ["init-issuer", "run"])
def test_f7_nao_mexe_nos_arquivos_nem_ecoa_o_conteudo(tmp_path, capsys, command):
    path = _only(tmp_path, ISSUER_PK_NAME, "SEGREDO-TESTE\n")
    cli.main(_issuer_args(command, tmp_path))
    captured = capsys.readouterr()
    assert path.read_text(encoding="ascii") == "SEGREDO-TESTE\n"
    assert "SEGREDO-TESTE" not in captured.out + captured.err
    assert "SEGREDO-TESTE" not in (tmp_path / "logs" / cli.RUN_LOG_NAME).read_text(encoding="utf-8")
    assert sorted(p.name for p in (tmp_path / "keys").iterdir()) == [ISSUER_PK_NAME]


def test_f7_par_completo_continua_com_a_mensagem_de_ja_existe(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(cli, "_run_keygen", lambda *a, **k: pytest.fail("o pipeline não devia rodar"))
    save_issuer_key(issuer_key_from_seed(b"\x04" * 32), tmp_path / "keys")
    assert cli.main(_issuer_args("init-issuer", tmp_path)) == 1
    err = capsys.readouterr().err
    assert "já existe" in err and "incompleta" not in err


def test_f7_run_sem_nenhum_arquivo_continua_pedindo_init_issuer(tmp_path, capsys):
    assert cli.main(_issuer_args("run", tmp_path)) == 1
    err = capsys.readouterr().err
    assert "não encontrada" in err and "init-issuer" in err and "incompleta" not in err


def test_f7_init_issuer_sem_nenhum_arquivo_chega_ao_pipeline(tmp_path, capsys, monkeypatch):
    def parado(*a, **k):
        raise cli._Fail("pipeline", "parado pelo teste")

    monkeypatch.setattr(cli, "_run_keygen", parado)
    assert cli.main(_issuer_args("init-issuer", tmp_path)) == 1
    assert "parado pelo teste" in capsys.readouterr().err
    assert _last_log(tmp_path)["stage"] == "pipeline"
