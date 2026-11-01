"""DEP_SESSAO, passo 2: analisar_coleta1.py e resumo_coleta1.py aceitam --sessao (padrão coleta1).

Uso único:  py -3.12 scripts\\aplicar_sessao_analise.py

Troca texto nos dois scripts. Só grava se os dois tiverem o SHA-256 do commit e1e7be2
(HASH_ANTES); o resultado tem de ter exatamente o HASH_DEPOIS de cada um. Tudo ou nada: se a
segunda troca falhar, a primeira é desfeita. Se os dois já estiverem em HASH_DEPOIS, diz "já
aplicado" e não grava nada. Com o padrão (coleta1), nomes de entrada e saída não mudam.

Na QPU real, o erro de leitura passa a ser o retrato da execução (R8) quando o lote o tem; os lotes
da coleta 1 não têm esse campo e continuam com o do envio.
"""
from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

AC_EDITS = [('Uso (na raiz do projeto):\n    py -3.12 scripts\\\\analisar_coleta1.py\nCódigo de saída: 0 gravado; 1 recusado ou erro (nada foi gravado); 2 erro de uso.\n', 'Uso (na raiz do projeto):\n    py -3.12 scripts\\\\analisar_coleta1.py\n    py -3.12 scripts\\\\analisar_coleta1.py --sessao coleta2\nCom ``--sessao`` diferente de ``coleta1``, o inventário padrão é\n``data/results/dia6_<sessao>_inventario.csv`` e as saídas ganham o prefixo ``dia6_<sessao>_``.\nNa QPU real, o erro de leitura é o retrato da execução (R8) quando o lote o tem; senão, o do\nenvio.\nCódigo de saída: 0 gravado; 1 recusado ou erro (nada foi gravado); 2 erro de uso.\n'), ('import os\nimport sys\n', 'import os\nimport re\nimport sys\n'), ('QUBIT_NAME = "dia6_qpu_vs_sim_por_qubit.csv"\n', 'QUBIT_NAME = "dia6_qpu_vs_sim_por_qubit.csv"\nSESSION_RE = re.compile(r"[A-Za-z0-9]+")\n'), ('def _sha256(data: bytes) -> str:\n    return hashlib.sha256(data).hexdigest()\n', 'def _sha256(data: bytes) -> str:\n    return hashlib.sha256(data).hexdigest()\n\n\ndef check_session(session: str) -> str:\n    """Só letras e dígitos: entra num glob e em nomes de arquivo, e ``_`` separa o rótulo."""\n    if not isinstance(session, str) or not SESSION_RE.fullmatch(session):\n        raise AnalysisError(f"sessão inválida: {session!r}")\n    return session\n\n\ndef session_file(name: str, session: str) -> str:\n    """``coleta1`` mantém o nome de sempre; outra sessão ganha o prefixo ``dia6_<sessao>_``."""\n    if session == SESSION:\n        return name\n    return name.replace("dia6_", f"dia6_{session}_", 1)\n\n\ndef inventory_for(session: str) -> Path:\n    """Inventário de uma sessão (o mesmo nome que ``inventario_coleta1.py --sessao`` grava)."""\n    return Path(f"data/results/dia6_{session}_inventario.csv")\n\n\ndef readout_of(params: dict[str, Any]) -> Any:\n    """Erro de leitura por posição: o da execução (R8) se o lote tiver; senão, o do envio."""\n    run = params.get("readout_error_run_by_position")\n    return run if run is not None else params.get("readout_error_by_position")\n'), ('def _targets(out_dir: Path) -> list[Path]:\n    return [out_dir / LOTS_NAME, out_dir / QUBIT_NAME]\n', 'def _targets(out_dir: Path, session: str = SESSION) -> list[Path]:\n    return [out_dir / session_file(LOTS_NAME, session),\n            out_dir / session_file(QUBIT_NAME, session)]\n'), ('def check_targets(out_dir: Path) -> None:\n    for t in _targets(out_dir):\n', 'def check_targets(out_dir: Path, session: str = SESSION) -> None:\n    for t in _targets(out_dir, session):\n'), ('def write_outputs(out_dir: Path, lots_text: str, qubit_text: str) -> list[Path]:\n    """Grava os dois CSVs, tudo ou nada (temporário e depois o nome final)."""\n    check_targets(out_dir)\n    out_dir.mkdir(parents=True, exist_ok=True)\n    targets = _targets(out_dir)\n', 'def write_outputs(out_dir: Path, lots_text: str, qubit_text: str,\n                  session: str = SESSION) -> list[Path]:\n    """Grava os dois CSVs, tudo ou nada (temporário e depois o nome final)."""\n    check_targets(out_dir, session)\n    out_dir.mkdir(parents=True, exist_ok=True)\n    targets = _targets(out_dir, session)\n'), ('        readout = b.params.get("readout_error_by_position") if use_readout else None\n', '        readout = readout_of(b.params) if use_readout else None\n'), ('        os_factory: Callable[[], Any] | None = None) -> list[dict[str, Any]]:\n    sim_factory = sim_factory or _default_sim\n    os_factory = os_factory or OsSource\n    check_targets(out_dir)  # falha cedo, antes de simular\n    real = load_real(raw_dir, inventory)\n', '        os_factory: Callable[[], Any] | None = None,\n        session: str = SESSION) -> list[dict[str, Any]]:\n    session = check_session(session)\n    sim_factory = sim_factory or _default_sim\n    os_factory = os_factory or OsSource\n    check_targets(out_dir, session)  # falha cedo, antes de simular\n    real = load_real(raw_dir, inventory, session)\n'), ('    paths = write_outputs(out_dir, lots_text, qubit_text)\n', '    paths = write_outputs(out_dir, lots_text, qubit_text, session)\n'), ('    ap.add_argument("--inventario", type=Path, default=INVENTORY_PATH)\n', '    ap.add_argument("--sessao", default=SESSION)\n    ap.add_argument("--inventario", type=Path, default=None)\n'), ('    try:\n        lots = run(args.raw_dir, args.inventario, args.out_dir, args.sim_seed,\n                   sim_factory=sim_factory, os_factory=os_factory)\n', '    try:\n        session = check_session(args.sessao)\n        inventory = args.inventario or inventory_for(session)\n        lots = run(args.raw_dir, inventory, args.out_dir, args.sim_seed,\n                   sim_factory=sim_factory, os_factory=os_factory, session=session)\n')]

RC_EDITS = [('Uso (na raiz do projeto):\n    py -3.12 scripts\\\\resumo_coleta1.py\nCódigo de saída: 0 gravado ou já igual; 1 recusado; 2 erro de uso.\n', 'Uso (na raiz do projeto):\n    py -3.12 scripts\\\\resumo_coleta1.py\n    py -3.12 scripts\\\\resumo_coleta1.py --sessao coleta2\nCom ``--sessao`` diferente de ``coleta1``, a entrada padrão e as saídas ganham o prefixo\n``dia6_<sessao>_`` (os mesmos nomes que ``analisar_coleta1.py --sessao`` grava).\nCódigo de saída: 0 gravado ou já igual; 1 recusado; 2 erro de uso.\n'), ('import os\nimport sys\n', 'import os\nimport re\nimport sys\n'), ('EXCESSO_NAME = "dia6_qpu_excesso_leitura.csv"\n', 'EXCESSO_NAME = "dia6_qpu_excesso_leitura.csv"\nSESSION = "coleta1"\nSESSION_RE = re.compile(r"[A-Za-z0-9]+")\n'), ('class SummaryError(Exception):\n    """Recusa: nada foi gravado."""\n', 'class SummaryError(Exception):\n    """Recusa: nada foi gravado."""\n\n\ndef check_session(session: str) -> str:\n    """Só letras e dígitos: entra em nomes de arquivo, e ``_`` separa o rótulo."""\n    if not isinstance(session, str) or not SESSION_RE.fullmatch(session):\n        raise SummaryError(f"sessão inválida: {session!r}")\n    return session\n\n\ndef session_file(name: str, session: str) -> str:\n    """``coleta1`` mantém o nome de sempre; outra sessão ganha o prefixo ``dia6_<sessao>_``."""\n    if session == SESSION:\n        return name\n    return name.replace("dia6_", f"dia6_{session}_", 1)\n\n\ndef input_for(session: str) -> Path:\n    """CSV por qubit que ``analisar_coleta1.py --sessao`` grava para a sessão."""\n    return IN_PATH.with_name(session_file(IN_PATH.name, session))\n'), ('    ap.add_argument("--entrada", type=Path, default=IN_PATH)\n    ap.add_argument("--out-dir", type=Path, default=OUT_DIR)\n    args = ap.parse_args(argv)\n    try:\n        resumo, excesso, summary = build(args.entrada)\n        targets = [(args.out_dir / RESUMO_NAME, resumo), (args.out_dir / EXCESSO_NAME, excesso)]\n', '    ap.add_argument("--sessao", default=SESSION)\n    ap.add_argument("--entrada", type=Path, default=None)\n    ap.add_argument("--out-dir", type=Path, default=OUT_DIR)\n    args = ap.parse_args(argv)\n    try:\n        session = check_session(args.sessao)\n        resumo, excesso, summary = build(args.entrada or input_for(session))\n        targets = [(args.out_dir / session_file(RESUMO_NAME, session), resumo),\n                   (args.out_dir / session_file(EXCESSO_NAME, session), excesso)]\n')]

FILES = [
    (ROOT / "scripts" / "analisar_coleta1.py", "b712e09b2ace2edee39ad028f2cb57f99e310fd3fbb08cd378eac07fb59a7763",
     "f32020255d4084088d0fc05385c0e80040b50f1f27bba7aa8c4d6579c2680ea9", AC_EDITS),
    (ROOT / "scripts" / "resumo_coleta1.py", "e36c92903cc1db5ca222ce475d6b123dc9ca1cd8315729ef65a541e2f2e41d4b",
     "2241bfca6ee24f00fdea999cfcc99058e31af7ed0dfd4a0de953ab375c22e4d0", RC_EDITS),
]


class Recusa(Exception):
    """Algo não bate: nada é gravado."""


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def plan() -> list[tuple[Path, bytes, bytes]]:
    """(caminho, bytes atuais, bytes novos) dos que faltam; [] se já aplicado. Levanta Recusa."""
    current = []
    for path, antes, depois, edits in FILES:
        if not path.is_file():
            raise Recusa(f"arquivo ausente: {path}")
        current.append((path, path.read_bytes(), antes, depois, edits))
    states = [sha(raw) == depois for _, raw, _, depois, _ in current]
    if all(states):
        return []
    if any(states):
        raise Recusa("um arquivo já tem o passo 2 e o outro não")
    work = []
    for path, raw, antes, depois, edits in current:
        if sha(raw) != antes:
            raise Recusa(f"{path.name}: SHA-256 atual {sha(raw)} difere do esperado {antes}")
        text = raw.decode("utf-8")
        for i, (old, new) in enumerate(edits, 1):
            if text.count(old) != 1:
                raise Recusa(f"{path.name}: trecho {i} não aparece exatamente uma vez")
            text = text.replace(old, new)
        compile(text, str(path), "exec")
        new = text.encode("utf-8")
        if sha(new) != depois:
            raise Recusa(f"{path.name}: o resultado teria SHA-256 {sha(new)}, não {depois}")
        work.append((path, raw, new))
    return work


def main() -> int:
    try:
        work = plan()
    except (Recusa, UnicodeDecodeError, SyntaxError, OSError) as exc:
        print(f"RECUSADO, nada foi gravado: {exc}")
        return 1
    if not work:
        print("Passo 2 já aplicado; nada foi gravado.")
        return 0
    done: list[tuple[Path, bytes]] = []
    try:
        for path, raw, new in work:
            tmp = path.with_name(path.name + ".tmp_sessao")
            with open(tmp, "xb") as fh:
                fh.write(new)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, path)
            done.append((path, raw))
    except OSError as exc:
        for path, raw in done:
            path.write_bytes(raw)
        for path, _, _ in work:
            path.with_name(path.name + ".tmp_sessao").unlink(missing_ok=True)
        print(f"RECUSADO, arquivos restaurados: {exc}")
        return 1
    for path, raw, new in work:
        print(f"{path.name}: {sha(raw).upper()} -> {sha(new).upper()}")
    print("Passo 2 aplicado.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
