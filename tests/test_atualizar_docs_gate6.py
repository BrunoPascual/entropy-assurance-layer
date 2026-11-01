"""Testes de scripts/atualizar_docs_gate6.py (Dia 6, R6), com PROJECT.md e CSV sintéticos."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "atualizar_docs_gate6",
    Path(__file__).resolve().parents[1] / "scripts" / "atualizar_docs_gate6.py")
mod = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(mod)

BASE = "# Projeto\r\n\r\nLinha com acentuação.\r\n<!-- coleta1-plano:end -->\r\n".encode("utf-8")
HEADER = ",".join(mod.COLUMNS)
ROW = ("2026-11-01_ibm_kingston_coleta1_{n:03d}.json,job{n},ibm_kingston,156,9616,1500096,"
       "{uso},20,2026-11-01 11:57:51-03:00,{h},{j}")


def csv_bytes(n_rows=2, uso="5", n_bits=None) -> bytes:
    lines = [HEADER]
    for n in range(1, n_rows + 1):
        line = ROW.format(n=n, uso=uso, h=f"{n:x}" * 64, j="e" * 64)
        if n_bits is not None:
            line = line.replace(",1500096,", f",{n_bits},")
        lines.append(line)
    return ("\r\n".join(lines) + "\r\n").encode("utf-8")


@pytest.fixture
def files(tmp_path):
    doc, data = tmp_path / "PROJECT.md", tmp_path / "inventario.csv"
    doc.write_bytes(BASE)
    data.write_bytes(csv_bytes())
    return doc, data


def run(doc, data):
    return mod.apply(doc, data, antes=mod.sha256(BASE))


def test_aplica_so_ao_fim_com_crlf(files):
    doc, data = files
    assert run(doc, data) == "aplicado"
    new = doc.read_bytes()
    assert new.startswith(BASE + b"\r\n" + mod.START.encode())
    assert new.endswith(mod.END.encode() + b"\r\n")
    rest = new.replace(b"\r\n", b"")
    assert b"\n" not in rest and b"\r" not in rest


def test_numeros_saem_do_csv(files):
    doc, data = files
    run(doc, data)
    text = doc.read_bytes().decode("utf-8")
    assert "**Resultado:** ATINGIDO. 3.000.192 bits" in text
    assert "a meta do plano congelado era 3.000.192" in text
    assert "**Lotes:** 2, backend ibm_kingston, 156 qubits." in text
    assert "job `job1`, 9.616 shots, 1.500.096 bits, uso 5 s" in text
    assert "**Uso de QPU da coleta 1:** 10 s no total." in text
    assert f"SHA-256 `{mod.sha256(data.read_bytes())}`" in text
    assert "1" * 64 in text and "2" * 64 in text


def test_abaixo_da_meta_registra_nao_atingido(files):
    doc, data = files
    data.write_bytes(csv_bytes(n_rows=1))
    run(doc, data)
    assert "**Resultado:** NÃO ATINGIDO. 1.500.096 bits" in doc.read_bytes().decode("utf-8")


def test_uso_fracionado_com_virgula(files):
    doc, data = files
    data.write_bytes(csv_bytes(uso="2.5"))
    run(doc, data)
    text = doc.read_bytes().decode("utf-8")
    assert "uso 2,5 s" in text and "5 s no total" in text


def test_linhas_em_branco_no_bloco(files):
    doc, data = files
    run(doc, data)
    text = doc.read_bytes().decode("utf-8")
    assert "(coleta 1)\r\n\r\nGerado por" in text and "vêm desse arquivo.\r\n\r\n- **Resultado" in text


def test_idempotente(files):
    doc, data = files
    run(doc, data)
    first, mtime = doc.read_bytes(), doc.stat().st_mtime_ns
    assert run(doc, data) == "ja aplicado"
    assert doc.read_bytes() == first and doc.stat().st_mtime_ns == mtime


def test_csv_mudou_depois_de_aplicar_recusa(files):
    doc, data = files
    run(doc, data)
    first = doc.read_bytes()
    data.write_bytes(csv_bytes(uso="6"))
    with pytest.raises(mod.Refused, match="difere do esperado"):
        run(doc, data)
    assert doc.read_bytes() == first


def test_recusa_hash_diferente(files):
    doc, data = files
    with pytest.raises(mod.Refused, match="difere do esperado"):
        mod.apply(doc, data, antes="0" * 64)
    assert doc.read_bytes() == BASE


def test_recusa_sem_csv(files):
    doc, data = files
    data.unlink()
    with pytest.raises(mod.Refused, match="falta"):
        run(doc, data)
    assert doc.read_bytes() == BASE


@pytest.mark.parametrize("content", [
    b"",
    b"a,b\r\n1,2\r\n",
    (HEADER + "\r\n").encode(),
    csv_bytes(n_bits="x"),
    csv_bytes() + b"curta,linha\r\n",
    b"\xff\xfe",
])
def test_recusa_csv_invalido(files, content):
    doc, data = files
    data.write_bytes(content)
    with pytest.raises(mod.Refused):
        run(doc, data)
    assert doc.read_bytes() == BASE


@pytest.mark.parametrize("base", [
    BASE + mod.START.encode() + b"\r\n",
    BASE + mod.END.encode() + b"\r\n",
    b"# so LF\nlinha\n",
    b"# misto\r\nlinha\n",
    b"# sem fim\r\nlinha",
])
def test_recusa_base_invalida(tmp_path, base):
    doc, data = tmp_path / "PROJECT.md", tmp_path / "inv.csv"
    doc.write_bytes(base)
    data.write_bytes(csv_bytes())
    with pytest.raises(mod.Refused):
        mod.apply(doc, data, antes=mod.sha256(base))
    assert doc.read_bytes() == base


def test_nao_deixa_temporario_quando_a_troca_falha(files, monkeypatch):
    doc, data = files
    monkeypatch.setattr(mod.os, "replace", lambda a, b: (_ for _ in ()).throw(OSError("x")))
    with pytest.raises(OSError):
        run(doc, data)
    assert doc.read_bytes() == BASE
    assert sorted(p.name for p in doc.parent.iterdir()) == ["PROJECT.md", "inventario.csv"]


def test_main_recusa_com_codigo_1(files, capsys):
    doc, data = files
    assert mod.main(doc, data) == 1  # BASE não tem o hash do commit 80837a0
    assert "RECUSADO (nada foi gravado)" in capsys.readouterr().out
    assert doc.read_bytes() == BASE


def test_constantes():
    assert mod.HASH_ANTES == "b18c74058405e4d04c82f988e4f9d523551f64d843f5bbfa124e8c873deeb55a"
    assert mod.META_BITS == 9616 * 156 * 2
    assert mod.pt(3000192) == "3.000.192" and mod.pt_s(5.0) == "5" and mod.pt_s(2.5) == "2,5"
