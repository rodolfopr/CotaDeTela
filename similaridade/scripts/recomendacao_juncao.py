"""
Recomendador de Filmes Nacionais — app Streamlit em arquivo único.
Galeria de capas em uma linha, com botão transparente sobreposto e paginação.
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
    print("Vetorizando as sinopses (TF-IDF)...")
    tfidf = TfidfVectorizer(min_df=2, max_df=0.9)
    matriz_tfidf = tfidf.fit_transform(df["sinopse"])

    print("Calculando a matriz de similaridade de cossenos...")
    matriz_similaridade = cosine_similarity(matriz_tfidf, matriz_tfidf)

    return df, matriz_similaridade


def obter_detalhes_filme(titulo, df):
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

st.set_page_config(page_title="Recomendador de Filmes Nacionais", layout="wide")
st.title("Sistema de Recomendação de Filmes Nacionais")
st.write("Clique na capa de um filme para ver suas informações e receber recomendações similares.")


@st.cache_data
def carregar_dados_com_cache():
    diretorio_atual = os.path.dirname(os.path.abspath(__file__))
    caminho_arquivo = os.path.join(diretorio_atual, "..", "data", "filmes_nacionais_enriquecidos.parquet")
    return calcular_matriz_similaridade(caminho_arquivo)


with st.spinner("Carregando base de dados e calculando similaridades..."):
    df_filmes, matriz_sim = carregar_dados_com_cache()


# ============================================================
# CSS: botão transparente ancorado sobre a capa
# ============================================================
# Estratégia: cada célula da galeria é um bloco relativo. A imagem é
# desenhada; o botão é posicionado com position:absolute cobrindo 100%
# da largura e da altura da imagem. Assim o clique atinge toda a capa,
# independentemente da proporção do pôster.
#
# A altura da imagem é fixada em 240px (proporção ~2:3 de pôster),
# então o botão cobre exatamente essa área.
st.markdown(
    """
    <style>
    /* Cada coluna da galeria vira um container relativo */
    div[data-testid="column"] {
        position: relative;
    }

    /* A imagem da capa tem altura fixa para o cálculo do overlay */
    div[data-testid="column"] img {
        height: 240px !important;
        width: 100% !important;
        object-fit: cover !important;
        border-radius: 6px;
    }

    /* O botão é absoluto, cobrindo exatamente a área da imagem */
    div[data-testid="column"] div[data-testid="stButton"] {
        position: absolute;
        top: 0;
        left: 0;
        width: 100%;
        height: 240px;
        z-index: 10;
        margin: 0;
        padding: 0;
    }

    /* Botão invisível, mas clicável */
    div[data-testid="column"] div[data-testid="stButton"] > button {
        background: transparent;
        border: none;
        color: transparent;
        width: 100%;
        height: 100%;
        cursor: pointer;
        transition: background 0.2s ease;
        padding: 0;
        margin: 0;
    }

    /* Feedback sutil no hover */
    div[data-testid="column"] div[data-testid="stButton"] > button:hover {
        background: rgba(0, 120, 255, 0.18);
        border: none;
        color: transparent;
    }

    div[data-testid="column"] div[data-testid="stButton"] > button:focus {
        box-shadow: none;
        border: none;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


# --- Estado da sessão ---
if "filme_selecionado" not in st.session_state:
    st.session_state["filme_selecionado"] = None
if "pagina_galeria" not in st.session_state:
    st.session_state["pagina_galeria"] = 0


# ============================================================
# Galeria: uma linha de capas + paginação
# ============================================================

st.subheader("Selecione um filme pela capa")

filmes_com_poster = df_filmes[df_filmes["poster_url"].notna()].copy().reset_index(drop=True)

CAPAS_POR_PAGINA = 6  # uma linha de 6 capas
total_paginas = max(1, (len(filmes_com_poster) + CAPAS_POR_PAGINA - 1) // CAPAS_POR_PAGINA)

# Garante que a página atual está dentro dos limites
if st.session_state["pagina_galeria"] >= total_paginas:
    st.session_state["pagina_galeria"] = total_paginas - 1
if st.session_state["pagina_galeria"] < 0:
    st.session_state["pagina_galeria"] = 0

pagina_atual = st.session_state["pagina_galeria"]
inicio = pagina_atual * CAPAS_POR_PAGINA
fim = inicio + CAPAS_POR_PAGINA
filmes_pagina = filmes_com_poster.iloc[inicio:fim]

# Uma linha de 6 colunas
cols = st.columns(CAPAS_POR_PAGINA)
for i, (_, row) in enumerate(filmes_pagina.iterrows()):
    with cols[i]:
        # Imagem (altura fixada pelo CSS em 240px)
        st.image(row["poster_url"], use_container_width=True)
        # Botão transparente sobreposto (CSS posiciona por cima da imagem)
        if st.button(" ", key=f"sel_{row['titulo_exibicao']}_{i}"):
            st.session_state["filme_selecionado"] = row["titulo_exibicao"]
            st.rerun()
        # Título abaixo, fora da área do botão
        st.caption(row["titulo_exibicao"])

# Controle de páginas
st.write("")  # respiro
col_prev, col_info, col_next = st.columns([1, 3, 1])
with col_prev:
    if st.button("⬅️ Anterior", disabled=(pagina_atual == 0), use_container_width=True):
        st.session_state["pagina_galeria"] -= 1
        st.rerun()
with col_info:
    st.markdown(
        f"<div style='text-align:center; padding-top:8px;'>"
        f"Página <b>{pagina_atual + 1}</b> de <b>{total_paginas}</b> — "
        f"{len(filmes_pagina)} de {len(filmes_com_poster)} filmes com capa"
        f"</div>",
        unsafe_allow_html=True,
    )
with col_next:
    if st.button("Próxima ➡️", disabled=(pagina_atual >= total_paginas - 1), use_container_width=True):
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

    recomendacoes = recomendar_filmes(titulo_selecionado, df_filmes, matriz_sim, top_n=5)

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
