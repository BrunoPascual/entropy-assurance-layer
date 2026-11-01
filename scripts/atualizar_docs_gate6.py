"""Dia 6, R6: registra no PROJECT.md o resultado do gate do Dia 6 (coleta 1).

Script de uso único. Acrescenta um bloco ao FIM do PROJECT.md, entre marcadores, sem editar
nenhuma linha existente. Os números do bloco saem de ``data/results/dia6_coleta1_inventario.csv``
(gerado por ``scripts/inventario_coleta1.py``); nada é digitado à mão.

Tudo ou nada:

- só grava se o SHA-256 atual do PROJECT.md for o do commit 80837a0 (HASH_ANTES);
- se o arquivo já tiver exatamente esse conteúdo mais o bloco gerado do CSV atual, diz "já
  aplicado" e não grava nada;
- recusa sem gravar se o hash for outro, se o CSV faltar ou tiver colunas diferentes, se algum
  marcador já existir ou se o arquivo não for CRLF puro;
- grava num arquivo temporário na mesma pasta e troca com os.replace.

Uso (na raiz do projeto):
    py -3.12 scripts\\atualizar_docs_gate6.py
Código de saída: 0 aplicado ou já aplicado; 1 recusado (nada foi gravado).
"""
from __future__ import annotations

import csv
import hashlib
import io
import os
import sys
from pathlib import Path

TARGET = Path("PROJECT.md")
CSV_PATH = Path("data/results/dia6_coleta1_inventario.csv")
HASH_ANTES = "b18c74058405e4d04c82f988e4f9d523551f64d843f5bbfa124e8c873deeb55a"
META_BITS = 3_000_192  # meta do plano congelado da coleta 1 (commit 80837a0)
START = "<!-- dia6-gate:start -->"
END = "<!-- dia6-gate:end -->"
COLUMNS = ("arquivo", "job_id", "backend", "qubits", "shots", "n_bits", "uso_qpu_s",
           "reserva_s", "calibracao", "npy_sha256", "json_sha256")
BACKUP = r"C:\projeto\ancoras\coleta1_2026-11-01"


class Refused(Exception):
    """Recusa: nada foi gravado."""


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def pt(n: int) -> str:
    """Inteiro com ponto de milhar (3000192 -> 3.000.192)."""
    return f"{n:,}".replace(",", ".")


def pt_s(x: float) -> str:
    """Segundos com vírgula decimal (5.0 -> 5; 2.5 -> 2,5)."""
    return f"{x:g}".replace(".", ",")


def read_csv(data: bytes) -> list[dict[str, str]]:
    """Linhas do inventário; levanta Refused se o CSV não tiver o formato esperado."""
    try:
        rows = list(csv.reader(io.StringIO(data.decode("utf-8"), newline="")))
    except (UnicodeDecodeError, csv.Error) as exc:
        raise Refused(f"CSV ilegível ({exc})") from None
    if not rows or tuple(rows[0]) != COLUMNS:
        raise Refused("CSV com cabeçalho diferente do esperado")
    body = [dict(zip(COLUMNS, r)) for r in rows[1:]]
    if not body or any(len(r) != len(COLUMNS) for r in rows[1:]):
        raise Refused("CSV sem linhas ou com linha de tamanho errado")
    try:
        for r in body:
            int(r["n_bits"]), int(r["shots"]), int(r["qubits"]), float(r["uso_qpu_s"])
    except ValueError:
        raise Refused("CSV com número inválido") from None
    return body


def make_block(csv_bytes: bytes, csv_name: str) -> str:
    """Texto do bloco (com \\n), gerado só a partir do CSV."""
    rows = read_csv(csv_bytes)
    total = sum(int(r["n_bits"]) for r in rows)
    uso = sum(float(r["uso_qpu_s"]) for r in rows)
    backends = sorted({r["backend"] for r in rows})
    qubits = sorted({int(r["qubits"]) for r in rows})
    result = "ATINGIDO" if total >= META_BITS else "NÃO ATINGIDO"
    lines = [
        START,
        "### Resultado do gate do Dia 6 (coleta 1)",
        "",
        f"Gerado por `scripts/atualizar_docs_gate6.py` a partir de `{csv_name}` "
        f"(SHA-256 `{sha256(csv_bytes)}`), que sai de `scripts/inventario_coleta1.py`. "
        "Os números abaixo vêm desse arquivo.",
        "",
        f"- **Resultado:** {result}. {pt(total)} bits reais da QPU salvos em `data/raw`, "
        f"sessão `coleta1`; a meta do plano congelado era {pt(META_BITS)}.",
        f"- **Lotes:** {len(rows)}, backend {', '.join(backends)}, "
        f"{', '.join(str(q) for q in qubits)} qubits.",
    ]
    for r in rows:
        lines.append(
            f"  - `{r['arquivo']}`: job `{r['job_id']}`, {pt(int(r['shots']))} shots, "
            f"{pt(int(r['n_bits']))} bits, uso {pt_s(float(r['uso_qpu_s']))} s, "
            f"SHA-256 do `.npy` `{r['npy_sha256']}`.")
    lines += [
        f"- **Uso de QPU da coleta 1:** {pt_s(uso)} s no total.",
        "- **Critérios de parada:** nenhum disparou; status DONE, conversão e params do lote OK "
        "e nenhum aviso de duplicata, conferidos com `inspecionar_job_ibm.py` em cada job.",
        f"- **Cópia dos dados crus:** `{BACKUP}`, com SHA-256 conferido arquivo a arquivo. "
        "`data/raw` não é versionado.",
        "- **Fica para depois:** reorganizar as seções 6.12, 9.3, 9.4 e 17 (R11), mudar o campo "
        "Status (R12) e analisar os dados no E1.",
        END,
        "",
    ]
    return "\n".join(lines)


def build(data: bytes, block: str) -> bytes:
    """Conteúdo novo: o arquivo atual, uma linha em branco e o bloco. Levanta Refused."""
    rest = data.replace(b"\r\n", b"")
    if b"\r\n" not in data or b"\n" in rest or b"\r" in rest:
        raise Refused("o arquivo não é CRLF puro")
    if not data.endswith(b"\r\n"):
        raise Refused("o arquivo não termina com fim de linha")
    for marker in (START, END):
        if marker.encode("utf-8") in data:
            raise Refused(f"o marcador {marker} já existe")
    return data + b"\r\n" + block.replace("\n", "\r\n").encode("utf-8")


def apply(path: Path, csv_path: Path, antes: str = HASH_ANTES) -> str:
    """Aplica em ``path``; devolve 'aplicado' ou 'ja aplicado'. Levanta Refused."""
    if not csv_path.exists():
        raise Refused(f"falta {csv_path} (rode antes scripts/inventario_coleta1.py)")
    block = make_block(csv_path.read_bytes(), csv_path.as_posix())
    data = path.read_bytes()
    if sha256(data) != antes:
        cut = data.find(b"\r\n" + START.encode("utf-8"))
        if cut >= 0 and sha256(data[:cut]) == antes and data == build(data[:cut], block):
            return "ja aplicado"
        raise Refused(f"SHA-256 atual {sha256(data)} difere do esperado {antes}")
    new = build(data, block)
    tmp = path.with_name(path.name + ".tmp_gate6")
    try:
        with open(tmp, "xb") as fh:
            fh.write(new)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()
    return "aplicado"


def main(path: Path = TARGET, csv_path: Path = CSV_PATH) -> int:
    try:
        before = sha256(path.read_bytes())
        state = apply(path, csv_path)
    except (Refused, OSError) as exc:
        print(f"RECUSADO (nada foi gravado): {exc}")
        return 1
    after = sha256(path.read_bytes()).upper()
    if state == "ja aplicado":
        print(f"já aplicado: {path} já tem o bloco do gate (SHA-256 {after}); nada foi gravado")
    else:
        print(f"aplicado:\n{path}: SHA-256 antes {before.upper()}; SHA-256 depois {after}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
