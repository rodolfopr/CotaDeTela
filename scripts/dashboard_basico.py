"""
Dashboard Streamlit para a bilheteria diária da ANCINE.

Consome o Parquet gerado por criar_parquet.py, que já traz as colunas
derivadas: ORIGEM_OBRA, HORA_SESSAO, PERIODO_SESSAO, DIASEMANA_EXIBICAO
e DIASEMANA_NUM_EXIBICAO.

Convenções:
  - Todas as referências de título usam TITULO_BRASIL (não TITULO_ORIGINAL).
  - Números exibidos no padrão pt-BR: milhar '.' e decimal ','.
  - Datas exibidas no padrão dd/mm/aaaa.
  - Gráficos:
      * Evolução: st.line_chart com 4 séries (Total, Nacional, Estrangeira,
        Não informado) e seletores de granularidade e métrica.
      * Composição percentual por origem: barras 100% empilhadas (Altair),
        agregadas por ANO, com menores na base do empilhamento.
      * Origem e Período: donut em Altair com seletor de métrica.
      * Dia da semana: barras em Altair (ordem Seg → Dom) com seletor de métrica.
"""

from pathlib import Path

import altair as alt
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


# --- Formatação pt-BR ---

def fmt_br(valor, casas: int = 0) -> str:
    """
    Formata número no padrão pt-BR: milhar '.' e decimal ','.
    Ex.: 1250.5 -> '1.250,50' (casas=2); 1250 -> '1.250' (casas=0).
    Valores nulos/NaN -> '—'.
    """
    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return "—"
    try:
        n = float(valor)
    except (TypeError, ValueError):
        return "—"
    s = f"{n:,.{casas}f}" if casas else f"{n:,.0f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def fmt_br_pct(valor, casas: int = 1) -> str:
    """Formata percentual pt-BR. Ex.: 12.3456 -> '12,3%'."""
    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return "—"
    return f"{fmt_br(valor, casas)}%"


def fmt_br_data(dt) -> str:
    """Formata data no padrão dd/mm/aaaa."""
    if dt is None or (isinstance(dt, float) and pd.isna(dt)):
        return "—"
    return pd.to_datetime(dt).strftime("%d/%m/%Y")


def df_para_exibicao(df: pd.DataFrame, colunas_numericas=None, casas: int = 0) -> pd.DataFrame:
    """
    Devolve cópia do DataFrame com colunas numéricas formatadas como string
    pt-BR, para uso em st.dataframe com TextColumn.
    """
    if colunas_numericas is None:
        colunas_numericas = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
    out = df.copy()
    for c in colunas_numericas:
        if c in out.columns:
            out[c] = out[c].apply(lambda v: fmt_br(v, casas))
    return out


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


# --- Helpers de SQL ---

def _lista_sql(valores) -> str:
    """Gera lista SQL escapando aspas simples."""
    return ",".join(f"'{str(v).replace(chr(39), chr(39)*2)}'" for v in valores)


# --- Carrega metadados para os filtros ---

def carrega_opcoes():
    """Carrega metadados gerais para os filtros (cacheado)."""
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
    sql = f"""
        SELECT DISTINCT MUNICIPIO_SALA_COMPLEXO AS mun
        FROM '{PARQUET_PADRAO}'
        WHERE UF_SALA_COMPLEXO IN ({_lista_sql(ufs_selecionadas)})
        ORDER BY mun
    """
    return query(sql)["mun"].tolist()


def carrega_complexos(municipios_selecionados=None):
    """
    Valores distintos de REGISTRO_COMPLEXO.
    Se municípios forem informados, restringe a eles.
    Retorna DataFrame com REGISTRO_COMPLEXO e rótulo amigável.
    """
    filtro = (
        f"AND MUNICIPIO_SALA_COMPLEXO IN ({_lista_sql(municipios_selecionados)})"
        if municipios_selecionados else ""
    )
    sql = f"""
        SELECT DISTINCT
            REGISTRO_COMPLEXO,
            MUNICIPIO_SALA_COMPLEXO,
            UF_SALA_COMPLEXO
        FROM '{PARQUET_PADRAO}'
        WHERE REGISTRO_COMPLEXO IS NOT NULL {filtro}
        ORDER BY UF_SALA_COMPLEXO, MUNICIPIO_SALA_COMPLEXO, REGISTRO_COMPLEXO
    """
    df = query(sql)
    if df.empty:
        return df.assign(rotulo=[])
    df["rotulo"] = df.apply(
        lambda r: f"{int(r['REGISTRO_COMPLEXO'])} — {r['MUNICIPIO_SALA_COMPLEXO']}/{r['UF_SALA_COMPLEXO']}",
        axis=1,
    )
    return df[["REGISTRO_COMPLEXO", "rotulo"]]


def carrega_exibidores():
    sql = f"""
        SELECT DISTINCT RAZAO_SOCIAL_EXIBIDORA AS exibidor
        FROM '{PARQUET_PADRAO}'
        WHERE RAZAO_SOCIAL_EXIBIDORA IS NOT NULL
        ORDER BY exibidor
    """
    return query(sql)["exibidor"].tolist()


def carrega_titulos():
    sql = f"""
        SELECT DISTINCT TITULO_BRASIL AS titulo
        FROM '{PARQUET_PADRAO}'
        WHERE TITULO_BRASIL IS NOT NULL
        ORDER BY titulo
    """
    return query(sql)["titulo"].tolist()


def carrega_origens():
    sql = f"""
        SELECT DISTINCT ORIGEM_OBRA AS origem
        FROM '{PARQUET_PADRAO}'
        WHERE ORIGEM_OBRA IS NOT NULL
        ORDER BY origem
    """
    return query(sql)["origem"].tolist()


def carrega_periodos():
    sql = f"""
        SELECT DISTINCT PERIODO_SESSAO AS periodo
        FROM '{PARQUET_PADRAO}'
        WHERE PERIODO_SESSAO IS NOT NULL
        ORDER BY
            CASE PERIODO_SESSAO
                WHEN 'Madrugada'  THEN 1
                WHEN 'Matutino'   THEN 2
                WHEN 'Vespertino' THEN 3
                WHEN 'Noturno'    THEN 4
                ELSE 5
            END
    """
    return query(sql)["periodo"].tolist()


def carrega_dias_semana():
    sql = f"""
        SELECT DIASEMANA_EXIBICAO AS dia
        FROM '{PARQUET_PADRAO}'
        WHERE DIASEMANA_EXIBICAO IS NOT NULL
        GROUP BY DIASEMANA_EXIBICAO, DIASEMANA_NUM_EXIBICAO
        ORDER BY DIASEMANA_NUM_EXIBICAO NULLS LAST
    """
    return query(sql)["dia"].tolist()


# --- Monta WHERE a partir dos filtros ---

def monta_where(filtros) -> str:
    cond = []

    if filtros["data_ini"] and filtros["data_fim"]:
        cond.append(
            f"DATA_EXIBICAO BETWEEN DATE '{filtros['data_ini']}' "
            f"AND DATE '{filtros['data_fim']}'"
        )

    if filtros["ufs"]:
        cond.append(f"UF_SALA_COMPLEXO IN ({_lista_sql(filtros['ufs'])})")

    if filtros["municipios"]:
        cond.append(f"MUNICIPIO_SALA_COMPLEXO IN ({_lista_sql(filtros['municipios'])})")

    if filtros["complexos"]:
        lista = ",".join(str(int(c)) for c in filtros["complexos"])
        cond.append(f"REGISTRO_COMPLEXO IN ({lista})")

    if filtros["exibidores"]:
        cond.append(f"RAZAO_SOCIAL_EXIBIDORA IN ({_lista_sql(filtros['exibidores'])})")

    if filtros["titulos"]:
        cond.append(f"TITULO_BRASIL IN ({_lista_sql(filtros['titulos'])})")

    if filtros["origens"]:
        cond.append(f"ORIGEM_OBRA IN ({_lista_sql(filtros['origens'])})")

    if filtros["periodos"]:
        cond.append(f"PERIODO_SESSAO IN ({_lista_sql(filtros['periodos'])})")

    if filtros["dias"]:
        cond.append(f"DIASEMANA_EXIBICAO IN ({_lista_sql(filtros['dias'])})")

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


def kpi_participacao_nacional(where: str) -> float:
    sql = f"""
        SELECT
            100.0 * SUM(CASE WHEN ORIGEM_OBRA = 'Nacional' THEN PUBLICO ELSE 0 END)
            / NULLIF(SUM(PUBLICO), 0) AS pct
        FROM '{PARQUET_PADRAO}'
        WHERE {where}
    """
    val = query(sql).iloc[0]["pct"]
    return float(val) if val is not None else 0.0


def serie_temporal_por_origem(where: str, granularidade: str) -> pd.DataFrame:
    """
    Série temporal com quatro séries (Total, Nacional, Estrangeira,
    Não informado) para cada métrica (publico, sessoes).
    Retorna DataFrame com índice 'periodo' e colunas:
      '<Origem> — Público' e '<Origem> — Sessões'.
    """
    if granularidade == "dia":
        expr = "DATA_EXIBICAO"
    elif granularidade == "mes":
        expr = "DATE_TRUNC('month', DATA_EXIBICAO)"
    else:
        expr = "DATE_TRUNC('year', DATA_EXIBICAO)"

    sql = f"""
        SELECT
            {expr} AS periodo,
            SUM(PUBLICO) AS total_publico,
            COUNT(*) AS total_sessoes,
            SUM(CASE WHEN ORIGEM_OBRA = 'Nacional' THEN PUBLICO ELSE 0 END) AS nacional_publico,
            SUM(CASE WHEN ORIGEM_OBRA = 'Nacional' THEN 1 ELSE 0 END) AS nacional_sessoes,
            SUM(CASE WHEN ORIGEM_OBRA = 'Estrangeira' THEN PUBLICO ELSE 0 END) AS estrangeira_publico,
            SUM(CASE WHEN ORIGEM_OBRA = 'Estrangeira' THEN 1 ELSE 0 END) AS estrangeira_sessoes,
            SUM(CASE WHEN ORIGEM_OBRA = 'Não informado' THEN PUBLICO ELSE 0 END) AS nao_informado_publico,
            SUM(CASE WHEN ORIGEM_OBRA = 'Não informado' THEN 1 ELSE 0 END) AS nao_informado_sessoes
        FROM '{PARQUET_PADRAO}'
        WHERE {where}
        GROUP BY periodo
        ORDER BY periodo
    """
    df = query(sql)

    out = {"periodo": df["periodo"]}
    for rotulo, prefixo in [
        ("Total", "total"),
        ("Nacional", "nacional"),
        ("Estrangeira", "estrangeira"),
        ("Não informado", "nao_informado"),
    ]:
        out[f"{rotulo} — Público"] = df[f"{prefixo}_publico"]
        out[f"{rotulo} — Sessões"] = df[f"{prefixo}_sessoes"]

    return pd.DataFrame(out).set_index("periodo")


def top_filmes(where: str, n: int = 15) -> pd.DataFrame:
    sql = f"""
        SELECT
            TITULO_BRASIL,
            ANY_VALUE(ORIGEM_OBRA) AS origem,
            SUM(PUBLICO) AS publico,
            COUNT(*) AS sessoes
        FROM '{PARQUET_PADRAO}'
        WHERE {where}
        GROUP BY TITULO_BRASIL
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


def por_origem(where: str) -> pd.DataFrame:
    sql = f"""
        SELECT
            ORIGEM_OBRA AS origem,
            SUM(PUBLICO) AS publico,
            COUNT(*) AS sessoes,
            COUNT(DISTINCT TITULO_BRASIL) AS filmes
        FROM '{PARQUET_PADRAO}'
        WHERE {where}
        GROUP BY ORIGEM_OBRA
        ORDER BY publico DESC
    """
    return query(sql)


def por_periodo(where: str) -> pd.DataFrame:
    sql = f"""
        SELECT
            PERIODO_SESSAO AS periodo,
            SUM(PUBLICO) AS publico,
            COUNT(*) AS sessoes
        FROM '{PARQUET_PADRAO}'
        WHERE {where}
        GROUP BY PERIODO_SESSAO
        ORDER BY
            CASE PERIODO_SESSAO
                WHEN 'Madrugada'  THEN 1
                WHEN 'Matutino'   THEN 2
                WHEN 'Vespertino' THEN 3
                WHEN 'Noturno'    THEN 4
                ELSE 5
            END
    """
    return query(sql)


def por_dia_semana(where: str) -> pd.DataFrame:
    sql = f"""
        SELECT
            DIASEMANA_EXIBICAO AS dia,
            DIASEMANA_NUM_EXIBICAO AS dia_num,
            SUM(PUBLICO) AS publico,
            COUNT(*) AS sessoes
        FROM '{PARQUET_PADRAO}'
        WHERE {where}
        GROUP BY DIASEMANA_EXIBICAO, DIASEMANA_NUM_EXIBICAO
        ORDER BY DIASEMANA_NUM_EXIBICAO NULLS LAST
    """
    return query(sql)


def tabela_detalhe(where: str, limite: int = 500) -> pd.DataFrame:
    """Retorna todas as colunas do Parquet (ordem por data e público)."""
    sql = f"""
        SELECT *
        FROM '{PARQUET_PADRAO}'
        WHERE {where}
        ORDER BY DATA_EXIBICAO DESC, PUBLICO DESC
        LIMIT {limite}
    """
    return query(sql)


# --- Gráficos (Altair) ---

def grafico_secao(df: pd.DataFrame, coluna: str, metrica: str = "publico", titulo: str = ""):
    """
    Donut em Altair com tooltip pt-BR (via coluna formatada).
    """
    df_plot = df[[coluna, metrica]].copy()
    df_plot.columns = ["categoria", "valor"]
    df_plot["valor_fmt"] = df_plot["valor"].apply(lambda v: fmt_br(v, 0))

    rotulo_metrica = "Público" if metrica == "publico" else "Sessões"

    chart = (
        alt.Chart(df_plot)
        .mark_arc(innerRadius=50)
        .encode(
            theta=alt.Theta(field="valor", type="quantitative"),
            color=alt.Color(field="categoria", type="nominal", title=titulo or coluna),
            tooltip=[
                alt.Tooltip("categoria:N", title=titulo or coluna),
                alt.Tooltip("valor_fmt:N", title=rotulo_metrica),
            ],
        )
        .properties(height=280)
    )
    return chart


def grafico_barras_dia(df: pd.DataFrame, metrica: str = "publico"):
    """
    Barras por dia da semana em Altair, com eixo X ordenado
    na sequência Seg., Ter., Qua., Qui., Sex., Sáb., Dom.
    """
    df_plot = df[["dia", "dia_num", metrica]].copy()
    df_plot["valor_fmt"] = df_plot[metrica].apply(lambda v: fmt_br(v, 0))
    df_plot["dia"] = df_plot["dia"].astype(str)

    ordem = ["Seg.", "Ter.", "Qua.", "Qui.", "Sex.", "Sáb.", "Dom."]
    rotulo_metrica = "Público" if metrica == "publico" else "Sessões"

    chart = (
        alt.Chart(df_plot)
        .mark_bar()
        .encode(
            x=alt.X(
                "dia:N",
                title="Dia da semana",
                sort=ordem,
                axis=alt.Axis(labelAngle=0),
            ),
            y=alt.Y(f"{metrica}:Q", title=rotulo_metrica),
            tooltip=[
                alt.Tooltip("dia:N", title="Dia"),
                alt.Tooltip("valor_fmt:N", title=rotulo_metrica),
            ],
        )
        .properties(height=280)
    )
    return chart


def grafico_barras_100_origem_ano(where: str, metrica: str = "Público"):
    """
    Barras empilhadas 100% por origem (Nacional/Estrangeira/Não informado),
    agregadas por ANO.

    Ordem do empilhamento: categorias ordenadas do MENOR para o MAIOR total,
    de modo que os menores fiquem próximos do eixo X (base da barra).

    metrica: 'Público' ou 'Sessões'.
    """
    expr_metrica = "PUBLICO" if metrica == "Público" else "1"

    sql = f"""
        SELECT
            EXTRACT(YEAR FROM DATA_EXIBICAO) AS ano,
            ORIGEM_OBRA AS origem,
            SUM({expr_metrica}) AS valor
        FROM '{PARQUET_PADRAO}'
        WHERE {where}
        GROUP BY EXTRACT(YEAR FROM DATA_EXIBICAO), ORIGEM_OBRA
        ORDER BY 1, 2
    """
    df_long = query(sql)

    if df_long.empty:
        return None

    df_long["total_ano"] = df_long.groupby("ano")["valor"].transform("sum")
    df_long["pct"] = df_long["valor"] / df_long["total_ano"].replace(0, pd.NA) * 100
    df_long["pct_fmt"] = df_long["pct"].apply(lambda v: fmt_br_pct(v, 1))
    df_long["valor_fmt"] = df_long["valor"].apply(lambda v: fmt_br(v, 0))

    # Menor -> maior: a menor categoria fica na base do empilhamento
    totais_por_origem = (
        df_long.groupby("origem")["valor"].sum().sort_values(ascending=True)
    )
    ordem_origens = totais_por_origem.index.tolist()

    cores = {
        "Nacional": "#2E7D32",
        "Estrangeira": "#1565C0",
        "Não informado": "#9E9E9E",
    }

    df_long["ano_str"] = df_long["ano"].astype(int).astype(str)

    chart = (
        alt.Chart(df_long)
        .mark_bar()
        .encode(
            x=alt.X("ano_str:N", title="Ano", axis=alt.Axis(labelAngle=0)),
            y=alt.Y("pct:Q", title="% do total", stack="normalize"),
            color=alt.Color(
                "origem:N",
                title="Origem",
                sort=ordem_origens,
                scale=alt.Scale(
                    domain=list(cores.keys()),
                    range=list(cores.values()),
                ),
            ),
            order=alt.Order("origem:N", sort="ascending"),
            tooltip=[
                alt.Tooltip("ano_str:N", title="Ano"),
                alt.Tooltip("origem:N", title="Origem"),
                alt.Tooltip("pct_fmt:N", title="% do total"),
                alt.Tooltip("valor_fmt:N", title=metrica),
            ],
        )
        .properties(height=320)
    )
    return chart


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

    complexos = []
    df_complexos = carrega_complexos(municipios if municipios else None)
    if not df_complexos.empty:
        opcoes_complexos = dict(zip(df_complexos["rotulo"], df_complexos["REGISTRO_COMPLEXO"]))
        rotulos_sel = st.sidebar.multiselect(
            "Complexo",
            options=list(opcoes_complexos.keys()),
            default=[],
            help="Deixe em branco para considerar todos os complexos.",
        )
        complexos = [opcoes_complexos[r] for r in rotulos_sel]

    exibidores = st.sidebar.multiselect(
        "Exibidor",
        options=carrega_exibidores(),
        default=[],
        help="Deixe em branco para considerar todos os exibidores.",
    )

    st.sidebar.subheader("Filmes")
    titulos = st.sidebar.multiselect(
        "Título (Brasil)",
        options=carrega_titulos(),
        default=[],
        help="Deixe em branco para considerar todos.",
    )

    st.sidebar.subheader("Origem da obra")
    origens = st.sidebar.multiselect(
        "Origem",
        options=carrega_origens(),
        default=[],
        help="Deixe em branco para incluir todas as origens.",
    )

    st.sidebar.subheader("Período da sessão")
    periodos = st.sidebar.multiselect(
        "Período",
        options=carrega_periodos(),
        default=[],
        help="Deixe em branco para incluir todos os períodos.",
    )

    st.sidebar.subheader("Dia da semana")
    dias = st.sidebar.multiselect(
        "Dia",
        options=carrega_dias_semana(),
        default=[],
        help="Deixe em branco para incluir todos os dias.",
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
        "complexos": complexos,
        "exibidores": exibidores,
        "titulos": titulos,
        "origens": origens,
        "periodos": periodos,
        "dias": dias,
    }


def main():
    st.title("🎬 Bilheteria Diária — ANCINE")
    st.caption("Dashboard interativo sobre público e sessões por exibidor.")

    if not arquivo_existe():
        st.error(
            f"Parquet não encontrado em `{PARQUET_PADRAO}`.\n\n"
            "Rode antes:\n"
            "```\npython scripts/baixa_arquivos.py\npython scripts/criar_parquet.py\n```"
        )
        st.stop()

    meta = carrega_opcoes().iloc[0].to_dict()
    ufs_todas = carrega_ufs()

    filtros = render_sidebar(meta, ufs_todas)
    where = monta_where(filtros)

    # --- KPIs ---
    k = kpis(where)
    pct_nacional = kpi_participacao_nacional(where)

    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("Público total", fmt_br(k["publico"], 0))
    c2.metric("Sessões", fmt_br(k["sessoes"], 0))
    c3.metric("Filmes", fmt_br(k["filmes"], 0))
    c4.metric("Salas", fmt_br(k["salas"], 0))
    c5.metric("Exibidores", fmt_br(k["exibidores"], 0))
    c6.metric("Participação nacional", fmt_br_pct(pct_nacional, 1))

    if k["dt_ini"] is None:
        st.warning("Nenhum registro para os filtros selecionados.")
        st.stop()

    st.caption(
        f"Período efetivo: {fmt_br_data(k['dt_ini'])} → {fmt_br_data(k['dt_fim'])}"
    )

    st.markdown("---")

    # --- Série temporal (4 séries + seletores) ---
    st.subheader("📈 Evolução do público e das sessões")

    col_g1, col_g2 = st.columns(2)
    with col_g1:
        granularidade = st.radio(
            "Granularidade",
            options=["dia", "mes", "ano"],
            index=1,
            horizontal=True,
            key="gran_serie",
        )
    with col_g2:
        metrica_serie = st.radio(
            "Métrica (eixo Y)",
            options=["Público", "Sessões"],
            index=0,
            horizontal=True,
            key="metrica_serie",
        )

    serie = serie_temporal_por_origem(where, granularidade)

    if not serie.empty:
        cols_metrica = [c for c in serie.columns if c.endswith(f"— {metrica_serie}")]
        df_plot = serie[cols_metrica].copy()
        df_plot.columns = [c.replace(f" — {metrica_serie}", "") for c in df_plot.columns]

        st.line_chart(df_plot, height=360)

        with st.expander("Ver tabela da série"):
            df_tab = df_para_exibicao(
                serie.reset_index(),
                colunas_numericas=list(serie.columns),
                casas=0,
            )
            st.dataframe(df_tab, use_container_width=True, hide_index=True)

    st.markdown("---")

    # --- Composição percentual por origem (barras 100% empilhadas por ANO) ---
    st.subheader("📊 Composição percentual por origem da obra (por ano)")

    fig_100 = grafico_barras_100_origem_ano(where, metrica_serie)
    if fig_100 is not None:
        st.altair_chart(fig_100, use_container_width=True)
    else:
        st.info("Sem dados para os filtros selecionados.")

    st.markdown("---")

    # --- Origem da obra (donut + seletor de métrica) ---
    st.subheader("🌎 Público por origem da obra")
    df_origem = por_origem(where)
    if not df_origem.empty:
        metrica_o = st.radio(
            "Métrica",
            options=["publico", "sessoes"],
            format_func=lambda x: "Público" if x == "publico" else "Sessões",
            horizontal=True,
            key="metrica_origem",
        )
        col_o1, col_o2 = st.columns([1, 1])
        with col_o1:
            st.dataframe(
                df_para_exibicao(df_origem, colunas_numericas=["publico", "sessoes", "filmes"]),
                use_container_width=True,
                hide_index=True,
                column_config={
                    "origem": "Origem",
                    "publico": st.column_config.TextColumn("Público"),
                    "sessoes": st.column_config.TextColumn("Sessões"),
                    "filmes": st.column_config.TextColumn("Filmes"),
                },
            )
        with col_o2:
            st.altair_chart(
                grafico_secao(df_origem, "origem", metrica_o, "Origem"),
                use_container_width=True,
            )

    st.markdown("---")

    # --- Período da sessão (donut + seletor de métrica) ---
    st.subheader("🕒 Público por período da sessão")
    df_periodo = por_periodo(where)
    if not df_periodo.empty:
        metrica_p = st.radio(
            "Métrica",
            options=["publico", "sessoes"],
            format_func=lambda x: "Público" if x == "publico" else "Sessões",
            horizontal=True,
            key="metrica_periodo",
        )
        col_p1, col_p2 = st.columns([1, 1])
        with col_p1:
            st.dataframe(
                df_para_exibicao(df_periodo, colunas_numericas=["publico", "sessoes"]),
                use_container_width=True,
                hide_index=True,
                column_config={
                    "periodo": "Período",
                    "publico": st.column_config.TextColumn("Público"),
                    "sessoes": st.column_config.TextColumn("Sessões"),
                },
            )
        with col_p2:
            st.altair_chart(
                grafico_secao(df_periodo, "periodo", metrica_p, "Período"),
                use_container_width=True,
            )

    st.markdown("---")

    # --- Dia da semana (barras ordenadas Seg → Dom + seletor de métrica) ---
    st.subheader("📅 Público por dia da semana")
    df_dia = por_dia_semana(where)
    if not df_dia.empty:
        metrica_d = st.radio(
            "Métrica",
            options=["publico", "sessoes"],
            format_func=lambda x: "Público" if x == "publico" else "Sessões",
            horizontal=True,
            key="metrica_dia",
        )
        col_d1, col_d2 = st.columns([1, 1])
        with col_d1:
            st.dataframe(
                df_para_exibicao(
                    df_dia.drop(columns=["dia_num"]),
                    colunas_numericas=["publico", "sessoes"],
                ),
                use_container_width=True,
                hide_index=True,
                column_config={
                    "dia": "Dia",
                    "publico": st.column_config.TextColumn("Público"),
                    "sessoes": st.column_config.TextColumn("Sessões"),
                },
            )
        with col_d2:
            st.altair_chart(
                grafico_barras_dia(df_dia, metrica_d),
                use_container_width=True,
            )

    st.markdown("---")

    # --- Rankings ---
    col_f, col_e = st.columns(2)

    with col_f:
        st.subheader("🏆 Top filmes")
        st.dataframe(
            df_para_exibicao(top_filmes(where, 15), colunas_numericas=["publico", "sessoes"]),
            use_container_width=True,
            hide_index=True,
            column_config={
                "TITULO_BRASIL": "Título",
                "origem": "Origem",
                "publico": st.column_config.TextColumn("Público"),
                "sessoes": st.column_config.TextColumn("Sessões"),
            },
        )

    with col_e:
        st.subheader("🏢 Top exibidores")
        st.dataframe(
            df_para_exibicao(
                top_exibidores(where, 15),
                colunas_numericas=["publico", "salas", "sessoes"],
            ),
            use_container_width=True,
            hide_index=True,
            column_config={
                "exibidor": "Exibidor",
                "publico": st.column_config.TextColumn("Público"),
                "salas": st.column_config.TextColumn("Salas"),
                "sessoes": st.column_config.TextColumn("Sessões"),
            },
        )

    st.markdown("---")

    # --- Detalhe (todas as colunas) ---
    st.subheader("🔎 Detalhe dos registros")
    limite = st.slider("Máximo de linhas", 100, 5000, 500, step=100)

    df_detalhe = tabela_detalhe(where, limite)
    df_detalhe_fmt = df_para_exibicao(df_detalhe, casas=0)

    st.dataframe(
        df_detalhe_fmt,
        use_container_width=True,
        hide_index=True,
    )

    st.caption(
        f"Exibindo até {fmt_br(limite)} linhas · "
        f"{len(df_detalhe.columns)} colunas."
    )


if __name__ == "__main__":
    main()