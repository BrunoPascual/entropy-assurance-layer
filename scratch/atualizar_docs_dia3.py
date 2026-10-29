"""Atualiza PROJECT.md e THREAT_MODEL.md com os α do Dia 3 (RCT 2^-40, APT 2^-20).

Uso, na raiz do projeto:
    py -3.12 scratch\\atualizar_docs_dia3.py            (só atualiza os documentos)
    py -3.12 scratch\\atualizar_docs_dia3.py --commit   (atualiza e faz o commit)

Regra: todos os trechos precisam aparecer exatamente uma vez. Se algum falhar,
nenhum arquivo é alterado.
"""
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path.cwd()

EDITS = {
    "PROJECT.md": [
        (
            "- Taxa de falso alarme por teste: `α = 2^-20`.",
            "- Taxa de falso alarme (α) por amostra no RCT e por janela no APT. "
            "Valores separados: RCT `α = 2^-40`, APT `α = 2^-20`.",
        ),
        (
            "- Exemplo: com `H = 1`, `C = 21`; com `H = 0,9`, `C = 24`.",
            "- Exemplo: com `H = 1`, `C = 41`; com `H = 0,9`, `C = 46` (α = 2^-40).",
        ),
        (
            "### 6.5 Estimativa de min-entropia",
            "**Justificativa dos α (medida, não suposta).** Num lote de 1.000.000 de bits "
            "há cerca de 500 mil sequências testadas pelo RCT. Com `α = 2^-20` e `H = 1` "
            "(`C = 21`), o falso alarme por lote fica perto de 38% mesmo para fonte justa, "
            "o que inviabiliza o gate. Com `α = 2^-40` (`C = 41`), fica perto de 5 × 10^-7 "
            "por lote e o RCT ainda pega o trecho travado de 64 bits. No APT, `α = 2^-20` "
            "dá cerca de 8 × 10^-4 de falso alarme por lote (976 janelas) e pega viés "
            "p = 0,55. Os dois valores ficam dentro da faixa 2^-40 a 2^-20 do SP 800-90B. "
            "Valores em `eal/config.py`.\n\n"
            "**Limitação do lote.** O APT só testa janelas completas de 1024 bits. "
            "Em 1.000.000 de bits, 576 bits ficam de fora e são registrados em "
            "`discarded_bits`.\n\n"
            "### 6.5 Estimativa de min-entropia",
        ),
    ],
    "THREAT_MODEL.md": [
        (
            "com taxa de falso alarme de cerca de `α = 2^-20` por teste, por desenho do teste",
            "com taxa de falso alarme `α = 2^-40` por amostra no RCT e `α = 2^-20` por janela "
            "no APT (cerca de 5 × 10^-7 e 8 × 10^-4 por lote de 1 milhão de bits), "
            "por desenho do teste",
        ),
    ],
}


def fail(msg: str) -> None:
    print(f"\nERRO: {msg}\nNenhum arquivo foi alterado.")
    sys.exit(1)


def plan_edits() -> dict[str, str]:
    """Lê todos os arquivos e aplica os trechos em memória. Aborta se algo não bater."""
    results = {}
    for filename, pairs in EDITS.items():
        path = ROOT / filename
        if not path.exists():
            fail(f"{filename} não encontrado na raiz do projeto")
        text = path.read_text(encoding="utf-8")
        for old, new in pairs:
            count = text.count(old)
            if count != 1:
                fail(
                    f"em {filename}, o trecho apareceu {count} vez(es), esperado 1:\n"
                    f"  {old[:80]}..."
                )
            text = text.replace(old, new)
        results[filename] = text
    return results


def write_all(results: dict[str, str]) -> None:
    for filename, text in results.items():
        path = ROOT / filename
        shutil.copy2(path, path.with_name(path.name + ".bak"))
        path.write_text(text, encoding="utf-8")
        print(f"  {filename} atualizado (backup: {filename}.bak)")


def commit() -> None:
    files = ["PROJECT.md", "THREAT_MODEL.md"]
    subprocess.run(["git", "add", *files], check=True)
    subprocess.run(
        ["git", "commit", "-m", "Docs Dia 3: α separados (RCT 2^-40, APT 2^-20) e justificativa"],
        check=True,
    )
    print("  commit feito")


def main() -> None:
    print("1. Verificando trechos nos documentos...")
    results = plan_edits()
    print("2. Gravando...")
    write_all(results)
    if "--commit" in sys.argv:
        print("3. Commit...")
        commit()
    else:
        print("\nPara fazer o commit, rode o script com --commit.")
        print("Ou manualmente: git add PROJECT.md THREAT_MODEL.md && git commit -m \"Docs Dia 3\"")


if __name__ == "__main__":
    main()