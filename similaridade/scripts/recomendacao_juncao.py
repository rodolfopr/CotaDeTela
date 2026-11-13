"""
Recomendador de Filmes Nacionais — app Streamlit em arquivo único.
Consulta em texto livre: o usuário digita o título e clica em Pesquisar.
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
    """
    Busca por título (exibição, original e PT-BR), case-insensitive.
    Retorna um DataFrame com as linhas que casam com o termo.
    """
    termo = termo.strip()
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
st.write("Digite o título de um filme brasileiro e clique em **Pesquisar** para ver os similares.")


@st.cache_data
def carregar_dados_com_cache():
    diretorio_atual = os.path.dirname(os.path.abspath(__file__))
    caminho_arquivo = os.path.join(
        diretorio_atual, "..", "data", "filmes_nacionais_enriquecidos.parquet"
    )
    return calcular_matriz_similaridade(caminho_arquivo)


with st.spinner("Carregando base de dados e calculando similaridades..."):
    df_filmes, matriz_sim = carregar_dados_com_cache()


# --- Consulta em texto livre ---
col_input, col_botao = st.columns([4, 1])
with col_input:
    termo_pesquisa = st.text_input(
        "Título do filme:",
        placeholder="Ex.: Cidade de Deus",
        label_visibility="collapsed",
    )
with col_botao:
    pesquisar = st.button("Pesquisar", type="primary", use_container_width=True)

# A busca só acontece quando o botão é acionado
if pesquisar:
    if not termo_pesquisa or not termo_pesquisa.strip():
        st.warning("Digite um título para pesquisar.")
    else:
        resultados = buscar_filmes(termo_pesquisa, df_filmes)

        if resultados.empty:
            st.info(f"Nenhum filme encontrado para **'{termo_pesquisa.strip()}'**.")
        else:
            # Se houver mais de um resultado, mostra todos; se houver só um, já exibe direto
            st.success(f"{len(resultados)} filme(s) encontrado(s) para **'{termo_pesquisa.strip()}'**.")

            # Para cada resultado, exibe o card do filme + suas recomendações
            # (limitado a 3 resultados para não sobrecarregar a tela)
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
                            st.image(poster, use_container_width=True)
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
                                    st.image(rec["poster_url"], use_container_width=True)
                            with col_txt:
                                st.markdown(f"**{i}. {rec['titulo']}**")
                                st.caption(f"Índice de similaridade: {rec['score']:.3f}")
                                if rec.get("sinopse"):
                                    st.write(f"*{rec['sinopse']}*")

            # Aviso se houver mais resultados do que os exibidos
            if len(resultados) > 3:
                st.caption(
                    f"Mostrando os 3 primeiros de {len(resultados)} resultados. "
                    "Refine o termo para ver outros filmes."
                )
