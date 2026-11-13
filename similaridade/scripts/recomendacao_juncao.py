"""
Recomendador de Filmes Nacionais — app Streamlit em arquivo único.

Combina a lógica de recomendação (TF-IDF + similaridade de cossenos)
e a interface Streamlit no mesmo módulo.
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
    # Usa o engine padrão do pandas (pyarrow), já instalado via requirements.txt
    df = pd.read_parquet(caminho_parquet)

    # Remove filmes sem sinopse (NaN ou string vazia)
    df = df[
        df["sinopse"].notna()
        & (df["sinopse"].astype(str).str.strip() != "")
    ].reset_index(drop=True)

    # Coluna derivada usada pelo frontend (chave de exibição)
    df["titulo_exibicao"] = _coluna_titulo_exibicao(df)
    df = df[df["titulo_exibicao"].notna()].reset_index(drop=True)

    print(f"Filmes com sinopse: {len(df)}")
    print("Vetorizando as sinopses (TF-IDF)...")
    tfidf = TfidfVectorizer(min_df=2, max_df=0.9)
    matriz_tfidf = tfidf.fit_transform(df["sinopse"])

    print("Calculando a matriz de similaridade de cossenos...")
    matriz_similaridade = cosine_similarity(matriz_tfidf, matriz_tfidf)

    return df, matriz_similaridade


def obter_detalhes_filme(titulo, df):
    """Retorna a linha (dict) do filme cujo `titulo_exibicao` casa com `titulo`."""
    if "titulo_exibicao" not in df.columns:
        return None

    exato = df[df["titulo_exibicao"] == titulo]
    if not exato.empty:
        return exato.iloc[0].to_dict()

    mask = df["titulo_exibicao"].astype(str).str.contains(titulo, case=False, na=False)
    match = df[mask]
    if match.empty:
        return None
    return match.iloc[0].to_dict()


def recomendar_filmes(titulo, df, matriz_similaridade, top_n=5):
    """Retorna lista de dicts (titulo, score, sinopse, poster_url) das top_n recomendações."""
    if "titulo_exibicao" not in df.columns:
        return []

    exato = df[df["titulo_exibicao"] == titulo]
    if not exato.empty:
        idx = exato.index[0]
    else:
        mask = df["titulo_exibicao"].astype(str).str.contains(titulo, case=False, na=False)
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
        recomendacoes.append(
            {
                "titulo": row["titulo_exibicao"],
                "score": float(score),
                "sinopse": row.get("sinopse") if pd.notna(row.get("sinopse")) else None,
                "poster_url": row.get("poster_url") if "poster_url" in df.columns else None,
            }
        )

    return recomendacoes


# ============================================================
# Interface Streamlit
# ============================================================

st.set_page_config(page_title="Recomendador de Filmes Nacionais", layout="centered")
st.title("Sistema de Recomendação de Filmes Nacionais")
st.write("Descubra filmes brasileiros semelhantes com base nas sinopses!")


@st.cache_data
def carregar_dados_com_cache():
    diretorio_atual = os.path.dirname(os.path.abspath(__file__))
    caminho_arquivo = os.path.join(
        diretorio_atual, "..", "data", "filmes_nacionais_enriquecidos.parquet"
    )
    return calcular_matriz_similaridade(caminho_arquivo)


with st.spinner("Carregando base de dados e calculando similaridades..."):
    df_filmes, matriz_sim = carregar_dados_com_cache()

# --- Seleção do filme ---
titulos_disponiveis = sorted(df_filmes["titulo_exibicao"].dropna().unique())

filme_selecionado = st.selectbox(
    "Escolha um filme:",
    options=titulos_disponiveis,
    index=None,
    placeholder="Digite ou selecione um filme...",
)

if st.button("Recomendar Filmes Similares", type="primary") and filme_selecionado:
    filme_escolhido = obter_detalhes_filme(filme_selecionado, df_filmes)

    if filme_escolhido is None:
        st.error("Filme não encontrado na base.")
        st.stop()

    # --- Filme selecionado ---
    st.subheader("Filme Selecionado")
    with st.container(border=True):
        col_img, col_txt = st.columns([1, 3])
        with col_img:
            poster = filme_escolhido.get("poster_url")
            if pd.notna(poster) and poster:
                st.image(poster, use_container_width=True)
        with col_txt:
            st.markdown(f"### **{filme_escolhido['titulo_exibicao']}**")
            sinopse_original = filme_escolhido.get("sinopse")
            if pd.notna(sinopse_original) and sinopse_original:
                st.write(f"*{sinopse_original}*")
            else:
                st.info("Sinopse não disponível para este filme.")

    st.divider()

    # --- Recomendações ---
    recomendacoes = recomendar_filmes(
        filme_selecionado, df_filmes, matriz_sim, top_n=5
    )

    if not recomendacoes:
        st.warning("Não foi possível gerar recomendações para este filme.")
        st.stop()

    st.subheader("Filmes Recomendados (Mais Similares):")
    for i, rec in enumerate(recomendacoes, 1):
        with st.container(border=True):
            col_img, col_txt = st.columns([1, 3])
            with col_img:
                if rec.get("poster_url"):
                    st.image(rec["poster_url"], use_container_width=True)
            with col_txt:
                st.markdown(f"**{i}. {rec['titulo']}**")
                st.caption(f"Índice de similaridade: {rec['score']:.3f}")
                if rec.get("sinopse"):
                    st.write(f"*{rec['sinopse']}*")
