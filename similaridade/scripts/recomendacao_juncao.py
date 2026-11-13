"""
Recomendador de Filmes Nacionais — app Streamlit em arquivo único.

Consulta em texto livre com:
  - Enter dispara a busca (on_change + st.session_state)
  - Sugestões aparecem enquanto digita (live=True + filtro local)
"""

import os

import pandas as pd
import streamlit as st
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity


# ============================================================
# Lógica de recomendação
# ============================================================

def _coluna_titulo_exibicao(df: pd.DataFrame) -> pd.Series:
    """PT-BR quando disponível, senão o título original."""
    ptbr = df["titulo_ptbr"] if "titulo_ptbr" in df.columns else pd.Series([None] * len(df))
    original = df["titulo_original"] if "titulo_original" in df.columns else pd.Series([None] * len(df))
    return ptbr.where(ptbr.notna() & (ptbr.astype(str).str.strip() != ""), original)


def calcular_matriz_similaridade(caminho_parquet):
    print("Lendo o arquivo parquet...")
    df = pd.read_parquet(caminho_parquet)

    df = df[
        df["sinopse"].notna()
        & (df["sinopse"].astype(str).str.strip() != "")
    ].reset_index(drop=True)

    df["titulo_exibicao"] = _coluna_titulo_exibicao(df)
    df = df[df["titulo_exibicao"].notna()].reset_index(drop=True)

    print(f"Filmes com sinopse: {len(df)}")
    print("Vetorizando as sinopses (TF-IDF)...")
    tfidf = TfidfVectorizer(min_df=2, max_df=0.9)
    matriz_tfidf = tfidf.fit_transform(df["sinopse"])

    print("Calculando a matriz de similaridade de cossenos...")
    matriz_similaridade = cosine_similarity(matriz_tfidf, matriz_tfidf)

    return df, matriz_similaridade


def buscar_filmes(termo, df):
    """Busca por título (exibição, original e PT-BR), case-insensitive."""
    termo = (termo or "").strip()
    if not termo:
        return df.iloc[0:0]

    colunas_busca = [c for c in ("titulo_exibicao", "titulo_original", "titulo_ptbr") if c in df.columns]
    if not colunas_busca:
        return df.iloc[0:0]

    mask = False
    for col in colunas_busca:
        mask = mask | df[col].astype(str).str.contains(termo, case=False, na=False, regex=False)

    return df[mask]


def obter_detalhes_filme(titulo, df):
    if "titulo_exibicao" not in df.columns:
        return None
    exato = df[df["titulo_exibicao"] == titulo]
    if not exato.empty:
        return exato.iloc[0].to_dict()
    mask = df["titulo_exibicao"].astype(str).str.contains(titulo, case=False, na=False, regex=False)
    match = df[mask]
    if match.empty:
        return None
    return match.iloc[0].to_dict()


def recomendar_filmes(titulo, df, matriz_similaridade, top_n=5):
    if "titulo_exibicao" not in df.columns:
        return []
    exato = df[df["titulo_exibicao"] == titulo]
    if not exato.empty:
        idx = exato.index[0]
    else:
        mask = df["titulo_exibicao"].astype(str).str.contains(titulo, case=False, na=False, regex=False)
        match = df[mask]
        if match.empty:
            return []
        idx = match.index[0]

    scores = list(enumerate(matriz_similaridade[idx]))
    scores = sorted(scores, key=lambda x: (-x[1], x[0]))
    scores = [s for s in scores if s[0] != idx][:top_n]

    recomendacoes = []
    for i, score in scores:
        row = df.loc[i]
        recomendacoes.append({
            "titulo": row["titulo_exibicao"],
            "score": float(score),
            "sinopse": row.get("sinopse") if pd.notna(row.get("sinopse")) else None,
            "poster_url": row.get("poster_url") if "poster_url" in df.columns else None,
        })
    return recomendacoes


# ============================================================
# Interface Streamlit
# ============================================================

st.set_page_config(page_title="Recomendador de Filmes Nacionais", layout="centered")
st.title("Sistema de Recomendação de Filmes Nacionais")
st.write("Digite o título de um filme brasileiro. Pressione **Enter** ou clique em **Pesquisar**.")


@st.cache_data
def carregar_dados_com_cache():
    diretorio_atual = os.path.dirname(os.path.abspath(__file__))
    caminho_arquivo = os.path.join(
        diretorio_atual, "..", "data", "filmes_nacionais_enriquecidos.parquet"
    )
    return calcular_matriz_similaridade(caminho_arquivo)


with st.spinner("Carregando base de dados e calculando similaridades..."):
    df_filmes, matriz_sim = carregar_dados_com_cache()


# --- Inicializa estado da sessão ---
if "pesquisar_acionado" not in st.session_state:
    st.session_state["pesquisar_acionado"] = False
if "termo_pesquisa" not in st.session_state:
    st.session_state["termo_pesquisa"] = ""


# --- Callback: Enter no campo dispara a busca ---
def _ao_submeter():
    """Chamado quando o usuário pressiona Enter no text_input."""
    st.session_state["pesquisar_acionado"] = True
    st.session_state["termo_pesquisa"] = st.session_state.get("campo_busca", "")


# --- Campo de busca com sugestões ao digitar ---
col_input, col_botao = st.columns([4, 1])
with col_input:
    termo_digitado = st.text_input(
        "Título do filme:",
        key="campo_busca",
        placeholder="Ex.: Cidade de Deus",
        label_visibility="collapsed",
        on_change=_ao_submeter,
        live=True,  # envia o valor ao Python após pausa na digitação
    )
with col_botao:
    if st.button("Pesquisar", type="primary", width="stretch"):
        st.session_state["pesquisar_acionado"] = True
        st.session_state["termo_pesquisa"] = termo_digitado


# --- Sugestões enquanto digita (aparecem antes de pesquisar) ---
if (
    not st.session_state["pesquisar_acionado"]
    and termo_digitado
    and len(termo_digitado.strip()) >= 2
):
    termo_lower = termo_digitado.strip().lower()
    titulos_unicos = df_filmes["titulo_exibicao"].dropna().unique()
    sugestoes = [t for t in titulos_unicos if termo_lower in str(t).lower()][:8]

    if sugestoes:
        st.caption("Sugestões — clique para pesquisar:")
        cols_sug = st.columns(min(len(sugestoes), 4))
        for i, s in enumerate(sugestoes):
            with cols_sug[i % len(cols_sug)]:
                if st.button(s, key=f"sug_{i}_{s}", width="stretch"):
                    st.session_state["campo_busca"] = s
                    st.session_state["termo_pesquisa"] = s
                    st.session_state["pesquisar_acionado"] = True
                    st.rerun()


# --- Executa a busca quando acionada ---
if st.session_state["pesquisar_acionado"]:
    termo = st.session_state["termo_pesquisa"].strip() if st.session_state["termo_pesquisa"] else ""

    # Reseta a flag para não repetir a busca em reruns não relacionados
    st.session_state["pesquisar_acionado"] = False

    if not termo:
        st.warning("Digite um título para pesquisar.")
    else:
        resultados = buscar_filmes(termo, df_filmes)

        if resultados.empty:
            st.info(f"Nenhum filme encontrado para **'{termo}'**.")
        else:
            st.success(f"{len(resultados)} filme(s) encontrado(s) para **'{termo}'**.")

            for _, row in resultados.head(3).iterrows():
                titulo = row["titulo_exibicao"]
                filme_escolhido = obter_detalhes_filme(titulo, df_filmes)
                if filme_escolhido is None:
                    continue

                st.divider()
                st.subheader(f"Filme: {titulo}")

                with st.container(border=True):
                    col_img, col_txt = st.columns([1, 3])
                    with col_img:
                        poster = filme_escolhido.get("poster_url")
                        if pd.notna(poster) and poster:
                            st.image(poster, width="stretch")
                    with col_txt:
                        st.markdown(f"### **{filme_escolhido['titulo_exibicao']}**")
                        sinopse_original = filme_escolhido.get("sinopse")
                        if pd.notna(sinopse_original) and sinopse_original:
                            st.write(f"*{sinopse_original}*")
                        else:
                            st.info("Sinopse não disponível para este filme.")

                recomendacoes = recomendar_filmes(titulo, df_filmes, matriz_sim, top_n=5)

                if not recomendacoes:
                    st.warning("Não foi possível gerar recomendações para este filme.")
                else:
                    st.markdown("**Filmes Recomendados (Mais Similares):**")
                    for i, rec in enumerate(recomendacoes, 1):
                        with st.container(border=True):
                            col_img, col_txt = st.columns([1, 3])
                            with col_img:
                                if rec.get("poster_url"):
                                    st.image(rec["poster_url"], width="stretch")
                            with col_txt:
                                st.markdown(f"**{i}. {rec['titulo']}**")
                                st.caption(f"Índice de similaridade: {rec['score']:.3f}")
                                if rec.get("sinopse"):
                                    st.write(f"*{rec['sinopse']}*")

            if len(resultados) > 3:
                st.caption(
                    f"Mostrando os 3 primeiros de {len(resultados)} resultados. "
                    "Refine o termo para ver outros filmes."
                )
