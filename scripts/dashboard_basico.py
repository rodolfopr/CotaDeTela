"""
Dashboard Streamlit para a bilheteria diária da ANCINE.
"""

from pathlib import Path

import duckdb
import pandas as pd
import streamlit as st

# --- Configuração ---

PASTA_RAIZ = Path(__file__).resolve().parent.parent
PARQUET_PADRAO = PASTA_RAIZ / "data" / "bilheteria.parquet"

st.set_page_config(
    page_title="Bilheteria ANCINE",
    page_icon="🎬",
    layout="wide",
    initial_sidebar_state="expanded",
)


# --- Conexão cacheada ---

@st.cache_resource
def get_conexao():
    """Cria uma conexão DuckDB persistente (cacheada)."""
    con = duckdb.connect()
    con.execute("SET memory_limit = '4GB';")
    con.execute("SET threads = 4;")
    return con


@st.cache_data(show_spinner="Consultando dados...")
def query(sql: str, _dummy: int = 0) -> pd.DataFrame:
    """Executa uma query e devolve um DataFrame (cacheado)."""
    con = get_conexao()
    return con.sql(sql).df()


def arquivo_existe() -> bool:
    return PARQUET_PADRAO.exists()


# --- Carrega metadados para os filtros ---

def carrega_opcoes():
    """Carrega listas de opções para os filtros (cacheado)."""
    sql = f"""
        SELECT
            MIN(DATA_EXIBICAO) AS dt_min,
            MAX(DATA_EXIBICAO) AS dt_max,
            COUNT(DISTINCT UF_SALA_COMPLEXO) AS n_uf,
            COUNT(DISTINCT MUNICIPIO_SALA_COMPLEXO) AS n_mun,
            COUNT(DISTINCT TITULO_BRASIL) AS n_titulos,
            COUNT(DISTINCT CNPJ_EXIBIDORA) AS n_exibidores
        FROM '{PARQUET_PADRAO}'
    """
    return query(sql)


def carrega_ufs():
    sql = f"""
        SELECT DISTINCT UF_SALA_COMPLEXO AS uf
        FROM '{PARQUET_PADRAO}'
        WHERE UF_SALA_COMPLEXO IS NOT NULL
        ORDER BY uf
    """
    return query(sql)["uf"].tolist()


def carrega_municipios(ufs_selecionadas):
    if not ufs_selecionadas:
        return []
    lista = ",".join(f"'{u}'" for u in ufs_selecionadas)
    sql = f"""
        SELECT DISTINCT MUNICIPIO_SALA_COMPLEXO AS mun
        FROM '{PARQUET_PADRAO}'
        WHERE UF_SALA_COMPLEXO IN ({lista})
        ORDER BY mun
    """
    return query(sql)["mun"].tolist()


def carrega_titulos():
    sql = f"""
        SELECT DISTINCT TITULO_BRASIL AS titulo
        FROM '{PARQUET_PADRAO}'
        WHERE TITULO_BRASIL IS NOT NULL
        ORDER BY titulo
    """
    return query(sql)["titulo"].tolist()


# --- Monta WHERE a partir dos filtros ---

def monta_where(filtros) -> str:
    cond = []

    if filtros["data_ini"] and filtros["data_fim"]:
        cond.append(
            f"DATA_EXIBICAO BETWEEN DATE '{filtros['data_ini']}' "
            f"AND DATE '{filtros['data_fim']}'"
        )

    if filtros["ufs"]:
        lista = ",".join(f"'{u}'" for u in filtros["ufs"])
        cond.append(f"UF_SALA_COMPLEXO IN ({lista})")

    if filtros["municipios"]:
        lista = ",".join(f"'{m}'" for m in filtros["municipios"])
        cond.append(f"MUNICIPIO_SALA_COMPLEXO IN ({lista})")

    if filtros["titulos"]:
        lista = ",".join(f"'{t.replace(chr(39), chr(39)*2)}'" for t in filtros["titulos"])
        cond.append(f"TITULO_BRASIL IN ({lista})")

    return " AND ".join(cond) if cond else "1=1"


# --- Consultas analíticas ---

def kpis(where: str) -> dict:
    sql = f"""
        SELECT
            SUM(PUBLICO) AS publico,
            COUNT(*) AS sessoes,
            COUNT(DISTINCT TITULO_BRASIL) AS filmes,
            COUNT(DISTINCT REGISTRO_SALA) AS salas,
            COUNT(DISTINCT CNPJ_EXIBIDORA) AS exibidores,
            MIN(DATA_EXIBICAO) AS dt_ini,
            MAX(DATA_EXIBICAO) AS dt_fim
        FROM '{PARQUET_PADRAO}'
        WHERE {where}
    """
    return query(sql).iloc[0].to_dict()


def serie_temporal(where: str, granularidade: str) -> pd.DataFrame:
    """granularidade: 'dia' | 'mes' | 'ano'"""
    if granularidade == "dia":
        expr = "DATA_EXIBICAO"
    elif granularidade == "mes":
        expr = "DATE_TRUNC('month', DATA_EXIBICAO)"
    else:
        expr = "DATE_TRUNC('year', DATA_EXIBICAO)"

    sql = f"""
        SELECT
            {expr} AS periodo,
            SUM(PUBLICO) AS publico,
            COUNT(*) AS sessoes
        FROM '{PARQUET_PADRAO}'
        WHERE {where}
        GROUP BY periodo
        ORDER BY periodo
    """
    return query(sql)


def top_filmes(where: str, n: int = 15) -> pd.DataFrame:
    sql = f"""
        SELECT
            TITULO_ORIGINAL AS titulo,
            SUM(PUBLICO) AS publico,
            COUNT(*) AS sessoes
        FROM '{PARQUET_PADRAO}'
        WHERE {where}
        GROUP BY titulo
        ORDER BY publico DESC
        LIMIT {n}
    """
    return query(sql)


def top_ufs(where: str, n: int = 15) -> pd.DataFrame:
    sql = f"""
        SELECT
            UF_SALA_COMPLEXO AS uf,
            SUM(PUBLICO) AS publico,
            COUNT(*) AS sessoes
        FROM '{PARQUET_PADRAO}'
        WHERE {where}
        GROUP BY uf
        ORDER BY publico DESC
        LIMIT {n}
    """
    return query(sql)


def top_exibidores(where: str, n: int = 15) -> pd.DataFrame:
    sql = f"""
        SELECT
            RAZAO_SOCIAL_EXIBIDORA AS exibidor,
            SUM(PUBLICO) AS publico,
            COUNT(DISTINCT REGISTRO_SALA) AS salas,
            COUNT(*) AS sessoes
        FROM '{PARQUET_PADRAO}'
        WHERE {where}
        GROUP BY exibidor
        ORDER BY publico DESC
        LIMIT {n}
    """
    return query(sql)


def tabela_detalhe(where: str, limite: int = 500) -> pd.DataFrame:
    sql = f"""
        SELECT
            DATA_EXIBICAO,
            TITULO_ORIGINAL,
            TITULO_BRASIL,            
            UF_SALA_COMPLEXO,
            MUNICIPIO_SALA_COMPLEXO,
            NOME_SALA,
            RAZAO_SOCIAL_EXIBIDORA,
            PUBLICO
        FROM '{PARQUET_PADRAO}'
        WHERE {where}
        ORDER BY DATA_EXIBICAO DESC, PUBLICO DESC
        LIMIT {limite}
    """
    return query(sql)


# --- Interface ---

def render_sidebar(meta, ufs_todas):
    st.sidebar.title("🎬 Filtros")

    dt_min = pd.to_datetime(meta["dt_min"]).date()
    dt_max = pd.to_datetime(meta["dt_max"]).date()

    st.sidebar.subheader("Período")
    col1, col2 = st.sidebar.columns(2)
    data_ini = col1.date_input("De", value=dt_min, min_value=dt_min, max_value=dt_max)
    data_fim = col2.date_input("Até", value=dt_max, min_value=dt_min, max_value=dt_max)

    st.sidebar.subheader("Localização")
    ufs = st.sidebar.multiselect("UF", options=ufs_todas, default=[])

    municipios = []
    if ufs:
        municipios = st.sidebar.multiselect(
            "Município",
            options=carrega_municipios(ufs),
            default=[],
        )

    st.sidebar.subheader("Filmes")
    titulos_disponiveis = carrega_titulos()
    titulos = st.sidebar.multiselect(
        "Título (Brasil)",
        options=titulos_disponiveis,
        default=[],
        help="Deixe em branco para considerar todos.",
    )

    st.sidebar.markdown("---")
    st.sidebar.caption(
        f"Base: **{meta['n_titulos']:,}** títulos · "
        f"**{meta['n_uf']}** UFs · "
        f"**{meta['n_exibidores']:,}** exibidores"
    )

    return {
        "data_ini": data_ini,
        "data_fim": data_fim,
        "ufs": ufs,
        "municipios": municipios,
        "titulos": titulos,
    }


def formatar_numero(n):
    if pd.isna(n):
        return "—"
    return f"{int(n):,}".replace(",", ".")


def main():
    st.title("🎬 Bilheteria Diária — ANCINE")
    st.caption("Dashboard interativo sobre público e sessões por exibidor.")

    if not arquivo_existe():
        st.error(
            f"Parquet não encontrado em `{PARQUET_PADRAO}`.\n\n"
            "Rode antes:\n"
            "```\npython src/baixa_arquivos.py\npython src/criar_parquet.py\n```"
        )
        st.stop()

    meta = carrega_opcoes().iloc[0].to_dict()
    ufs_todas = carrega_ufs()

    filtros = render_sidebar(meta, ufs_todas)
    where = monta_where(filtros)

    # --- KPIs ---
    k = kpis(where)

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Público total", formatar_numero(k["publico"]))
    c2.metric("Sessões", formatar_numero(k["sessoes"]))
    c3.metric("Filmes", formatar_numero(k["filmes"]))
    c4.metric("Salas", formatar_numero(k["salas"]))
    c5.metric("Exibidores", formatar_numero(k["exibidores"]))

    if k["dt_ini"] is None:
        st.warning("Nenhum registro para os filtros selecionados.")
        st.stop()

    st.caption(
        f"Período efetivo: {pd.to_datetime(k['dt_ini']).date()} → "
        f"{pd.to_datetime(k['dt_fim']).date()}"
    )

    st.markdown("---")

    # --- Série temporal ---
    st.subheader("📈 Evolução do público")
    granularidade = st.radio(
        "Granularidade",
        options=["dia", "mes", "ano"],
        index=1,
        horizontal=True,
    )
    serie = serie_temporal(where, granularidade)

    if not serie.empty:
        serie = serie.set_index("periodo")
        st.line_chart(serie["publico"], height=320)
        with st.expander("Ver tabela da série"):
            st.dataframe(serie, use_container_width=True)

    st.markdown("---")

    # --- Rankings ---
    col_f, col_u, col_e = st.columns(3)

    with col_f:
        st.subheader("🏆 Top filmes")
        st.dataframe(
            top_filmes(where, 15),
            use_container_width=True,
            hide_index=True,
            column_config={
                "titulo": "Título",
                "publico": st.column_config.NumberColumn("Público", format="%d"),
                "sessoes": st.column_config.NumberColumn("Sessões", format="%d"),
            },
        )

    with col_u:
        st.subheader("📍 Top UFs")
        st.dataframe(
            top_ufs(where, 15),
            use_container_width=True,
            hide_index=True,
            column_config={
                "uf": "UF",
                "publico": st.column_config.NumberColumn("Público", format="%d"),
                "sessoes": st.column_config.NumberColumn("Sessões", format="%d"),
            },
        )

    with col_e:
        st.subheader("🏢 Top exibidores")
        st.dataframe(
            top_exibidores(where, 15),
            use_container_width=True,
            hide_index=True,
            column_config={
                "exibidor": "Exibidor",
                "publico": st.column_config.NumberColumn("Público", format="%d"),
                "salas": st.column_config.NumberColumn("Salas", format="%d"),
                "sessoes": st.column_config.NumberColumn("Sessões", format="%d"),
            },
        )

    st.markdown("---")

    # --- Detalhe ---
    st.subheader("🔎 Detalhe dos registros")
    limite = st.slider("Máximo de linhas", 100, 5000, 500, step=100)
    st.dataframe(
        tabela_detalhe(where, limite),
        use_container_width=True,
        hide_index=True,
    )

    st.caption(f"Exibindo até {limite} linhas.")


if __name__ == "__main__":
    main()
