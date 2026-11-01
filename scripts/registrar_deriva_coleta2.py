"""Dia 6: registra no fim do PROJECT.md a coleta 2 e a deriva contra a coleta 1, gerado dos CSVs.

Nenhum número é digitado: tudo sai de data/results (inventário, saúde e os quatro CSVs de
analisar_deriva.py). Acrescenta um bloco ao FIM do PROJECT.md, entre marcadores, sem editar
nenhuma linha existente. Tudo ou nada:

- só grava se o SHA-256 atual do PROJECT.md for o do commit ca9e652 (HASH_ANTES);
- "já aplicado" quando o arquivo termina exatamente com o bloco e, sem ele, volta a HASH_ANTES;
- recusa sem gravar se faltar CSV ou coluna, se o hash for outro, se o marcador já existir, se o
  arquivo não for CRLF puro ou não terminar com fim de linha.

Classificação de cada item do conjunto fixo (critério do plano congelado da coleta 2):
  não testável (efeito esperado < 2,8 erros-padrão); replica (mesmo sinal, |z| > 2 e magnitude
  compatível); "direção reproduzida, magnitude não" (mesmo sinal e |z| > 2, magnitude
  incompatível); não replica (o resto).

Uso (na raiz do projeto):
    py -3.12 scripts\\registrar_deriva_coleta2.py
Código de saída: 0 aplicado ou já aplicado; 1 recusado (nada foi gravado).
"""
from __future__ import annotations

import csv
import hashlib
import os
import sys
from pathlib import Path

TARGET = Path("PROJECT.md")
RESULTS = Path("data/results")
HASH_ANTES = "295d7fa3e6f2abae2b2ac463354cec398abd4b17b947d84cee1f808b0f12c31e"
START = "<!-- dia6-coleta2:start -->"
END = "<!-- dia6-coleta2:end -->"

FILES = {
    "inventario": ("dia6_coleta2_inventario.csv", ("arquivo", "job_id", "n_bits", "uso_qpu_s")),
    "saude": ("dia6_coleta2_qpu_vs_sim_lotes.csv",
              ("fonte", "lote", "saude_approved", "saude_h_estimated", "ext_n_output_bits")),
    "lotes": ("dia6_deriva_coleta2_lotes.csv",
              ("lote", "sessao", "calibracao_no_envio", "calibracao_execucao", "retrato_leitura",
               "calibracao_igual_coleta1", "frac1")),
    "fixo": ("dia6_deriva_coleta2_conjunto_fixo.csv",
             ("tipo", "grupo", "id", "lote", "estimativa", "z", "z_esperado", "testavel",
              "sinal_igual", "replica", "magnitude_compativel")),
    "estab": ("dia6_deriva_coleta2_estabilidade.csv",
              ("lote_a", "lote_b", "zdiff_media", "zdiff_dp", "zdiff_n_acima3")),
}


class Refused(Exception):
    """Recusa: nada foi gravado."""


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ---------------------------------------------------------------- leitura

def read_csv(path: Path, columns: tuple[str, ...]) -> list[dict[str, str]]:
    if not path.is_file():
        raise Refused(f"CSV ausente: {path}")
    with open(path, encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        missing = [c for c in columns if c not in (reader.fieldnames or [])]
        if missing:
            raise Refused(f"{path.name}: faltam as colunas {missing}")
        rows = list(reader)
    if not rows:
        raise Refused(f"{path.name}: sem linhas")
    return rows


def load(results: Path) -> dict:
    facts: dict = {"sha": {}}
    for key, (name, cols) in FILES.items():
        facts[key] = read_csv(results / name, cols)
        facts["sha"][name] = sha256((results / name).read_bytes())
    return facts


# ---------------------------------------------------------------- formatação

def num(value: str, digits: int) -> str:
    if value == "":
        return "-"
    return f"{float(value):.{digits}f}".replace(".", ",")


def thousands(value: str) -> str:
    return f"{int(float(value)):,}".replace(",", ".")


def yes_no(value: str) -> str:
    return {"True": "sim", "False": "não", "": "-"}[value]


def table(header: list[str], rows: list[list[str]]) -> list[str]:
    out = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    out += ["| " + " | ".join(r) + " |" for r in rows]
    return out


def outcome(row: dict[str, str]) -> str:
    """Classificação de um lote comparado (linhas da coleta 1 não chegam aqui)."""
    if row["testavel"] == "False":
        return "não testável"
    if row["replica"] == "True":
        if row["magnitude_compativel"] == "True":
            return "replica"
        return "direção reproduzida, magnitude não"
    return "não replica"


def calibration_used(row: dict[str, str]) -> str:
    return row["calibracao_execucao"] or row["calibracao_no_envio"]


# ---------------------------------------------------------------- bloco

def render(facts: dict) -> str:
    inv, saude, lotes = facts["inventario"], facts["saude"], facts["lotes"]
    fixo, estab = facts["fixo"], facts["estab"]
    total_bits = sum(int(r["n_bits"]) for r in inv)
    total_uso = sum(float(r["uso_qpu_s"]) for r in inv)
    out = [START,
           "### Coleta 2 e deriva no mesmo dia (Dia 6, registro gerado dos CSVs)",
           "",
           "Gerado por `scripts/registrar_deriva_coleta2.py` a partir dos CSVs listados no fim "
           "deste bloco. Nenhum número foi digitado à mão. Os critérios são os do plano congelado "
           "da coleta 2, registrado antes do primeiro envio.",
           "",
           f"**Lotes da coleta 2 (inventário):** {len(inv)} lotes, {thousands(str(total_bits))} "
           f"bits, {num(str(total_uso), 0)} s de QPU.",
           ""]
    out += table(["Arquivo", "Job", "Bits", "Uso (s)"],
                 [[r["arquivo"], r["job_id"], thousands(r["n_bits"]), num(r["uso_qpu_s"], 0)]
                  for r in inv])
    out += ["", "**Saúde por lote (mesmo pipeline da coleta 1, limiar 0,9):**", ""]
    out += table(["Fonte", "Lote", "Aprovado", "H estimada", "Bits extraídos"],
                 [[r["fonte"], r["lote"], yes_no(r["saude_approved"]),
                   num(r["saude_h_estimated"], 6), thousands(r["ext_n_output_bits"] or "0")]
                  for r in saude])
    out += ["", "**Calibração e fração de 1 por lote:**", ""]
    out += table(["Lote", "Sessão", "Calibração em vigor", "Retrato de leitura",
                  "Igual à coleta 1", "Fração de 1"],
                 [[r["lote"], r["sessao"], calibration_used(r), r["retrato_leitura"],
                   yes_no(r["calibracao_igual_coleta1"]), num(r["frac1"], 4)] for r in lotes])
    compared = [r for r in fixo if r["testavel"] != ""]
    out += ["", "**Conjunto fixo, coleta 2 contra a coleta 1:**", ""]
    out += table(["Item", "Grupo", "Lote", "Estimativa", "z", "z esperado", "Resultado"],
                 [[f"{r['tipo']} {r['id']}", r["grupo"], r["lote"], num(r["estimativa"], 4),
                   num(r["z"], 2), num(r["z_esperado"], 2), outcome(r)] for r in compared])
    counts: dict[str, int] = {}
    for r in compared:
        counts[outcome(r)] = counts.get(outcome(r), 0) + 1
    out += ["", "Contagem: " + "; ".join(f"{k}: {v}" for k, v in sorted(counts.items())) + "."]
    out += ["", "**Estabilidade entre pares de lotes (zdiff dos qubits):**", ""]
    out += table(["Lote A", "Lote B", "Média", "Desvio-padrão", "Qubits acima de 3"],
                 [[r["lote_a"], r["lote_b"], num(r["zdiff_media"], 3), num(r["zdiff_dp"], 3),
                   r["zdiff_n_acima3"]] for r in estab])
    ref = {calibration_used(r) for r in lotes if r["sessao"] == "coleta1"}
    other = sorted({calibration_used(r) for r in lotes
                    if r["sessao"] != "coleta1" and r["calibracao_igual_coleta1"] == "False"})
    out += ["", "**Limites:**", ""]
    if other:
        out.append(f"- A coleta 2 rodou sob outra calibração ({', '.join(other)}) que a coleta 1 "
                   f"({', '.join(sorted(ref))}). A diferença entre as coletas mistura o tempo "
                   "decorrido e a troca de calibração, e estes dados não separam os dois.")
    else:
        out.append("- A coleta 2 rodou sob a mesma calibração da coleta 1.")
    out += ["- O critério de réplica (mesmo sinal e |z| > 2) é fraco; por isso a magnitude é "
            "relatada à parte.",
            "- Isto é um registro de medições. A causa de qualquer diferença (leitura, porta, "
            "relaxação, calibração ou outra) não é afirmada aqui.",
            "", "**CSVs (SHA-256 dos bytes em disco):**", ""]
    out += [f"- `{name}`: `{digest}`" for name, digest in sorted(facts["sha"].items())]
    out.append(END)
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------- aplicação

def tail_bytes(block: str) -> bytes:
    return b"\r\n" + block.replace("\n", "\r\n").encode("utf-8")


def build(data: bytes, block: str) -> bytes:
    rest = data.replace(b"\r\n", b"")
    if b"\r\n" not in data or b"\n" in rest or b"\r" in rest:
        raise Refused("o arquivo não é CRLF puro")
    if not data.endswith(b"\r\n"):
        raise Refused("o arquivo não termina com fim de linha")
    for marker in (START, END):
        if marker.encode("utf-8") in data:
            raise Refused(f"o marcador {marker} já existe")
    return data + tail_bytes(block)


def apply(path: Path, block: str, antes: str = HASH_ANTES) -> str:
    data = path.read_bytes()
    t = tail_bytes(block)
    if data.endswith(t) and sha256(data[:-len(t)]) == antes:
        return "ja aplicado"
    if sha256(data) != antes:
        raise Refused(f"SHA-256 atual {sha256(data)} difere do esperado {antes}")
    new = build(data, block)
    tmp = path.with_name(path.name + ".tmp_coleta2")
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


def main(path: Path = TARGET, results: Path = RESULTS) -> int:
    try:
        block = render(load(results))
        before = sha256(path.read_bytes())
        state = apply(path, block)
    except (Refused, OSError, ValueError, KeyError) as exc:
        print(f"RECUSADO (nada foi gravado): {type(exc).__name__}: {exc}")
        return 1
    after = sha256(path.read_bytes())
    if state == "ja aplicado":
        print(f"já aplicado: {path} já tem o bloco (SHA-256 {after.upper()}); nada foi gravado")
    else:
        print(f"aplicado:\n{path}: SHA-256 antes {before.upper()}; SHA-256 depois {after.upper()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
