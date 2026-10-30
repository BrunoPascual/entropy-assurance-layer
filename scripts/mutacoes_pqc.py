"""Mutações manuais do eal/pqc/keygen.py (Dia 5, etapa 1, passo 4).

Aplica uma mutação por vez numa cópia em memória do módulo, roda
tests/test_pqc_keygen.py e espera que pelo menos um teste fique vermelho.
O arquivo original é restaurado sempre (finally) e conferido byte a byte.

Uso, a partir da raiz do projeto:  py -3.12 -m scripts.mutacoes_pqc
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

TARGET = Path("eal/pqc/keygen.py")
TESTS = "tests/test_pqc_keygen.py"

# (nome, trecho original, trecho mutado). Cada trecho original deve aparecer 1 vez.
MUTATIONS: list[tuple[str, str, str]] = [
    ("M01 KEM: SHA3-512 no lugar de SHAKE256",
     "hashlib.shake_256(KEM_DOMAIN + seed).digest(KEM_SEED_BYTES)",
     "hashlib.sha3_512(KEM_DOMAIN + seed).digest()"),
    ("M02 DSA: SHA3-256 no lugar de SHAKE256",
     "hashlib.shake_256(DSA_DOMAIN + seed).digest(DSA_SEED_BYTES)",
     "hashlib.sha3_256(DSA_DOMAIN + seed).digest()"),
    ("M03 KEM: ordem z||d no lugar de d||z",
     "kem_material = hashlib.shake_256(KEM_DOMAIN + seed).digest(KEM_SEED_BYTES)",
     "kem_material = hashlib.shake_256(KEM_DOMAIN + seed).digest(KEM_SEED_BYTES); "
     "kem_material = kem_material[32:] + kem_material[:32]"),
    ("M04 KEM: sem prefixo de domínio",
     "shake_256(KEM_DOMAIN + seed)", "shake_256(seed)"),
    ("M05 DSA: sem prefixo de domínio",
     "shake_256(DSA_DOMAIN + seed)", "shake_256(seed)"),
    ("M06 KEM com o prefixo do DSA",
     "shake_256(KEM_DOMAIN + seed)", "shake_256(DSA_DOMAIN + seed)"),
    ("M07 KEM com 32 bytes em vez de 64",
     "digest(KEM_SEED_BYTES)", "digest(32)"),
    ("M08 mix: sem checagem de seed_hash",
     "if not hmac.compare_digest(expected, seed_hash):", "if False:"),
    ("M09 mix: aceita modo experiment",
     "mode == KEYGEN_MODE", "mode in (KEYGEN_MODE, 'experiment')"),
    ("M10 mix: flag usable_for_key aceita qualquer valor verdadeiro",
     "    return False", "    return bool(value)"),
    ("M11 semente: aceita bytearray",
     "isinstance(seed, bytes)", "isinstance(seed, (bytes, bytearray))"),
    ("M12 repr vaza a chave privada do KEM",
     "kem_dk: bytes = field(repr=False)", "kem_dk: bytes"),
    ("M13 repr vaza a chave privada do DSA",
     "dsa_sk: bytes = field(repr=False)", "dsa_sk: bytes"),
    ("M14 resumo público com hash da chave privada do KEM",
     "hashlib.sha3_256(self.kem_ek).hexdigest()",
     "hashlib.sha3_256(self.kem_dk).hexdigest()"),
]


def run_tests() -> tuple[bool, str]:
    """Roda os testes; devolve (todos_passaram, última linha do resumo)."""
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", TESTS, "-q", "-x", "-p", "no:cacheprovider"],
        capture_output=True, text=True,
    )
    lines = [x for x in proc.stdout.splitlines() if x.strip()]
    return proc.returncode == 0, (lines[-1] if lines else "(sem saída)")


def main() -> int:
    original = TARGET.read_bytes()
    text = original.decode("utf-8")
    # Pré-checagem: todos os padrões existem exatamente uma vez.
    for name, old, _ in MUTATIONS:
        if text.count(old) != 1:
            print(f"ERRO: padrão de {name!r} aparece {text.count(old)} vezes (esperado 1)")
            return 2
    ok, resumo = run_tests()
    print(f"Controle (original): {'verde' if ok else 'VERMELHO'} | {resumo}")
    if not ok:
        print("A suíte precisa estar verde antes das mutações.")
        return 2

    survivors: list[str] = []
    try:
        for name, old, new in MUTATIONS:
            TARGET.write_bytes(text.replace(old, new).encode("utf-8"))
            passed, resumo = run_tests()
            verdict = "SOBREVIVEU" if passed else "morta"
            print(f"{name}: {verdict} | {resumo}")
            if passed:
                survivors.append(name)
    finally:
        TARGET.write_bytes(original)
    restored = TARGET.read_bytes() == original
    print(f"Arquivo restaurado byte a byte: {restored}")
    print(f"Mutações: {len(MUTATIONS)}; mortas: {len(MUTATIONS) - len(survivors)}; "
          f"sobreviventes: {len(survivors)}")
    for s in survivors:
        print(f"  SOBREVIVENTE: {s}")
    return 0 if restored and not survivors else 1


if __name__ == "__main__":
    raise SystemExit(main())
