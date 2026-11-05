"""Carga de dados do painel (Dia 8). Sem Streamlit: só lê arquivos e devolve DataFrames.

Regra do projeto: todo número mostrado vem de um arquivo em data/results ou data/receipts.
Nada é digitado à mão aqui. Funções que não acham o arquivo levantam FileNotFoundError.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from eal.config import ISSUER_PK_NAME, RECEIPT_CHAIN_NAME
from eal.receipt.chain import verify_chain
from eal.receipt.sign import load_issuer_public_key
from eal.receipt.verify import verify_receipt

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "data" / "results"
RECEIPTS = ROOT / "data" / "receipts"
KEYS = ROOT / "keys"

# Coleta -> prefixo dos CSVs do Dia 6 e 7 (a coleta 1 não tem prefixo no nome).
COLETAS: dict[int, str] = {1: "dia6_", 2: "dia6_coleta2_", 3: "dia6_coleta3_"}
FONTES_ROTULO = {"qpu_real": "QPU real (ibm_kingston)", "simulador": "Simulador com ruído", "os": "Sistema operacional"}

HEALTH_COLS = {
    "saude_rct_pass": "RCT",
    "saude_apt_pass": "APT",
    "saude_replay_pass": "Replay",
    "saude_h_health_pass": "Min-entropia",
    "saude_stats_pass": "SP 800-22",
    "saude_approved": "Aprovado",
}


def _read(name: str, results: Path = RESULTS) -> pd.DataFrame:
    path = Path(results) / name
    if not path.is_file():
        raise FileNotFoundError(f"arquivo de resultados ausente: {path.name}")
    return pd.read_csv(path, encoding="utf-8-sig")


def load_lotes(results: Path = RESULTS) -> pd.DataFrame:
    """Um registro por lote das 3 coletas: saúde, pipeline e extração (coluna `coleta` acrescentada)."""
    frames = []
    for coleta, prefix in COLETAS.items():
        df = _read(f"{prefix}qpu_vs_sim_lotes.csv", results)
        df.insert(0, "coleta", coleta)
        frames.append(df)
    return pd.concat(frames, ignore_index=True)


def fontes_resumo(lotes: pd.DataFrame) -> pd.DataFrame:
    """Fontes, tipo e quantos lotes passaram nos testes de saúde (contagens dos próprios lotes)."""
    g = lotes.groupby("fonte")
    out = pd.DataFrame(
        {
            "Fonte": [FONTES_ROTULO.get(f, f) for f in g.size().index],
            "Simulada": g["is_simulated"].first().astype(bool).map({True: "sim", False: "não"}).values,
            "Lotes": g.size().values,
            "Aprovados": g["saude_approved"].sum().astype(int).values,
            "Bits extraídos": g["ext_n_output_bits"].sum().astype(int).values,
        }
    )
    out["Aprovação"] = (out["Aprovados"] / out["Lotes"]).round(3)
    return out


def saude_por_lote(lotes: pd.DataFrame) -> pd.DataFrame:
    """Tabela de saúde: um teste por coluna, motivo de reprovação e estado no pipeline."""
    cols = ["coleta", "fonte", "lote", *HEALTH_COLS, "saude_h_estimated", "pipe_status", "saude_reasons"]
    out = lotes[cols].rename(
        columns={**HEALTH_COLS, "coleta": "Coleta", "fonte": "Fonte", "lote": "Lote",
                 "saude_h_estimated": "H estimada", "pipe_status": "Pipeline", "saude_reasons": "Motivo"}
    )
    out["Fonte"] = out["Fonte"].map(lambda f: FONTES_ROTULO.get(f, f))
    return out.fillna({"Motivo": ""})


def min_entropia(lotes: pd.DataFrame) -> tuple[pd.DataFrame, float]:
    """H estimada por lote e o limiar do projeto (coluna saude_h_threshold, igual em todas as linhas)."""
    limiares = lotes["saude_h_threshold"].dropna().unique()
    if len(limiares) != 1:
        raise ValueError(f"limiar de min-entropia não é único nos dados: {list(limiares)}")
    df = lotes[["coleta", "fonte", "lote", "saude_h_estimated"]].copy()
    df["lote_id"] = "C" + df["coleta"].astype(str) + "·L" + df["lote"].astype(str)
    df["fonte"] = df["fonte"].map(lambda f: FONTES_ROTULO.get(f, f))
    return df.rename(columns={"saude_h_estimated": "h_estimada"}), float(limiares[0])


def vies_por_qubit(coleta: int, results: Path = RESULTS) -> pd.DataFrame:
    """P(1) por qubit, QPU real e simulador, com o z contra 0,5 (arquivo por_qubit da coleta)."""
    df = _read(f"{COLETAS[coleta]}qpu_vs_sim_por_qubit.csv", results)
    return df[["fonte", "lote", "posicao", "qubit_fisico", "p1", "z_p1", "erro_leitura"]]


def deriva_resumo(results: Path = RESULTS) -> pd.DataFrame:
    """Estabilidade entre lotes: mesmo dia, coleta 2 e coleta 3 contra a coleta 1."""
    nomes = {"mesmo_dia": "deriva_dia", "coleta2_vs_coleta1": "deriva_coleta2", "coleta3_vs_coleta1": "deriva_coleta3"}
    frames = []
    for rotulo, base in nomes.items():
        df = _read(f"dia6_{base}_estabilidade.csv", results)
        df.insert(0, "comparacao", rotulo)
        frames.append(df)
    return pd.concat(frames, ignore_index=True)


def experimentos_gate(results: Path = RESULTS) -> pd.DataFrame:
    """Tabela do gate do Dia 7: estado e ressalva de cada experimento."""
    return _read("consolidado_gate.csv", results)[["experimento", "estado", "n_metricas", "ressalva"]].fillna("")


def e2(results: Path = RESULTS) -> pd.DataFrame:
    return _read("e2_resumo.csv", results)


def e3(results: Path = RESULTS) -> pd.DataFrame:
    return _read("e3_resumo.csv", results)


def e4(results: Path = RESULTS) -> pd.DataFrame:
    return _read("e4_resumo.csv", results)


def e5(results: Path = RESULTS) -> pd.DataFrame:
    return _read("e5_resumo.csv", results)


# ---------------------------------------------------------------- recibos

@dataclass(frozen=True)
class ReceiptView:
    """Último recibo da cadeia, só com hashes e metadados (nunca semente nem chave privada)."""

    receipt: dict
    position: int
    chain_length: int


def last_receipt(receipts: Path = RECEIPTS) -> ReceiptView:
    """Lê a última linha de chain.jsonl. Levanta FileNotFoundError se o log não existir ou estiver vazio."""
    log = Path(receipts) / RECEIPT_CHAIN_NAME
    if not log.is_file():
        raise FileNotFoundError(f"{RECEIPT_CHAIN_NAME} ausente em {receipts}")
    lines = [ln for ln in log.read_bytes().split(b"\n") if ln.strip()]
    if not lines:
        raise FileNotFoundError("cadeia de recibos vazia")
    return ReceiptView(json.loads(lines[-1]), len(lines), len(lines))


def receipt_sources(receipt: dict) -> pd.DataFrame:
    """Fontes do recibo: estado, aprovação e motivos."""
    rows = [
        {"Fonte": s.get("source_id"), "Tipo": s.get("source_type"), "Estado": s.get("status"),
         "Aprovada": bool(s.get("approved")), "Motivos": "; ".join(s.get("reasons") or [])}
        for s in receipt.get("sources", [])
    ]
    return pd.DataFrame(rows, columns=["Fonte", "Tipo", "Estado", "Aprovada", "Motivos"])


@dataclass(frozen=True)
class Verification:
    ok: bool
    reasons: tuple[str, ...]
    chain_length: int
    head: str


def verify_last(receipts: Path = RECEIPTS, keys: Path = KEYS) -> Verification:
    """Confere a assinatura do último recibo e a cadeia inteira, com a chave pública do emissor."""
    pk = load_issuer_public_key(Path(keys) / ISSUER_PK_NAME)
    view = last_receipt(receipts)
    one = verify_receipt(view.receipt, pk)
    chain = verify_chain(Path(receipts), pk)
    return Verification(one.ok and chain.ok, one.reasons + chain.reasons, chain.length, chain.head)
