"""
Dashboard de comparação de períodos da bilheteria ANCINE.

Mesma estrutura do dashboard_basico.py, com cada seção duplicada
lado a lado para comparar dois períodos distintos.

Filtros globais (UF, Município, Complexo, Exibidor, Título, Origem,
Período da sessão, Dia) aplicam-se aos dois lados. Apenas o período
(data inicial/final) é independente por lado, limitado a 2 anos.
"""

from datetime import date
from pathlib import Path

import altair as alt
import duckdb
import pandas as pd
import streamlit as st

# --- Configuração ---

PASTA_RAIZ = Path(__file__).resolve().parent.parent
PARQUET_PADRAO = PASTA_RAIZ / "data" / "bilheteria.parquet"

st.set_page_config(
    page_title="Bilheteria ANCINE — Comparação",
    page_icon="🆚",
    layout="wide",
    initial_sidebar_state="expanded",
)

MAX_DIAS_PERIODO = 366 * 2  # 2 anos (com folga para ano bissexto)


# --- Formatação pt-BR ---

def fmt_br(valor, casas: int = 0) -> str:
    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return "—"
    try:
        n = float(valor)
    except (TypeError, ValueError):
        return "—"
    s = f"{n:,.{casas}f}" if casas else f"{n:,.0f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def fmt_br_pct(valor, casas: int = 1) -> str:
    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return "—"
    return f"{fmt_br(valor, casas)}%"


def fmt_br_data(dt) -> str:
    if dt is None or (isinstance(dt, float) and pd.isna(dt)):
        return "—"
    return pd.to_datetime(dt).strftime("%d/%m/%Y")


def df_para_exibicao(df, colunas_numericas=None, casas: int = 0):
    if colunas_numericas is None:
        colunas_numericas = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
    out = df.copy()
    for c in colunas_numericas:
        if c in out.columns:
            out[c] = out[c].apply(lambda v: fmt_br(v, casas))
    return out


def fmt_variacao(atual, anterior, casas_pct: int = 1) -> tuple[str, str]:
    """
    Retorna (texto_absoluto, texto_percentual) da variação atual - anterior.
    """
    if anterior is None or pd.isna(anterior) or anterior == 0:
        return ("—", "—")
    delta = (atual or 0) - anterior
    delta_pct = 100.0 * delta / anterior
    return (fmt_br(delta, 0), fmt_br_pct(delta_pct, casas_pct))


# --- Conexão cacheada ---

@st.cache_resource
def get_conexao():
    con = duckdb.connect()
    con.execute("SET memory_limit = '4GB';")
    con.execute("SET threads = 4;")
    return con


@st.cache_data(show_spinner="Consultando dados...")
def query(sql: str, _dummy: int = 0) -> pd.DataFrame:
    con = get_conexao()
    return con.sql(sql).df()


def arquivo_existe() -> bool:
    return PARQUET_PADRAO.exists()


def _lista_sql(valores) -> str:
    return ",".join(f"'{str(v).replace(chr(39), chr(39)*2)}'" for v in valores)


# --- Carrega metadados ---

def carrega_opcoes():
    sql = f"""
        SELECT
            MIN(DATA_EXIBICAO) AS dt_min,
            MAX(DATA_EXIBICAO) AS dt_max,
            COUNT(DISTINCT UF_SALA_COMPLEXO) AS n_uf,
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


def carrega_municipios(ufs):
    if not ufs:
        return []
    sql = f"""
        SELECT DISTINCT MUNICIPIO_SALA_COMPLEXO AS mun
        FROM '{PARQUET_PADRAO}'
        WHERE UF_SALA_COMPLEXO IN ({_lista_sql(ufs)})
        ORDER BY mun
    """
    return query(sql)["mun"].tolist()


def carrega_complexos(municipios=None):
    filtro = (
        f"AND MUNICIPIO_SALA_COMPLEXO IN ({_lista_sql(municipios)})"
        if municipios else ""
    )
    sql = f"""
        SELECT DISTINCT REGISTRO_COMPLEXO, MUNICIPIO_SALA_COMPLEXO, UF_SALA_COMPLEXO
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


# --- WHERE (filtros comuns + período) ---

def monta_where(filtros, data_ini, data_fim) -> str:
    cond = [
        f"DATA_EXIBICAO BETWEEN DATE '{data_ini}' AND DATE '{data_fim}'"
    ]

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

    return " AND ".join(cond)


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
    sql = f"""
        SELECT *
        FROM '{PARQUET_PADRAO}'
        WHERE {where}
        ORDER BY DATA_EXIBICAO DESC, PUBLICO DESC
        LIMIT {limite}
    """
    return query(sql)


# --- Gráficos ---

def grafico_secao(df, coluna, metrica="publico", titulo=""):
    df_plot = df[[coluna, metrica]].copy()
    df_plot.columns = ["categoria", "valor"]
    df_plot["valor_fmt"] = df_plot["valor"].apply(lambda v: fmt_br(v, 0))
    rotulo = "Público" if metrica == "publico" else "Sessões"
    return (
        alt.Chart(df_plot)
        .mark_arc(innerRadius=50)
        .encode(
            theta=alt.Theta(field="valor", type="quantitative"),
            color=alt.Color(field="categoria", type="nominal", title=titulo or coluna),
            tooltip=[
                alt.Tooltip("categoria:N", title=titulo or coluna),
                alt.Tooltip("valor_fmt:N", title=rotulo),
            ],
        )
        .properties(height=260)
    )


def grafico_barras_dia(df, metrica="publico"):
    df_plot = df[["dia", "dia_num", metrica]].copy()
    df_plot["valor_fmt"] = df_plot[metrica].apply(lambda v: fmt_br(v, 0))
    df_plot["dia"] = df_plot["dia"].astype(str)
    ordem = ["Seg.", "Ter.", "Qua.", "Qui.", "Sex.", "Sáb.", "Dom."]
    rotulo = "Público" if metrica == "publico" else "Sessões"
    return (
        alt.Chart(df_plot)
        .mark_bar()
        .encode(
            x=alt.X("dia:N", title="Dia", sort=ordem, axis=alt.Axis(labelAngle=0)),
            y=alt.Y(f"{metrica}:Q", title=rotulo),
            tooltip=[
                alt.Tooltip("dia:N", title="Dia"),
                alt.Tooltip("valor_fmt:N", title=rotulo),
            ],
        )
        .properties(height=260)
    )


def grafico_barras_100_origem_ano(where, metrica="Público"):
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

    ordem_origens = (
        df_long.groupby("origem")["valor"].sum().sort_values(ascending=True).index.tolist()
    )
    cores = {"Nacional": "#2E7D32", "Estrangeira": "#1565C0", "Não informado": "#9E9E9E"}
    df_long["ano_str"] = df_long["ano"].astype(int).astype(str)

    return (
        alt.Chart(df_long)
        .mark_bar()
        .encode(
            x=alt.X("ano_str:N", title="Ano", axis=alt.Axis(labelAngle=0)),
            y=alt.Y("pct:Q", title="% do total", stack="normalize"),
            color=alt.Color(
                "origem:N",
                title="Origem",
                sort=ordem_origens,
                scale=alt.Scale(domain=list(cores.keys()), range=list(cores.values())),
            ),
            order=alt.Order("origem:N", sort="ascending"),
            tooltip=[
                alt.Tooltip("ano_str:N", title="Ano"),
                alt.Tooltip("origem:N", title="Origem"),
                alt.Tooltip("pct_fmt:N", title="% do total"),
                alt.Tooltip("valor_fmt:N", title=metrica),
            ],
        )
        .properties(height=280)
    )


# --- Sidebar ---

def render_sidebar(meta, ufs_todas):
    st.sidebar.title("🎬 Filtros globais")

    st.sidebar.subheader("Localização")
    ufs = st.sidebar.multiselect("UF", options=ufs_todas, default=[])

    municipios = []
    if ufs:
        municipios = st.sidebar.multiselect("Município", options=carrega_municipios(ufs), default=[])

    complexos = []
    df_complexos = carrega_complexos(municipios if municipios else None)
    if not df_complexos.empty:
        opcoes = dict(zip(df_complexos["rotulo"], df_complexos["REGISTRO_COMPLEXO"]))
        sel = st.sidebar.multiselect("Complexo", options=list(opcoes.keys()), default=[])
        complexos = [opcoes[r] for r in sel]

    exibidores = st.sidebar.multiselect(
        "Exibidor", options=carrega_exibidores(), default=[],
        help="Deixe em branco para considerar todos.",
    )

    st.sidebar.subheader("Filmes")
    titulos = st.sidebar.multiselect(
        "Título (Brasil)", options=carrega_titulos(), default=[],
        help="Deixe em branco para considerar todos.",
    )

    st.sidebar.subheader("Origem da obra")
    origens = st.sidebar.multiselect("Origem", options=carrega_origens(), default=[])

    st.sidebar.subheader("Período da sessão")
    periodos = st.sidebar.multiselect("Período", options=carrega_periodos(), default=[])

    st.sidebar.subheader("Dia da semana")
    dias = st.sidebar.multiselect("Dia", options=carrega_dias_semana(), default=[])

    st.sidebar.markdown("---")
    st.sidebar.caption(
        f"Base: **{meta['n_titulos']:,}** títulos · "
        f"**{meta['n_uf']}** UFs · "
        f"**{meta['n_exibidores']:,}** exibidores"
    )

    return {
        "ufs": ufs, "municipios": municipios, "complexos": complexos,
        "exibidores": exibidores, "titulos": titulos, "origens": origens,
        "periodos": periodos, "dias": dias,
    }


# --- Seletores de período por lado ---

def render_periodo_lado(lado: str, dt_min, dt_max, default_ini, default_fim):
    """
    Renderiza os dois date_inputs do lado ('A' ou 'B').
    Valida que o intervalo não excede 2 anos.
    """
    st.markdown(f"#### 🗓️ Período {lado}")

    col1, col2 = st.columns(2)
    ini = col1.date_input(
        f"De ({lado})",
        value=default_ini,
        min_value=dt_min,
        max_value=dt_max,
        key=f"ini_{lado}",
    )
    fim = col2.date_input(
        f"Até ({lado})",
        value=default_fim,
        min_value=dt_min,
        max_value=dt_max,
        key=f"fim_{lado}",
    )

    if fim < ini:
        st.error(f"Período {lado}: 'Até' deve ser ≥ 'De'.")
        return None

    dias = (fim - ini).days
    if dias > MAX_DIAS_PERIODO:
        st.error(
            f"Período {lado}: intervalo de {dias} dias excede o máximo de 2 anos "
            f"({MAX_DIAS_PERIODO} dias)."
        )
        return None

    st.caption(f"Intervalo: {dias} dias ({fmt_br_data(ini)} → {fmt_br_data(fim)})")
    return (ini, fim)


# --- Blocos de visualização (cada lado) ---

def render_serie_lado(where: str, lado: str):
    col1, col2 = st.columns(2)
    with col1:
        gran = st.radio(
            "Granularidade",
            options=["dia", "mes", "ano"],
            index=1,
            horizontal=True,
            key=f"gran_{lado}",
        )
    with col2:
        metrica = st.radio(
            "Métrica",
            options=["Público", "Sessões"],
            index=0,
            horizontal=True,
            key=f"metrica_serie_{lado}",
        )

    serie = serie_temporal_por_origem(where, gran)
    if serie.empty:
        st.info("Sem dados.")
        return None, metrica

    cols = [c for c in serie.columns if c.endswith(f"— {metrica}")]
    df_plot = serie[cols].copy()
    df_plot.columns = [c.replace(f" — {metrica}", "") for c in df_plot.columns]
    st.line_chart(df_plot, height=260)
    return serie, metrica


def render_composicao_lado(where: str, metrica: str):
    fig = grafico_barras_100_origem_ano(where, metrica)
    if fig is None:
        st.info("Sem dados.")
    else:
        st.altair_chart(fig, use_container_width=True)


def render_origem_lado(where: str, lado: str):
    df = por_origem(where)
    if df.empty:
        st.info("Sem dados.")
        return
    metrica = st.radio(
        "Métrica",
        options=["publico", "sessoes"],
        format_func=lambda x: "Público" if x == "publico" else "Sessões",
        horizontal=True,
        key=f"metrica_origem_{lado}",
    )
    col1, col2 = st.columns([1, 1])
    with col1:
        st.dataframe(
            df_para_exibicao(df, ["publico", "sessoes", "filmes"]),
            use_container_width=True, hide_index=True,
        )
    with col2:
        st.altair_chart(grafico_secao(df, "origem", metrica, "Origem"), use_container_width=True)


def render_periodo_sessao_lado(where: str, lado: str):
    df = por_periodo(where)
    if df.empty:
        st.info("Sem dados.")
        return
    metrica = st.radio(
        "Métrica",
        options=["publico", "sessoes"],
        format_func=lambda x: "Público" if x == "publico" else "Sessões",
        horizontal=True,
        key=f"metrica_periodo_{lado}",
    )
    col1, col2 = st.columns([1, 1])
    with col1:
        st.dataframe(
            df_para_exibicao(df, ["publico", "sessoes"]),
            use_container_width=True, hide_index=True,
        )
    with col2:
        st.altair_chart(grafico_secao(df, "periodo", metrica, "Período"), use_container_width=True)


def render_dia_lado(where: str, lado: str):
    df = por_dia_semana(where)
    if df.empty:
        st.info("Sem dados.")
        return
    metrica = st.radio(
        "Métrica",
        options=["publico", "sessoes"],
        format_func=lambda x: "Público" if x == "publico" else "Sessões",
        horizontal=True,
        key=f"metrica_dia_{lado}",
    )
    col1, col2 = st.columns([1, 1])
    with col1:
        st.dataframe(
            df_para_exibicao(df.drop(columns=["dia_num"]), ["publico", "sessoes"]),
            use_container_width=True, hide_index=True,
        )
    with col2:
        st.altair_chart(grafico_barras_dia(df, metrica), use_container_width=True)


def render_ranking_filmes(where: str):
    st.dataframe(
        df_para_exibicao(top_filmes(where, 15), ["publico", "sessoes"]),
        use_container_width=True, hide_index=True,
        column_config={
            "TITULO_BRASIL": "Título",
            "origem": "Origem",
            "publico": st.column_config.TextColumn("Público"),
            "sessoes": st.column_config.TextColumn("Sessões"),
        },
    )


def render_ranking_exibidores(where: str):
    st.dataframe(
        df_para_exibicao(top_exibidores(where, 15), ["publico", "salas", "sessoes"]),
        use_container_width=True, hide_index=True,
        column_config={
            "exibidor": "Exibidor",
            "publico": st.column_config.TextColumn("Público"),
            "salas": st.column_config.TextColumn("Salas"),
            "sessoes": st.column_config.TextColumn("Sessões"),
        },
    )


def render_detalhe_lado(where: str, lado: str):
    limite = st.slider(
        "Máximo de linhas", 100, 5000, 500, step=100,
        key=f"limite_detalhe_{lado}",
    )
    df = tabela_detalhe(where, limite)
    st.dataframe(
        df_para_exibicao(df, casas=0),
        use_container_width=True, hide_index=True,
    )
    st.caption(f"Exibindo até {fmt_br(limite)} linhas · {len(df.columns)} colunas.")


# --- Main ---

def main():
    st.title("🆚 Bilheteria ANCINE — Comparação de Períodos")
    st.caption("Compare dois períodos lado a lado (máx. 2 anos cada).")

    if not arquivo_existe():
        st.error(f"Parquet não encontrado em `{PARQUET_PADRAO}`.")
        st.stop()

    meta = carrega_opcoes().iloc[0].to_dict()
    ufs_todas = carrega_ufs()
    dt_min = pd.to_datetime(meta["dt_min"]).date()
    dt_max = pd.to_datetime(meta["dt_max"]).date()

    filtros = render_sidebar(meta, ufs_todas)

    # --- Seleção dos dois períodos ---
    st.markdown("---")
    col_per_a, col_per_b = st.columns(2)

    # Defaults: B = últimos 365 dias até dt_max; A = 365 dias anteriores a B
    default_b_fim = dt_max
    default_b_ini = max(dt_min, dt_max - pd.Timedelta(days=365).to_pytimedelta())
    default_a_fim = max(dt_min, default_b_ini - pd.Timedelta(days=1).to_pytimedelta())
    default_a_ini = max(dt_min, default_a_fim - pd.Timedelta(days=365).to_pytimedelta())

    with col_per_a:
        periodo_a = render_periodo_lado("A", dt_min, dt_max, default_a_ini, default_a_fim)
    with col_per_b:
        periodo_b = render_periodo_lado("B", dt_min, dt_max, default_b_ini, default_b_fim)

    if not periodo_a or not periodo_b:
        st.stop()

    where_a = monta_where(filtros, periodo_a[0], periodo_a[1])
    where_b = monta_where(filtros, periodo_b[0], periodo_b[1])

    st.markdown("---")

    # --- KPIs comparativos ---
    st.subheader("📌 KPIs")
    k_a = kpis(where_a)
    k_b = kpis(where_b)
    pct_a = kpi_participacao_nacional(where_a)
    pct_b = kpi_participacao_nacional(where_b)

    if k_a["dt_ini"] is None or k_b["dt_ini"] is None:
        st.warning("Um dos períodos não tem registros para os filtros selecionados.")
        st.stop()

    st.caption(
        f"Período A: {fmt_br_data(k_a['dt_ini'])} → {fmt_br_data(k_a['dt_fim'])}  |  "
        f"Período B: {fmt_br_data(k_b['dt_ini'])} → {fmt_br_data(k_b['dt_fim'])}"
    )

    linhas = [
        ("Público", k_a["publico"], k_b["publico"]),
        ("Sessões", k_a["sessoes"], k_b["sessoes"]),
        ("Filmes", k_a["filmes"], k_b["filmes"]),
        ("Salas", k_a["salas"], k_b["salas"]),
        ("Exibidores", k_a["exibidores"], k_b["exibidores"]),
        ("Participação nacional (%)", pct_a, pct_b),
    ]
    rows = []
    for nome, va, vb in linhas:
        is_pct = "%" in nome
        delta_txt, delta_pct_txt = fmt_variacao(vb, va)
        rows.append({
            "KPI": nome,
            "Período A": fmt_br(va, 1 if is_pct else 0) + ("%" if is_pct else ""),
            "Período B": fmt_br(vb, 1 if is_pct else 0) + ("%" if is_pct else ""),
            "Δ (B − A)": delta_txt + ("%" if is_pct and delta_txt != "—" else ""),
            "Δ %": delta_pct_txt,
        })
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    st.markdown("---")

    # --- Evolução ---
    st.subheader("📈 Evolução do público e das sessões")
    col_a, col_b = st.columns(2)
    with col_a:
        st.markdown("##### 🅰️ Período A")
        serie_a, metrica_a = render_serie_lado(where_a, "A")
    with col_b:
        st.markdown("##### 🅱️ Período B")
        serie_b, metrica_b = render_serie_lado(where_b, "B")

    st.markdown("---")

    # --- Composição 100% por origem (por ano) ---
    st.subheader("📊 Composição percentual por origem (por ano)")
    col_a, col_b = st.columns(2)
    with col_a:
        st.markdown("##### 🅰️ Período A")
        render_composicao_lado(where_a, metrica_a or "Público")
    with col_b:
        st.markdown("##### 🅱️ Período B")
        render_composicao_lado(where_b, metrica_b or "Público")

    st.markdown("---")

    # --- Origem ---
    st.subheader("🌎 Público por origem da obra")
    col_a, col_b = st.columns(2)
    with col_a:
        st.markdown("##### 🅰️ Período A")
        render_origem_lado(where_a, "A")
    with col_b:
        st.markdown("##### 🅱️ Período B")
        render_origem_lado(where_b, "B")

    st.markdown("---")

    # --- Período da sessão ---
    st.subheader("🕒 Público por período da sessão")
    col_a, col_b = st.columns(2)
    with col_a:
        st.markdown("##### 🅰️ Período A")
        render_periodo_sessao_lado(where_a, "A")
    with col_b:
        st.markdown("##### 🅱️ Período B")
        render_periodo_sessao_lado(where_b, "B")

    st.markdown("---")

    # --- Dia da semana ---
    st.subheader("📅 Público por dia da semana")
    col_a, col_b = st.columns(2)
    with col_a:
        st.markdown("##### 🅰️ Período A")
        render_dia_lado(where_a, "A")
    with col_b:
        st.markdown("##### 🅱️ Período B")
        render_dia_lado(where_b, "B")

    st.markdown("---")

    # --- Top filmes ---
    st.subheader("🏆 Top filmes")
    col_a, col_b = st.columns(2)
    with col_a:
        st.markdown("##### 🅰️ Período A")
        render_ranking_filmes(where_a)
    with col_b:
        st.markdown("##### 🅱️ Período B")
        render_ranking_filmes(where_b)

    st.markdown("---")

    # --- Top exibidores ---
    st.subheader("🏢 Top exibidores")
    col_a, col_b = st.columns(2)
    with col_a:
        st.markdown("##### 🅰️ Período A")
        render_ranking_exibidores(where_a)
    with col_b:
        st.markdown("##### 🅱️ Período B")
        render_ranking_exibidores(where_b)

    st.markdown("---")

    # --- Detalhe ---
    st.subheader("🔎 Detalhe dos registros")
    col_a, col_b = st.columns(2)
    with col_a:
        st.markdown("##### 🅰️ Período A")
        render_detalhe_lado(where_a, "A")
    with col_b:
        st.markdown("##### 🅱️ Período B")
        render_detalhe_lado(where_b, "B")


if __name__ == "__main__":
    main()