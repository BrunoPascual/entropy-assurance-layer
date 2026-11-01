"""Dia 6, R4: registra no PROJECT.md o plano congelado da coleta 1, antes do primeiro envio.

Script de uso único: acrescenta um bloco ao FIM do PROJECT.md, entre marcadores, sem editar
nenhuma linha existente. Tudo ou nada:

- só grava se o SHA-256 atual do arquivo for o do commit 2ce238c (HASH_ANTES);
- se o arquivo já estiver no estado final (HASH_DEPOIS), diz "já aplicado" e não grava nada;
- recusa sem gravar se o hash for outro, se algum marcador já existir, se o arquivo não for
  CRLF puro ou se o resultado não tiver exatamente o hash esperado;
- grava num arquivo temporário na mesma pasta e troca com os.replace (sem arquivo pela metade).

Uso (na raiz do projeto):
    py -3.12 scripts\\atualizar_docs_coleta1.py
Código de saída: 0 aplicado ou já aplicado; 1 recusado (nada foi gravado).
"""
from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path

TARGET = Path("PROJECT.md")
HASH_ANTES = "b7284816dda2796c7fc418f17de620a01a0fc41760a6b1bc0133b2d5ba64c4fa"
HASH_DEPOIS = "b18c74058405e4d04c82f988e4f9d523551f64d843f5bbfa124e8c873deeb55a"
START = "<!-- coleta1-plano:start -->"
END = "<!-- coleta1-plano:end -->"

BLOCK = f"""{START}
### Plano congelado da coleta 1 (Dia 6, registrado antes do primeiro envio)

Registrado em 01/11/2026 sobre o commit dca8fb6. Nenhum parâmetro abaixo muda depois do primeiro envio da coleta 1 (seção 6.5).

- **Backend:** ibm_kingston.
- **Qubits:** os 156 operacionais, todos, sem exclusão. A decisão foi tomada quando já existia saída da QPU nos jobs de calibração; excluir algum qubit agora seria escolher olhando os dados.
- **Circuito:** Hadamard em todos os qubits e medição (`hadamard_all_measure`), SamplerV2, `rep_delay` padrão do backend (0,00025 s).
- **Sessão:** `coleta1`.
- **Jobs:** 2, enviados um de cada vez. O segundo só é enviado depois que o primeiro for recuperado e inspecionado.
- **Shots por job:** 9.616, o que dá 1.500.096 bits por job e 3.000.192 no total.
- **Reserva por job:** 20 s.
- **Base do custo:** dois jobs de calibração (1.000 shots: 2 s; 4.000 shots: 3 s). O modelo é 1,667 s fixos + 0,333 ms por shot, com estimativa central de 4,9 s por job. A IBM cobra em segundos inteiros; com ±0,5 s em cada ponto, o pior caso é cerca de 7,2 s por job.
- **Critérios de parada:** a coleta encerra quando os 2 jobs estiverem salvos. Ela para antes se acontecer qualquer uma destas situações:
  - recusa do orçamento;
  - job com status diferente de DONE;
  - falha de conversão, ou params do lote diferentes de OK no `inspecionar`;
  - aviso de lote duplicado;
  - primeiro job usando mais de 15 s (3 vezes a estimativa central, sinal de que o modelo de custo está errado).

  Ao parar: documentar e não reenviar sem uma nova decisão registrada aqui.
- **O que não é critério de parada:** a estatística dos bits (viés, H estimada). Reprovação no limiar 0,9 é resultado válido.
- **Bits de calibração:** os da sessão `cal` (`cal_001` e `cal_002`, 780.000 bits) não contam para o gate.
- **Gate do Dia 6:** 3.000.192 bits reais salvos em `data/raw`, na sessão `coleta1`.
{END}
"""


class Refused(Exception):
    """Recusa: nada foi gravado."""


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def block_bytes() -> bytes:
    """O bloco em UTF-8 com fim de linha CRLF."""
    return BLOCK.replace("\n", "\r\n").encode("utf-8")


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
    return data + b"\r\n" + block_bytes()


def apply(path: Path, antes: str = HASH_ANTES, depois: str = HASH_DEPOIS) -> str:
    """Aplica a alteração em ``path``; devolve 'aplicado' ou 'ja aplicado'. Levanta Refused."""
    data = path.read_bytes()
    current = sha256(data)
    if current == depois:
        return "ja aplicado"
    if current != antes:
        raise Refused(f"SHA-256 atual {current} difere do esperado {antes}")
    new = build(data)
    if sha256(new) != depois:
        raise Refused(f"o resultado teria SHA-256 {sha256(new)}, e não o esperado {depois}")
    tmp = path.with_name(path.name + ".tmp_coleta1")
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
    if state == "ja aplicado":
        print(f"já aplicado: {path} já tem SHA-256 {HASH_DEPOIS.upper()}; nada foi gravado")
    else:
        print(f"aplicado:\n{path}: SHA-256 antes {before.upper()}; "
              f"SHA-256 depois {sha256(path.read_bytes()).upper()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
