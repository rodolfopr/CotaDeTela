"""
Recomendador de Filmes Nacionais — app Streamlit em arquivo único.
Usa apenas recursos nativos do Streamlit para a galeria de capas.
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

st.set_page_config(page_title="Recomendador de Filmes Nacionais", layout="wide")
st.title("Sistema de Recomendação de Filmes Nacionais")
st.write("Clique em **Selecionar** na capa de um filme para ver suas informações e receber recomendações similares.")


@st.cache_data
def carregar_dados_com_cache():
    diretorio_atual = os.path.dirname(os.path.abspath(__file__))
    caminho_arquivo = os.path.join(
        diretorio_atual, "..", "data", "filmes_nacionais_enriquecidos.parquet"
    )
    return calcular_matriz_similaridade(caminho_arquivo)


with st.spinner("Carregando base de dados e calculando similaridades..."):
    df_filmes, matriz_sim = carregar_dados_com_cache()


# --- Inicializa estado da sessão para o filme selecionado ---
if "filme_selecionado" not in st.session_state:
    st.session_state["filme_selecionado"] = None


# ============================================================
# Galeria de capas com recursos nativos
# ============================================================

st.subheader("Selecione um filme pela capa")

# Filtra apenas filmes com pôster para evitar imagens quebradas
filmes_com_poster = df_filmes[df_filmes["poster_url"].notna()].copy()

# Paginação simples: mostra 24 filmes por página (6 colunas x 4 linhas)
FILMES_POR_PAGINA = 24
total_paginas = max(1, (len(filmes_com_poster) + FILMES_POR_PAGINA - 1) // FILMES_POR_PAGINA)

# Controle de página no estado da sessão
if "pagina_galeria" not in st.session_state:
    st.session_state["pagina_galeria"] = 0

pagina_atual = st.session_state["pagina_galeria"]
inicio = pagina_atual * FILMES_POR_PAGINA
fim = inicio + FILMES_POR_PAGINA
filmes_pagina = filmes_com_poster.iloc[inicio:fim]

# Exibe a grade de capas
cols = st.columns(6)
for i, (_, row) in enumerate(filmes_pagina.iterrows()):
    with cols[i % 6]:
        st.image(row["poster_url"], use_container_width=True)
        # Botão ocupa a largura da coluna e tem chave única por título
        if st.button(
            "Selecionar",
            key=f"sel_{row['titulo_exibicao']}",
            use_container_width=True,
        ):
            st.session_state["filme_selecionado"] = row["titulo_exibicao"]
            st.rerun()

# Navegação entre páginas
if total_paginas > 1:
    col_prev, col_info, col_next = st.columns([1, 2, 1])
    with col_prev:
        if st.button("⬅️ Anterior", disabled=(pagina_atual == 0)):
            st.session_state["pagina_galeria"] -= 1
            st.rerun()
    with col_info:
        st.caption(f"Página {pagina_atual + 1} de {total_paginas} — "
                   f"{len(filmes_pagina)} de {len(filmes_com_poster)} filmes com capa")
    with col_next:
        if st.button("Próxima ➡️", disabled=(pagina_atual >= total_paginas - 1)):
            st.session_state["pagina_galeria"] += 1
            st.rerun()


# ============================================================
# Detalhes do filme selecionado + recomendações
# ============================================================

if st.session_state["filme_selecionado"]:
    titulo_selecionado = st.session_state["filme_selecionado"]
    filme_escolhido = obter_detalhes_filme(titulo_selecionado, df_filmes)

    if filme_escolhido is None:
        st.error("Filme não encontrado na base.")
        st.stop()

    st.divider()
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

    # --- Recomendações ---
    recomendacoes = recomendar_filmes(
        titulo_selecionado, df_filmes, matriz_sim, top_n=5
    )

    if not recomendacoes:
        st.warning("Não foi possível gerar recomendações para este filme.")
    else:
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
