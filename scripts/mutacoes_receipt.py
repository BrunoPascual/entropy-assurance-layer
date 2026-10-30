"""Mutações manuais do núcleo do recibo (Dia 5, etapa 2A).

Mesmo método do scripts/mutacoes_pqc.py: uma mutação por vez, testes de
tests/test_receipt_core.py, restauração byte a byte no finally.

Uso, a partir da raiz do projeto:  py -3.12 -m scripts.mutacoes_receipt
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

TESTS = "tests/test_receipt_core.py"
SCHEMA = Path("eal/receipt/schema.py")
SIGN = Path("eal/receipt/sign.py")
VERIFY = Path("eal/receipt/verify.py")
SEP = " ||| "

# (nome, arquivo, trecho original, trecho mutado). Cada trecho deve aparecer 1 vez no arquivo.
# Uma mutação pode ter vários pares: use " ||| " para separar (aplicados juntos).
MUTATIONS: list[tuple[str, Path, str, str]] = [
    ("R01 canônico sem ordenar chaves", SCHEMA, "sort_keys=True", "sort_keys=False"),
    ("R02 canônico aceita NaN", SCHEMA, "allow_nan=False", "allow_nan=True"),
    ("R03 campos desconhecidos aceitos", SCHEMA,
     'problems.append(f"campos desconhecidos: {sorted(map(str, extra))}")', "pass"),
    ("R04 modo experiment aceito", SCHEMA,
     'body["mode"] == KEYGEN_MODE', 'body["mode"] in (KEYGEN_MODE, "experiment")'),
    ("R05 UUID sem forma canônica", SCHEMA,
     "return str(uuid.UUID(value)) == value", "return bool(uuid.UUID(value))"),
    ("R06 data aceita qualquer fuso", SCHEMA,
     "return parsed.utcoffset() == timedelta(0)", "return True"),
    ("R07 hash aceita maiúsculas", SCHEMA,
     '_HEX64 = re.compile(r"[0-9a-f]{64}")', '_HEX64 = re.compile(r"[0-9a-fA-F]{64}")'),
    ("R08 limitações obrigatórias ignoradas", SCHEMA,
     'return [f"limitations sem itens obrigatórios: {absent}"] if absent else []', "return []"),
    ("R09 flags aceitam inteiro", SCHEMA,
     "if type(src[flag]) is not bool:", "if not isinstance(src[flag], (bool, int)):"),
    ("R10 fonte simulada aceita", SCHEMA,
     'problems.append("fonte simulada em recibo keygen")', "pass"),
    ("R11 sem exigência de fonte local", SCHEMA,
     'problems.append("nenhuma fonte local, não simulada e aprovada na mistura")', "pass"),
    ("R12 source_id repetido aceito", SCHEMA, "elif sid in seen:", "elif False:"),
    ("R13 hash do recibo sem a assinatura", SCHEMA,
     "return hashlib.sha3_256(canonical_bytes(receipt)).hexdigest()",
     "return hashlib.sha3_256(canonical_bytes(receipt_body(receipt))).hexdigest()"),
    ("R14 assinatura sem contexto", SIGN,
     "sig = ML_DSA_65.sign(key.sk, message, ctx=RECEIPT_CTX, deterministic=True)",
     "sig = ML_DSA_65.sign(key.sk, message, deterministic=True)"),
    ("R15 assina corpo inválido", SIGN, "    if problems:\n", "    if False:\n"),
    ("R16 assina sem copiar (altera o original)", SIGN,
     "signed = copy.deepcopy(body)", "signed = body"),
    ("R17 salvar sobrescreve (sem checagem e sem modo x)", SIGN,
     'if sk_path.exists() or pk_path.exists(): ||| with open(path, "x", encoding="ascii") as f:',
     'if False: ||| with open(path, "w", encoding="ascii") as f:'),
    ("R18 carregar não confere o par", SIGN,
     "if not ML_DSA_65.verify(pk, _PAIR_PROBE, probe, ctx=RECEIPT_CTX):", "if False:"),
    ("R19 verificação sem contexto", VERIFY,
     "return bool(ML_DSA_65.verify(pk, message, sig, ctx=RECEIPT_CTX))",
     "return bool(ML_DSA_65.verify(pk, message, sig))"),
    ("R20 não confere o emissor", VERIFY,
     "if not (is_hex64(pk_hash) and hmac.compare_digest(pk_hash, expected)):", "if False:"),
    ("R21 não confere o algoritmo", VERIFY,
     'if block["alg"] != RECEIPT_SIG_ALG:', "if False:"),
    ("R22 base64 sem validação estrita", VERIFY,
     "base64.b64decode(value, validate=True)", "base64.b64decode(value)"),
    ("R23 verifica sem validar o corpo", VERIFY,
     "reasons += validate_body(body)", "pass"),
    ("R24 aceita chave repetida no JSON", VERIFY,
     "if len(keys) != len(set(keys)):", "if False:"),
    ("R25 aceita NaN no JSON", VERIFY,
     'raise ValueError(f"JSON com constante não permitida: {name}")', "return float(name)"),
    ("R26 assinatura sobre o recibo inteiro", VERIFY,
     "message = canonical_bytes(body)", "message = canonical_bytes(receipt)"),
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
