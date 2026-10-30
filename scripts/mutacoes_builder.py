"""Mutações manuais do construtor do recibo (Dia 5, etapa 2B).

Mesmo método do scripts/mutacoes_receipt.py: uma mutação por vez, testes de
tests/test_receipt_builder.py, restauração byte a byte no finally.

Uso, a partir da raiz do projeto:  py -3.12 -m scripts.mutacoes_builder
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

TESTS = "tests/test_receipt_builder.py"
BUILDER = Path("eal/receipt/builder.py")
SEP = " ||| "

# (nome, arquivo, trecho original, trecho mutado). Cada trecho deve aparecer 1 vez no arquivo.
# Uma mutação pode ter vários pares: use " ||| " para separar (aplicados juntos).
MUTATIONS: list[tuple[str, Path, str, str]] = [
    ("B01 não confere as chaves com a semente", BUILDER, "if given != expected:", "if False:"),
    ("B02 aceita modo diferente de keygen", BUILDER,
     'if getattr(result, "mode", None) != KEYGEN_MODE:', "if False:"),
    ("B03 aceita execução sem semente", BUILDER,
     'if getattr(result, "mix", None) is None or getattr(result, "error", None) is not None:', "if False:"),
    ("B04 não confere flags do lote com a fonte", BUILDER,
     'if (_strict_bool(mi.is_local, "is_local do lote") != is_local', "if (False"),
    ("B05 não confere batch_id", BUILDER, "if mi.batch_id != outcome.batch_id:", "if False:"),
    ("B06 aceita misturada sem Toeplitz", BUILDER,
     "if outcome.status == MIXED_STATUS and mi.extraction.extractor_type != RECEIPT_EXTRACTOR_TYPE:", "if False:"),
    ("B07 flag aceita inteiro", BUILDER,
     "    if isinstance(value, (bool, np.bool_)):\n        return bool(value)\n    raise",
     "    if isinstance(value, (bool, np.bool_, int)):\n        return bool(value)\n    raise"),
    ("B08 to_native aceita bytes", BUILDER,
     'raise TypeError(f"tipo não permitido no recibo: {type(value).__name__}")', "return repr(value)"),
    ("B09 to_native aceita NaN", BUILDER, "if not math.isfinite(f):", "if False:"),
    ("B10 não confere seed_hash do mixer", BUILDER,
     'if mix_meta.get("seed_hash") != result.mix.seed_hash:', "if False:"),
    ("B11 emissor sem separação de domínio", BUILDER,
     "hashlib.shake_256(ISSUER_DOMAIN + mix.seed)", "hashlib.shake_256(mix.seed)"),
    ("B12 emissor sem validar o mix", BUILDER,
     "derive_keys_from_mix(mix)  # mesma validação", "pass  # mesma validação"),
    ("B13 fonte repetida aceita", BUILDER, "if sid in out:", "if False:"),
    ("B14 resultado sem objeto de fonte ignorado", BUILDER,
     'raise ValueError("resultado de fonte sem objeto Source correspondente")', "continue"),
    ("B15 receipt_id aleatório", BUILDER,
     "uuid.uuid5(uuid.UUID(RECEIPT_ID_NAMESPACE), seed_hash)", "uuid.uuid4()"),
    ("B16 approved sempre verdadeiro", BUILDER,
     'entry["approved"] = _strict_bool(mi.report.approved, "approved do relatório")',
     'entry["approved"] = True'),
    ("B17 batch_hash errado", BUILDER, 'entry["batch_hash"] = mi.input_hash', 'entry["batch_hash"] = mi.batch_id'),
    ("B18 saúde não registrada", BUILDER,
     'entry["health"] = to_native(mi.report.to_dict())', 'entry["health"] = None'),
    ("B19 keys sem checagem de tipo", BUILDER, "if not isinstance(keys, DerivedKeys):", "if False:"),
]


def run_tests() -> tuple[bool, str]:
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", TESTS, "-q", "-x", "-p", "no:cacheprovider"],
        capture_output=True, text=True,
    )
    lines = [x for x in proc.stdout.splitlines() if x.strip()]
    return proc.returncode == 0, (lines[-1] if lines else "(sem saída)")


def main() -> int:
    originals = {p: p.read_bytes() for p in {m[1] for m in MUTATIONS}}
    texts = {p: b.decode("utf-8") for p, b in originals.items()}
    for name, path, olds, _ in MUTATIONS:
        for old in olds.split(SEP):
            # No Windows o arquivo pode ter CRLF: o trecho é procurado nas duas formas.
            n = texts[path].count(old) + (texts[path].count(old.replace("\n", "\r\n")) if "\n" in old else 0)
            if n != 1:
                print(f"ERRO: padrão de {name!r} aparece {n} vezes em {path} (esperado 1)")
                return 2
    ok, resumo = run_tests()
    print(f"Controle (original): {'verde' if ok else 'VERMELHO'} | {resumo}")
    if not ok:
        return 2
    survivors: list[str] = []
    try:
        for name, path, olds, news in MUTATIONS:
            text = texts[path]
            for old, new in zip(olds.split(SEP), news.split(SEP), strict=True):
                if old not in text:
                    old, new = old.replace("\n", "\r\n"), new.replace("\n", "\r\n")
                text = text.replace(old, new)
            path.write_bytes(text.encode("utf-8"))
            passed, resumo = run_tests()
            path.write_bytes(originals[path])
            print(f"{name}: {'SOBREVIVEU' if passed else 'morta'} | {resumo}")
            if passed:
                survivors.append(name)
    finally:
        for p, b in originals.items():
            p.write_bytes(b)
    restored = all(p.read_bytes() == b for p, b in originals.items())
    print(f"Arquivos restaurados byte a byte: {restored}")
    print(f"Mutações: {len(MUTATIONS)}; mortas: {len(MUTATIONS) - len(survivors)}; "
          f"sobreviventes: {len(survivors)}")
    for s in survivors:
        print(f"  SOBREVIVENTE: {s}")
    return 0 if restored and not survivors else 1


if __name__ == "__main__":
    raise SystemExit(main())
