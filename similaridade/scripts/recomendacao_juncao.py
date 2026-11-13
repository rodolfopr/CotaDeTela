"""
Recomendador de Filmes Nacionais — app Streamlit em arquivo único.
Ao escolher um filme no combobox, o card e os similares aparecem imediatamente.
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
    tfidf = TfidfVectorizer(min_df=2, max_df=0.9)
    matriz_tfidf = tfidf.fit_transform(df["sinopse"])

    print("Calculando a matriz de similaridade de cossenos...")
    matriz_similaridade = cosine_similarity(matriz_tfidf, matriz_tfidf)

    return df, matriz_similaridade


def obter_detalhes_filme(titulo, df):
    exato = df[df["titulo_exibicao"] == titulo]
    if not exato.empty:
        return exato.iloc[0].to_dict()
    mask = df["titulo_exibicao"].astype(str).str.contains(titulo, case=False, na=False, regex=False)
    match = df[mask]
    return match.iloc[0].to_dict() if not match.empty else None


def recomendar_filmes(titulo, df, matriz_similaridade, top_n=5):
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
        poster = row.get("poster_url")
        if pd.isna(poster) or not poster:
            poster = None
        sinopse = row.get("sinopse")
        if pd.isna(sinopse) or not sinopse:
            sinopse = None

        recomendacoes.append({
            "titulo": row["titulo_exibicao"],
            "score": float(score),
            "sinopse": sinopse,
            "poster_url": poster,
        })
    return recomendacoes


# ============================================================
# Interface Streamlit
# ============================================================

st.set_page_config(page_title="Recomendador de Filmes Nacionais", layout="centered")
st.title("Sistema de Recomendação de Filmes Nacionais")
st.write("Escolha um filme brasileiro para ver seus dados e os similares.")


@st.cache_data
def carregar_dados_com_cache():
    diretorio_atual = os.path.dirname(os.path.abspath(__file__))
    caminho_arquivo = os.path.join(
        diretorio_atual, "..", "data", "filmes_nacionais_enriquecidos.parquet"
    )
    return calcular_matriz_similaridade(caminho_arquivo)


with st.spinner("Carregando base de dados e calculando similaridades..."):
    df_filmes, matriz_sim = carregar_dados_com_cache()


# --- Combobox ---
titulos_disponiveis = sorted(df_filmes["titulo_exibicao"].dropna().unique())

filme_selecionado = st.selectbox(
    "Filme:",
    options=titulos_disponiveis,
    index=None,
    placeholder="Digite ou selecione um filme...",
)


# --- Resultado imediato ao escolher ---
if filme_selecionado:
    filme = obter_detalhes_filme(filme_selecionado, df_filmes)
    if filme is None:
        st.error("Filme não encontrado na base.")
        st.stop()

    st.divider()

    # Card do filme selecionado
    with st.container(border=True):
        col_img, col_txt = st.columns([1, 3])
        with col_img:
            poster = filme.get("poster_url")
            if poster and isinstance(poster, str):
                st.image(poster, width="stretch")
        with col_txt:
            st.markdown(f"### **{filme['titulo_exibicao']}**")
            sinopse = filme.get("sinopse")
            if pd.notna(sinopse) and sinopse:
                st.write(f"*{sinopse}*")
            else:
                st.info("Sinopse não disponível para este filme.")

    # Similares (sempre visíveis após a escolha)
    recs = recomendar_filmes(filme_selecionado, df_filmes, matriz_sim, top_n=5)

    if not recs:
        st.warning("Não foi possível gerar recomendações para este filme.")
    else:
        st.subheader("Filmes Recomendados (Mais Similares):")
        for i, rec in enumerate(recs, 1):
            with st.container(border=True):
                col_img, col_txt = st.columns([1, 3])
                with col_img:
                    if rec["poster_url"]:
                        st.image(rec["poster_url"], width="stretch")
                with col_txt:
                    st.markdown(f"**{i}. {rec['titulo']}**")
                    st.caption(f"Similaridade: {rec['score']:.3f}")
                    if rec["sinopse"]:
                        st.write(f"*{rec['sinopse']}*")
