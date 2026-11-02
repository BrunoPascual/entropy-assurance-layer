"""Dia 7: registra no PROJECT.md o plano congelado da coleta 3, antes do primeiro envio.

Script de uso único: acrescenta um bloco ao FIM do PROJECT.md, entre marcadores, sem editar
nenhuma linha existente. Tudo ou nada:

- só grava se o SHA-256 atual do arquivo for o do commit 01666ec (HASH_ANTES);
- "já aplicado" quando o arquivo termina exatamente com o bloco e, sem ele, volta a HASH_ANTES;
  nesse caso não grava nada;
- recusa sem gravar se o hash for outro, se algum marcador já existir, se o arquivo não for
  CRLF puro ou não terminar com fim de linha;
- grava num arquivo temporário na mesma pasta e troca com os.replace (sem arquivo pela metade).

Uso (na raiz do projeto):
    py -3.12 scripts\\atualizar_docs_coleta3.py
Código de saída: 0 aplicado ou já aplicado; 1 recusado (nada foi gravado).
"""
from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path

TARGET = Path("PROJECT.md")
HASH_ANTES = "ec6847c6dd4ac0874f9566c8f154fc6925da10bc790dd961fd9ceba54f320d01"
START = "<!-- coleta3-plano:start -->"
END = "<!-- coleta3-plano:end -->"

BLOCK = f"""{START}
### Plano congelado da coleta 3 (Dia 7, registrado antes do primeiro envio)

Registrado em 02/11/2026 sobre o commit 01666ec. Nenhum parâmetro abaixo muda depois do primeiro envio da coleta 3 (seção 6.5).

- **Objetivo:** medir a deriva entre dias (seção 9.3).
- **Backend, qubits, circuito e `rep_delay`:** iguais aos das coletas 1 e 2 (ibm_kingston; os 156 operacionais, sem exclusão; `hadamard_all_measure` com SamplerV2; 0,00025 s).
- **Sessão:** `coleta3`.
- **Jobs:** 2, enviados um de cada vez. O segundo só é enviado depois que o primeiro for recuperado e inspecionado.
- **Shots por job:** 9.616, o que dá 1.500.096 bits por job e 3.000.192 no total.
- **Reserva por job:** 20 s.
- **Horário:** o primeiro envio acontece entre 17:00 e 20:00 (-03:00) de 02/11/2026: o dia seguinte ao das coletas 1 e 2, na mesma faixa horária da coleta 2. Se o primeiro envio não acontecer nessa janela, este plano não vale e é refeito.
- **Custo:** as coletas 1 e 2 usaram 5 s por job. Saldo depois da coleta 2: 573 s; o saldo é conferido de novo com `coletar_ibm.py status` antes do primeiro envio.
- **Calibração:** cada lote grava o retrato do envio (`calibration_date`, `readout_error_by_position`) e o da execução (`calibration_date_run`, `readout_error_run_by_position`, R8).
- **Critérios de parada e o que não é critério de parada:** iguais aos das coletas 1 e 2, inclusive parar se o primeiro job usar mais de 15 s. Ao parar: documentar e não reenviar sem uma nova decisão registrada aqui.
- **Critérios de análise, fixados antes de ver os dados:**
  - saúde e H estimada por lote, pelo mesmo pipeline das coletas 1 e 2, com limiar 0,9;
  - conjunto fixo: viés além da leitura nos qubits 14, 21 e 138; controles 121 e 131; pares 112-113 e 130-131. Nenhum item entra ou sai depois de ver a coleta 3;
  - análise principal: contra a coleta 1, com `analisar_deriva.py --sessao coleta3`. Réplica: mesmo sinal e |z| > 2; onde a direção se reproduz e a magnitude não (`magnitude_compativel`), o resultado é "direção reproduzida, magnitude não". Esta comparação mistura o dia com a hora do dia (coleta 1 perto do meio-dia, coleta 3 depois das 17:00), e o registro diz isso;
  - análise secundária, opcional: contra a coleta 2 (mesma faixa horária, dia seguinte), com o mesmo conjunto fixo e a mesma regra de réplica, só se o `analisar_deriva.py` ganhar um parâmetro de referência, com testes. Se não for feita, o registro diz que não foi feita;
  - cada comparação registra se a calibração da execução é a mesma da referência ou não.
- **Análise:** com os comandos que já aceitam `--sessao` (inventário, saúde, resumo e deriva).
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


def ja_aplicado(data: bytes) -> bool:
    t = tail()
    return data.endswith(t) and sha256(data[:-len(t)]) == HASH_ANTES


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
    if sha256(data) != HASH_ANTES:
        raise Refused(f"SHA-256 do PROJECT.md ({sha256(data)}) difere de HASH_ANTES")
    return data + tail()


def main() -> int:
    try:
        if not TARGET.is_file():
            raise Refused(f"arquivo ausente: {TARGET}")
        data = TARGET.read_bytes()
        if ja_aplicado(data):
            print(f"já aplicado; PROJECT.md: {sha256(data)}")
            return 0
        novo = build(data)
        tmp = TARGET.with_name(TARGET.name + ".tmp")
        tmp.write_bytes(novo)
        os.replace(tmp, TARGET)
        print(f"aplicado; PROJECT.md: {sha256(novo)}")
        return 0
    except Refused as exc:
        print(f"RECUSADO: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
