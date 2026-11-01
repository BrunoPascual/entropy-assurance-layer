"""Dia 6: registra no PROJECT.md o plano congelado da coleta 2, antes do primeiro envio.

Script de uso único: acrescenta um bloco ao FIM do PROJECT.md, entre marcadores, sem editar
nenhuma linha existente. Tudo ou nada:

- só grava se o SHA-256 atual do arquivo for o do commit a593273 (HASH_ANTES);
- "já aplicado" quando o arquivo termina exatamente com o bloco e, sem ele, volta a HASH_ANTES;
  nesse caso não grava nada;
- recusa sem gravar se o hash for outro, se algum marcador já existir, se o arquivo não for
  CRLF puro ou não terminar com fim de linha;
- grava num arquivo temporário na mesma pasta e troca com os.replace (sem arquivo pela metade).

Uso (na raiz do projeto):
    py -3.12 scripts\\atualizar_docs_coleta2.py
Código de saída: 0 aplicado ou já aplicado; 1 recusado (nada foi gravado).
"""
from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path

TARGET = Path("PROJECT.md")
HASH_ANTES = "ee16e117b65d795b791587204733b252804d3221e8b8313b31d4845a97e211f4"
START = "<!-- coleta2-plano:start -->"
END = "<!-- coleta2-plano:end -->"

BLOCK = f"""{START}
### Plano congelado da coleta 2 (Dia 6, registrado antes do primeiro envio)

Registrado em 01/11/2026 sobre o commit e82e081. Nenhum parâmetro abaixo muda depois do primeiro envio da coleta 2 (seção 6.5).

- **Objetivo:** medir a deriva no mesmo dia (seção 9.3), comparando com a coleta 1.
- **Backend, qubits, circuito e `rep_delay`:** iguais aos da coleta 1 (ibm_kingston; os 156 operacionais, sem exclusão; `hadamard_all_measure` com SamplerV2; 0,00025 s).
- **Sessão:** `coleta2`.
- **Jobs:** 2, enviados um de cada vez. O segundo só é enviado depois que o primeiro for recuperado e inspecionado.
- **Shots por job:** 9.616, o que dá 1.500.096 bits por job e 3.000.192 no total.
- **Reserva por job:** 20 s.
- **Horário:** o primeiro envio não acontece antes das 17:00 (-03:00) de 01/11/2026, cerca de 5 h depois da coleta 1.
- **Custo:** a coleta 1 usou 5 s por job. Saldo antes do envio: 583 s.
- **Calibração:** cada lote grava o retrato do envio (`calibration_date`, `readout_error_by_position`) e, pelo R8 (commit e82e081), o da execução (`calibration_date_run`, `readout_error_run_by_position`).
- **Critérios de parada e o que não é critério de parada:** iguais aos da coleta 1, inclusive parar se o primeiro job usar mais de 15 s. Ao parar: documentar e não reenviar sem uma nova decisão registrada aqui.
- **Critérios de análise, fixados antes de ver os dados:**
  - saúde e H estimada por lote, pelo mesmo pipeline da coleta 1, com limiar 0,9;
  - conjunto fixo: viés além da leitura nos qubits 14, 21 e 138; controles 121 e 131; pares 112-113 e 130-131. Nenhum item entra ou sai depois de ver a coleta 2;
  - réplica contra a coleta 1: mesmo sinal e |z| > 2. Onde a direção se reproduz e a magnitude não (`magnitude_compativel`), o resultado é "direção reproduzida, magnitude não";
  - cada comparação registra se a calibração da execução é a mesma da coleta 1 ou não.
- **Análise:** só depois da parametrização da sessão nos scripts de análise (DEP_SESSAO).
{END}
"""


class Refused(Exception):
    """Recusa: nada foi gravado."""


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def block_bytes() -> bytes:
    """O bloco em UTF-8 com fim de linha CRLF."""
    return BLOCK.replace("\n", "\r\n").encode("utf-8")


def tail() -> bytes:
    """O que o script acrescenta: uma linha em branco e o bloco."""
    return b"\r\n" + block_bytes()


def build(data: bytes) -> bytes:
    """Conteúdo novo: o arquivo atual, uma linha em branco e o bloco. Levanta Refused."""
    rest = data.replace(b"\r\n", b"")
    if b"\r\n" not in data or b"\n" in rest or b"\r" in rest:
        raise Refused("o arquivo não é CRLF puro")
    if not data.endswith(b"\r\n"):
        raise Refused("o arquivo não termina com fim de linha")
    for marker in (START, END):
        if marker.encode("utf-8") in data:
            raise Refused(f"o marcador {marker} já existe")
    return data + tail()


def already_applied(data: bytes, antes: str) -> bool:
    """O arquivo é exatamente o original (HASH_ANTES) seguido do bloco."""
    t = tail()
    return (data.endswith(t) and sha256(data[:-len(t)]) == antes
            and data.count(START.encode("utf-8")) == 1)


def apply(path: Path, antes: str = HASH_ANTES) -> str:
    """Aplica a alteração em ``path``; devolve 'aplicado' ou 'ja aplicado'. Levanta Refused."""
    data = path.read_bytes()
    if already_applied(data, antes):
        return "ja aplicado"
    current = sha256(data)
    if current != antes:
        raise Refused(f"SHA-256 atual {current} difere do esperado {antes}")
    new = build(data)
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


def main(path: Path = TARGET) -> int:
    try:
        before = sha256(path.read_bytes())
        state = apply(path)
    except (Refused, OSError) as exc:
        print(f"RECUSADO (nada foi gravado): {exc}")
        return 1
    after = sha256(path.read_bytes())
    if state == "ja aplicado":
        print(f"já aplicado: {path} já tem o bloco (SHA-256 {after.upper()}); nada foi gravado")
    else:
        print(f"aplicado:\n{path}: SHA-256 antes {before.upper()}; SHA-256 depois {after.upper()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
