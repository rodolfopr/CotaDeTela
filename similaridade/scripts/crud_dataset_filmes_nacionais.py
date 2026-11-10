"""
CRUD Streamlit para o arquivo Parquet de filmes nacionais enriquecidos.
"""

from pathlib import Path

import pandas as pd
import streamlit as st

# --- Configuração de caminhos ---
def _encontrar_pasta_similaridade(inicio: Path) -> Path:
    for candidato in [inicio, *inicio.parents]:
        if candidato.name == "similaridade":
            return candidato
    raise FileNotFoundError(
        f"Não encontrei a pasta 'similaridade' subindo a partir de {inicio}"
    )

# Como este script roda via `streamlit run`, __file__ aponta para ele mesmo.
PASTA_SIMILARIDADE = _encontrar_pasta_similaridade(Path(__file__).resolve().parent)
ARQUIVO_PARQUET = PASTA_SIMILARIDADE / "data" / "filmes_nacionais_enriquecidos.parquet"

# --- Carregamento e persistência ---
@st.cache_data
def carregar_dados(caminho: str) -> pd.DataFrame:
    """Lê o Parquet. O cache evita reler o arquivo a cada rerun do Streamlit."""
    return pd.read_parquet(caminho)

def salvar_dados(df: pd.DataFrame, caminho: str) -> None:
    """Persiste o DataFrame de volta no Parquet."""
    df.to_parquet(caminho, index=False)

# --- Interface ---
st.set_page_config(page_title="CRUD Filmes Nacionais", layout="wide")
st.title("🎬 CRUD — Filmes Nacionais Enriquecidos")

# Carrega os dados originais
try:
    df = carregar_dados(str(ARQUIVO_PARQUET))
except FileNotFoundError:
    st.error(f"Arquivo não encontrado: {ARQUIVO_PARQUET}")
    st.stop()

# --- Filtro (Read) ---
st.subheader("Filtro")
col_filtro1, col_filtro2 = st.columns(2)
with col_filtro1:
    termo_busca = st.text_input("Buscar por título (original ou PT-BR):", "")
with col_filtro2:
    apenas_com_sinopse = st.checkbox("Apenas com sinopse preenchida", value=False)

df_filtrado = df.copy()
if termo_busca:
    mask = (
        df_filtrado["titulo_original"].str.contains(termo_busca, case=False, na=False)
        | df_filtrado["titulo_ptbr"].str.contains(termo_busca, case=False, na=False)
    )
    df_filtrado = df_filtrado[mask]

if apenas_com_sinopse:
    df_filtrado = df_filtrado[df_filtrado["sinopse"].notna()]

st.caption(f"Exibindo {len(df_filtrado)} de {len(df)} linhas.")

# --- Editor (Update / Create / Delete) ---
st.subheader("Editar dados")
st.info(
    "Edite células diretamente, adicione novas linhas no final ou "
    "selecione linhas para excluir. Clique em **Salvar alterações** para persistir."
)

# st.data_editor retorna um DataFrame editado.
# num_rows="dynamic" permite adicionar e remover linhas [citation:2].
df_editado = st.data_editor(
    df_filtrado,
    num_rows="dynamic",
    use_container_width=True,
    key="editor_filmes",
    column_config={
        "cpb_roe": st.column_config.TextColumn("CPB_ROE", disabled=True),
        "titulo_original": st.column_config.TextColumn("Título Original"),
        "titulo_ptbr": st.column_config.TextColumn("Título PT-BR"),
        "primeira_exibicao": st.column_config.DateColumn("Primeira Exibição"),
        "ultima_exibicao": st.column_config.DateColumn("Última Exibição"),
        "total_sessoes": st.column_config.NumberColumn("Sessões"),
        "dias_com_exibicao": st.column_config.NumberColumn("Dias"),
        "salas_distintas": st.column_config.NumberColumn("Salas"),
        "publico_total": st.column_config.NumberColumn("Público Total", format="%d"),
        "publico_medio_por_sessao": st.column_config.NumberColumn("Público Médio/Sessão"),
        "sinopse": st.column_config.TextColumn("Sinopse", width="large"),
        "poster_path": st.column_config.TextColumn("Poster Path"),
        "poster_url": st.column_config.LinkColumn("Poster URL", display_text="Ver pôster"),
        "tmdb_id": st.column_config.NumberColumn("TMDb ID", disabled=True),
    },
)

# --- Persistência ---
if st.button("💾 Salvar alterações", type="primary"):
    # O editor retorna apenas as linhas visíveis (filtradas).
    # Para um CRUD completo, o ideal é mesclar com o df original.
    # Aqui, uma abordagem simples: se não há filtro, salva direto o editado.
    # Se há filtro, aplica as edições sobre as linhas correspondentes.
    if termo_busca == "" and not apenas_com_sinopse:
        df_final = df_editado
    else:
        # Mescla: atualiza as linhas filtradas com as edições e mantém as demais.
        # Usa cpb_roe como chave (assumindo que é única).
        df_final = df.set_index("cpb_roe")
        df_editado_idx = df_editado.set_index("cpb_roe")
        df_final.update(df_editado_idx)
        # Adiciona linhas novas (se houver) que não estavam no original.
        novas = df_editado_idx.loc[~df_editado_idx.index.isin(df_final.index)]
        if not novas.empty:
            df_final = pd.concat([df_final, novas])
        df_final = df_final.reset_index()

    salvar_dados(df_final, str(ARQUIVO_PARQUET))
    st.cache_data.clear()  # invalida o cache para recarregar na próxima execução
    st.success(f"Alterações salvas em {ARQUIVO_PARQUET}")
    st.rerun()

# --- Download (opcional) ---
st.subheader("Download")
csv = df_editado.to_csv(index=False).encode("utf-8")
st.download_button(
    "⬇️ Baixar CSV do que está na tela",
    data=csv,
    file_name="filmes_nacionais_editado.csv",
    mime="text/csv",
)