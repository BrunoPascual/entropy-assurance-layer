"""Dia 6: registra o estado ao fim da etapa 5 (PROJECT.md e JSON para o próximo chat).

Faz duas coisas, juntas ou nenhuma:
  1. acrescenta ao PROJECT.md o bloco ``<!-- dia6-estado:start -->`` ... ``<!-- dia6-estado:end -->``,
     logo depois de ``<!-- dia6-e1parcial:end -->``;
  2. grava ``estado_dia6_fim_etapa5.json`` para abrir o chat da coleta 2.

Nenhum número é digitado: commits e branch vêm do git; hashes, bits e uso de QPU vêm dos CSVs de
``data/results``; limites de orçamento vêm de ``eal.config``. O único valor informado por quem
roda é ``--suite`` (o resultado da suíte completa, colado do terminal).

Regras:
  - por padrão só mostra o que seria gravado; ``--aplicar`` grava;
  - árvore do git precisa estar limpa (o estado tem de bater com o HEAD);
  - o bloco depende do git no momento da execução, então não é recalculado: se o bloco já existe,
    nada é feito e nada é sobrescrito; se o JSON já existe sem o bloco, recusa;
  - preserva o fim de linha do PROJECT.md (CRLF ou LF); fim de linha misto recusa;
  - não mexe no campo Status (R12 depende do R11) nem nas demais seções.

Uso (na raiz do projeto, com o git no PATH):
    py -3.12 scripts\\atualizar_estado_dia6.py --suite "NNNN passed, 1 skipped"
    py -3.12 scripts\\atualizar_estado_dia6.py --suite "NNNN passed, 1 skipped" --aplicar
Código de saída: 0 ok; 1 recusado; 2 erro de uso.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import date
from pathlib import Path
from typing import Any, Callable

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_HERE.parent))
import atualizar_docs_e1parcial as doc  # noqa: E402
from eal import config  # noqa: E402

PROJECT_PATH = Path("PROJECT.md")
RESULTS_DIR = Path("data/results")
JSON_PATH = Path("estado_dia6_fim_etapa5.json")
BASE_DEFAULT = "23d328a"
START = "<!-- dia6-estado:start -->"
END = "<!-- dia6-estado:end -->"
ANCHOR = doc.END
SUITE_RE = re.compile(r"[0-9]+ passed(, [0-9]+ skipped)?")
SUITE_COMMAND = "py -3.12 -m pytest -q"

PENDENCIAS: tuple[tuple[str, str, str], ...] = (
    ("T11", "checagem de segredos (T11) sobre todos os commits da lista acima; o usuário ainda não "
            "confirmou a saída dela nos commits feitos nesta fase", "antes de qualquer novo commit"),
    ("COLETA2", "coleta 2 em outro horário do dia, para medir deriva (seção 9.3): plano congelado no "
                "PROJECT.md antes do primeiro envio; só o usuário envia, com comando explícito e SIM",
     "próxima etapa"),
    ("DEP_SESSAO", "inventario_coleta1.py, analisar_coleta1.py e analisar_cal.py fixam a sessão "
                   "coleta1 (e o prefixo coleta1_); parametrizar a sessão antes de analisar a coleta 2 "
                   "(muda código: precisa de plano e aprovação)", "antes de analisar a coleta 2"),
    ("R8", "gravar o retrato da calibração da execução em cada lote; sem isso a deriva por tempo e "
           "por calibração não se separa (o registro da seção 18 diz que o cal_001 rodou sob uma "
           "calibração diferente da data gravada no lote)", "antes da coleta 2"),
    ("CRITERIO_REPLICA", "o critério 'replica' (mesmo sinal e |z| > 2) é fraco: onde a magnitude é "
                         "incompatível, relatar 'direção reproduzida, magnitude não'", "ao escrever o relatório"),
    ("R11", "reorganizar as seções 6.12, 9.3, 9.4 e 17 do PROJECT.md com o conteúdo dos blocos "
            "acrescentados ao fim (dia6-e1parcial e dia6-estado incluídos)", "antes de mudar o Status"),
    ("R12", "campo Status do PROJECT.md ainda diz Dia 5 de 9; atualizar depois do R11", "depois do R11"),
    ("BACKUP_RESULTADOS", "copiar data/results para C:\\projeto\\ancoras (os dados crus já têm cópia "
                          "em coleta1_2026-11-01)", "baixa"),
    ("COLETA3", "coleta 3 (deriva entre dias), seção 9.3: decisão do usuário; vem antes da coleta 2 "
                "na ordem de cortes da seção 16", "decidir antes do Dia 7"),
    ("R7", "copiar data\\logs\\replay_history.json para C:\\projeto\\ancoras após o primeiro eal run real",
     "depois do primeiro eal run real"),
    ("R9", "trocar SamplerV2 pelo executor_sampler.Sampler antes de qualquer atualização do pacote",
     "baixa, versão fixada"),
    ("R10", "limpeza: texto 'disponível para um job' do status ignora o limite de 60 s; "
            "RuntimeJobNotFound aparece como erro inesperado; entrada de log do dry-run recusado", "baixa"),
    ("T_TEMPO", "test_noisy_million_bits_fast depende da velocidade da máquina; registrar como "
                "limitação na seção 17", "junto com o R11"),
)

REGRAS = [
    "não alterar código sem aprovação explícita do usuário",
    "não escrever código antes de plano em até 5 linhas, arquivos afetados e forma de teste",
    "todo arquivo entregue é conferido por SHA-256 antes de copiar; blocos PowerShell confirmam o hash e só copiam se bater",
    "scripts de alteração: uso único, tudo ou nada, idempotentes, preservam CRLF ou LF, recusam sem gravar se algo não bater",
    "git add por nome de arquivo, nunca git add .; checagem de segredos (T11) antes de cada commit; commit só com árvore limpa",
    "não usar sed em blocos PowerShell; trocar texto com Python",
    "não adivinhar nomes de campos, flags ou cálculos: ler o código ou a saída real antes",
    "ao fim de cada bloco, indicar modelo e intensidade do Claude para o próximo bloco",
    "gasto de QPU: só o usuário envia, com comando explícito e SIM; o assistente não roda CLI da IBM nem testes da suíte real",
    "todo número do relatório e do PROJECT.md sai de um CSV em data/results gerado por script; nada digitado à mão (seção 11)",
    "texto com acento passado ao Python por stdin no PowerShell sai trocado; usar escapes \\uXXXX ou um arquivo",
    "o assistente só diz que testou o que de fato rodou e diz o que não rodou (o ambiente dele não tem o repositório)",
    "critérios de análise (conjunto de qubits, limiares) são fixados no código antes de ler os dados novos",
]

LIMITACOES_ASSISTENTE = [
    "não roda a CLI, o pipeline nem os testes da suíte real: vale só a saída colada pelo usuário",
    "não acessa a conta IBM nem a QPU",
    "os módulos reconstruídos no ambiente do assistente são aproximações; a verdade é a suíte do usuário",
]


class StateError(Exception):
    """Recusa: nada foi gravado."""


# ---------------------------------------------------------------- git

def run_git(*args: str) -> str:
    try:
        p = subprocess.run(["git", *args], capture_output=True, text=True, encoding="utf-8")
    except OSError:
        raise StateError("git não encontrado no PATH") from None
    if p.returncode != 0:
        raise StateError(f"git {args[0]} falhou")
    return p.stdout


def git_info(git: Callable[..., str], base: str) -> dict[str, Any]:
    if git("status", "--porcelain").strip():
        raise StateError("árvore do git com alterações; commite antes de registrar o estado")
    git("cat-file", "-e", f"{base}^{{commit}}")
    commits = []
    for line in git("log", "--reverse", "--format=%h%x09%s", f"{base}..HEAD").splitlines():
        if line.strip():
            h, _, s = line.partition("\t")
            commits.append({"hash": h, "titulo": s})
    if not commits:
        raise StateError("nenhum commit depois da base")
    return {"branch": git("rev-parse", "--abbrev-ref", "HEAD").strip(),
            "head": git("rev-parse", "--short", "HEAD").strip(), "base": base, "commits": commits}


# ---------------------------------------------------------------- fatos dos CSVs

def _g(x: float) -> str:
    return f"{x:g}"


def read_facts(results_dir: Path) -> dict[str, Any]:
    inv = doc.read_csv(results_dir / "dia6_coleta1_inventario.csv", ("job_id", "n_bits", "uso_qpu_s"))
    lotes = doc.read_csv(results_dir / "dia6_qpu_vs_sim_lotes.csv",
                         ("fonte", "lote", "saude_approved", "saude_h_estimated", "ext_n_output_bits"))
    fixo = doc.read_csv(results_dir / "dia6_deriva_dia_conjunto_fixo.csv",
                        ("tipo", "grupo", "id", "lote", "testavel", "replica"))
    coleta1 = {"jobs": [r["job_id"] for r in inv],
               "bits_totais": sum(doc._int(r["n_bits"], "inventario n_bits") for r in inv),
               "uso_qpu_s": sum(doc._flt(r["uso_qpu_s"], "inventario uso_qpu_s") for r in inv)}
    saude = []
    for r in sorted(lotes, key=lambda r: (doc.FONTES.index(r["fonte"]), r["lote"])):
        w = f"lotes {r['fonte']} {r['lote']}"
        saude.append({"fonte": r["fonte"], "lote": r["lote"],
                      "aprovado": doc._bool(r["saude_approved"], w),
                      "h_estimada": round(doc._flt(r["saude_h_estimated"], w), 6),
                      "bits_extraidos": doc._int(r["ext_n_output_bits"], w)})
    items: dict[tuple[str, str], list[dict[str, str]]] = {}
    for r in fixo:
        if r["lote"].startswith("cal_"):
            items.setdefault((r["tipo"], r["id"]), []).append(r)
    if not items:
        raise StateError("conjunto fixo sem linhas de lotes cal")
    cal = []
    for (tipo, ident), rs in items.items():
        cal.append({"item": f"{tipo} {ident}", "grupo": rs[0]["grupo"],
                    "replica_em": [r["lote"] for r in rs if doc._bool(r["replica"], "replica") is True],
                    "nao_replica_em": [r["lote"] for r in rs if doc._bool(r["replica"], "replica") is False],
                    "nao_testavel_em": [r["lote"] for r in rs if doc._bool(r["testavel"], "testavel") is False]})
    csvs = []
    for p in sorted(results_dir.glob("dia6_*.csv")):
        csvs.append({"arquivo": p.name,
                     "sha256": hashlib.sha256(p.read_bytes().replace(b"\r\n", b"\n")).hexdigest()})
    return {"coleta1": coleta1, "saude": saude, "cal": cal, "csvs": csvs}


def budget_facts() -> dict[str, Any]:
    return {"limite_total_s": config.QPU_TOTAL_BUDGET_SECONDS,
            "janela_dias": config.QPU_BUDGET_WINDOW_DAYS,
            "teto_24h_s": config.QPU_DAILY_CAP_SECONDS,
            "reserva_maxima_por_job_s": config.QPU_MAX_JOB_RESERVE_SECONDS,
            "margem_s": config.QPU_BUDGET_MARGIN_SECONDS}


# ---------------------------------------------------------------- bloco do PROJECT.md

def _cell(s: str) -> str:
    return s.replace("|", "\\|")


def build_block(info: dict[str, Any], facts: dict[str, Any], suite: str) -> str:
    c1, bud = facts["coleta1"], budget_facts()
    L = [START, "### Estado ao fim da etapa 5 do Dia 6 (registro)", "",
         "Gerado por `scripts/atualizar_estado_dia6.py` a partir do git, dos CSVs de `data/results` "
         "e de `eal/config.py`. O campo Status deste documento não foi alterado (R12 depende do R11).", "",
         f"- Branch `{info['branch']}`; HEAD no momento do registro (antes do commit do próprio registro): "
         f"`{info['head']}`; árvore limpa.",
         f"- Última execução completa da suíte, informada na hora do registro: {suite} "
         f"(`{SUITE_COMMAND}`).",
         f"- Coleta 1: {len(c1['jobs'])} jobs, {c1['bits_totais']} bits, {_g(c1['uso_qpu_s'])} s de QPU "
         "(pelo inventário).",
         f"- Orçamento (`eal/config.py`): {bud['limite_total_s']} s por janela de {bud['janela_dias']} dias; "
         f"teto de 24 h {bud['teto_24h_s']} s; reserva máxima por job {bud['reserva_maxima_por_job_s']} s; "
         f"margem {bud['margem_s']} s. O saldo atual não está neste registro: conferir antes de qualquer envio.",
         "", f"#### Commits desde `{info['base']}`", "", *doc.table(
             ["Commit", "Título"], [[f"`{x['hash']}`", _cell(x["titulo"])] for x in info["commits"]]),
         "", "#### Resultados deste estágio (SHA-256 com fim de linha normalizado para LF)", "",
         *doc.table(["Arquivo", "SHA-256"], [[f"`{x['arquivo']}`", f"`{x['sha256']}`"] for x in facts["csvs"]]),
         "", "A análise está no bloco `dia6-e1parcial`, logo acima.", "", "#### O que resta", "",
         *doc.table(["Id", "Pendência", "Quando"], [[i, _cell(t), q] for i, t, q in PENDENCIAS]),
         "", "#### Próxima etapa", "",
         "Sessão de coleta 2 em outro horário do dia, para medir deriva (seção 9.3). Primeiro o plano "
         "congelado neste documento, sem enviar nada; o envio é só do usuário.", "", END]
    return "\n".join(L)


def inspect_project(data: bytes) -> tuple[str, bool, str]:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        raise StateError("PROJECT.md não é UTF-8") from None
    crlf = "\r\n" in text
    text_lf = text.replace("\r\n", "\n") if crlf else text
    if "\r" in text_lf:
        raise StateError("PROJECT.md com fim de linha misto ou CR solto")
    if crlf and text_lf.replace("\n", "\r\n") != text:
        raise StateError("PROJECT.md com fim de linha misto (CRLF e LF)")
    n_s, n_e = text_lf.count(START), text_lf.count(END)
    if (n_s, n_e) == (1, 1) and text_lf.index(START) < text_lf.index(END):
        return text_lf, crlf, "registrado"
    if (n_s, n_e) != (0, 0):
        raise StateError("marcadores do bloco de estado inconsistentes")
    if text_lf.count(ANCHOR) != 1:
        raise StateError(f"âncora {ANCHOR} deve aparecer exatamente uma vez")
    return text_lf, crlf, "novo"


def insert_block(text_lf: str, crlf: bool, block: str) -> bytes:
    idx = text_lf.index(ANCHOR) + len(ANCHOR)
    new = text_lf[:idx] + "\n\n" + block + text_lf[idx:]
    return (new.replace("\n", "\r\n") if crlf else new).encode("utf-8")


# ---------------------------------------------------------------- JSON

def build_json(info: dict[str, Any], facts: dict[str, Any], suite: str, today: str) -> dict[str, Any]:
    return {
        "tipo": "estado_para_novo_chat",
        "projeto": "EAL (Entropy Assurance Layer), protótipo de pesquisa",
        "data_do_estado": today,
        "etapa_concluida": "Dia 6, etapa 5: E1 parcial (QPU real, simulador e os; jobs cal contra a coleta 1) "
                           "registrado no PROJECT.md",
        "proxima_etapa": "Sessão de coleta 2 em outro horário do dia, para medir deriva (2 h)",
        "onde_estamos": "Gate do Dia 6 atingido e E1 parcial feito sobre a coleta 1. A coleta 2 não foi "
                        "iniciada. O campo Status do PROJECT.md ainda diz Dia 5 de 9 (R12, depois do R11).",
        "contexto": {
            "pasta_projeto": "C:\\projeto\\EntropyAssuranceLayer",
            "sistema": "Windows 11, PowerShell",
            "python": "py -3.12 sempre; sem ambiente virtual",
            "idioma_do_usuario": "português; prefere passos curtos, blocos PowerShell colados inteiros e "
                                 "saída do terminal, não relatórios longos",
            "regras_de_trabalho": REGRAS,
            "limitacoes_do_assistente": LIMITACOES_ASSISTENTE,
        },
        "estado_do_repositorio": {
            "branch": info["branch"],
            "ultimo_commit": info["head"],
            "observacao_ultimo_commit": "HEAD no momento do registro, antes do commit do próprio registro",
            "arvore": "limpa no momento do registro",
            "commit_base_anterior_ao_dia_6": info["base"],
            "commits_desde_a_base": info["commits"],
        },
        "suite": {"ultima_execucao_completa": suite, "comando": SUITE_COMMAND,
                  "observacao": "test_noisy_million_bits_fast depende da velocidade da máquina (T_TEMPO)"},
        "resultados_dia6": {
            "coleta_1": facts["coleta1"],
            "e1_parcial": {
                "onde_ler": "PROJECT.md, blocos dia6-e1parcial e dia6-estado",
                "saude_por_lote": facts["saude"],
                "cal_contra_coleta1": facts["cal"],
            },
            "csvs": facts["csvs"],
        },
        "orcamento": {**budget_facts(),
                      "aviso": "o saldo atual não está neste arquivo; ver saldo_remoto_s em "
                               "estado_dia6_fim_coleta1.json (lido antes de fechar a coleta 1) e conferir "
                               "o saldo no painel da IBM ou no comando de status antes de qualquer envio"},
        "pendencias": [{"id": i, "titulo": t, "prioridade": q} for i, t, q in PENDENCIAS],
        "comando_de_abertura_sugerido": (
            "Leia este JSON e o PROJECT.md. Estamos no Dia 6 do EAL. Etapa concluída: E1 parcial "
            "(gate da coleta 1 atingido). Próximo passo: coleta 2, em outro horário do dia, para medir "
            "deriva. Antes de qualquer código: (1) peça git status e git log -5; (2) leia no PROJECT.md "
            "a seção 9.3, o plano congelado da coleta 1 e os blocos dia6-estado e dia6-e1parcial; "
            "(3) proponha o plano congelado da coleta 2 em até 5 linhas, sem código e sem enviar nada, "
            "incluindo como a sessão será parametrizada (DEP_SESSAO) e o R8. Não rode nada que gaste QPU."),
        "modelo_recomendado_para_o_proximo_chat": {
            "modelo": "Opus 5.5", "intensidade": "média",
            "motivo": "planejar e congelar a coleta 2 e mudar poucos scripts; sem gasto de QPU até o SIM do usuário"},
    }


# ---------------------------------------------------------------- gravação

def write_both(project: Path, project_bytes: bytes, json_path: Path, json_bytes: bytes) -> None:
    tmps = [project.with_name(project.name + ".tmp"), json_path.with_name(json_path.name + ".tmp")]
    for t in tmps:
        if t.exists():
            raise StateError(f"temporário esquecido: {t.name}")
    try:
        for t, data in zip(tmps, (project_bytes, json_bytes)):
            with open(t, "xb") as fh:
                fh.write(data)
    except BaseException:
        for t in tmps:
            t.unlink(missing_ok=True)
        raise
    os.replace(tmps[1], json_path)  # o JSON primeiro: se algo falhar depois, o bloco não existe
    os.replace(tmps[0], project)


def main(argv: list[str] | None = None, *, git: Callable[..., str] | None = None,
         today: str | None = None) -> int:
    ap = argparse.ArgumentParser(description="Dia 6: registra o estado ao fim da etapa 5")
    ap.add_argument("--suite", required=True, help='ex.: "2500 passed, 1 skipped" (colado do terminal)')
    ap.add_argument("--base", default=BASE_DEFAULT)
    ap.add_argument("--projeto", type=Path, default=PROJECT_PATH)
    ap.add_argument("--results-dir", type=Path, default=RESULTS_DIR)
    ap.add_argument("--json", type=Path, default=JSON_PATH)
    ap.add_argument("--aplicar", action="store_true", help="grava (padrão: só mostra)")
    args = ap.parse_args(argv)
    try:
        if not SUITE_RE.fullmatch(args.suite):
            raise StateError("--suite deve ter o formato 'N passed' ou 'N passed, M skipped'")
        if not args.projeto.exists():
            raise StateError(f"não encontrado: {args.projeto}")
        text_lf, crlf, state = inspect_project(args.projeto.read_bytes())
        if state == "registrado":
            print("já registrado: o bloco dia6-estado existe; nada foi recalculado nem gravado")
            return 0
        if args.json.exists():
            raise StateError(f"{args.json} já existe sem o bloco no PROJECT.md; não sobrescrevo")
        info = git_info(git or run_git, args.base)
        facts = read_facts(args.results_dir)
        block = build_block(info, facts, args.suite)
        payload = build_json(info, facts, args.suite, today or date.today().isoformat())
        json_bytes = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        project_bytes = insert_block(text_lf, crlf, block)
        if not args.aplicar:
            print(block)
            print(f"\n--- JSON que seria gravado em {args.json}: {len(json_bytes)} bytes, "
                  f"{len(payload['pendencias'])} pendências, {len(info['commits'])} commits")
            print("--- nada gravado (use --aplicar)")
            return 0
        write_both(args.projeto, project_bytes, args.json, json_bytes)
        print(f"gravado: {args.json}")
        print(f"gravado: {args.projeto} (bloco dia6-estado)")
    except (StateError, doc.DocError) as exc:
        print(f"RECUSADO: {exc}")
        return 1
    except Exception as exc:  # texto de exceção não é impresso, só a classe
        print(f"erro inesperado: {type(exc).__name__}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
