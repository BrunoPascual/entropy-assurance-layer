"""Registra o commit verificado dos vetores ACVP (item 4 do fechamento do Dia 5).

Duas correções, conferidas antes de gravar qualquer coisa:

1. ``tests/data/kat/SOURCE.json``: cada arquivo de vetores ganha o commit do
   ACVP-Server em que ele aparece. Os commits foram confirmados em 31/10/2026
   com ``git show <commit>:<caminho>`` num clone do histórico: o tamanho e o
   SHA3-256 do conteúdo são iguais aos já registrados no próprio arquivo. Os
   campos de vetores (subconjunto, tamanho, SHA3-256) não são alterados.
2. ``PROJECT.md``: a frase que dizia que o commit não tinha sido registrado
   passa a citar os commits verificados.

Se qualquer conferência falhar, nada é gravado. Idempotente.

Uso (raiz do projeto)::

    py -3.12 -m scripts.corrigir_source_kat_dia5
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_REL = Path("tests") / "data" / "kat" / "SOURCE.json"
PROJECT_REL = Path("PROJECT.md")
URL_BASE = "https://raw.githubusercontent.com/usnistgov/ACVP-Server/master/"
MASTER_CONSULTADO = "975de31eb83d87039ec88934fdc47d8c312b892d"
VERIFIED_EM = "2026-10-31"
METODO = (
    "git show <commit>:<caminho> em clone do histórico do ACVP-Server; "
    "tamanho e SHA3-256 do conteúdo iguais aos registrados"
)
COMMIT_LABEL = "por arquivo; ver arquivos[*].commit (verificado pelo SHA3-256 do conteúdo)"
UNREGISTERED_PREFIX = "não registrado"
OLD_TOP_KEYS = {"fonte", "branch", "commit", "baixado_em", "arquivos"}
NEW_TOP_KEYS = {
    "fonte", "branch", "commit", "baixado_em", "verificado_em",
    "metodo_verificacao", "master_consultado", "arquivos",
}
VERIFIED = {
    "ml_kem_768_keygen.json": {
        "caminho": "gen-val/json-files/ML-KEM-keyGen-FIPS203/internalProjection.json",
        "commit": "15c0f3deeefbfa8cb6cd32a99e1ca3b738c66bf0",
        "commit_data": "2026-04-16T16:41:44-04:00",
        "original_bytes": 558841,
        "original_sha3_256_bytes": "77d18ef0bb338d608a15c7e6598974ab9f14fd303a3d96b3c1c429ba848d39ba",
    },
    "ml_dsa_65_keygen.json": {
        "caminho": "gen-val/json-files/ML-DSA-keyGen-FIPS204/internalProjection.json",
        "commit": "2972def23bf9f3680c2c531561ed9bdd0f1086ad",
        "commit_data": "2026-07-20T16:31:36-04:00",
        "original_bytes": 882437,
        "original_sha3_256_bytes": "f3b2f06a7bf677a9647436743b6cb5151c8ebaa876df09974b81ab293918e19e",
    },
}
OLD_SENTENCE = "baixado em 30/10/2026; o commit exato não foi registrado."
NEW_SENTENCE = (
    "baixado em 30/10/2026; o commit de cada arquivo foi verificado pelo SHA3-256 do "
    "conteúdo original: ML-KEM-768 `15c0f3deeefbfa8cb6cd32a99e1ca3b738c66bf0`, ML-DSA-65 "
    "`2972def23bf9f3680c2c531561ed9bdd0f1086ad` (ver `tests/data/kat/SOURCE.json`)."
)


class CorrError(Exception):
    """Falha de conferência. Nada é gravado quando ela acontece."""


def _no_dupes(pairs: list[tuple[str, object]]) -> dict:
    out: dict = {}
    for key, value in pairs:
        if key in out:
            raise CorrError("JSON com chave repetida")
        out[key] = value
    return out


def corrigir_source(raw: bytes) -> bytes | None:
    """Devolve o SOURCE.json com os commits, ou None se já estiver corrigido."""
    try:
        obj = json.loads(raw.decode("utf-8-sig"), object_pairs_hook=_no_dupes)
    except (UnicodeDecodeError, ValueError) as exc:
        raise CorrError("SOURCE.json não é JSON UTF-8 válido") from exc
    if not isinstance(obj, dict):
        raise CorrError("SOURCE.json não é um objeto")
    commit = obj.get("commit")
    expected_top = NEW_TOP_KEYS if commit == COMMIT_LABEL else OLD_TOP_KEYS
    if set(obj) != expected_top:
        raise CorrError("SOURCE.json tem campos de topo inesperados")
    files = obj["arquivos"]
    if not isinstance(files, dict) or set(files) != set(VERIFIED):
        raise CorrError("SOURCE.json: conjunto de arquivos inesperado")
    if commit == COMMIT_LABEL:
        if all(isinstance(files[n], dict) and files[n].get("commit") == VERIFIED[n]["commit"]
               for n in VERIFIED):
            return None
        raise CorrError("SOURCE.json: rótulo de commit já presente, mas os arquivos não batem")
    if not isinstance(commit, str) or not commit.startswith(UNREGISTERED_PREFIX):
        raise CorrError("o campo commit do SOURCE.json não é o esperado")
    new_files: dict[str, dict] = {}
    for name, ver in VERIFIED.items():
        info = files[name]
        if not isinstance(info, dict):
            raise CorrError(f"{name}: formato inválido")
        if info.get("original_bytes") != ver["original_bytes"]:
            raise CorrError(f"{name}: tamanho registrado não é o verificado")
        if info.get("original_sha3_256_bytes") != ver["original_sha3_256_bytes"]:
            raise CorrError(f"{name}: SHA3-256 registrado não é o verificado")
        if info.get("url") != URL_BASE + ver["caminho"]:
            raise CorrError(f"{name}: URL registrada não aponta para o caminho verificado")
        new_info: dict = {}
        for key, value in info.items():
            new_info[key] = value
            if key == "url":
                new_info["commit"] = ver["commit"]
                new_info["commit_data"] = ver["commit_data"]
        new_files[name] = new_info
    out = {
        "fonte": obj["fonte"],
        "branch": obj["branch"],
        "commit": COMMIT_LABEL,
        "baixado_em": obj["baixado_em"],
        "verificado_em": VERIFIED_EM,
        "metodo_verificacao": METODO,
        "master_consultado": MASTER_CONSULTADO,
        "arquivos": new_files,
    }
    text = json.dumps(out, indent=2, ensure_ascii=False) + "\n"
    if b"\r\n" in raw:
        text = text.replace("\n", "\r\n")
    return text.encode("utf-8")


def corrigir_projeto(text: str) -> str | None:
    """Troca a frase do commit no PROJECT.md (texto em LF). None se já trocada."""
    if NEW_SENTENCE in text:
        return None
    if text.count(OLD_SENTENCE) != 1:
        raise CorrError("a frase do commit não aparece exatamente uma vez no PROJECT.md")
    return text.replace(OLD_SENTENCE, NEW_SENTENCE, 1)


def _decode_project(raw: bytes) -> tuple[str, bool]:
    crlf = raw.count(b"\r\n")
    if crlf not in (0, raw.count(b"\n")):
        raise CorrError("o PROJECT.md mistura CRLF e LF")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CorrError("o PROJECT.md não é UTF-8") from exc
    return text.replace("\r\n", "\n"), crlf > 0


def build_parser() -> argparse.ArgumentParser:
    """Sem opções: corrige o SOURCE.json e a frase do PROJECT.md."""
    return argparse.ArgumentParser(
        prog="py -3.12 -m scripts.corrigir_source_kat_dia5",
        description="Registra os commits verificados dos vetores ACVP.")


def main(argv: Sequence[str] | None = None, *, _root: Path | None = None) -> int:
    """Ponto de entrada. ``_root`` existe só para testes."""
    build_parser().parse_args(argv)
    root = Path(_root) if _root is not None else PROJECT_ROOT
    source_path, project_path = root / SOURCE_REL, root / PROJECT_REL
    try:
        raw_source = source_path.read_bytes()
        raw_project = project_path.read_bytes()
        new_source = corrigir_source(raw_source)
        project_norm, project_crlf = _decode_project(raw_project)
        new_project_norm = corrigir_projeto(project_norm)
    except OSError as exc:
        print("erro: arquivo não encontrado ou ilegível", file=sys.stderr)
        print("nada foi gravado", file=sys.stderr)
        return 1
    except CorrError as exc:
        print(f"erro: {exc}", file=sys.stderr)
        print("nada foi gravado", file=sys.stderr)
        return 1
    # Só grava depois de conferir as duas partes.
    if new_source is not None:
        source_path.write_bytes(new_source)
    if new_project_norm is not None:
        text = new_project_norm.replace("\n", "\r\n") if project_crlf else new_project_norm
        project_path.write_bytes(text.encode("utf-8"))
    if new_source is None and new_project_norm is None:
        print("já estava corrigido; nada mudou")
    else:
        print("SOURCE.json: commits registrados" if new_source is not None
              else "SOURCE.json: já estava corrigido")
        print("PROJECT.md: frase do commit atualizada" if new_project_norm is not None
              else "PROJECT.md: frase já estava atualizada")
    return 0


if __name__ == "__main__":
    sys.exit(main())
