import os
import streamlit as st
import pandas as pd
from recomendacao import calcular_matriz_similaridade, recomendar_filmes, obter_detalhes_filme

# Configuração da página do Streamlit
st.set_page_config(page_title="Recomendador de Filmes Nacionais", layout="centered")

st.title("Sistema de Recomendação de Filmes Nacionais")
st.write("Descubra filmes brasileiros semelhantes com base nas sinopses!")

@st.cache_data
def carregar_dados_com_cache():
    diretorio_atual = os.path.dirname(os.path.abspath(__file__))
    caminho_arquivo = os.path.join(diretorio_atual, "..", "data", "filmes_nacionais_enriquecidos.parquet")
    
    return calcular_matriz_similaridade(caminho_arquivo)

with st.spinner("Carregando base de dados e calculando similaridades..."):
    df_filmes, matriz_sim = carregar_dados_com_cache()

titulos_disponiveis = sorted(df_filmes['titulo_exibicao'].dropna().unique())

# Interface do usuário (Selectbox)
filme_selecionado = st.selectbox(
    "Escolha um filme:",
    options=titulos_disponiveis
)

# Botão para gerar recomendações
if st.button("Recomendar Filmes Similares", type="primary"):
    filme_escolhido = obter_detalhes_filme(filme_selecionado, df_filmes)
    
    if filme_escolhido is not None:
        # Exibe o filme escolhido e sua sinopse
        st.subheader("Filme Selecionado")
        with st.container(border=True):
            st.markdown(f"### **{filme_escolhido['titulo_exibicao']}**")
            sinopse_original = filme_escolhido.get('sinopse')
            if pd.notna(sinopse_original):
                st.write(f"*{sinopse_original}*")
            else:
                st.info("Sinopse não disponível para este filme.")
                
        st.divider()
        
        # Exibir recomendação
        recomendacoes = recomendar_filmes(filme_selecionado, df_filmes, matriz_sim, top_n=5)
        
        st.subheader("Filmes Recomendados (Mais Similares):")
        for i, rec in enumerate(recomendacoes, 1):
            with st.container(border=True):
                st.markdown(f"**{i}. {rec['titulo']}**")
                st.caption(f"Índice de similaridade: {rec['score']:.3f}")
                
                if pd.notna(rec['sinopse']):
                    st.write(f"*{rec['sinopse']}*")