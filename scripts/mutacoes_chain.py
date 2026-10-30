"""Mutações manuais do log encadeado (Dia 5, etapa 3).

Cada mutação troca UM trecho de eal/receipt/chain.py por uma versão errada, roda
os testes da cadeia e espera que algum falhe ("morta"). Mutação que sobrevive
significa teste faltando: NÃO ajustar este script para esconder a sobrevivente.

Regras: cada trecho original deve aparecer exatamente uma vez (checado antes de
rodar qualquer coisa); o arquivo é restaurado sempre no ``finally`` e conferido
byte a byte no fim. Isto mostra que os testes pegam estes erros, não que o
módulo esteja correto.

Uso (na raiz do projeto):  py -3.12 -m scripts.mutacoes_chain
         só os testes unitários:  py -3.12 -m scripts.mutacoes_chain --so-unitarios
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "eal" / "receipt" / "chain.py"
UNIT = "tests/test_receipt_chain.py"
INTEGRATION = "tests/test_receipt_chain_pipeline.py"

# (nome, trecho original, trecho mutado)
MUTATIONS: list[tuple[str, str, str]] = [
    ("pk: tamanho == vira >=",
     "return isinstance(issuer_pk, bytes) and len(issuer_pk) == DSA_PK_BYTES",
     "return isinstance(issuer_pk, bytes) and len(issuer_pk) >= DSA_PK_BYTES"),
    ("pk: sem checar o tipo",
     "return isinstance(issuer_pk, bytes) and len(issuer_pk) == DSA_PK_BYTES",
     "return len(issuer_pk) == DSA_PK_BYTES"),
    ("log ausente deixa de ser vazio",
     'return log.read_bytes() if log.exists() else b""',
     "return log.read_bytes() if log.exists() else None"),
    ("split: log vazio vira uma linha vazia",
     "    if not data:\n        return []\n    parts",
     "    parts"),
    ("split: descarta a última linha sem \\n",
     'return parts[:-1] if data.endswith(b"\\n") else parts',
     "return parts[:-1]"),
    ("split: guarda a linha vazia depois do último \\n",
     'return parts[:-1] if data.endswith(b"\\n") else parts',
     "return parts"),
    ("linha vazia não é detectada",
     '    if raw == b"":\n        return None, [f"linha {n}: vazia"]',
     '    if raw == b"\\x00":\n        return None, [f"linha {n}: vazia"]'),
    ("JSON inválido sem motivo",
     'return None, [f"linha {n}: JSON inválido"]',
     "return None, []"),
    ("canônico: comparação invertida",
     "if canonical_bytes(receipt) != raw:",
     "if canonical_bytes(receipt) == raw:"),
    ("canônico: checagem removida",
     "if canonical_bytes(receipt) != raw:",
     "if False:"),
    ("scan: verificação do recibo invertida",
     "    if not verdict.ok:\n        reasons.append(",
     "    if verdict.ok:\n        reasons.append("),
    ("scan: id repetido nunca detectado",
     '        if rid in seen:\n            reasons.append(f"linha {n}: receipt_id repetido")',
     '        if rid in set():\n            reasons.append(f"linha {n}: receipt_id repetido")'),
    ("scan: não registra o id visto",
     "        seen.add(rid)\n    seed_hash",
     "        pass\n    seed_hash"),
    ("scan: id == uuid5 vira !=",
     "rid == receipt_id_for(seed_hash)",
     "rid != receipt_id_for(seed_hash)"),
    ("scan: id != uuid5 sem motivo",
     '        reasons.append(f"linha {n}: receipt_id não corresponde ao seed_hash")',
     "        pass"),
    ("scan: gênese errada",
     "    expected_prev: str | None = GENESIS_PREV_HASH",
     '    expected_prev: str | None = "1" * 64'),
    ("scan: elo == em vez de !=",
     'receipt.get("prev_receipt_hash") != expected_prev:',
     'receipt.get("prev_receipt_hash") == expected_prev:'),
    ("scan: elo checado mesmo após linha ruim (cascata)",
     'if expected_prev is not None and receipt.get("prev_receipt_hash") != expected_prev:',
     'if receipt.get("prev_receipt_hash") != expected_prev:'),
    ("scan: não zera o elo após linha ruim",
     "            expected_prev = None  # o elo seguinte",
     "            pass  # o elo seguinte"),
    ("scan: linha boa não vai para a lista de arquivos",
     '        entries.append((n, raw, receipt.get("receipt_id")))',
     "        pass"),
    ("scan: hash do elo sem a assinatura",
     "head = expected_prev = receipt_hash(receipt)",
     'head = expected_prev = receipt_hash({k: v for k, v in receipt.items() if k != "signature"})'),
    ("arquivos: não pula id fora do UUID",
     "        if not _is_uuid(rid):\n            continue",
     "        if False:\n            continue"),
    ("arquivos: ausente vira presente",
     "            if not path.is_file():",
     "            if path.is_file():"),
    ("arquivos: compara sem o \\n final",
     'elif path.read_bytes() != raw + b"\\n":',
     "elif path.read_bytes() != raw:"),
    ("arquivos: sobrando = os que têm linha",
     "if p.stem not in ids]",
     "if p.stem in ids]"),
    ("arquivos: sobrando nunca acusado",
     "    if strays:\n",
     "    if not strays:\n"),
    ("arquivos: glob pega tudo",
     'directory.glob("*.json")',
     'directory.glob("*")'),
    ("verify: pasta inexistente aceita",
     '    if not directory.is_dir():\n        return ChainResult(False, ("pasta do log não existe",)',
     '    if False:\n        return ChainResult(False, ("pasta do log não existe",)'),
    ("verify: erro de leitura ignorado",
     '    if data is None:\n        return ChainResult(False, ("não foi possível ler o log",)',
     '    if False:\n        return ChainResult(False, ("não foi possível ler o log",)'),
    ("verify: sem checar \\n final",
     '    if data and not data.endswith(b"\\n"):\n        reasons.append("última linha sem quebra de linha")',
     '    if False:\n        reasons.append("última linha sem quebra de linha")'),
    ("verify: expected_head por verdade em vez de None",
     "    if expected_head is not None and not (is_hex64(expected_head) and expected_head == head):",
     "    if expected_head and not (is_hex64(expected_head) and expected_head == head):"),
    ("verify: expected_head == vira !=",
     "expected_head == head):",
     "expected_head != head):"),
    ("verify: length conta só linhas boas",
     "len(lines), head)",
     "len(entries), head)"),
    ("chain_head: aceita log inválido",
     '    if not res.ok:\n        raise ChainError(f"cadeia existente inválida ({len(res.reasons)} problema(s))")\n    return res.head',
     '    if False:\n        raise ChainError(f"cadeia existente inválida ({len(res.reasons)} problema(s))")\n    return res.head'),
    ("ids do log sempre vazios",
     '    return {r["receipt_id"] for r in found if r and isinstance(r.get("receipt_id"), str)}',
     "    return set()"),
    ("escrita: sem flush antes do fsync",
     "        fh.flush()\n        os.fsync",
     "        os.fsync"),
    ("escrita: sem fsync",
     "        os.fsync(fh.fileno())\n",
     "        pass\n"),
    ("append: chave inválida não checada",
     '    if not _pk_ok(issuer_pk):\n        raise ChainError("chave pública do emissor inválida")',
     '    if False:\n        raise ChainError("chave pública do emissor inválida")'),
    ("append: não verifica a cadeia existente",
     "    if directory.exists():\n        res = verify_chain",
     "    if False:\n        res = verify_chain"),
    ("append: cabeça sempre gênese",
     "        head, seen = res.head, _logged_ids(directory)",
     "        head, seen = GENESIS_PREV_HASH, set()"),
    ("append: recibo inválido aceito",
     "    if not verdict.ok:\n        raise ChainError",
     "    if False:\n        raise ChainError"),
    ("append: prev == em vez de !=",
     '    if receipt["prev_receipt_hash"] != head:',
     '    if receipt["prev_receipt_hash"] == head:'),
    ("append: prev não checado",
     '    if receipt["prev_receipt_hash"] != head:',
     "    if False:"),
    ("append: id != uuid5 aceito",
     '    if rid != receipt_id_for(receipt["seed_hash"]):',
     "    if False:"),
    ("append: id repetido aceito",
     '    if rid in seen:\n        raise ChainError("receipt_id repetido")',
     '    if False:\n        raise ChainError("receipt_id repetido")'),
    ("append: arquivo existente não checado",
     '    if path.exists():\n        raise ChainError("arquivo individual já existe")',
     '    if False:\n        raise ChainError("arquivo individual já existe")'),
    ("append: não cria a pasta",
     "    directory.mkdir(parents=True, exist_ok=True)\n",
     ""),
    ("append: cria a pasta antes de validar",
     "    head, seen = GENESIS_PREV_HASH, set()\n    if directory.exists():",
     "    directory.mkdir(parents=True, exist_ok=True)\n    head, seen = GENESIS_PREV_HASH, set()\n    if directory.exists():"),
    ("append: arquivo individual antes da linha",
     '    _fsynced_write(directory / RECEIPT_CHAIN_NAME, "ab", line)\n    try:\n        _write_individual(path, line)\n'
     '    except OSError:\n        raise ChainError("linha gravada no log, mas o arquivo individual falhou") from None',
     '    _write_individual(path, line)\n    _fsynced_write(directory / RECEIPT_CHAIN_NAME, "ab", line)'),
    ("append: log sobrescrito (wb)",
     '"ab", line)',
     '"wb", line)'),
    ("individual: sobrescreve (wb em vez de xb)",
     '    _fsynced_write(path, "xb", data)',
     '    _fsynced_write(path, "wb", data)'),
    ("append: linha sem \\n",
     '    line = canonical_bytes(receipt) + b"\\n"',
     "    line = canonical_bytes(receipt)"),
    ("append: arquivo individual sem \\n",
     "        _write_individual(path, line)\n    except OSError:",
     '        _write_individual(path, line.rstrip(b"\\n"))\n    except OSError:'),
    ("append: falha do arquivo individual vaza OSError",
     '    except OSError:\n        raise ChainError("linha gravada',
     '    except KeyError:\n        raise ChainError("linha gravada'),
    ("append: devolve o caminho errado",
     "    return path\n",
     "    return directory / RECEIPT_CHAIN_NAME\n"),
]


def _run_tests(unit_only: bool) -> tuple[bool, str]:
    """True se algum teste falhou (mutação morta)."""
    files = [UNIT] if unit_only else [UNIT, INTEGRATION]
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    proc = subprocess.run(
        [sys.executable, "-B", "-m", "pytest", "-x", "-q", "-p", "no:cacheprovider", *files],
        cwd=ROOT, env=env, capture_output=True, text=True,
    )
    tail = (proc.stdout.strip().splitlines() or [""])[-1]
    return proc.returncode != 0, tail


def _prepare(original: bytes) -> list[tuple[str, str, str]]:
    """Confere que cada trecho aparece exatamente uma vez; ajusta a quebra de linha ao arquivo."""
    crlf = b"\r\n" in original
    text = original.decode("utf-8")
    prepared, problems = [], []
    for name, old, new in MUTATIONS:
        if crlf:
            old, new = old.replace("\n", "\r\n"), new.replace("\n", "\r\n")
        n = text.count(old)
        if n != 1:
            problems.append(f"{name}: trecho aparece {n} vez(es), esperado 1")
        prepared.append((name, old, new))
    if problems:
        sys.exit("ABORTADO, nada foi mutado:\n  " + "\n  ".join(problems))
    return prepared


def main() -> int:
    unit_only = "--so-unitarios" in sys.argv
    original = TARGET.read_bytes()
    prepared = _prepare(original)
    text = original.decode("utf-8")
    survivors: list[str] = []
    print(f"{len(prepared)} mutações; testes: {'só unitários' if unit_only else 'unitários + integração'}")
    try:
        for i, (name, old, new) in enumerate(prepared, start=1):
            TARGET.write_bytes(text.replace(old, new, 1).encode("utf-8"))
            t0 = time.time()
            killed, tail = _run_tests(unit_only)
            print(f"[{i:02d}/{len(prepared)}] {'morta     ' if killed else 'SOBREVIVEU'} {name}  ({time.time() - t0:.1f}s)")
            if not killed:
                survivors.append(name)
    finally:
        TARGET.write_bytes(original)
    restored = TARGET.read_bytes() == original
    print(f"\nrestaurado byte a byte: {'sim' if restored else 'NAO, conferir com git diff'}")
    print(f"mortas: {len(prepared) - len(survivors)} de {len(prepared)}")
    for s in survivors:
        print(f"  SOBREVIVENTE: {s}")
    return 0 if (restored and not survivors) else 1


if __name__ == "__main__":
    raise SystemExit(main())
