"""Testes do registro automático do gate do Dia 5 (etapa 5).

Tudo roda em pasta temporária. O Git é trocado por um executor falso, e o
handoff real não é lido aqui: a conferência com o arquivo real acontece na
máquina do autor, pelos passos do roteiro.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path

import pytest

from scripts import registrar_gate_dia5 as reg

ROOT = Path(__file__).resolve().parents[1]
PROJECT_TEXT = (
    "# Projeto\r\n\r\nIntrodução.\r\n\r\n"
    "<!-- dia4-gate:start -->\r\n### 16.2 Antigo\r\n<!-- dia4-gate:end -->\r\n\r\n"
    "## 17. Limitações conhecidas\r\n\r\n- item\r\n"
)
BLOCK = reg.START + "\n### 16.3 Novo\nconteúdo\n" + reg.END


def _snapshot() -> list[tuple[str, int, int]]:
    items: list[tuple[str, int, int]] = []
    for name in ("data", "keys"):
        base = ROOT / name
        if base.is_dir():
            for path in sorted(base.rglob("*")):
                if path.is_file():
                    st = path.stat()
                    items.append((str(path.relative_to(ROOT)), st.st_size, st.st_mtime_ns))
    project = ROOT / "PROJECT.md"
    if project.is_file():
        st = project.stat()
        items.append(("PROJECT.md", st.st_size, st.st_mtime_ns))
    return items


@pytest.fixture(autouse=True)
def _nunca_tocar_no_projeto_real():
    """Barreira: nenhum teste deste arquivo pode alterar dados, chaves ou o PROJECT.md reais."""
    before = _snapshot()
    yield
    assert _snapshot() == before, "o teste mexeu em arquivos reais do projeto"


# ------------------------------------------------------------- fabricação

def hx(text: str) -> str:
    return hashlib.sha3_256(text.encode("utf-8")).hexdigest()


def build_world(count: int = 2) -> tuple[dict, list[bytes]]:
    """Gate e log consistentes entre si, sem tocar no disco."""
    runs: list[dict] = []
    lines: list[bytes] = []
    for i in range(1, count + 1):
        rid = str(uuid.UUID(int=0x1000 + i))
        body = {
            "keys": {"ml_dsa_65_pk_hash": hx(f"dsa{i}"), "ml_kem_768_pk_hash": hx(f"kem{i}")},
            "mode": "keygen",
            "receipt_id": rid,
            "seed_hash": hx(f"seed{i}"),
        }
        line = json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
        lines.append(line)
        runs.append({
            "tentativa": i,
            "codigo": 0,
            "receipt_id": rid,
            "seed_hash": hx(f"seed{i}"),
            "ml_kem_768_pk_hash": hx(f"kem{i}"),
            "ml_dsa_65_pk_hash": hx(f"dsa{i}"),
            "fontes": "os=mixed",
            "cabeca": reg.sha3_hex(line),
        })
    gate = {
        "data": "2026-10-31, teste",
        "init_issuer": "código 0; pk_hash de teste",
        "runs": runs,
        "checagens_todas_ok": ["verify de teste: código 0"],
        "outros": "nenhuma falha",
        "origem": {"bloco": reg.HANDOFF_BLOCK, "handoff_sha3_256": hx("handoff")},
    }
    return gate, lines


def put_disk(root: Path, lines: list[bytes], *, individual: bool = True) -> None:
    receipts = root / reg.RECEIPTS_REL
    receipts.mkdir(parents=True, exist_ok=True)
    (receipts / reg.CHAIN_NAME).write_bytes(b"".join(line + b"\n" for line in lines))
    if individual:
        for line in lines:
            rid = json.loads(line)["receipt_id"]
            (receipts / f"{rid}.json").write_bytes(line + b"\n")


def put_gate(root: Path, gate: dict) -> None:
    path = root / reg.GATE_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(json.dumps(gate, indent=2, ensure_ascii=False).encode("utf-8") + b"\n")


def put_project(root: Path, text: str = PROJECT_TEXT) -> Path:
    path = root / "PROJECT.md"
    path.write_bytes(text.encode("utf-8"))
    return path


def handoff_block_from(gate: dict) -> dict:
    block = {key: gate[key] for key in reg.BASE_KEYS}
    block["observacao"] = "nota de trabalho do handoff"
    return block


def handoff_bytes(block: dict) -> bytes:
    return json.dumps({"contexto": "teste", reg.HANDOFF_BLOCK: block},
                      ensure_ascii=False).encode("utf-8")


def receipts_of(lines: list[bytes]) -> dict[str, bytes]:
    return {json.loads(line)["receipt_id"]: line + b"\n" for line in lines}


def git_ok(rel: str, root: Path) -> int:
    return 0


def git_not_ignored_sk(rel: str, root: Path) -> int:
    return 1 if rel.endswith(".sk") else 0


def doc_world(tmp_path: Path, count: int = 2) -> tuple[Path, dict, list[bytes]]:
    gate, lines = build_world(count)
    root = tmp_path / "proj"
    root.mkdir()
    put_disk(root, lines)
    put_gate(root, gate)
    put_project(root)
    return root, gate, lines


# ------------------------------------------------------------ hash e JSON

def test_sha3_hex_resposta_conhecida():
    assert reg.sha3_hex(b"abc") == "3a985da74fe225b2045c172d6bd390bd855f086e3e9d525b46bfe24511431532"


def test_parse_json_aceita_bom():
    assert reg.parse_json(b'\xef\xbb\xbf{"a":1}') == {"a": 1}


def test_parse_json_recusa_chave_repetida():
    with pytest.raises(reg.GateError):
        reg.parse_json(b'{"a":1,"a":2}')


def test_parse_json_recusa_nan():
    with pytest.raises(reg.GateError):
        reg.parse_json(b'{"a":NaN}')


def test_parse_json_recusa_utf8_invalido():
    with pytest.raises(reg.GateError):
        reg.parse_json(b"\xff\xfe{")


# ------------------------------------------------------------- validação

def test_validate_aceita_gate_valido():
    gate, _ = build_world()
    assert reg.validate_gate(gate) is gate


def test_validate_aceita_base_sem_origem():
    gate, _ = build_world()
    base = {key: gate[key] for key in reg.BASE_KEYS}
    assert reg.validate_gate(base, reg.BASE_KEYS) is base


def test_validate_recusa_campo_extra():
    gate, _ = build_world()
    gate["sobra"] = "x"
    with pytest.raises(reg.GateError, match="não previstos: 1"):
        reg.validate_gate(gate)


def test_validate_recusa_campo_faltando():
    gate, _ = build_world()
    del gate["outros"]
    with pytest.raises(reg.GateError, match="outros"):
        reg.validate_gate(gate)


def test_validate_recusa_lista_de_execucoes_vazia():
    gate, _ = build_world()
    gate["runs"] = []
    with pytest.raises(reg.GateError):
        reg.validate_gate(gate)


def test_validate_recusa_tentativa_fora_de_ordem():
    gate, _ = build_world()
    gate["runs"][0]["tentativa"] = 2
    with pytest.raises(reg.GateError, match="execução 1"):
        reg.validate_gate(gate)


def test_validate_recusa_codigo_booleano():
    gate, _ = build_world()
    gate["runs"][0]["codigo"] = True
    with pytest.raises(reg.GateError, match="código"):
        reg.validate_gate(gate)


def test_validate_recusa_receipt_id_em_maiusculas():
    gate, _ = build_world()
    gate["runs"][0]["receipt_id"] = "ABCDEF00-0000-4000-8000-00000000000A"  # letras, senão upper() não muda nada
    with pytest.raises(reg.GateError, match="receipt_id"):
        reg.validate_gate(gate)


@pytest.mark.parametrize("key", reg.HASH_KEYS)
def test_validate_recusa_hash_que_nao_e_hex64(key):
    gate, _ = build_world()
    gate["runs"][0][key] = "ABC"
    with pytest.raises(reg.GateError, match=key):
        reg.validate_gate(gate)


def test_validate_recusa_checagens_vazias():
    gate, _ = build_world()
    gate["checagens_todas_ok"] = []
    with pytest.raises(reg.GateError, match="checagens"):
        reg.validate_gate(gate)


def test_validate_recusa_origem_de_outro_bloco():
    gate, _ = build_world()
    gate["origem"]["bloco"] = "outro"
    with pytest.raises(reg.GateError, match="origem"):
        reg.validate_gate(gate)


def test_validate_recusa_nao_objeto():
    with pytest.raises(reg.GateError):
        reg.validate_gate(["lista"])


# ------------------------------------------------------------- extração

def test_build_gate_copia_so_os_campos_e_registra_o_hash_do_handoff():
    gate, _ = build_world()
    data_in = handoff_bytes(handoff_block_from(gate))
    data_out, dropped = reg.build_gate(data_in)
    out = json.loads(data_out)
    assert set(out) == set(reg.FILE_KEYS)
    assert out["origem"] == {"bloco": reg.HANDOFF_BLOCK, "handoff_sha3_256": reg.sha3_hex(data_in)}
    assert out["runs"] == gate["runs"]
    assert dropped == ["observacao"]


def test_build_gate_termina_com_quebra_e_e_utf8():
    gate, _ = build_world()
    data_out, _ = reg.build_gate(handoff_bytes(handoff_block_from(gate)))
    assert data_out.endswith(b"\n")
    data_out.decode("utf-8")


def test_build_gate_e_deterministico():
    gate, _ = build_world()
    data_in = handoff_bytes(handoff_block_from(gate))
    assert reg.build_gate(data_in) == reg.build_gate(data_in)


def test_build_gate_sem_o_bloco_recusa():
    with pytest.raises(reg.GateError, match=reg.HANDOFF_BLOCK):
        reg.build_gate(json.dumps({"outro": 1}).encode())


def test_build_gate_bloco_que_nao_e_objeto_recusa():
    with pytest.raises(reg.GateError):
        reg.build_gate(json.dumps({reg.HANDOFF_BLOCK: [1]}).encode())


def test_build_gate_campo_desconhecido_recusa_sem_ecoar_o_valor():
    gate, _ = build_world()
    block = handoff_block_from(gate)
    block["extra"] = "SEGREDO-DE-TESTE"
    with pytest.raises(reg.GateError) as info:
        reg.build_gate(handoff_bytes(block))
    assert "SEGREDO-DE-TESTE" not in str(info.value)


def test_build_gate_bloco_incompleto_recusa():
    gate, _ = build_world()
    block = handoff_block_from(gate)
    del block["runs"]
    with pytest.raises(reg.GateError, match="runs"):
        reg.build_gate(handoff_bytes(block))


def test_build_gate_nao_json_recusa():
    with pytest.raises(reg.GateError):
        reg.build_gate(b"isto nao e json")


# -------------------------------------------------------------- gravação

def test_write_new_cria_pastas_e_grava_os_bytes(tmp_path):
    target = tmp_path / "a" / "b" / "x.json"
    reg.write_new(target, b"conteudo\n")
    assert target.read_bytes() == b"conteudo\n"


def test_write_new_recusa_existente_e_mantem_o_conteudo(tmp_path):
    target = tmp_path / "x.json"
    target.write_bytes(b"antigo")
    with pytest.raises(reg.GateError):
        reg.write_new(target, b"novo")
    assert target.read_bytes() == b"antigo"


# ------------------------------------------------------------ leitura do disco

def test_read_disk_le_linhas_e_recibos(tmp_path):
    gate, lines = build_world()
    root = tmp_path / "proj"
    put_disk(root, lines)
    read_lines, receipts = reg.read_disk(root)
    assert read_lines == lines
    assert receipts == receipts_of(lines)


def test_read_disk_sem_o_log_recusa(tmp_path):
    with pytest.raises(reg.GateError):
        reg.read_disk(tmp_path)


def test_read_disk_recusa_log_sem_quebra_final(tmp_path):
    gate, lines = build_world()
    root = tmp_path / "proj"
    put_disk(root, lines)
    chain = root / reg.RECEIPTS_REL / reg.CHAIN_NAME
    chain.write_bytes(chain.read_bytes()[:-1])
    with pytest.raises(reg.GateError, match="quebra"):
        reg.read_disk(root)


def test_read_disk_recusa_linha_vazia_no_meio(tmp_path):
    gate, lines = build_world()
    root = tmp_path / "proj"
    put_disk(root, lines)
    (root / reg.RECEIPTS_REL / reg.CHAIN_NAME).write_bytes(lines[0] + b"\n\n" + lines[1] + b"\n")
    with pytest.raises(reg.GateError):
        reg.read_disk(root)


def test_read_disk_recusa_receipt_id_que_nao_e_uuid(tmp_path):
    root = tmp_path / "proj"
    put_disk(root, [b'{"receipt_id":"../../x"}'])
    with pytest.raises(reg.GateError, match="receipt_id"):
        reg.read_disk(root)


def test_read_disk_sem_arquivo_individual_nao_recusa_so_omite(tmp_path):
    gate, lines = build_world()
    root = tmp_path / "proj"
    put_disk(root, lines, individual=False)
    _, receipts = reg.read_disk(root)
    assert receipts == {}


# ----------------------------------------------------------- conferência

def run_problems(gate: dict, lines: list[bytes], receipts: dict[str, bytes]) -> list[str]:
    return reg.cross_check(gate, lines, receipts)


def test_cross_check_tudo_bate_nao_acusa_nada():
    gate, lines = build_world()
    assert run_problems(gate, lines, receipts_of(lines)) == []


def test_cross_check_numero_de_linhas_diferente():
    gate, lines = build_world(2)
    problems = run_problems(gate, lines[:1], receipts_of(lines[:1]))
    assert any("1 linha" in p and "2 execução" in p for p in problems)


def test_cross_check_receipt_id_diferente_do_log():
    gate, lines = build_world()
    gate["runs"][0]["receipt_id"] = gate["runs"][1]["receipt_id"]
    problems = run_problems(gate, lines, receipts_of(lines))
    assert "execução 1: receipt_id diferente do log" in problems


def test_cross_check_cabeca_diferente_da_do_log():
    gate, lines = build_world()
    gate["runs"][1]["cabeca"] = hx("outra cabeça")
    problems = run_problems(gate, lines, receipts_of(lines))
    assert problems == ["execução 2: cabeça diferente da cabeça do log"]


def test_cross_check_recibo_ausente():
    gate, lines = build_world()
    problems = run_problems(gate, lines, {})
    assert "execução 1: arquivo do recibo ausente" in problems
    assert "execução 2: arquivo do recibo ausente" in problems


def test_cross_check_recibo_com_bytes_diferentes_da_linha():
    gate, lines = build_world()
    receipts = receipts_of(lines)
    rid = gate["runs"][0]["receipt_id"]
    receipts[rid] = lines[0] + b" \n"
    problems = run_problems(gate, lines, receipts)
    assert "execução 1: arquivo do recibo diferente da linha do log" in problems


def test_cross_check_aceita_recibo_sem_quebra_final():
    gate, lines = build_world()
    receipts = {json.loads(line)["receipt_id"]: line for line in lines}
    assert run_problems(gate, lines, receipts) == []


def test_cross_check_seed_hash_do_recibo_diferente():
    gate, lines = build_world()
    gate["runs"][0]["seed_hash"] = hx("outra semente")
    problems = run_problems(gate, lines, receipts_of(lines))
    assert problems == ["execução 1: seed_hash do recibo diferente do gate"]


def test_cross_check_chave_kem_e_dsa_conferidas_separadamente():
    gate, lines = build_world()
    gate["runs"][1]["ml_kem_768_pk_hash"] = hx("x")
    gate["runs"][1]["ml_dsa_65_pk_hash"] = hx("y")
    problems = run_problems(gate, lines, receipts_of(lines))
    assert "execução 2: chave ML-KEM-768 do recibo diferente do gate" in problems
    assert "execução 2: chave ML-DSA-65 do recibo diferente do gate" in problems


def test_cross_check_mensagens_nao_trazem_hashes():
    gate, lines = build_world()
    gate["runs"][0]["cabeca"] = hx("x")
    gate["runs"][0]["seed_hash"] = hx("y")
    for problem in run_problems(gate, lines, receipts_of(lines)):
        assert hx("x") not in problem and hx("y") not in problem


# ------------------------------------------------------------------- Git

def test_git_problems_consulta_todos_os_caminhos_e_aceita_ignorados(tmp_path):
    seen: list[str] = []

    def runner(rel: str, root: Path) -> int:
        seen.append(rel)
        return 0

    assert reg.git_problems(tmp_path, runner) == []
    assert seen == list(reg.GIT_IGNORED)


def test_git_problems_acusa_caminho_nao_ignorado(tmp_path):
    problems = reg.git_problems(tmp_path, git_not_ignored_sk)
    assert len(problems) == 1 and "keys/issuer_ml_dsa_65.sk" in problems[0]


def test_git_problems_acusa_erro_do_git(tmp_path):
    problems = reg.git_problems(tmp_path, lambda rel, root: -1)
    assert len(problems) == len(reg.GIT_IGNORED)


def test_default_git_runner_sem_pasta_devolve_erro(tmp_path):
    assert reg.default_git_runner("x", tmp_path / "nao_existe") == -1


# ------------------------------------------------------------- seção 16.3

def test_render_tem_ancoras_titulo_e_hash(tmp_path):
    gate, _ = build_world()
    text = reg.render_section(gate, "f" * 64)
    assert text.startswith(reg.START)
    assert text.endswith(reg.END)
    assert "### 16.3 Gate manual do Dia 5" in text
    assert "`" + "f" * 64 + "`" in text


def test_render_tem_uma_linha_por_execucao_com_os_valores():
    gate, _ = build_world()
    text = reg.render_section(gate, "a" * 64)
    for run in gate["runs"]:
        row = next(line for line in text.splitlines() if run["receipt_id"] in line)
        assert run["cabeca"] in row
        assert run["seed_hash"] in row
        assert row.startswith("| ") and row.endswith(" |")


def test_render_escapa_barra_vertical_na_tabela():
    gate, _ = build_world()
    gate["runs"][0]["fontes"] = "os|mixed"
    text = reg.render_section(gate, "a" * 64)
    assert "os\\|mixed" in text


def test_render_bullets_das_checagens_e_dos_limites():
    gate, _ = build_world()
    gate["checagens_todas_ok"] = ["um", "dois", "três"]
    text = reg.render_section(gate, "a" * 64)
    bullets = [line for line in text.splitlines() if line.startswith("- ")]
    assert bullets[:3] == ["- um", "- dois", "- três"]
    assert len(bullets) == 3 + len(reg._limits(len(gate["runs"])))


def test_render_nao_tem_linha_com_quebra_de_windows():
    gate, _ = build_world()
    assert "\r" not in reg.render_section(gate, "a" * 64)


# -------------------------------------------------------------- âncoras

def test_apply_insere_antes_da_secao_17():
    text = "a\n\n" + reg.NEXT_HEADING + "\n\nfim\n"
    out = reg.apply_section(text, BLOCK)
    assert out == "a\n\n" + BLOCK + "\n\n" + reg.NEXT_HEADING + "\n\nfim\n"


def test_apply_substitui_so_o_bloco_entre_ancoras():
    old = "x\n" + reg.START + "\nvelho\n" + reg.END + "\nfim\n"
    assert reg.apply_section(old, BLOCK) == "x\n" + BLOCK + "\nfim\n"


def test_apply_e_idempotente():
    text = "a\n\n" + reg.NEXT_HEADING + "\n"
    once = reg.apply_section(text, BLOCK)
    assert reg.apply_section(once, BLOCK) == once


@pytest.mark.parametrize(
    "text",
    [
        "a\n" + reg.START + "\n" + reg.NEXT_HEADING,
        "a\n" + reg.END + "\n" + reg.NEXT_HEADING,
        reg.START + "\n" + reg.START + "\n" + reg.END + "\n" + reg.NEXT_HEADING,
        reg.END + "\n" + reg.START + "\n" + reg.NEXT_HEADING,
        "sem nada\n",
        reg.NEXT_HEADING + "\n" + reg.NEXT_HEADING + "\n",
    ],
)
def test_apply_recusa_ancoras_inconsistentes(text):
    with pytest.raises(reg.GateError):
        reg.apply_section(text, BLOCK)


# ---------------------------------------------------------- PROJECT.md

def test_write_project_preserva_crlf(tmp_path):
    path = put_project(tmp_path)
    assert reg.write_project(path, BLOCK) is True
    raw = path.read_bytes()
    assert raw.count(b"\n") == raw.count(b"\r\n")
    assert (reg.START + "\n").encode("utf-8").replace(b"\n", b"\r\n") in raw


def test_write_project_segunda_vez_nao_muda(tmp_path):
    path = put_project(tmp_path)
    reg.write_project(path, BLOCK)
    first = path.read_bytes()
    assert reg.write_project(path, BLOCK) is False
    assert path.read_bytes() == first


def test_write_project_arquivo_so_com_lf_continua_so_com_lf(tmp_path):
    path = put_project(tmp_path, PROJECT_TEXT.replace("\r\n", "\n"))
    assert reg.write_project(path, BLOCK) is True
    assert b"\r" not in path.read_bytes()


def test_write_project_recusa_mistura_de_quebras_sem_tocar(tmp_path):
    original = "a\r\nb\n## 17. Limitações conhecidas\r\n".encode("utf-8")
    path = tmp_path / "PROJECT.md"
    path.write_bytes(original)
    with pytest.raises(reg.GateError, match="mistura"):
        reg.write_project(path, BLOCK)
    assert path.read_bytes() == original


def test_write_project_recusa_nao_utf8_sem_tocar(tmp_path):
    original = b"\xff\n" + "## 17. Limitações conhecidas\n".encode("utf-8")
    path = tmp_path / "PROJECT.md"
    path.write_bytes(original)
    with pytest.raises(reg.GateError, match="UTF-8"):
        reg.write_project(path, BLOCK)
    assert path.read_bytes() == original


# -------------------------------------------------------- comandos (main)

def test_extrair_grava_o_gate_e_nao_sobrescreve(tmp_path, capsys):
    gate, _ = build_world()
    handoff = tmp_path / "handoff.json"
    handoff.write_bytes(handoff_bytes(handoff_block_from(gate)))
    root = tmp_path / "proj"
    root.mkdir()
    assert reg.main(["extrair", "--handoff", str(handoff)], _root=root) == 0
    target = root / reg.GATE_REL
    reg.validate_gate(reg.parse_json(target.read_bytes()))
    assert "SHA3-256 do gate:" in capsys.readouterr().out
    saved = target.read_bytes()
    assert reg.main(["extrair", "--handoff", str(handoff)], _root=root) == 1
    assert target.read_bytes() == saved


def test_extrair_handoff_invalido_nao_cria_nada(tmp_path):
    handoff = tmp_path / "handoff.json"
    handoff.write_bytes(b"{nao e json")
    root = tmp_path / "proj"
    root.mkdir()
    assert reg.main(["extrair", "--handoff", str(handoff)], _root=root) == 1
    assert not (root / reg.GATE_REL).exists()


def test_extrair_handoff_inexistente_devolve_2(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    assert reg.main(["extrair", "--handoff", str(tmp_path / "nada.json")], _root=root) == 2


def test_doc_grava_a_secao_e_e_idempotente(tmp_path, capsys):
    root, gate, lines = doc_world(tmp_path)
    assert reg.main(["doc"], _root=root, _git_runner=git_ok) == 0
    assert "gravada" in capsys.readouterr().out
    raw = (root / "PROJECT.md").read_bytes()
    text = raw.decode("utf-8")
    assert "### 16.3 Gate manual do Dia 5" in text
    assert "\n" not in text.replace("\r\n", "")
    assert "<!-- dia4-gate:end -->" in text
    for run in gate["runs"]:
        assert run["receipt_id"] in text
    assert reg.main(["doc"], _root=root, _git_runner=git_ok) == 0
    assert (root / "PROJECT.md").read_bytes() == raw
    assert "já estava igual" in capsys.readouterr().out


def test_doc_com_out_nao_toca_no_project(tmp_path):
    root, _, _ = doc_world(tmp_path)
    before = (root / "PROJECT.md").read_bytes()
    out = tmp_path / "bloco.md"
    assert reg.main(["doc", "--out", str(out)], _root=root, _git_runner=git_ok) == 0
    assert (root / "PROJECT.md").read_bytes() == before
    assert out.read_text(encoding="utf-8").startswith(reg.START)


def test_doc_com_out_existente_devolve_1(tmp_path):
    root, _, _ = doc_world(tmp_path)
    out = tmp_path / "bloco.md"
    out.write_text("antigo", encoding="utf-8")
    assert reg.main(["doc", "--out", str(out)], _root=root, _git_runner=git_ok) == 1
    assert out.read_text(encoding="utf-8") == "antigo"


def test_doc_recibo_adulterado_nao_grava_e_avisa(tmp_path, capsys):
    root, gate, _ = doc_world(tmp_path)
    before = (root / "PROJECT.md").read_bytes()
    rid = gate["runs"][0]["receipt_id"]
    (root / reg.RECEIPTS_REL / f"{rid}.json").write_bytes(b"adulterado\n")
    assert reg.main(["doc"], _root=root, _git_runner=git_ok) == 1
    assert (root / "PROJECT.md").read_bytes() == before
    err = capsys.readouterr().err
    assert "falhou: execução 1" in err
    assert "nada foi gravado" in err


def test_doc_git_nao_ignora_chave_nao_grava(tmp_path):
    root, _, _ = doc_world(tmp_path)
    before = (root / "PROJECT.md").read_bytes()
    assert reg.main(["doc"], _root=root, _git_runner=git_not_ignored_sk) == 1
    assert (root / "PROJECT.md").read_bytes() == before


def test_doc_sem_gate_devolve_1(tmp_path):
    gate, lines = build_world()
    root = tmp_path / "proj"
    root.mkdir()
    put_disk(root, lines)
    put_project(root)
    assert reg.main(["doc"], _root=root, _git_runner=git_ok) == 1


def test_doc_sem_log_devolve_1_e_nao_grava(tmp_path):
    gate, _ = build_world()
    root = tmp_path / "proj"
    root.mkdir()
    put_gate(root, gate)
    before_project = put_project(root).read_bytes()
    assert reg.main(["doc"], _root=root, _git_runner=git_ok) == 1
    assert (root / "PROJECT.md").read_bytes() == before_project


def test_doc_mais_execucoes_no_gate_que_no_log_nao_grava(tmp_path):
    gate, lines = build_world(3)
    root = tmp_path / "proj"
    root.mkdir()
    put_disk(root, lines[:2])
    put_gate(root, gate)
    before = put_project(root).read_bytes()
    assert reg.main(["doc"], _root=root, _git_runner=git_ok) == 1
    assert (root / "PROJECT.md").read_bytes() == before


def test_subcomando_inexistente_sai_com_codigo_de_uso():
    with pytest.raises(SystemExit) as info:
        reg.main(["nao-existe"])
    assert info.value.code == 2
