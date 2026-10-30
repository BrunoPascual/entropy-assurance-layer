"""Baixa os vetores oficiais de keyGen do NIST ACVP e grava só os grupos usados.

Fonte: https://github.com/usnistgov/ACVP-Server (gen-val/json-files, branch master).
Grava em tests/data/kat/: ml_kem_768_keygen.json, ml_dsa_65_keygen.json e SOURCE.json
(procedência e hashes). O hash do conteúdo é calculado sobre o JSON canônico
(chaves ordenadas, sem espaços), para não depender de quebra de linha (CRLF).

Uso, a partir da raiz do projeto:  py -3.12 -m scripts.baixar_kat_pqc
"""
from __future__ import annotations

import datetime
import hashlib
import json
import urllib.request
from pathlib import Path

BASE = "https://raw.githubusercontent.com/usnistgov/ACVP-Server/master/gen-val/json-files"
OUT = Path("tests/data/kat")
TARGETS = [
    # (pasta no ACVP, parameterSet, arquivo de saída)
    ("ML-KEM-keyGen-FIPS203", "ML-KEM-768", "ml_kem_768_keygen.json"),
    ("ML-DSA-keyGen-FIPS204", "ML-DSA-65", "ml_dsa_65_keygen.json"),
]


def canonical_hash(data: object) -> str:
    """SHA3-256 do JSON canônico (independe de quebra de linha)."""
    text = json.dumps(data, sort_keys=True, separators=(",", ":"))
    return hashlib.sha3_256(text.encode("utf-8")).hexdigest()


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    meta: dict[str, object] = {
        "fonte": "https://github.com/usnistgov/ACVP-Server (gen-val/json-files)",
        "branch": "master",
        "commit": "não registrado (a API do GitHub estava com limite de requisições)",
        "baixado_em": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "arquivos": {},
    }
    for folder, param_set, out_name in TARGETS:
        url = f"{BASE}/{folder}/internalProjection.json"
        with urllib.request.urlopen(url, timeout=60) as resp:
            raw = resp.read()
        full = json.loads(raw)
        groups = [g for g in full["testGroups"] if g["parameterSet"] == param_set]
        if len(groups) != 1:
            raise SystemExit(f"{param_set}: esperado 1 grupo, achei {len(groups)}")
        subset = {
            "vsId": full["vsId"], "algorithm": full["algorithm"],
            "mode": full["mode"], "revision": full["revision"],
            "isSample": full["isSample"], "testGroups": groups,
        }
        (OUT / out_name).write_text(json.dumps(subset, separators=(",", ":")), encoding="utf-8")
        meta["arquivos"][out_name] = {  # type: ignore[index]
            "url": url,
            "parameterSet": param_set,
            "vsId": full["vsId"],
            "testes": len(groups[0]["tests"]),
            "original_bytes": len(raw),
            "original_sha3_256_bytes": hashlib.sha3_256(raw).hexdigest(),
            "subconjunto_sha3_256_canonico": canonical_hash(subset),
        }
        print(f"{out_name}: {len(groups[0]['tests'])} vetores")
    (OUT / "SOURCE.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    print("SOURCE.json gravado")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
