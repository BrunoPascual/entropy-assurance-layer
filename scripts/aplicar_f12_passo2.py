"""F12, passo 2: a CLI guarda o histórico do detector de replay entre execuções.

Uso (na raiz do projeto):  py -3.12 scripts\\aplicar_f12_passo2.py [raiz do projeto]

Muda dois arquivos, tudo ou nada:
  - eal/cli.py: o _run_keygen carrega o histórico (de <logs-dir>/replay_history.json) ANTES de ler
    qualquer fonte, passa o detector ao pipeline e grava o histórico logo depois do pipeline e
    ANTES de qualquer recibo. Histórico ruim ou gravação que falha recusam (fail-closed).
  - tests/test_cli.py: o ShakeStandin passa a girar os bits conhecidos por mais 1 posição a cada
    leitura, porque a fonte determinística repetiria o mesmo lote e viraria replay de verdade.

Idempotente, preserva LF ou CRLF de cada arquivo e recusa sem gravar se qualquer conferência falhar.
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

HISTORY_HELPERS = '''def _load_history(path: Path) -> Any:
    """Histórico do detector de replay (F12). Ruim: recusa antes de ler qualquer fonte, sem apagar nada."""
    try:
        return load_detector(path)
    except ReplayHistoryError as exc:
        raise _Fail(
            "replay_history",
            f"{exc}; nenhuma fonte foi lida (fail-closed). Se o arquivo for mesmo inútil, arquive-o à mão: "
            "isso zera a proteção contra replay entre execuções.",
        ) from None


def _save_history(detector: Any, path: Path) -> None:
    """Grava o histórico ANTES de qualquer recibo. Se falhar, nenhum recibo é emitido (fail-closed)."""
    try:
        save_detector(detector, path)
    except ReplayHistoryError as exc:
        raise _Fail("replay_history", f"{exc}; nenhum recibo foi emitido (fail-closed)") from None


'''

RUN_BLOCK = '''    history_path = logs_dir / REPLAY_HISTORY_NAME
    detector = _load_history(history_path)  # antes de ler fonte: histórico ruim não gasta entropia
    seen_before = detector.history_batches
    result = run_pipeline(srcs, seed, mode="keygen", n_bits=n_bits, detector=detector)
    if detector.history_batches != seen_before:  # lote novo visto: grava mesmo se a semente falhou
        _save_history(detector, history_path)
'''

TEST_ROLL = '''        bits = np.unpackbits(np.frombuffer(raw, dtype=np.uint8))[:n_bits].copy()
        # F12: com o histórico de replay guardado entre execuções, cada leitura precisa de bits novos.
        # Girar a sequência conhecida por mais 1 posição a cada leitura dá bits novos (os blocos de
        # 4096 bits mudam; replay deslocado não é detectado, ver replay.py) com as mesmas propriedades.
        bits = np.roll(bits, next(_READS)).copy()
        return self._build_batch(bits, {"label": STANDIN_LABEL.decode()})
'''

PLAN: list[tuple[str, str, list[tuple[str, str]]]] = [
    ("eal/cli.py", "def _load_history(", [
        ("from eal.config import DEFAULT_N_BITS, GENESIS_PREV_HASH, ISSUER_PK_NAME, ISSUER_SK_NAME, RECEIPT_CHAIN_NAME\n",
         "from eal.config import (\n"
         "    DEFAULT_N_BITS,\n"
         "    GENESIS_PREV_HASH,\n"
         "    ISSUER_PK_NAME,\n"
         "    ISSUER_SK_NAME,\n"
         "    RECEIPT_CHAIN_NAME,\n"
         "    REPLAY_HISTORY_NAME,\n"
         ")\n"),
        ("from eal.pipeline import run_pipeline\n",
         "from eal.health.replay_store import ReplayHistoryError, load_detector, save_detector\n"
         "from eal.pipeline import run_pipeline\n"),
        ("def _run_keygen(sources: Sequence[Any] | None, seed_source: Any, n_bits: int) -> tuple[Any, list[Any]]:\n",
         HISTORY_HELPERS
         + "def _run_keygen(\n"
         "    sources: Sequence[Any] | None, seed_source: Any, n_bits: int, logs_dir: Path\n"
         ") -> tuple[Any, list[Any]]:\n"),
        ('    result = run_pipeline(srcs, seed, mode="keygen", n_bits=n_bits)\n', RUN_BLOCK),
        ("    result, _ = _run_keygen(sources, seed_source, args.bits)\n",
         "    result, _ = _run_keygen(sources, seed_source, args.bits, args.logs_dir)\n"),
        ("    result, srcs = _run_keygen(chosen, seed_source, args.bits)\n",
         "    result, srcs = _run_keygen(chosen, seed_source, args.bits, args.logs_dir)\n"),
    ]),
    ("tests/test_cli.py", "_READS = itertools.count(1)", [
        ("import io\nimport json\n", "import io\nimport itertools\nimport json\n"),
        ('STANDIN_LABEL = b"EAL-v1|test-standin|1"\n',
         'STANDIN_LABEL = b"EAL-v1|test-standin|1"\n'
         "_READS = itertools.count(1)  # F12: cada leitura do ShakeStandin gira os bits por mais 1 posição\n"),
        ('        bits = np.unpackbits(np.frombuffer(raw, dtype=np.uint8))[:n_bits].copy()\n'
         '        return self._build_batch(bits, {"label": STANDIN_LABEL.decode()})\n',
         TEST_ROLL),
    ]),
]


def _load(path: Path) -> tuple[str, bool] | str:
    try:
        text = path.read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return f"não consegui ler {path} ({type(exc).__name__})"
    crlf = "\r\n" in text
    if crlf and text.count("\n") != text.count("\r\n"):
        return f"{path} mistura LF e CRLF"
    return text.replace("\r\n", "\n"), crlf


def _apply(norm: str, edits: list[tuple[str, str]]) -> str | None:
    for old, _ in edits:
        if norm.count(old) != 1:
            return None
    for old, new in edits:
        norm = norm.replace(old, new, 1)
    return norm


def main() -> int:
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[1]
    staged: list[tuple[Path, bytes]] = []
    already = 0
    for rel, marker, edits in PLAN:
        path = root / rel
        loaded = _load(path)
        if isinstance(loaded, str):
            print(f"RECUSADO: {loaded}; nada foi gravado")
            return 1
        norm, crlf = loaded
        if marker in norm:
            if all(new in norm for _, new in edits):
                already += 1
                continue
            print(f"RECUSADO: {rel} com aplicação parcial anterior; nada foi gravado")
            return 1
        result = _apply(norm, edits)
        if result is None:
            bad = [i for i, (o, _) in enumerate(edits, 1) if norm.count(o) != 1]
            print(f"RECUSADO: {rel}: trecho(s) {bad} não aparece(m) exatamente 1 vez; nada foi gravado")
            return 1
        out = result.replace("\n", "\r\n") if crlf else result
        staged.append((path, out.encode("utf-8")))
    if already == len(PLAN):
        print("já aplicado; nada a fazer")
        return 0
    if already:
        print("RECUSADO: só parte dos arquivos já estava aplicada; nada foi gravado")
        return 1
    for path, data in staged:
        path.write_bytes(data)
        print(f"aplicado em {path}; sha256 novo: {hashlib.sha256(data).hexdigest()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
