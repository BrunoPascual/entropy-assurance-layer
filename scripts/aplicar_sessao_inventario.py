"""DEP_SESSAO, passo 1: scripts/inventario_coleta1.py aceita --sessao (padrão coleta1).

Uso único:  py -3.12 scripts\\aplicar_sessao_inventario.py

Só grava se o SHA-256 atual for o do commit ca9e652 (HASH_ANTES). Tudo ou nada: cada trecho
original tem de aparecer exatamente uma vez. Preserva CRLF ou LF. Uma segunda execução diz que
já foi aplicado e não grava nada. Com o padrão (coleta1), o nome da saída e o conteúdo do CSV
não mudam.
"""
from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TARGET = ROOT / "scripts" / "inventario_coleta1.py"
HASH_ANTES = "4d19e7b55cd22e7b4209b4ad8568d46ad0b054bea4512eab456d23c3bfa8f5d5"
BS = "\\\\"  # as duas barras que o docstring do alvo tem no texto

USAGE_OLD = ("Uso (na raiz do projeto):\n"
             f"    py -3.12 scripts{BS}inventario_coleta1.py\n"
             "Código de saída: 0 gravado ou já igual; 1 recusado (nada foi gravado).\n")
USAGE_NEW = ("Uso (na raiz do projeto):\n"
             f"    py -3.12 scripts{BS}inventario_coleta1.py\n"
             f"    py -3.12 scripts{BS}inventario_coleta1.py --sessao coleta2\n"
             "A sessão (só letras e dígitos) escolhe os lotes e o nome da saída,\n"
             "``data/results/dia6_<sessao>_inventario.csv``; o padrão é ``coleta1``.\n"
             "Código de saída: 0 gravado ou já igual; 1 recusado (nada foi gravado); "
             "2 erro de uso.\n")

EDITS = [
    (USAGE_OLD, USAGE_NEW),
    ("import csv\nimport hashlib\n", "import argparse\nimport csv\nimport hashlib\n"),
    ("import os\nimport sys\n", "import os\nimport re\nimport sys\n"),
    ('OUT_PATH = Path("data/results/dia6_coleta1_inventario.csv")\n',
     'SESSION_RE = re.compile(r"[A-Za-z0-9]+")\n'
     'OUT_PATH = Path("data/results/dia6_coleta1_inventario.csv")\n'),
    ('def main(raw_dir: Path = RAW_DIR, log_path: Path = LOG_PATH, out_path: Path = OUT_PATH) -> int:\n'
     '    try:\n'
     '        rows = build_rows(raw_dir, log_path)\n',
     'def out_path_for(session: str) -> Path:\n'
     '    """CSV do inventário de uma sessão; ``coleta1`` dá o nome de sempre (OUT_PATH)."""\n'
     '    return Path(f"data/results/dia6_{session}_inventario.csv")\n'
     '\n'
     '\n'
     'def check_session(session: str) -> str:\n'
     '    """Só letras e dígitos: o nome entra num glob e no nome do arquivo, e ``_`` separa o rótulo."""\n'
     '    if not isinstance(session, str) or not SESSION_RE.fullmatch(session):\n'
     '        raise InventoryError(f"sessão inválida: {session!r}")\n'
     '    return session\n'
     '\n'
     '\n'
     'def main(raw_dir: Path = RAW_DIR, log_path: Path = LOG_PATH, out_path: Path | None = None,\n'
     '         session: str = SESSION) -> int:\n'
     '    try:\n'
     '        session = check_session(session)\n'
     '        if out_path is None:\n'
     '            out_path = out_path_for(session)\n'
     '        rows = build_rows(raw_dir, log_path, session)\n'),
    ('if __name__ == "__main__":\n    sys.exit(main())\n',
     'def cli(argv: list[str] | None = None) -> int:\n'
     '    ap = argparse.ArgumentParser(description="Dia 6: inventário dos lotes de uma sessão")\n'
     '    ap.add_argument("--sessao", default=SESSION)\n'
     '    args = ap.parse_args(argv)\n'
     '    return main(session=args.sessao)\n'
     '\n'
     '\n'
     'if __name__ == "__main__":\n    sys.exit(cli())\n'),
]


class Recusa(Exception):
    """Algo não bate: nada é gravado."""


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> int:
    try:
        if not TARGET.is_file():
            raise Recusa(f"arquivo ausente: {TARGET}")
        raw = TARGET.read_bytes()
        crlf, lf = raw.count(b"\r\n"), raw.count(b"\n")
        if crlf and crlf != lf:
            raise Recusa("fim de linha misto (CRLF e LF)")
        text = raw.decode("utf-8").replace("\r\n", "\n")
        if all(text.count(new) == 1 for _, new in EDITS) and "def cli(" in text:
            print(f"Passo 1 já aplicado; nada foi gravado. {TARGET.name}: {sha(raw).upper()}")
            return 0
        if sha(raw) != HASH_ANTES:
            raise Recusa(f"SHA-256 atual {sha(raw)} difere do esperado {HASH_ANTES}")
        for i, (old, new) in enumerate(EDITS, 1):
            if text.count(old) != 1:
                raise Recusa(f"trecho {i} não aparece exatamente uma vez")
            text = text.replace(old, new)
        compile(text, str(TARGET), "exec")
    except (Recusa, UnicodeDecodeError, SyntaxError) as exc:
        print(f"RECUSADO, nada foi gravado: {exc}")
        return 1
    data = (text.replace("\n", "\r\n") if crlf else text).encode("utf-8")
    tmp = TARGET.with_name(TARGET.name + ".tmp_sessao")
    try:
        tmp.write_bytes(data)
        os.replace(tmp, TARGET)
    except OSError as exc:
        tmp.unlink(missing_ok=True)
        print(f"RECUSADO, nada foi gravado: {exc}")
        return 1
    print(f"{TARGET.name}: {sha(raw).upper()} -> {sha(data).upper()}")
    print("Passo 1 aplicado.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
