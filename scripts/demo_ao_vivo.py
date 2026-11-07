"""Demo ao vivo para apresentação: um job real na QPU da IBM vira uma página visual.

Fluxo: mostra o plano e o orçamento, pede SIM, envia um job de Hadamard em todos os qubits,
espera o tempo que for (mostrando o estado), salva o lote cru pelo mesmo coletor da coleta,
roda os testes de saúde da EAL sobre os bits da QPU e sobre um lote do mesmo tamanho da
fonte `os` (comparação), monta uma página HTML autocontida e abre no navegador.

Uso (na raiz do projeto):
    py -3.12 -m scripts.demo_ao_vivo                      envia (pede SIM), espera e abre
    py -3.12 -m scripts.demo_ao_vivo --shots 4000         job menor
    py -3.12 -m scripts.demo_ao_vivo --job JOB_ID         retoma a espera de um job já enviado
    py -3.12 -m scripts.demo_ao_vivo --arquivo LOTE.npy   ensaio sem QPU: página de um lote já salvo

O orçamento, o log de uso e o manifesto são os do `eal/ibm_cli.py` (mesmas travas). O token
nunca é impresso. A página diz "gravado" quando vem de --arquivo, nunca finge ser ao vivo.
"""
from __future__ import annotations

import argparse
import base64
import html
import json
import sys
import time
import webbrowser
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np

from eal import config
from eal.health.replay import ReplayDetector
from eal.health.report import build_health_report
from eal.storage import load_batch

OUT_DIR = Path("ao_vivo")
SESSION = "aovivo"
DEFAULT_SHOTS = 9616  # 1.500.096 bits em 156 qubits; ~5 s de QPU nas coletas anteriores
DEFAULT_RESERVE = 20
POLL_SECONDS = 4.0
USAGE_WAIT_SECONDS = 90.0
MOSAIC_SHOTS = 52  # linhas do mosaico: proporção ~3:1 com 156 colunas
EXIT_OK, EXIT_ERROR, EXIT_REFUSED = 0, 1, 3


# ---------------------------------------------------------------- layout do chip

def chip_layout(n_qubits: int, edges: Sequence[tuple[int, int]]) -> dict[int, tuple[float, float]]:
    """Coordenadas (x, y) de cada qubit físico no heavy-hex do Heron (fileiras de 16, pontes de 4).

    Fileira r: qubits 20r..20r+15 em y = r, x = coluna. Ponte (20r+16..20r+19): y = r + 0,5, x = coluna
    do vizinho de menor índice. Se o mapa não seguir esse padrão, cai numa grade simples.
    """
    nb: dict[int, list[int]] = {q: [] for q in range(n_qubits)}
    for a, b in edges:
        if a < n_qubits and b < n_qubits:
            nb[a].append(b)
            nb[b].append(a)
    pos: dict[int, tuple[float, float]] = {}
    for q in range(n_qubits):
        r, c = divmod(q, 20)
        if c < 16:
            pos[q] = (float(c), float(r))
        else:
            lower = [v for v in nb[q] if v < q and v % 20 < 16]
            if len(lower) != 1:
                return {q: (float(q % 13), float(q // 13)) for q in range(n_qubits)}
            pos[q] = (float(lower[0] % 20), r + 0.5)
    return pos


def kingston_edges() -> list[tuple[int, int]]:
    """Arestas do mapa de acoplamento do FakeKingston (offline); vazio se não der para carregar."""
    try:
        import warnings

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            from qiskit_ibm_runtime.fake_provider import FakeKingston

            cm = FakeKingston().coupling_map
        return sorted({tuple(sorted(e)) for e in cm.get_edges()})
    except Exception:  # noqa: BLE001
        return []


# ---------------------------------------------------------------- dados da página

def _test_rows(rep: Any) -> list[dict[str, Any]]:
    """Os testes de saúde em linguagem de plateia, com o número que decide cada um."""
    s = rep.stats
    p = lambda k: s.get(k)  # noqa: E731
    fmt_p = lambda v: "-" if v is None else (f"p = {v:.2g}" if v < 0.001 else f"p = {v:.3f}")  # noqa: E731
    h = rep.h_estimated
    return [
        {"nome": "Repetição (RCT)", "o_que": "nenhum trecho longo de bits iguais",
         "ok": rep.rct_pass, "valor": f"maior sequência {rep.rct_max_run} (limite {rep.rct_cutoff})"},
        {"nome": "Proporção (APT)", "o_que": "nenhuma janela com excesso de um valor",
         "ok": rep.apt_pass, "valor": f"máximo {rep.apt_max_count} (limite {rep.apt_cutoff})"},
        {"nome": "Replay", "o_que": "o lote não repete um lote anterior",
         "ok": rep.replay_pass, "valor": "sem repetição" if rep.replay_pass else "lote repetido"},
        {"nome": "Min-entropia", "o_que": "imprevisibilidade estimada por bit",
         "ok": rep.h_health_pass, "valor": "-" if h is None else f"H = {h:.4f} (mínimo {rep.h_threshold})"},
        {"nome": "Frequência (monobit)", "o_que": "uns e zeros em proporção 50/50",
         "ok": (p("monobit") or 0) >= 0.01, "valor": fmt_p(p("monobit"))},
        {"nome": "Frequência por bloco", "o_que": "50/50 também dentro de cada bloco",
         "ok": (p("block") or 0) >= 0.01, "valor": fmt_p(p("block"))},
        {"nome": "Sequências (runs)", "o_que": "trocas entre 0 e 1 na taxa esperada",
         "ok": (p("runs") or 0) >= 0.01,
         "valor": fmt_p(p("runs")) + (" (depende do monobit)" if p("runs") == 0 else "")},
    ]


Z_VISIVEL = 2.576  # |z| a partir do qual o monobit reprova (p < 0,01, o mesmo limiar de _test_rows)


def _pt(x: float, casas: int = 0) -> str:
    """Número no formato pt-BR (milhar com ponto, decimal com vírgula), como o toLocaleString da página."""
    s = f"{x:,.{casas}f}"
    return s.replace(",", "\0").replace(".", ",").replace("\0", ".")


def verdict_paragraphs(data: dict[str, Any]) -> list[str]:
    """Texto do veredito da QPU, montado só com o que os testes de fato mostraram (texto puro, sem HTML)."""
    qpu = data["qpu"]
    n_bits, n_testes = data["n_bits"], len(qpu["testes"])
    if qpu["aprovado"]:
        return [f"Os {_pt(n_bits)} bits da QPU passaram nos {n_testes} testes. Na EAL, este lote poderia entrar "
                "na mistura, sempre junto com uma fonte local, nunca sozinho."]
    falhas = [t["nome"] for t in qpu["testes"] if not t["ok"]]
    frac, z = data["frac1"], data["z_total"]
    desvio = _pt(abs(frac - 0.5) * 100, 2)
    if abs(z) >= Z_VISIVEL:
        freq = (f"A fração de uns foi {_pt(frac, 4)}: um desvio de {desvio} ponto percentual de 50/50. "
                f"Parece pouco, mas com {_pt(n_bits)} bits ele é estatisticamente visível (z = {_pt(z, 1)}).")
    else:
        freq = (f"A fração de uns foi {_pt(frac, 4)}, desvio de {desvio} ponto percentual de 50/50, "
                f"dentro do esperado para {_pt(n_bits)} bits (z = {_pt(z, 1)}): a reprovação não vem da frequência.")
    return [f"{freq} Falhou em: {', '.join(falhas)}.",
            "A EAL exclui o lote, registra o motivo no recibo e não deixa esses bits entrarem numa chave. "
            "É exatamente o papel dela: confiar na fonte só depois de testar."]


def page_data(batch: Any, rep_qpu: Any, rep_os: Any, *, mode: str, quantum_seconds: float | None,
              wait_seconds: float | None, duplicate_of: str | None, edges: Sequence[tuple[int, int]]) -> dict[str, Any]:
    """Tudo o que a página mostra, só com tipos nativos. Nenhum segredo: bits públicos do lote, hashes, parâmetros."""
    prm = batch.params
    nq = int(prm["n_qubits"])
    shots = int(prm["shots"])
    m = np.asarray(batch.bits[: shots * nq], dtype=np.uint8).reshape(shots, nq)
    p1 = m.mean(axis=0)
    z = (p1 - 0.5) / np.sqrt(0.25 / shots)
    phys = [int(q) for q in prm["physical_qubits"]]
    layout = chip_layout(max(phys) + 1, edges) if edges else {q: (float(q % 13), float(q // 13)) for q in phys}
    mosaic = m[: min(MOSAIC_SHOTS, shots)]
    frac1 = float(m.mean())
    data = {
        "modo": mode,
        "job_id": prm.get("job_id", ""),
        "backend": prm.get("backend", ""),
        "n_qubits": nq,
        "shots": shots,
        "n_bits": int(batch.n_bits),
        "criado_em": batch.created_at,
        "calibracao": prm.get("calibration_date_run") or prm.get("calibration_date") or "",
        "segundos_qpu": quantum_seconds,
        "espera_s": wait_seconds,
        "batch_hash": batch.batch_hash,
        "duplicado_de": duplicate_of or "",
        "duplicado_verificado": duplicate_of is not None,  # só a recuperação ao vivo compara com os lotes anteriores
        "frac1": frac1,
        "z_total": float((frac1 - 0.5) / np.sqrt(0.25 / m.size)),
        "qubits": [{"q": phys[i], "x": layout.get(phys[i], (0.0, 0.0))[0], "y": layout.get(phys[i], (0.0, 0.0))[1],
                    "p1": round(float(p1[i]), 5), "z": round(float(z[i]), 2)} for i in range(nq)],
        "arestas": [[a, b] for a, b in edges if a in layout and b in layout],
        "mosaico": {"linhas": int(mosaic.shape[0]), "colunas": nq,
                    "b64": base64.b64encode(np.packbits(mosaic.ravel()).tobytes()).decode("ascii")},
        "qpu": {"aprovado": bool(rep_qpu.approved), "testes": _test_rows(rep_qpu)},
        "os": {"aprovado": bool(rep_os.approved), "testes": _test_rows(rep_os)},
    }
    data["veredito"] = verdict_paragraphs(data)
    return data


# ---------------------------------------------------------------- HTML

TEMPLATE = Path(__file__).with_name("demo_ao_vivo_template.html")


def render_html(data: dict[str, Any]) -> str:
    """Injeta os dados (JSON) no modelo. O JSON vai escapado para não fechar a tag <script>."""
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    titulo = html.escape(f"Bits quânticos · {data['backend']} · {data['job_id']}")
    return TEMPLATE.read_text(encoding="utf-8").replace("__TITULO__", titulo).replace("__DADOS__", payload)


def write_page(data: dict[str, Any], out_dir: Path = OUT_DIR) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = out_dir / f"{stamp}_{data['job_id'] or 'lote'}.html"
    path.write_text(render_html(data), encoding="utf-8")
    return path


# ---------------------------------------------------------------- execução

def analyze(npy: Path, *, mode: str, quantum_seconds: float | None, wait_seconds: float | None,
            duplicate_of: str | None = None, os_reader: Callable[[int], Any] | None = None,
            edges: Sequence[tuple[int, int]] | None = None) -> dict[str, Any]:
    """Carrega o lote, roda a saúde na QPU e numa referência `os` do mesmo tamanho e monta os dados."""
    batch = load_batch(npy)
    rep_qpu = build_health_report(batch, ReplayDetector())
    if os_reader is None:
        from eal.sources.os_source import OsSource

        os_reader = OsSource().read
    rep_os = build_health_report(os_reader(batch.n_bits), ReplayDetector())
    return page_data(batch, rep_qpu, rep_os, mode=mode, quantum_seconds=quantum_seconds,
                     wait_seconds=wait_seconds, duplicate_of=duplicate_of,
                     edges=kingston_edges() if edges is None else edges)


def logged_seconds(npy: Path, logs_dir: Path) -> float | None:
    """Segundos de QPU do lote gravado, lidos do log de uso (linha final com o mesmo arquivo); None se não houver."""
    from eal.sources.qpu_budget import read_log

    entries, _ = read_log(Path(logs_dir) / config.QPU_USAGE_LOG_NAME)
    for e in entries:
        if e.event == "final" and e.output_file == npy.name:
            return e.quantum_seconds
    return None


@dataclass
class Waited:
    output_file: str
    quantum_seconds: float | None
    duplicate_of: str | None  # None: a comparação com lotes anteriores não rodou nesta recuperação
    wait_seconds: float


def wait_for(collector: Any, job_id: str, out: Callable[[str], None], *,
             sleep: Callable[[float], None] = time.sleep, clock: Callable[[], float] = time.monotonic) -> Waited | None:
    """Espera o job terminar (sem limite), mostrando estado e tempo; None se o job falhou."""
    t0 = clock()
    usage_since: float | None = None
    while True:
        r = collector.retrieve(job_id)
        el = clock() - t0
        if r.state == "pending":
            out(f"\r  aguardando a IBM ... estado {r.status or '?'} · {el:5.0f} s ")
        elif r.state == "usage_pending":
            usage_since = el if usage_since is None else usage_since
            if el - usage_since >= USAGE_WAIT_SECONDS:
                out("\n  dados salvos; a IBM ainda calcula o uso (feche depois com coletar_ibm.py recuperar)")
                return Waited(r.output_file, None, None, el)
            out(f"\r  bits recebidos; aguardando o uso de QPU ser calculado · {el:5.0f} s ")
        elif r.state == "failed":
            out(f"\n  o job terminou com estado {r.status}; nada para mostrar")
            return None
        else:
            out(f"\n  job concluído em {el:.0f} s (uso de QPU: {r.quantum_seconds if r.quantum_seconds is not None else '?'} s)")
            checked = r.state == "final"  # já fechado antes: a comparação não rodou agora
            return Waited(r.output_file, r.quantum_seconds, r.duplicate_of if checked else None, el)
        sleep(POLL_SECONDS)


def _ctx_and_collector(args: argparse.Namespace, out: Callable[[str], None]) -> tuple[Any, Any, Any]:
    from eal import ibm_cli

    ctx = ibm_cli.Context(
        backend=args.backend, instance=config.IBM_DEFAULT_INSTANCE, policy=ibm_cli.policy_from_config(),
        log_path=args.logs_dir / config.QPU_USAGE_LOG_NAME, raw_dir=args.raw_dir,
        manifest_dir=args.logs_dir / "qpu_jobs", results_dir=Path("data/results"),
        clock=ibm_cli.utc_now, out=out, input_fn=input)
    service = ibm_cli.build_service(ctx.instance)
    return ibm_cli, ctx, ibm_cli.default_collector_factory(service, ctx)


def _submit(args: argparse.Namespace, out: Callable[[str], None]) -> tuple[Any, str] | int:
    ibm_cli, ctx, collector = _ctx_and_collector(args, out)
    from eal.sources.qpu_budget import check_budget, read_log

    n_qubits = len(collector.prepare(None).physical_qubits)
    entries, problems = read_log(ctx.log_path)
    decision = check_budget(entries, args.reserva, ctx.policy, ibm_cli._remote_remaining(collector.service),
                            now=ctx.clock(), log_problems=problems)
    ns = SimpleNamespace(shots=args.shots, reserva=args.reserva, sessao=SESSION, sim=False)
    ibm_cli._preview(ctx, ns, n_qubits, decision)
    if not decision.allowed:
        return EXIT_REFUSED
    if not ibm_cli._confirmed(ctx, ns, n_qubits):
        out("Cancelado: nada foi enviado.")
        return EXIT_REFUSED
    res = collector.submit(args.shots, args.reserva, SESSION)
    out(f"Job enviado: {res.job_id}")
    return collector, res.job_id


def terminal(s: str) -> None:
    """Escreve no terminal; texto que começa com retorno de carro reescreve a linha (contador de espera)."""
    sys.stdout.write(s if s.startswith("\r") else s + "\n")
    sys.stdout.flush()


def run(args: argparse.Namespace, out: Callable[[str], None] = terminal) -> int:
    say = out
    if args.arquivo:
        npy = Path(args.arquivo)
        out(f"Ensaio com lote gravado: {npy.name}")
        data = analyze(npy, mode="gravado", quantum_seconds=logged_seconds(npy, args.logs_dir), wait_seconds=None)
    else:
        if args.job:
            _, _, collector = _ctx_and_collector(args, say)
            job_id = args.job
        else:
            sent = _submit(args, say)
            if isinstance(sent, int):
                return sent
            collector, job_id = sent
        try:
            w = wait_for(collector, job_id, say)
        except KeyboardInterrupt:
            out(f"\nInterrompido. O job continua na IBM; retome com: py -3.12 -m scripts.demo_ao_vivo --job {job_id}")
            return EXIT_ERROR
        if w is None:
            return EXIT_ERROR
        out("Rodando os testes de saúde da EAL (QPU e, para comparar, a fonte os) ...")
        data = analyze(args.raw_dir / w.output_file, mode="ao vivo", quantum_seconds=w.quantum_seconds,
                       wait_seconds=w.wait_seconds, duplicate_of=w.duplicate_of)
    path = write_page(data, args.out_dir)
    veredito = "APROVADO" if data["qpu"]["aprovado"] else "REPROVADO"
    out(f"Lote da QPU: {veredito} · fração de uns {data['frac1']:.4f} · página: {path}")
    if not args.nao_abrir:
        webbrowser.open(path.resolve().as_uri())
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="demo_ao_vivo", description=__doc__.splitlines()[0])
    ap.add_argument("--shots", type=int, default=DEFAULT_SHOTS)
    ap.add_argument("--reserva", type=int, default=DEFAULT_RESERVE, help="segundos máximos de QPU do job")
    ap.add_argument("--backend", default=config.IBM_DEFAULT_BACKEND)
    ap.add_argument("--job", help="retoma a espera de um job já enviado")
    ap.add_argument("--arquivo", help="ensaio: monta a página de um lote .npy já salvo, sem QPU")
    ap.add_argument("--raw-dir", type=Path, default=Path("data/raw"))
    ap.add_argument("--logs-dir", type=Path, default=Path("data/logs"))
    ap.add_argument("--out-dir", type=Path, default=OUT_DIR)
    ap.add_argument("--nao-abrir", action="store_true", help="não abre o navegador")
    return ap


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.job and args.arquivo:
        print("Use --job ou --arquivo, não os dois.")
        return 2
    try:
        return run(args)
    except Exception as exc:  # noqa: BLE001  (a mensagem pode trazer dados do provedor: só a classe)
        print(f"\nERRO: {type(exc).__name__}: {exc}" if type(exc).__module__.startswith("eal") else f"\nERRO inesperado: {type(exc).__name__}")
        return EXIT_ERROR


if __name__ == "__main__":
    raise SystemExit(main())
