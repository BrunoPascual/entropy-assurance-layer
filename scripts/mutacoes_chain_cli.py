"""Mutações manuais da linha de comando (Dia 5, etapa 4).

Cada mutação troca UM trecho de eal/cli.py por uma versão errada, roda os testes
da CLI e espera que algum falhe ("morta"). Mutação que sobrevive significa teste
faltando: NÃO ajustar este script para esconder a sobrevivente.

Regras: cada trecho original deve aparecer exatamente uma vez (checado antes de
rodar qualquer coisa); o arquivo é restaurado sempre no ``finally`` e conferido
byte a byte no fim. Isto mostra que os testes pegam estes erros, não que o
módulo esteja correto.

Uso (na raiz do projeto):  py -3.12 -m scripts.mutacoes_chain_cli
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "eal" / "cli.py"
TESTS = "tests/test_cli.py"

# (nome, trecho original, trecho mutado)
MUTATIONS: list[tuple[str, str, str]] = [
    ("bits: zero passa a valer", "    if bits <= 0:", "    if bits < 0:"),
    ("sources: 'os' deixa de ser aceita", '    if names == ["os"]:', '    if names == ["os", "os"]:'),
    ("sources: qpu_sim deixa de ser reconhecida como simulada",
     'n.startswith(("qpu_sim", "faulty"))', 'n.startswith(("faulty",))'),
    ("sources: IBM deixa de ser reconhecida",
     'n.startswith(("ibm", "qpu_ibm"))', 'n.startswith(("qpu_ibm",))'),
    ("console: errors=strict em vez de replace", 'reconfigure(errors="replace")', 'reconfigure(errors="strict")'),
    ("console: não configura os fluxos",
     "    _configure_streams()\n    try:\n        args = _build_parser()",
     "    try:\n        args = _build_parser()"),
    ("log: ok=True", '"stage": fail.stage, "ok": False,', '"stage": fail.stage, "ok": True,'),
    ("log: não cria a pasta", "        logs_dir.mkdir(parents=True, exist_ok=True)\n", ""),
    ("log: sobrescreve em vez de acrescentar",
     'with open(logs_dir / RUN_LOG_NAME, "ab") as fh:', 'with open(logs_dir / RUN_LOG_NAME, "wb") as fh:'),
    ("log: sem plano B para pipeline não serializável",
     '            line = json.dumps({**record, "pipeline": None}, ensure_ascii=False, sort_keys=True)',
     "            raise"),
    ("log: falha ao gravar não avisa", '        _err("aviso: não foi possível gravar o log de falhas")', "        pass"),
    ("keygen: lista de fontes vazia vira os",
     "srcs = list(sources) if sources is not None else [OsSource()]",
     "srcs = list(sources) if sources else [OsSource()]"),
    ("keygen: modo experiment em vez de keygen",
     'result = run_pipeline(srcs, seed, mode="keygen", n_bits=n_bits)',
     'result = run_pipeline(srcs, seed, mode="experiment", n_bits=n_bits)'),
    ("keygen: fail-closed invertido",
     "    if result.mix is None:\n        ids =", "    if result.mix is not None:\n        ids ="),
    ("keygen: pipeline fora do log",
     'raise _Fail("pipeline", "\\n".join(lines), pipeline=result.to_dict())',
     'raise _Fail("pipeline", "\\n".join(lines), pipeline=None)'),
    ("init: recusa só se as DUAS chaves existirem", "    if sk.exists() or pk.exists():", "    if sk.exists() and pk.exists():"),
    ("init: emissor não deriva do mix keygen",
     "key = issuer_key_from_seed(issuer_seed_from_mix(result.mix))",
     "key = issuer_key_from_seed(result.mix.seed[:32])"),
    ("init: não cria a pasta das chaves",
     "    args.keys_dir.mkdir(parents=True, exist_ok=True)\n    save_issuer_key", "    save_issuer_key"),
    ("run: basta uma das chaves para seguir",
     "    if not (sk.exists() and pk.exists()):", "    if not (sk.exists() or pk.exists()):"),
    ("run: chave ilegível escapa como erro inesperado",
     '    except (OSError, ValueError):\n        raise _Fail("issuer_key", "chave do emissor ilegível',
     '    except KeyError:\n        raise _Fail("issuer_key", "chave do emissor ilegível'),
    ("chaves públicas: sobrescreve",
     '    folder.mkdir(parents=True, exist_ok=False)\n    for name, raw in ((PUBLIC_KEM_NAME, keys.kem_ek), (PUBLIC_DSA_NAME, keys.dsa_pk)):\n        with open(folder / name, "xb") as fh:',
     '    folder.mkdir(parents=True, exist_ok=True)\n    for name, raw in ((PUBLIC_KEM_NAME, keys.kem_ek), (PUBLIC_DSA_NAME, keys.dsa_pk)):\n        with open(folder / name, "wb") as fh:'),
    ("chaves públicas: arquivos trocados",
     "((PUBLIC_KEM_NAME, keys.kem_ek), (PUBLIC_DSA_NAME, keys.dsa_pk))",
     "((PUBLIC_KEM_NAME, keys.dsa_pk), (PUBLIC_DSA_NAME, keys.kem_ek))"),
    ("chaves públicas: sem \\n final", 'fh.write(raw.hex().encode("ascii") + b"\\n")', 'fh.write(raw.hex().encode("ascii"))'),
    ("chaves públicas: modo texto (o Windows troca \\n por \\r\\n)",
     '        with open(folder / name, "xb") as fh:  # binário: o Windows não troca \\n por \\r\\n\n            fh.write(raw.hex().encode("ascii") + b"\\n")',
     '        with open(folder / name, "x", encoding="ascii") as fh:\n            fh.write(raw.hex() + "\\n")'),
    ("run: cadeia vazia deixa de começar na gênese",
     "    if not receipts_dir.exists():\n        return GENESIS_PREV_HASH",
     "    if False:\n        return GENESIS_PREV_HASH"),
    ("run: confere a cadeia só depois do pipeline",
     "    head = _current_head(args.receipts_dir, issuer.pk)  # antes do pipeline: log ruim não gasta entropia\n    result, srcs = _run_keygen(sources, seed_source, args.bits)",
     "    result, srcs = _run_keygen(sources, seed_source, args.bits)\n    head = _current_head(args.receipts_dir, issuer.pk)"),
    ("run: recibo sem o prev da cadeia",
     "body = build_receipt_body(result, keys, srcs, prev_receipt_hash=head)",
     "body = build_receipt_body(result, keys, srcs)"),
    ("run: recusa do append escapa como erro inesperado",
     '    except ChainError as exc:\n        raise _Fail("chain", f"recibo recusado',
     '    except KeyError as exc:\n        raise _Fail("chain", f"recibo recusado'),
    ("run: falha nas chaves públicas escapa como erro inesperado",
     '    except OSError:\n        raise _Fail("public_keys",', '    except KeyError:\n        raise _Fail("public_keys",'),
    ("run: não imprime a semente (hash)", "    _out(f\"semente (hash): {receipt['seed_hash']}\")\n", ""),
    ("run: não imprime os hashes das chaves públicas",
     "    _out(f\"chaves públicas (hash): ML-KEM-768 {receipt['keys']['ml_kem_768_pk_hash']}; \"\n         f\"ML-DSA-65 {receipt['keys']['ml_dsa_65_pk_hash']}\")\n", ""),
    ("run: não imprime as fontes",
     "    _out(\"fontes:\" + \"\".join(f\" {getattr(o, 'source_id', '?')}={getattr(o, 'status', '?')}\" for o in result.outcomes))\n", ""),
    ("run: cabeça impressa é a semente",
     '_out(f"cabeça da cadeia: {receipt_hash(receipt)}")', "_out(f\"cabeça da cadeia: {receipt['seed_hash']}\")"),
    ("verify: posição começa em 0", 'for n, line in enumerate(data.split(b"\\n"), start=1):',
     'for n, line in enumerate(data.split(b"\\n"), start=0):'),
    ("verify: chave pública ausente escapa como erro inesperado",
     '    except (OSError, ValueError):\n        raise _Fail("verify", f"chave pública',
     '    except KeyError:\n        raise _Fail("verify", f"chave pública'),
    ("verify: arquivo inexistente vira 'ilegível'",
     '    except FileNotFoundError:\n        raise _Fail("verify", f"arquivo não encontrado',
     '    except KeyError:\n        raise _Fail("verify", f"arquivo não encontrado'),
    ("verify: arquivo com UTF-8 inválido escapa",
     '    except (OSError, UnicodeDecodeError):\n        raise _Fail("verify", "arquivo ilegível")',
     '    except OSError:\n        raise _Fail("verify", "arquivo ilegível")'),
    ("verify: recibo reprovado passa",
     '    if not verdict.ok:\n        raise _Fail("verify", f"recibo reprovado',
     '    if verdict.ok:\n        raise _Fail("verify", f"recibo reprovado'),
    ("verify: --sem-cadeia invertido",
     '    if args.sem_cadeia:\n        lines.append("AVISO', '    if not args.sem_cadeia:\n        lines.append("AVISO'),
    ("verify: ignora --chain-dir", "chain_dir = args.chain_dir or args.file.parent", "chain_dir = args.file.parent"),
    ("verify: pasta sem log não é tratada",
     '        if not (chain_dir / RECEIPT_CHAIN_NAME).exists():\n            raise _Fail("verify", f"não há',
     '        if False:\n            raise _Fail("verify", f"não há'),
    ("verify: ignora --expected-head",
     "res = verify_chain(chain_dir, pk, expected_head=args.expected_head)", "res = verify_chain(chain_dir, pk)"),
    ("verify: cadeia reprovada passa",
     '        if not res.ok:\n            raise _Fail("verify", f"cadeia reprovada',
     '        if res.ok:\n            raise _Fail("verify", f"cadeia reprovada'),
    ("verify: recibo fora do log passa",
     '        if position is None:\n            raise _Fail("verify", "recibo não está na cadeia")',
     '        if False:\n            raise _Fail("verify", "recibo não está na cadeia")'),
    ("verify: 'cabeça conferida' invertido",
     '        if args.expected_head is not None:\n            lines.append("cabeça conferida")',
     '        if args.expected_head is None:\n            lines.append("cabeça conferida")'),
    ("main: verify passa a gravar log", '_LOGGED_COMMANDS = ("init-issuer", "run")',
     '_LOGGED_COMMANDS = ("init-issuer", "run", "verify")'),
    ("main: mensagem da exceção vai para a saída",
     '        message = f"erro inesperado ({type(exc).__name__})"', '        message = f"erro inesperado ({exc})"'),
    ("main: --help e uso viram código 1",
     "return exc.code if isinstance(exc.code, int) else", "return 1 if isinstance(exc.code, int) else"),
    ("main: falha esperada sai com 2", "            _log_failure(logs_dir, args.command, fail)\n        return 1",
     "            _log_failure(logs_dir, args.command, fail)\n        return 2"),
    ("padrão: --bits do init", '    init.add_argument("--bits", type=_bits_arg, default=DEFAULT_N_BITS,',
     '    init.add_argument("--bits", type=_bits_arg, default=1000,'),
    ("padrão: --bits do run", '    run.add_argument("--bits", type=_bits_arg, default=DEFAULT_N_BITS,',
     '    run.add_argument("--bits", type=_bits_arg, default=1000,'),
    ("padrão: pasta das chaves", 'KEYS_DIR = Path("keys")', 'KEYS_DIR = Path("chaves")'),
    ("padrão: pasta dos recibos", 'RECEIPTS_DIR = Path("data/receipts")', 'RECEIPTS_DIR = Path("data/recibos")'),
    ("padrão: pasta das chaves públicas", 'PUBLIC_KEYS_DIR = Path("data/public_keys")',
     'PUBLIC_KEYS_DIR = Path("data/chaves_publicas")'),
    ("padrão: pasta dos logs", 'LOGS_DIR = Path("data/logs")', 'LOGS_DIR = Path("data/log")'),
    ("padrão: nome do log de falhas", 'RUN_LOG_NAME = "eal_runs.jsonl"', 'RUN_LOG_NAME = "runs.jsonl"'),
    ("padrão: nome da chave pública ML-KEM", 'PUBLIC_KEM_NAME = "ml_kem_768.ek.hex"', 'PUBLIC_KEM_NAME = "kem.hex"'),
    ("padrão: nome da chave pública ML-DSA", 'PUBLIC_DSA_NAME = "ml_dsa_65.pk.hex"', 'PUBLIC_DSA_NAME = "dsa.hex"'),
]


def _run_tests() -> tuple[bool, str]:
    """True se algum teste falhou (mutação morta)."""
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    proc = subprocess.run(
        [sys.executable, "-B", "-m", "pytest", "-x", "-q", "-p", "no:cacheprovider", TESTS],
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
    original = TARGET.read_bytes()
    prepared = _prepare(original)
    text = original.decode("utf-8")
    survivors: list[str] = []
    print(f"{len(prepared)} mutações; testes: {TESTS}")
    try:
        for i, (name, old, new) in enumerate(prepared, start=1):
            TARGET.write_bytes(text.replace(old, new, 1).encode("utf-8"))
            t0 = time.time()
            killed, tail = _run_tests()
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
