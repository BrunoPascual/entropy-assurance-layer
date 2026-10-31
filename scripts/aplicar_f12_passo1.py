"""F12, passo 1: o ReplayDetector passa a salvar e restaurar o estado (eal/health/replay.py)
e o config.py ganha as constantes do histórico.

Uso (na raiz do projeto):  py -3.12 scripts\\aplicar_f12_passo1.py [raiz do projeto]

Tudo ou nada: confere os dois arquivos antes de gravar qualquer um. Idempotente, preserva
LF ou CRLF de cada arquivo e recusa sem gravar se qualquer conferência falhar.
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

CONFIG_BLOCK = '''
# --- F12: histórico do detector de replay entre execuções (Dia 6) ---
REPLAY_HISTORY_NAME: str = "replay_history.json"  # em data/logs/, fora do Git
REPLAY_HISTORY_SCHEMA: str = "eal-replay-history-v1"
REPLAY_HISTORY_MAX_BYTES: int = 64 * 1024 * 1024  # acima disso, recusa ler e gravar (fail-closed)
'''

CONSTANTS = '''
_STATE_FIELDS = frozenset({"block_bits", "batch_ids", "batch_hashes", "blocks"})
_HEX64 = re.compile(r"[0-9a-f]{64}")
_MAX_ID_CHARS = 128


def _valid_id(value: object) -> bool:
    return isinstance(value, str) and 0 < len(value) <= _MAX_ID_CHARS


def _valid_ref(value: object, ids: set[str]) -> bool:
    """Referência de bloco no formato "<batch_id>#<índice>", com batch_id conhecido."""
    if not isinstance(value, str):
        return False
    batch_id, sep, index = value.rpartition("#")
    return bool(sep) and batch_id in ids and index.isascii() and index.isdigit()
'''

BLOCK_BITS_PROPERTY = '''    @property
    def block_bits(self) -> int:
        """Tamanho do bloco, em bits, usado nas comparações."""
        return self._block_bits

'''

STATE_METHODS = '''    def to_state(self) -> dict[str, Any]:
        """Estado serializável: só hashes e ids de lote, nenhum bit."""
        return {
            "block_bits": self._block_bits,
            "batch_ids": sorted(self._batch_ids),
            "batch_hashes": dict(self._batch_hashes),
            "blocks": {digest.hex(): ref for digest, ref in self._blocks.items()},
        }

    @classmethod
    def from_state(cls, state: object) -> ReplayDetector:
        """Restaura o estado salvo. Estado malformado levanta ValueError; a mensagem cita só o campo."""
        if not isinstance(state, dict) or state.keys() != _STATE_FIELDS:
            raise ValueError("estado do detector: campos inesperados")
        block_bits = state["block_bits"]
        if isinstance(block_bits, bool) or not isinstance(block_bits, int):
            raise ValueError("estado do detector: block_bits inválido")
        detector = cls(block_bits)  # recusa tamanho não positivo ou que não seja múltiplo de 8
        ids = state["batch_ids"]
        if not (isinstance(ids, list) and all(_valid_id(x) for x in ids)) or len(set(ids)) != len(ids):
            raise ValueError("estado do detector: batch_ids inválido")
        known = set(ids)
        hashes = state["batch_hashes"]
        if not (isinstance(hashes, dict)
                and all(_valid_id(k) and isinstance(v, str) and v in known for k, v in hashes.items())):
            raise ValueError("estado do detector: batch_hashes inválido")
        raw_blocks = state["blocks"]
        if not isinstance(raw_blocks, dict):
            raise ValueError("estado do detector: blocks inválido")
        blocks: dict[bytes, str] = {}
        for hex_digest, ref in raw_blocks.items():
            if not (isinstance(hex_digest, str) and _HEX64.fullmatch(hex_digest) and _valid_ref(ref, known)):
                raise ValueError("estado do detector: blocks inválido")
            blocks[bytes.fromhex(hex_digest)] = ref
        detector._batch_ids = known
        detector._batch_hashes = dict(hashes)
        detector._blocks = blocks
        return detector

'''

# (arquivo relativo, marcador de "já aplicado", lista de (antigo, novo); "APPEND" acrescenta no fim)
PLAN: list[tuple[str, str, list[tuple[str, str]]]] = [
    ("eal/config.py", "REPLAY_HISTORY_NAME", [("APPEND", CONFIG_BLOCK)]),
    ("eal/health/replay.py", "def from_state(", [
        ("O detector guarda, só em\nmemória e só durante a execução, o hash de cada lote e o hash de cada bloco\n"
         "completo de 4096 bits. Um lote falha se:",
         "O detector guarda o hash de cada lote e o hash de cada bloco\n"
         "completo de 4096 bits (só hashes e ids, nunca bits). O estado pode ser salvo e\n"
         "restaurado (to_state, from_state; ver replay_store.py). Um lote falha se:"),
        ("  - o estado não persiste entre execuções.",
         "  - o estado só persiste entre execuções se o chamador o salvar (replay_store.py);\n"
         "    apagar ou trocar o arquivo salvo zera a proteção sem alarme."),
        ("import hashlib\nfrom dataclasses import dataclass\n",
         "import hashlib\nimport re\nfrom dataclasses import dataclass\nfrom typing import Any\n"),
        ("from eal.config import REPLAY_BLOCK_BITS\n",
         "from eal.config import REPLAY_BLOCK_BITS\n" + CONSTANTS),
        ('    """Guarda hashes em memória e checa cada lote novo. Uma instância por execução."""\n',
         '    """Guarda hashes e checa cada lote novo. O estado pode ser salvo e restaurado."""\n'),
        ("    @property\n    def history_batches(self) -> int:\n",
         BLOCK_BITS_PROPERTY + "    @property\n    def history_batches(self) -> int:\n"),
        ("    def check(self, bits: np.ndarray, *, batch_hash: str, batch_id: str) -> ReplayResult:\n",
         STATE_METHODS + "    def check(self, bits: np.ndarray, *, batch_hash: str, batch_id: str) -> ReplayResult:\n"),
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
        if old != "APPEND" and norm.count(old) != 1:
            return None
    for old, new in edits:
        if old == "APPEND":
            norm = (norm if norm.endswith("\n") else norm + "\n") + new
        else:
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
            applied = all(new in norm for old, new in edits if old != "APPEND") and (
                edits[0][0] != "APPEND" or edits[0][1].strip() in norm)
            if applied:
                already += 1
                continue
            print(f"RECUSADO: {rel} com aplicação parcial anterior; nada foi gravado")
            return 1
        result = _apply(norm, edits)
        if result is None:
            bad = [i for i, (o, _) in enumerate(edits, 1) if o != "APPEND" and norm.count(o) != 1]
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
