"""Lançador do ponto de entrada da coleta na IBM (a lógica fica em eal/ibm_cli.py).

Uso (na raiz do projeto):
    py -3.12 scripts\\coletar_ibm.py status
    py -3.12 scripts\\coletar_ibm.py --help
"""
import sys
from pathlib import Path

# O scripts/ não tem a raiz do projeto no caminho de importação; este lançador a acrescenta.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from eal.ibm_cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
