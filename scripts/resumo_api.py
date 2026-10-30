"""Resume a API de arquivos Python: classes, campos, assinaturas e constantes.

Não mostra o corpo das funções, então a saída fica pequena e serve para colar
no chat. Para um trecho completo, use --full com o nome da classe ou função.

Uso, a partir da raiz do projeto:
  py -3.12 scripts\\resumo_api.py eal\\mix\\mixer.py eal\\config.py --out resumo_api.txt
  py -3.12 scripts\\resumo_api.py eal\\mix\\mixer.py --full MixResult --out trecho.txt
"""
from __future__ import annotations

import argparse
import ast
from pathlib import Path

MAX = 110  # largura máxima de cada linha gerada


def short(node: ast.AST | None) -> str:
    """Texto de um nó do AST, truncado para não inflar a saída."""
    if node is None:
        return ""
    text = ast.unparse(node)
    return text if len(text) <= MAX else text[: MAX - 3] + "..."


def first_doc_line(node: ast.AST) -> str:
    doc = ast.get_docstring(node)
    return doc.splitlines()[0] if doc else ""


def signature(fn: ast.FunctionDef | ast.AsyncFunctionDef, indent: str) -> list[str]:
    prefix = "async def" if isinstance(fn, ast.AsyncFunctionDef) else "def"
    lines = [f"{indent}@{short(d)}" for d in fn.decorator_list]
    ret = f" -> {short(fn.returns)}" if fn.returns else ""
    lines.append(f"{indent}{prefix} {fn.name}({short(fn.args)}){ret}:")
    doc = first_doc_line(fn)
    if doc:
        lines.append(f'{indent}    "{doc}"')
    return lines


def describe_class(cls: ast.ClassDef) -> list[str]:
    bases = ", ".join(short(b) for b in cls.bases)
    lines = [f"@{short(d)}" for d in cls.decorator_list]
    lines.append(f"class {cls.name}({bases}):" if bases else f"class {cls.name}:")
    doc = first_doc_line(cls)
    if doc:
        lines.append(f'    "{doc}"')
    for stmt in cls.body:
        if isinstance(stmt, ast.AnnAssign):
            value = f" = {short(stmt.value)}" if stmt.value is not None else ""
            lines.append(f"    {short(stmt.target)}: {short(stmt.annotation)}{value}")
        elif isinstance(stmt, ast.Assign):
            targets = ", ".join(short(t) for t in stmt.targets)
            lines.append(f"    {targets} = {short(stmt.value)}")
        elif isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
            lines += signature(stmt, "    ")
    return lines


def describe_module(tree: ast.Module) -> list[str]:
    lines: list[str] = []
    for stmt in tree.body:
        if isinstance(stmt, ast.ClassDef):
            lines += ["", *describe_class(stmt)]
        elif isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
            lines += ["", *signature(stmt, "")]
        elif isinstance(stmt, ast.ImportFrom) and (stmt.module or "").startswith("eal"):
            names = ", ".join(a.name for a in stmt.names)
            lines.append(f"from {stmt.module} import {names}")
        elif isinstance(stmt, ast.Assign):
            targets = ", ".join(short(t) for t in stmt.targets)
            lines.append(f"{targets} = {short(stmt.value)}")
        elif isinstance(stmt, ast.AnnAssign):
            value = f" = {short(stmt.value)}" if stmt.value is not None else ""
            lines.append(f"{short(stmt.target)}: {short(stmt.annotation)}{value}")
    return lines


def full_source(source: str, tree: ast.Module, name: str) -> list[str]:
    """Código completo de uma classe ou função de primeiro nível."""
    for stmt in tree.body:
        if getattr(stmt, "name", None) == name:
            return [ast.get_source_segment(source, stmt) or f"(sem trecho para {name})"]
    return [f"(nome {name!r} não encontrado no nível superior)"]


def process(path: Path, full: str | None) -> list[str]:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    header = [f"===== {path.as_posix()} ({len(source.splitlines())} linhas) ====="]
    body = full_source(source, tree, full) if full else describe_class_or_module(tree)
    return header + body + [""]


def describe_class_or_module(tree: ast.Module) -> list[str]:
    return describe_module(tree)


def main() -> int:
    parser = argparse.ArgumentParser(description="Resumo de API de arquivos Python.")
    parser.add_argument("files", nargs="+", type=Path)
    parser.add_argument("--full", metavar="NOME", help="imprime o código completo deste nome")
    parser.add_argument("--out", type=Path, help="grava em arquivo UTF-8 em vez de imprimir")
    args = parser.parse_args()
    lines: list[str] = []
    for path in args.files:
        lines += process(path, args.full)
    text = "\n".join(lines) + "\n"
    if args.out:
        args.out.write_text(text, encoding="utf-8")
        print(f"gravado: {args.out} ({len(lines)} linhas)")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
