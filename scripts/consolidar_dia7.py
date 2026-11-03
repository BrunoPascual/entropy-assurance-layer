"""Consolida os resultados de E1 a E5 em CSV para o painel (último item do Dia 7).

Lê só CSVs já gerados em data/results e grava dois arquivos novos:

- consolidado_e1_e5.csv: formato longo, uma linha por experimento, chave e
  métrica; o valor é copiado como texto, sem reformatar nem recalcular;
  células vazias na origem não viram linha.
- consolidado_gate.csv: uma linha por experimento, com estado, número de
  métricas, arquivos de origem e ressalva fixa (só o que falta, sem números).

O viés por qubit e o excesso de leitura ficam nos dia6_*_por_qubit.csv e
dia6_*_excesso_leitura.csv; o painel lê esses arquivos direto.

Uso (na raiz do projeto):
    py -3.12 scripts/consolidar_dia7.py --conferir   # monta e mostra, não grava
    py -3.12 scripts/consolidar_dia7.py --gravar     # exige árvore limpa
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

RESULTS = Path("data/results")
OUT_LONG = "consolidado_e1_e5.csv"
OUT_GATE = "consolidado_gate.csv"
CAMPOS_LONG = ("experimento", "chave", "metrica", "valor", "unidade", "estado",
               "arquivo_origem", "sha256_origem")
CAMPOS_GATE = ("experimento", "estado", "n_metricas", "n_arquivos", "arquivos",
               "ressalva", "commit")
EXPERIMENTOS = ("E1", "E2", "E3", "E4", "E5")

# Estado e ressalva fixados antes de ler os dados; nenhum número aqui.
ESTADOS = {
    "E1": ("parcial", "deriva entre dias medida só contra a coleta 1; coleta 3 "
                      "contra a coleta 2 não feita"),
    "E2": ("completo", ""),
    "E3": ("completo", "custo teórico, sem gasto (Open Plan)"),
    "E4": ("completo", ""),
    "E5": ("parcial", "só etapa A, sem QPU; CHSH na QPU real não feito"),
}


def _por_lote(prefixos: dict[str, str]) -> dict[str, str]:
    return {f"{p}_lote{i}": u for p, u in prefixos.items() for i in (1, 2)}


UNIDADES: dict[str, str] = {
    # E1, resumo QPU contra simulador
    "n_qubits": "contagem", "n_shots": "contagem",
    **_por_lote({"frac1": "fração", "zp1_max_abs": "z", "zp1_n_acima3": "contagem",
                 "corr_viz_n_validos": "contagem", "corr_viz_max_abs": "correlação",
                 "corr_viz_n_acima3": "contagem", "corr_shot_n_validos": "contagem",
                 "corr_shot_max_abs": "correlação", "corr_shot_n_acima3": "contagem"}),
    "zdiff_n": "contagem", "zdiff_dp": "z", "zdiff_n_acima3": "contagem",
    "zdiff_max_abs": "z", "zdiff_max_pos": "índice", "zdiff_media": "z",
    # E1, saúde por lote
    "n_bits": "bits", "saude_h_estimated": "bits/bit", "saude_rct_pass": "booleano",
    "saude_apt_pass": "booleano", "saude_replay_pass": "booleano",
    "saude_h_health_pass": "booleano", "saude_stats_monobit": "p",
    "saude_stats_block": "p", "saude_stats_runs": "p", "saude_stats_pass": "booleano",
    "saude_approved": "booleano", "pipe_status": "texto",
    "ext_n_output_bits": "bits", "ext_rendimento": "fração",
    # E1, conjunto fixo
    "estimativa": "estimativa (ver tipo)", "se": "erro-padrão (ver tipo)", "z": "z",
    "z_esperado": "z", "testavel": "booleano", "sinal_igual": "booleano",
    "replica": "booleano", "zdiff_vs_coleta1": "z", "magnitude_compativel": "booleano",
    "erro_leitura": "fração", "excesso": "estimativa (ver tipo)",
    # E2
    "n_lotes": "contagem", "n_reprovados": "contagem", "taxa": "fração",
    "ic95_inf": "fração", "ic95_sup": "fração", "n_rct_falhou": "contagem",
    "n_apt_falhou": "contagem", "n_replay_falhou": "contagem",
    "n_h_falhou": "contagem", "n_stats_falhou": "contagem",
    "n_stats_inconclusivo": "contagem", "h_estimada_min": "bits/bit",
    "h_estimada_max": "bits/bit", "t_lote_mediana_s": "s",
    # E4
    "esperado": "texto", "n_seq": "contagem", "n_seq_completas": "contagem",
    "n_aprovadas": "contagem", "taxa_aprovacao": "fração",
    "sementes_total": "contagem", "recusadas_total": "contagem",
    "frac_alvo": "fração", "distintas_min": "contagem", "distintas_max": "contagem",
    "max_abs_z_max": "z", "pos_z5_min": "contagem", "pos_z5_max": "contagem",
    "falhas_forca_total": "contagem", "t_seq_mediana_s": "s",
    # E5
    "n_reps": "contagem", "s_media": "S", "s_dp": "S", "se_media": "S",
    "s_min": "S", "s_max": "S", "frac_s_maior_2": "fração", "margem": "S",
    "criterio_ok": "booleano",
}


@dataclass(frozen=True)
class Fonte:
    """Um CSV de origem: colunas que formam a chave e colunas copiadas."""
    experimento: str
    grupo: str
    arquivo: str
    chave: tuple[str, ...]
    valores: tuple[str, ...]
    longo: bool = False  # True: já é metrica,valor,unidade (E3)


RESUMO = ("n_qubits", "n_shots", *[f"{p}_lote{i}" for p in (
    "frac1", "zp1_max_abs", "zp1_n_acima3", "corr_viz_n_validos", "corr_viz_max_abs",
    "corr_viz_n_acima3", "corr_shot_n_validos", "corr_shot_max_abs",
    "corr_shot_n_acima3") for i in (1, 2)],
    "zdiff_n", "zdiff_dp", "zdiff_n_acima3", "zdiff_max_abs", "zdiff_max_pos")
LOTES = ("n_bits", "saude_h_estimated", "saude_rct_pass", "saude_apt_pass",
         "saude_replay_pass", "saude_h_health_pass", "saude_stats_monobit",
         "saude_stats_block", "saude_stats_runs", "saude_stats_pass",
         "saude_approved", "pipe_status", "ext_n_output_bits", "ext_rendimento")
ESTAB = ("n_qubits", "zdiff_media", "zdiff_dp", "zdiff_n_acima3", "zdiff_max_abs",
         "zdiff_max_pos")
FIXO = ("estimativa", "se", "z", "z_esperado", "testavel", "sinal_igual", "replica",
        "zdiff_vs_coleta1", "magnitude_compativel", "erro_leitura", "excesso")
COLETAS = (("1", "dia6_"), ("2", "dia6_coleta2_"), ("3", "dia6_coleta3_"))
DERIVAS = (("mesmo_dia", "dia6_deriva_dia_"),
           ("coleta2_vs_coleta1", "dia6_deriva_coleta2_"),
           ("coleta3_vs_coleta1", "dia6_deriva_coleta3_"))

FONTES: tuple[Fonte, ...] = (
    *[Fonte("E1", f"tabela=qpu_vs_sim_resumo;coleta={c}", f"{p}qpu_vs_sim_resumo.csv",
            ("fonte",), RESUMO) for c, p in COLETAS],
    *[Fonte("E1", f"tabela=qpu_vs_sim_lotes;coleta={c}", f"{p}qpu_vs_sim_lotes.csv",
            ("fonte", "lote"), LOTES) for c, p in COLETAS],
    *[Fonte("E1", f"tabela=deriva_estabilidade;deriva={d}", f"{p}estabilidade.csv",
            ("lote_a", "lote_b"), ESTAB) for d, p in DERIVAS],
    *[Fonte("E1", f"tabela=deriva_conjunto_fixo;deriva={d}", f"{p}conjunto_fixo.csv",
            ("tipo", "grupo", "id", "lote"), FIXO) for d, p in DERIVAS],
    Fonte("E2", "tabela=e2_resumo", "e2_resumo.csv",
          ("fonte", "parametro", "valor", "n_bits", "leitura", "tipo"),
          ("n_lotes", "n_reprovados", "taxa", "ic95_inf", "ic95_sup", "n_rct_falhou",
           "n_apt_falhou", "n_replay_falhou", "n_h_falhou", "n_stats_falhou",
           "n_stats_inconclusivo", "h_estimada_min", "h_estimada_max",
           "t_lote_mediana_s")),
    Fonte("E3", "tabela=e3_resumo", "e3_resumo.csv", (), (), longo=True),
    Fonte("E4", "tabela=e4_resumo", "e4_resumo.csv", ("cenario", "combinador", "k"),
          ("esperado", "n_seq", "n_seq_completas", "n_aprovadas", "taxa_aprovacao",
           "ic95_inf", "ic95_sup", "sementes_total", "recusadas_total", "frac_alvo",
           "distintas_min", "distintas_max", "max_abs_z_max", "pos_z5_min",
           "pos_z5_max", "falhas_forca_total", "t_seq_mediana_s")),
    Fonte("E5", "tabela=e5_resumo", "e5_resumo.csv", ("configuracao",),
          ("esperado", "n_reps", "s_media", "s_dp", "se_media", "s_min", "s_max",
           "frac_s_maior_2", "margem", "criterio_ok")),
)


class Recusa(Exception):
    """Algo não bateu; nada é gravado."""


def sha256(data: bytes) -> str:
    """SHA-256 em hex dos bytes."""
    return hashlib.sha256(data).hexdigest()


def ler_csv(path: Path, exigidas: tuple[str, ...]) -> tuple[list[dict[str, str]], str]:
    """Lê um CSV UTF-8 e devolve as linhas e o SHA-256 dos bytes em disco."""
    if not path.is_file():
        raise Recusa(f"arquivo ausente: {path.name}")
    data = path.read_bytes()
    try:
        texto = data.decode("utf-8")
    except UnicodeDecodeError:
        raise Recusa(f"não é UTF-8: {path.name}") from None
    leitor = csv.DictReader(io.StringIO(texto, newline=""))
    faltam = [c for c in exigidas if c not in (leitor.fieldnames or [])]
    if faltam:
        raise Recusa(f"{path.name}: colunas ausentes: {', '.join(faltam)}")
    linhas = list(leitor)
    if not linhas:
        raise Recusa(f"{path.name}: sem linhas")
    if any(None in l or None in l.values() for l in linhas):
        raise Recusa(f"{path.name}: linha com número de campos diferente do cabeçalho")
    return linhas, sha256(data)


def linhas_da_fonte(f: Fonte, results: Path) -> list[dict[str, str]]:
    """Linhas do formato longo vindas de um CSV de origem."""
    exigidas = ("metrica", "valor", "unidade") if f.longo else f.chave + f.valores
    linhas, digest = ler_csv(results / f.arquivo, exigidas)
    estado = ESTADOS[f.experimento][0]
    saida = []
    for linha in linhas:
        chave = ";".join([f.grupo, *[f"{c}={linha[c]}" for c in f.chave]])
        if f.longo:
            pares = [(linha["metrica"], linha["valor"], linha["unidade"])]
        else:
            pares = [(c, linha[c], UNIDADES[c]) for c in f.valores]
        for metrica, valor, unidade in pares:
            if valor == "":
                continue
            saida.append({"experimento": f.experimento, "chave": chave,
                          "metrica": metrica, "valor": valor, "unidade": unidade,
                          "estado": estado, "arquivo_origem": f.arquivo,
                          "sha256_origem": digest})
    return saida


def montar(results: Path, commit: str) -> tuple[list[dict], list[dict]]:
    """Monta as linhas dos dois CSVs; recusa chave repetida ou experimento vazio."""
    longo: list[dict] = []
    for f in FONTES:
        longo.extend(linhas_da_fonte(f, results))
    vistas: set[tuple[str, str, str]] = set()
    for l in longo:
        k = (l["experimento"], l["chave"], l["metrica"])
        if k in vistas:
            raise Recusa(f"chave repetida: {'|'.join(k)}")
        vistas.add(k)
    gate = []
    for e in EXPERIMENTOS:
        arquivos = sorted({f.arquivo for f in FONTES if f.experimento == e})
        n = sum(1 for l in longo if l["experimento"] == e)
        if n == 0:
            raise Recusa(f"{e} sem nenhuma métrica")
        estado, ressalva = ESTADOS[e]
        gate.append({"experimento": e, "estado": estado, "n_metricas": str(n),
                     "n_arquivos": str(len(arquivos)), "arquivos": ";".join(arquivos),
                     "ressalva": ressalva, "commit": commit})
    return longo, gate


def csv_bytes(campos: tuple[str, ...], linhas: list[dict]) -> bytes:
    """CSV em UTF-8 sem BOM, fim de linha LF."""
    buf = io.StringIO(newline="")
    w = csv.DictWriter(buf, fieldnames=campos, lineterminator="\n")
    w.writeheader()
    w.writerows(linhas)
    return buf.getvalue().encode("utf-8")


def estado_git() -> tuple[bool, str]:
    """(árvore limpa, commit atual) pelo git da pasta atual."""
    try:
        st = subprocess.run(["git", "status", "--porcelain"], capture_output=True,
                            text=True, check=True).stdout
        head = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True,
                              text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        raise Recusa("git indisponível ou pasta fora do repositório") from None
    return st.strip() == "", head


def gravar(results: Path, longo: bytes, gate: bytes) -> None:
    """Grava os dois arquivos, tudo ou nada; recusa se algum já existir."""
    destinos = [results / OUT_LONG, results / OUT_GATE]
    existentes = [p.name for p in destinos if p.exists()]
    if existentes:
        raise Recusa(f"já existe: {', '.join(existentes)}")
    feitos: list[Path] = []
    try:
        for p, dados in zip(destinos, (longo, gate)):
            with open(p, "xb") as fh:
                feitos.append(p)
                fh.write(dados)
    except BaseException:
        for p in feitos:
            p.unlink(missing_ok=True)
        raise


def mostrar(gate: list[dict]) -> None:
    """Imprime a tabela do gate."""
    for g in gate:
        print(f"{g['experimento']}  {g['estado']:<9} {g['n_metricas']:>5} métricas  "
              f"{g['n_arquivos']:>2} arquivos  {g['ressalva']}")


def main(argv: list[str] | None = None, results: Path = RESULTS,
         git: Callable[[], tuple[bool, str]] = estado_git) -> int:
    """Ponto de entrada; 0 ok, 1 recusa."""
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    modo = ap.add_mutually_exclusive_group(required=True)
    modo.add_argument("--conferir", action="store_true")
    modo.add_argument("--gravar", action="store_true")
    args = ap.parse_args(argv)
    try:
        limpa, commit = git()
        if args.gravar and not limpa:
            raise Recusa("árvore suja: faça commit do script antes de gravar")
        longo, gate = montar(results, commit)
        b_longo = csv_bytes(CAMPOS_LONG, longo)
        b_gate = csv_bytes(CAMPOS_GATE, gate)
        mostrar(gate)
        print(f"linhas no consolidado: {len(longo)}; commit {commit}")
        if args.gravar:
            gravar(results, b_longo, b_gate)
            print(f"gravado {OUT_LONG}: {sha256(b_longo)}")
            print(f"gravado {OUT_GATE}: {sha256(b_gate)}")
        else:
            print("conferência: nada gravado")
        print("gate do Dia 7: tabela com os 5 experimentos montada")
        return 0
    except Recusa as exc:
        print(f"RECUSADO: {exc}; nada gravado")
        return 1


if __name__ == "__main__":
    sys.exit(main())
