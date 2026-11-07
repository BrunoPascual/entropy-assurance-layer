"""Painel EAL (Dia 8): uma página. Rodar: py -3.12 -m streamlit run dashboard/app.py

Só lê data/results e data/receipts. Não escreve nada e não mostra semente nem chave privada.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import altair as alt  # noqa: E402  (vem junto com o streamlit)
import streamlit as st  # noqa: E402

from dashboard import data  # noqa: E402

st.set_page_config(page_title="EAL — Entropy Assurance Layer", layout="wide")
st.title("Entropy Assurance Layer")
st.caption(
    "Protótipo de pesquisa. Não é certificado (NIST SP 800-90B, FIPS 140-3) e não é um serviço de bits quânticos. "
    "Todo número abaixo vem de um CSV em data/results ou de um recibo em data/receipts."
)


@st.cache_data(show_spinner=False)
def _lotes():
    return data.load_lotes()


try:
    lotes = _lotes()
except FileNotFoundError as e:
    st.error(f"Dados não encontrados: {e}. Rode os scripts dos dias 6 e 7 antes de abrir o painel.")
    st.stop()

# 1. Fontes
st.header("1. Fontes e status")
st.dataframe(data.fontes_resumo(lotes), hide_index=True, width="stretch")
st.caption("Contagens das 3 coletas somadas (lotes de 1,5 milhão de bits). O simulador usa gerador clássico e semente fixa: os mesmos lotes reaparecem em cada coleta (ver Lotes distintos), e ele nunca entra em chave. Aprovado quer dizer sem defeito visível na saída, não que a fonte seja imprevisível.")

# 2. Saúde por lote
st.header("2. Saúde por lote")
saude = data.saude_por_lote(lotes)
fonte_sel = st.multiselect("Fonte", sorted(saude["Fonte"].unique()), default=sorted(saude["Fonte"].unique()))
st.dataframe(saude[saude["Fonte"].isin(fonte_sel)], hide_index=True, width="stretch")
st.caption("A QPU real e o simulador reprovam no monobit; o runs reprova por pré-requisito (p = 0 quando o monobit falha) e não é uma segunda falha independente. A `os` passa em todos.")

# 3. Min-entropia
st.header("3. Min-entropia estimada")
h, limiar = data.min_entropia(lotes)
barras = alt.Chart(h).mark_bar().encode(
    x=alt.X("lote_id:N", title="Coleta · lote", sort=None),
    y=alt.Y("h_estimada:Q", title="H estimada (bits por bit)", scale=alt.Scale(domain=[0.9, 1.0])),
    color=alt.Color("fonte:N", title="Fonte"),
    tooltip=["fonte", "lote_id", alt.Tooltip("h_estimada:Q", format=".4f")],
)
st.altair_chart(barras + alt.Chart({"values": [{"y": limiar}]}).mark_rule(strokeDash=[4, 4]).encode(y="y:Q"), width="stretch")
st.caption(f"Estimador conservador (menor entre bit e byte). Limiar do projeto (tracejado): {limiar}. O eixo começa em 0,9.")

# 4. Viés por qubit
st.header("4. Viés por qubit")
coleta = st.radio("Coleta", [1, 2, 3], horizontal=True, index=2)
try:
    q = data.vies_por_qubit(coleta)
    q = q.assign(fonte=q["fonte"].map(lambda f: data.FONTES_ROTULO.get(f, f)))
    pontos = alt.Chart(q).mark_circle(size=40).encode(
        x=alt.X("posicao:Q", title="Posição do qubit"),
        y=alt.Y("p1:Q", title="P(1)", scale=alt.Scale(domain=[0.46, 0.54])),
        color=alt.Color("fonte:N", title="Fonte"),
        tooltip=["fonte", "lote", "posicao", "qubit_fisico", alt.Tooltip("p1:Q", format=".4f"), alt.Tooltip("z_p1:Q", format=".2f")],
    )
    st.altair_chart(pontos + alt.Chart({"values": [{"y": 0.5}]}).mark_rule(strokeDash=[4, 4]).encode(y="y:Q"), width="stretch")
    st.caption("Cada ponto é um qubit de um lote (156 qubits, 9.616 shots). Tracejado: 0,5. Valores fora da faixa do eixo ficam de fora do gráfico.")
except FileNotFoundError as e:
    st.warning(str(e))

with st.expander("Deriva entre lotes e entre dias"):
    st.dataframe(data.deriva_resumo(), hide_index=True, width="stretch")
    st.caption("zdiff compara o P(1) de cada qubit entre dois lotes. Seria 1 só com amostragem binomial; aqui já passa de 1 dentro do mesmo dia e chega a 3 entre coletas. Mais detalhes, com faixas de incerteza, no relatório (relatorio/RELATORIO.md).")

# 5. Recibo
st.header("5. Último recibo")
try:
    rec_dir, keys_dir, is_demo = data.resolve_receipts()
    if is_demo:
        st.warning("Cadeia de demonstração (pasta demo/): não há cadeia real neste computador. Gerada pela própria CLI com uma chave de emissor só da demo, e a chave privada não foi publicada.")
    view = data.last_receipt(rec_dir)
    r = view.receipt
    c1, c2, c3 = st.columns(3)
    c1.metric("Posição na cadeia", f"{view.position} de {view.chain_length}")
    c2.metric("Modo", r.get("mode", "?"))
    c3.metric("Utilizável como chave", "sim" if r.get("mixer", {}).get("usable_for_key") else "não")
    st.text(f"receipt_id: {r.get('receipt_id')}\ncriado em:  {r.get('created_at')}\nseed_hash:  {r.get('seed_hash')}")
    st.dataframe(data.receipt_sources(r), hide_index=True, width="stretch")
    if st.button("Verificar assinatura e cadeia"):
        try:
            v = data.verify_last(rec_dir, keys_dir)
            if v.ok:
                st.success(f"Recibo e cadeia válidos ({v.chain_length} recibos). Cabeça: {v.head}")
                st.caption("Esta conferência não detecta a remoção dos últimos recibos: compare a cabeça acima com uma cabeça guardada fora do log (eal verify --expected-head).")
            else:
                st.error("Verificação reprovada:\n" + "\n".join(f"- {m}" for m in v.reasons))
        except (OSError, ValueError) as e:
            st.error(f"Não foi possível verificar: {type(e).__name__}")
    st.caption("O recibo traz só hashes. Os recibos reais ficam fora do Git; a cadeia de demonstração está em demo/ (README).")
except FileNotFoundError as e:
    st.info(f"Nenhum recibo para mostrar: {e}")

# 6. Experimentos
st.header("6. Resultados dos experimentos")
st.dataframe(data.experimentos_gate(), hide_index=True, width="stretch")
e1_tab, e2_tab, e3_tab, e4_tab, e5_tab = st.tabs(["E1 QPU", "E2 Ataques", "E3 Custo", "E4 Mistura", "E5 CHSH"])
with e1_tab:
    st.write("E1 está nas seções 2 a 4 acima (saúde, min-entropia, viés e deriva das 3 coletas).")
with e2_tab:
    d = data.e2()
    d["rotulo"] = d["fonte"] + " " + d["parametro"].astype("string").fillna("") + " " + d["valor"].astype("string").fillna("")
    sel = d[d["tipo"].isin(["deteccao", "falso_positivo", "referencia"])]
    graf = alt.Chart(sel).mark_bar().encode(
        y=alt.Y("rotulo:N", title=None, sort=None), x=alt.X("taxa:Q", title="Taxa de reprovação", scale=alt.Scale(domain=[0, 1])),
        color=alt.Color("n_bits:N", title="Bits por lote"), yOffset="n_bits:N",
        tooltip=["rotulo", "tipo", "n_bits", "n_lotes", "n_reprovados", "taxa", "ic95_inf", "ic95_sup"],
    )
    st.altair_chart(graf, width="stretch")
    st.dataframe(sel.drop(columns="rotulo"), hide_index=True, width="stretch")
    st.caption("Intervalo de 95% nas colunas ic95. O gerador pseudoaleatório disfarçado (faulty_prng) passa nos testes: limite de testar só a saída.")
with e3_tab:
    st.dataframe(data.e3(), hide_index=True, width="stretch")
    st.caption("Custo teórico no Open Plan, sem gasto real. A razão QPU/os é de tempo, não de dinheiro, e fica perto do limiar de 10 conforme o custo (médio ou marginal) e a velocidade da máquina local: ver o relatório.")
with e4_tab:
    st.dataframe(data.e4(), hide_index=True, width="stretch")
with e5_tab:
    d5 = data.e5()
    st.dataframe(d5, hide_index=True, width="stretch")
    st.caption("Só a etapa A, sem QPU real. Limite clássico 2; máximo quântico 2√2 ≈ 2,83. É verificação de sanidade, não prova de aleatoriedade.")
