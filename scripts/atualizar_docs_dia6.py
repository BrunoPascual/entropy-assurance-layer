"""Dia 6: registra no fim de PROJECT.md e THREAT_MODEL.md o resultado da calibração e as pendências.

Uso único, tudo ou nada, idempotente (na raiz do projeto):
    py -3.12 scripts\\atualizar_docs_dia6.py

Por que ACRESCENTA em vez de editar seções: o texto atual das seções 9.3, 9.4, 17 e 6.12 não foi
conferido neste ambiente, e trocar texto por âncora sem ver o original seria chute. O bloco novo
diz, no próprio documento, o que mudou; a reorganização das seções fica para depois.

- recusa, sem gravar nada, se algum arquivo não existir, não for UTF-8, ou se o bloco já existir
  mas diferente do esperado (ou não estiver no fim);
- preserva o fim de linha de cada arquivo (LF ou CRLF);
- grava os dois arquivos por temporário e, se a segunda troca falhar, restaura a primeira.
"""
from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path

PROJECT = Path("PROJECT.md")
THREAT = Path("THREAT_MODEL.md")

PROJECT_MARKER = "## 18. Dia 6: calibração na QPU real e pendências (registro)"
PROJECT_LINES: tuple[str, ...] = (
    "Job de calibração: dbji1pgnceqs73ak2c8g, backend ibm_kingston, 156 qubits, 1000 shots, "
    "reserva de 20 s, SamplerV2 (qiskit 2.6.1, qiskit-ibm-runtime 0.51.0).",
    "Estado: DONE. Uso cobrado: 2 s de QPU (usage() e qpu_charge_time_seconds). Criado às 08:22 "
    "(horário de São Paulo) e já concluído na inspeção das 11:26.",
    "Conversão validada com resultado real: BitArray com 156 bits e 1000 shots; a conversão do "
    "adaptador é igual a to_bool_array(order='little'). 156000 bits uint8. Fração geral de 1: 0,4971.",
    "Colunas mais afastadas de 0,5 (posição, qubit físico, fração de 1): 121, 0,3450; 46, 0,4080; "
    "112, 0,5740. Amostra de um job: não é conclusão sobre viés.",
    "Calibração: properties() no início da execução tem data 2026-11-01 11:09:06 (-03:00); o "
    "retrato gravado no envio tem 07:36:54 (-03:00). A data mudou, mas o erro de leitura dos 156 "
    "qubits não mudou (diferença máxima 0,00000). Não se sabe ainda qual propriedade mudou.",
    "Confirmado no ibm_kingston: 156 qubits operacionais; max_shots 100000; default_rep_delay "
    "0,00025 s; erro de leitura (31/10/2026) mínimo 0,00134, mediana 0,00989, máximo 0,49451.",
    "Janela do orçamento: 28 dias rolantes (usage_period de 03/10 a 31/10 na sonda de 31/10). "
    "Limite do Open Plan: 600 s.",
    "Dry-run indisponível para o ibm_kingston no Open Plan (QiskitBackendNotFoundError: não há "
    "backend mock_). O custo real só se mede com job real. Mensagem de falha corrigida no commit ab11bc5.",
    "SamplerV2 obsoleto desde qiskit-ibm-runtime 0.50.0 (DeprecationWarning, remoção não antes de "
    "3 meses após o lançamento). Versão fixada em 0.51.0; a troca para executor_sampler fica depois da coleta 1.",
    "Estimativa com um único ponto (limite superior, não medida): 2 milhões de bits cabem em um job "
    "de cerca de 12.821 shots com reserva de ~41 s; 3 milhões em cerca de 19.231 shots com reserva "
    "de ~60 s. Um segundo job de calibração confirma ou derruba isso.",
    "Pendências antes da coleta 1: (1) recuperar o job de calibração, que fecha a conta no log; "
    "(2) segundo job de calibração; (3) registrar aqui o plano congelado da coleta 1 antes do "
    "primeiro envio; (4) P1: copiar data/logs/replay_history.json após o primeiro eal run real; "
    "(5) gate do Dia 6 (2 a 3 milhões de bits reais salvos), ainda não avaliado.",
    "Limitação nova (seção 17): o adaptador lê o uso primeiro em metrics()['usage']['quantum_seconds'], "
    "chave que a IBM não devolveu neste job; a IBM expõe qpu_charge_time_seconds. A leitura caiu "
    "em usage(), que devolveu o mesmo valor. Corrigir antes da coleta 1.",
    "Limitações novas (seção 17), ainda não listadas: janela de queda entre a checagem do lote e a "
    "gravação (o lote fica consumido e não registrado); leituras de semente Toeplitz não passam pelo "
    "detector de replay (premissa P3); limite de 64 MiB do histórico de replay.",
)

THREAT_MARKER = "## Anexo do Dia 6: observações de execução (não altera a versão do documento)"
THREAT_LINES: tuple[str, ...] = (
    "Observado: a calibração da IBM mudou entre o envio e a execução de um job (07:36 para 11:09), "
    "sem mudança no erro de leitura medido. O risco de deriva entre envio e execução segue sem "
    "cobertura completa: o retrato gravado no envio pode não representar a execução. Mitigação "
    "atual: o inspetor compara os dois. Mitigação planejada, não implementada: gravar também o "
    "retrato da execução no lote.",
    "Observado: dry-run indisponível no Open Plan para o ibm_kingston. Não afeta a guarda de "
    "orçamento, que não depende do dry-run; perde-se apenas a validação prévia no servidor.",
    "Observado: a IBM devolve o uso em qpu_charge_time_seconds e em usage(); o código lê primeiro "
    "outra chave. Sem efeito de segurança hoje (os valores coincidem), mas é falha de contrato a corrigir.",
    "Confirmado: a mensagem de falha do dry-run não diz mais 'resultado incerto' (commit ab11bc5); "
    "o texto de envio real foi mantido.",
)


def eol_of(text: str) -> str:
    """Fim de linha predominante do arquivo."""
    return "\r\n" if "\r\n" in text else "\n"


def block_text(marker: str, lines: tuple[str, ...], eol: str) -> str:
    """Bloco com título e linhas, cada uma numa linha própria, terminando em quebra."""
    return eol.join((marker, *lines)) + eol


def plan(text: str, marker: str, lines: tuple[str, ...], name: str) -> str | None:
    """Texto novo do arquivo, ou None se o bloco já está lá, exatamente como deve estar."""
    eol = eol_of(text)
    addition = eol + block_text(marker, lines, eol)
    if text.count(marker) > 1:
        raise ValueError(f"{name}: o bloco do Dia 6 aparece mais de uma vez")
    if marker in text:
        if text.endswith(addition):
            return None
        raise ValueError(f"{name}: o bloco do Dia 6 já existe, mas está diferente do esperado "
                         "ou não está no fim do arquivo")
    base = text if text.endswith(eol) else text + eol
    return base + addition


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def apply_all(project: Path = PROJECT, threat: Path = THREAT) -> str:
    """Aplica os dois blocos ou nenhum. Devolve um resumo; levanta ValueError ou OSError."""
    targets = (
        (project, PROJECT_MARKER, PROJECT_LINES, "PROJECT.md"),
        (threat, THREAT_MARKER, THREAT_LINES, "THREAT_MODEL.md"),
    )
    originals: dict[Path, bytes] = {}
    news: dict[Path, str] = {}
    for path, marker, lines, name in targets:
        if not path.is_file():
            raise ValueError(f"{name}: arquivo não encontrado em {path.resolve().parent}")
        raw = path.read_bytes()
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError(f"{name}: não é UTF-8 ({exc.reason})") from None
        originals[path] = raw
        new = plan(text, marker, lines, name)
        if new is not None:
            news[path] = new
    if not news:
        return "já aplicado: nada a fazer"
    staged: list[tuple[Path, Path]] = []
    replaced: list[Path] = []
    try:
        for path, text in news.items():
            tmp = path.with_name(path.name + ".tmp")
            tmp.write_bytes(text.encode("utf-8"))
            staged.append((tmp, path))
        for tmp, path in staged:
            os.replace(tmp, path)
            replaced.append(path)
    except OSError:
        for path in replaced:
            path.write_bytes(originals[path])
        for tmp, _ in staged:
            if tmp.exists():
                tmp.unlink()
        raise
    lines = []
    for path in news:
        lines.append(f"{path}: SHA-256 antes {_sha256(originals[path])}; "
                     f"SHA-256 depois {_sha256(path.read_bytes())}")
    return "aplicado:\n" + "\n".join(lines)


def main() -> int:
    """Aplica os blocos; 0 se aplicou ou já estava aplicado, 1 se recusou (nada foi gravado)."""
    try:
        print(apply_all())
    except (ValueError, OSError) as exc:
        print(f"RECUSADO (nada foi gravado ou foi restaurado): {exc}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
