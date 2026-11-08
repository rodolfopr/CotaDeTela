"""
Dashboard Streamlit para a bilheteria diária da ANCINE.

[docstring resumida — ver versão anterior]

Correções desta revisão:
  - Eixo Y sem zeros à direita:
      * Gráfico de linhas: eixo Y categórico com texto pré-formatado (fmt_br).
      * Gráfico de barras empilhadas: eixo Y numérico com format ',.0f' +
        labelExpr apenas para trocar separador.
  - Título do eixo X dinâmico (Semana / Mês / Ano).
"""

from pathlib import Path

import altair as alt
import duckdb
import pandas as pd
import streamlit as st

# --- Configuração ---

PASTA_RAIZ = Path(__file__).resolve().parent.parent
PARQUET_PADRAO = PASTA_RAIZ / "data" / "bilheteria.parquet"

ORIGENS_ESPERADAS = ("Nacional", "Estrangeira")

CORES_PERIODO = {
    "Madrugada":  "#4A148C",
    "Matutino":   "#F9A825",
    "Vespertino": "#EF6C00",
    "Noturno":    "#1A237E",
}
ORDEM_PERIODO = ["Madrugada", "Matutino", "Vespertino", "Noturno"]

ROTULO_PERIODO = {
    "Madrugada": "0h - 5h59min",
    "Matutino": "6h - 11h59min",
    "Vespertino": "12h - 18h59min",
    "Noturno": "19h - 23h59min",
}
ROTULO_PARA_PERIODO = {v: k for k, v in ROTULO_PERIODO.items()}
ORDEM_PERIODO_ROTULO = [ROTULO_PERIODO[p] for p in ORDEM_PERIODO]

CORES_ORIGEM = {
    "Nacional": "#2E7D32",
    "Estrangeira": "#1565C0",
}
COR_TOTAL = "#616161"

CORES_HORA = {
    12: "#FFF59D", 13: "#FFE082", 14: "#FFCC80", 15: "#FFB74D",
    16: "#FFA726", 17: "#FB8C00", 18: "#F57C00", 19: "#E65100",
    20: "#D84315", 21: "#BF360C", 22: "#8D2B0A",
}
CORES_HORA_FORA = "#BDBDBD"

COR_FONTE = "#1A1A1A"
COR_FONTE_EIXO = "#1A1A1A"
COR_FONTE_LEGENDA = "#1A1A1A"

# labelExpr apenas troca o separador; o formato vem do axis.format
LABEL_EXPR_BR = "replace(replace(datum.label, ',', 'X'), 'X', '.')"
LABEL_EXPR_BR_PCT = "datum.label + '%'"
LABEL_EXPR_BR_PCT_NORM = "datum.label + '%'"

FORMATO_EIXO_X = {"semana": "%d/%m/%Y", "mes": "%m/%Y", "ano": "%Y"}
FORMATO_TOOLTIP_DATA = {"semana": "%d/%m/%Y", "mes": "%m/%Y", "ano": "%Y"}
TITULO_EIXO_X = {"semana": "Semana", "mes": "Mês", "ano": "Ano"}

st.set_page_config(
    page_title="Bilheteria ANCINE",
    page_icon="🎬",
    layout="wide",
    initial_sidebar_state="expanded",
)


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


def fmt_br_compacto(valor, casas_max: int = 1) -> str:
    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return "—"
    try:
        n = float(valor)
    except (TypeError, ValueError):
        return "—"
    sinal = "-" if n < 0 else ""
    n_abs = abs(n)
    if n_abs < 1_000:
        return f"{sinal}{fmt_br(n_abs, 0)}"
    if n_abs < 1_000_000:
        divisor, sufixo = 1_000, "mil"
    elif n_abs < 1_000_000_000:
        divisor, sufixo = 1_000_000, "mi"
    else:
        divisor, sufixo = 1_000_000_000, "bi"
    reduzido = n_abs / divisor
    fator = 10 ** casas_max
    truncado = int(reduzido * fator) / fator
    casas = 2 if truncado < 10 else casas_max
    texto = f"{truncado:,.{casas}f}"
    if "." in texto:
        texto = texto.rstrip("0").rstrip(".")
    texto = texto.replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{sinal}{texto} {sufixo}"


def fmt_br_data(dt) -> str:
    if dt is None or (isinstance(dt, float) and pd.isna(dt)):
        return "—"
    return pd.to_datetime(dt).strftime("%d/%m/%Y")


def df_para_exibicao(df: pd.DataFrame, colunas_numericas=None, casas: int = 0) -> pd.DataFrame:
    if colunas_numericas is None:
        colunas_numericas = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
    out = df.copy()
    for c in colunas_numericas:
        if c in out.columns:
            out[c] = out[c].apply(lambda v: fmt_br(v, casas))
    return out


def traduz_periodo_df(df: pd.DataFrame, coluna: str = "periodo") -> pd.DataFrame:
    out = df.copy()
    if coluna in out.columns:
        out[coluna] = out[coluna].map(ROTULO_PERIODO).fillna(out[coluna])
    return out


def _formata_data_coluna(serie: pd.Series, granularidade: str) -> pd.Series:
    fmt = FORMATO_TOOLTIP_DATA.get(granularidade, "%d/%m/%Y")
    return pd.to_datetime(serie).dt.strftime(fmt)


# --- Conexão / query ---

@st.cache_resource
def get_conexao():
    con = duckdb.connect()
    con.execute("SET memory_limit = '2GB';")
    con.execute("SET threads = 2;")
    con.execute("SET preserve_insertion_order = false;")
    con.execute(
        f"CREATE OR REPLACE VIEW bilheteria AS "
        f"SELECT * FROM '{PARQUET_PADRAO}'"
    )
    return con


def query(sql: str) -> pd.DataFrame:
    con = get_conexao()
    cur = con.cursor()
    try:
        return cur.execute(sql).df()
    finally:
        cur.close()


def arquivo_existe() -> bool:
    return PARQUET_PADRAO.exists()


def _lista_sql(valores) -> str:
    return ",".join(f"'{str(v).replace(chr(39), chr(39)*2)}'" for v in valores)


# --- Listas de filtros ---

@st.cache_data(show_spinner=False)
def carrega_opcoes(_dummy: int = 0):
    sql = """
        SELECT
            MIN(DATA_EXIBICAO) AS dt_min,
            MAX(DATA_EXIBICAO) AS dt_max,
            COUNT(DISTINCT UF_SALA_COMPLEXO) AS n_uf,
            COUNT(DISTINCT MUNICIPIO_SALA_COMPLEXO) AS n_mun,
            COUNT(DISTINCT TITULO_PTBR) AS n_titulos,
            COUNT(DISTINCT CNPJ_EXIBIDORA) AS n_exibidores
        FROM bilheteria
    """
    return query(sql)


@st.cache_data(show_spinner=False)
def carrega_ufs(_dummy: int = 0):
    sql = """
        SELECT DISTINCT UF_SALA_COMPLEXO AS uf
        FROM bilheteria
        WHERE UF_SALA_COMPLEXO IS NOT NULL
        ORDER BY uf
    """
    return query(sql)["uf"].tolist()


def carrega_municipios(ufs_selecionadas):
    if not ufs_selecionadas:
        return []
    sql = f"""
        SELECT DISTINCT MUNICIPIO_SALA_COMPLEXO AS mun
        FROM bilheteria
        WHERE UF_SALA_COMPLEXO IN ({_lista_sql(ufs_selecionadas)})
        ORDER BY mun
    """
    return query(sql)["mun"].tolist()


def carrega_complexos(municipios_selecionados=None):
    filtro = (
        f"AND MUNICIPIO_SALA_COMPLEXO IN ({_lista_sql(municipios_selecionados)})"
        if municipios_selecionados else ""
    )
    sql = f"""
        SELECT DISTINCT REGISTRO_COMPLEXO, MUNICIPIO_SALA_COMPLEXO, UF_SALA_COMPLEXO
        FROM bilheteria
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


@st.cache_data(show_spinner=False)
def carrega_exibidores(_dummy: int = 0):
    sql = """
        SELECT DISTINCT RAZAO_SOCIAL_EXIBIDORA AS exibidor
        FROM bilheteria
        WHERE RAZAO_SOCIAL_EXIBIDORA IS NOT NULL
        ORDER BY exibidor
    """
    return query(sql)["exibidor"].tolist()


@st.cache_data(show_spinner=False)
def carrega_titulos(_dummy: int = 0):
    sql = """
        SELECT DISTINCT TITULO_PTBR AS titulo
        FROM bilheteria
        WHERE TITULO_PTBR IS NOT NULL AND TRIM(TITULO_PTBR) <> ''
        ORDER BY titulo
    """
    return query(sql)["titulo"].tolist()


@st.cache_data(show_spinner=False)
def carrega_origens(_dummy: int = 0):
    sql = f"""
        SELECT DISTINCT ORIGEM_OBRA AS origem
        FROM bilheteria
        WHERE ORIGEM_OBRA IN ({_lista_sql(ORIGENS_ESPERADAS)})
        ORDER BY origem
    """
    return query(sql)["origem"].tolist()


@st.cache_data(show_spinner=False)
def carrega_periodos(_dummy: int = 0):
    sql = """
        SELECT DISTINCT PERIODO_SESSAO AS periodo
        FROM bilheteria
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


@st.cache_data(show_spinner=False)
def carrega_dias_semana(_dummy: int = 0):
    sql = """
        SELECT DIASEMANA_EXIBICAO AS dia
        FROM bilheteria
        WHERE DIASEMANA_EXIBICAO IS NOT NULL
        GROUP BY DIASEMANA_EXIBICAO, DIASEMANA_NUM_EXIBICAO
        ORDER BY DIASEMANA_NUM_EXIBICAO NULLS LAST
    """
    return query(sql)["dia"].tolist()


# --- Filtros ---

def monta_where(filtros) -> str:
    cond = []
    if filtros["data_ini"] and filtros["data_fim"]:
        cond.append(
            f"DATA_EXIBICAO BETWEEN DATE '{filtros['data_ini']}' AND DATE '{filtros['data_fim']}'"
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
        cond.append(f"TITULO_PTBR IN ({_lista_sql(filtros['titulos'])})")
    if filtros["origens"]:
        cond.append(f"ORIGEM_OBRA IN ({_lista_sql(filtros['origens'])})")
    if filtros["periodos"]:
        cond.append(f"PERIODO_SESSAO IN ({_lista_sql(filtros['periodos'])})")
    if filtros["dias"]:
        cond.append(f"DIASEMANA_EXIBICAO IN ({_lista_sql(filtros['dias'])})")
    return " AND ".join(cond) if cond else "1=1"


# --- Consultas analíticas (cacheadas) ---

@st.cache_data(show_spinner=False)
def kpis(where: str) -> dict:
    sql = f"""
        SELECT
            SUM(PUBLICO) AS publico,
            COUNT(*) AS sessoes,
            COUNT(DISTINCT TITULO_PTBR) FILTER (WHERE TRIM(TITULO_PTBR) <> '') AS filmes,
            COUNT(DISTINCT REGISTRO_SALA) AS salas,
            COUNT(DISTINCT CNPJ_EXIBIDORA) AS exibidores,
            MIN(DATA_EXIBICAO) AS dt_ini,
            MAX(DATA_EXIBICAO) AS dt_fim
        FROM bilheteria
        WHERE {where}
    """
    return query(sql).iloc[0].to_dict()


@st.cache_data(show_spinner=False)
def kpi_participacao_nacional(where: str) -> float:
    sql = f"""
        SELECT
            100.0 * SUM(CASE WHEN ORIGEM_OBRA = 'Nacional' THEN PUBLICO ELSE 0 END)
            / NULLIF(SUM(PUBLICO), 0) AS pct
        FROM bilheteria
        WHERE {where}
    """
    val = query(sql).iloc[0]["pct"]
    return float(val) if val is not None else 0.0


@st.cache_data(show_spinner=False)
def serie_temporal_por_origem(where: str, granularidade: str) -> pd.DataFrame:
    if granularidade == "semana":
        expr = "DATE_TRUNC('week', DATA_EXIBICAO)"
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
            SUM(CASE WHEN ORIGEM_OBRA = 'Estrangeira' THEN 1 ELSE 0 END) AS estrangeira_sessoes
        FROM bilheteria
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
    ]:
        out[f"{rotulo} — Público"] = df[f"{prefixo}_publico"]
        out[f"{rotulo} — Sessões"] = df[f"{prefixo}_sessoes"]
    return pd.DataFrame(out).set_index("periodo")


@st.cache_data(show_spinner=False)
def top_filmes(where: str, n: int = 15) -> pd.DataFrame:
    sql = f"""
        SELECT
            TITULO_PTBR AS titulo,
            MIN(ORIGEM_OBRA) AS origem,
            SUM(PUBLICO) AS publico,
            COUNT(*) AS sessoes,
            MIN(DATA_EXIBICAO) AS dt_ini,
            MAX(DATA_EXIBICAO) AS dt_fim
        FROM bilheteria
        WHERE {where}
        GROUP BY TITULO_PTBR
        ORDER BY publico DESC
        LIMIT {n}
    """
    df = query(sql)
    if df.empty:
        return df
    df.insert(0, "posicao", [f"{i}º" for i in range(1, len(df) + 1)])
    return df


@st.cache_data(show_spinner=False)
def top_exibidores(where: str, n: int = 15) -> pd.DataFrame:
    sql = f"""
        SELECT
            RAZAO_SOCIAL_EXIBIDORA AS exibidor,
            SUM(PUBLICO) AS publico,
            COUNT(DISTINCT REGISTRO_SALA) AS salas,
            COUNT(*) AS sessoes,
            COUNT(DISTINCT REGISTRO_COMPLEXO) AS n_complexos,
            COUNT(DISTINCT UF_SALA_COMPLEXO) AS n_estados,
            COUNT(DISTINCT MUNICIPIO_SALA_COMPLEXO) AS n_municipios
        FROM bilheteria
        WHERE {where}
        GROUP BY exibidor
        ORDER BY publico DESC
        LIMIT {n}
    """
    df = query(sql)
    if df.empty:
        return df
    df.insert(0, "posicao", [f"{i}º" for i in range(1, len(df) + 1)])
    return df


@st.cache_data(show_spinner=False)
def por_origem(where: str) -> pd.DataFrame:
    sql = f"""
        SELECT
            ORIGEM_OBRA AS origem,
            SUM(PUBLICO) AS publico,
            COUNT(*) AS sessoes,
            COUNT(DISTINCT TITULO_PTBR) AS filmes
        FROM bilheteria
        WHERE {where}
          AND ORIGEM_OBRA IN ({_lista_sql(ORIGENS_ESPERADAS)})
        GROUP BY ORIGEM_OBRA
        ORDER BY publico DESC
    """
    return query(sql)


@st.cache_data(show_spinner=False)
def por_origem_e_periodo(where: str) -> pd.DataFrame:
    sql = f"""
        SELECT
            ORIGEM_OBRA AS origem,
            PERIODO_SESSAO AS periodo,
            SUM(PUBLICO) AS publico,
            COUNT(*) AS sessoes
        FROM bilheteria
        WHERE {where}
          AND ORIGEM_OBRA IN ({_lista_sql(ORIGENS_ESPERADAS)})
          AND PERIODO_SESSAO IN ({_lista_sql(ORDEM_PERIODO)})
        GROUP BY ORIGEM_OBRA, PERIODO_SESSAO
        ORDER BY ORIGEM_OBRA, PERIODO_SESSAO
    """
    return query(sql)


@st.cache_data(show_spinner=False)
def por_dia_semana_por_hora(where: str) -> pd.DataFrame:
    sql = f"""
        SELECT
            DIASEMANA_EXIBICAO AS dia,
            DIASEMANA_NUM_EXIBICAO AS dia_num,
            HORA_SESSAO AS hora,
            SUM(PUBLICO) AS publico,
            COUNT(*) AS sessoes
        FROM bilheteria
        WHERE {where}
          AND HORA_SESSAO IS NOT NULL
        GROUP BY DIASEMANA_EXIBICAO, DIASEMANA_NUM_EXIBICAO, HORA_SESSAO
        ORDER BY DIASEMANA_NUM_EXIBICAO NULLS LAST, HORA_SESSAO
    """
    return query(sql)


@st.cache_data(show_spinner=False)
def por_dia_semana_origem_periodo(where: str) -> pd.DataFrame:
    sql = f"""
        SELECT
            DIASEMANA_EXIBICAO AS dia,
            DIASEMANA_NUM_EXIBICAO AS dia_num,
            ORIGEM_OBRA AS origem,
            PERIODO_SESSAO AS periodo,
            SUM(PUBLICO) AS publico,
            COUNT(*) AS sessoes
        FROM bilheteria
        WHERE {where}
          AND ORIGEM_OBRA IN ({_lista_sql(ORIGENS_ESPERADAS)})
          AND PERIODO_SESSAO IN ({_lista_sql(ORDEM_PERIODO)})
        GROUP BY DIASEMANA_EXIBICAO, DIASEMANA_NUM_EXIBICAO, ORIGEM_OBRA, PERIODO_SESSAO
        ORDER BY
            DIASEMANA_NUM_EXIBICAO NULLS LAST,
            ORIGEM_OBRA,
            CASE PERIODO_SESSAO
                WHEN 'Madrugada'  THEN 1
                WHEN 'Matutino'   THEN 2
                WHEN 'Vespertino' THEN 3
                WHEN 'Noturno'    THEN 4
            END
    """
    return query(sql)


@st.cache_data(show_spinner=False)
def tabela_detalhe(where: str, limite: int = 200) -> pd.DataFrame:
    sql = f"""
        SELECT *
        FROM (
            SELECT *
            FROM bilheteria
            WHERE {where}
            LIMIT {limite * 10}
        )
        ORDER BY DATA_EXIBICAO DESC, PUBLICO DESC
        LIMIT {limite}
    """
    df = query(sql)
    if df.empty:
        return df
    prioridade = ["DATA_EXIBICAO", "SESSAO", "TITULO_PTBR"]
    existentes = [c for c in prioridade if c in df.columns]
    outras = [c for c in df.columns if c not in existentes]
    return df[existentes + outras]


# --- Eixos comuns ---

def eixo_x(title: str = None, granularidade: str = None, **kwargs) -> alt.Axis:
    if title is None and granularidade is not None:
        title = TITULO_EIXO_X.get(granularidade, "Dimensão")
    return alt.Axis(
        title=title,
        labelColor=COR_FONTE_EIXO,
        titleColor=COR_FONTE_EIXO,
        **kwargs,
    )


def eixo_y(title: str, label_expr: str = None, **kwargs) -> alt.Axis:
    base = dict(
        title=title,
        labelColor=COR_FONTE_EIXO,
        titleColor=COR_FONTE_EIXO,
    )
    if label_expr is not None:
        base["labelExpr"] = label_expr
        base["format"] = ",.0f"   # força inteiro en-US antes do labelExpr
    base.update(kwargs)
    return alt.Axis(**base)


def legenda_origem(**kwargs) -> alt.Legend:
    base = dict(
        title="Origem",
        labelColor=COR_FONTE_LEGENDA,
        titleColor=COR_FONTE_LEGENDA,
        symbolStrokeWidth=0,
    )
    base.update(kwargs)
    return alt.Legend(**base)


# --- Gráficos (Altair) ---

def grafico_pizza_origem(df: pd.DataFrame, metrica: str = "publico", titulo: str = "Origem"):
    df_plot = df[["origem", metrica]].copy()
    df_plot.columns = ["categoria", "valor"]
    df_plot["valor_fmt"] = df_plot["valor"].apply(lambda v: fmt_br(v, 0))
    total = df_plot["valor"].sum()
    df_plot["pct"] = df_plot["valor"] / total * 100 if total else 0
    df_plot["pct_fmt"] = df_plot["pct"].apply(lambda v: fmt_br_pct(v, 1))
    rotulo_metrica = "Público" if metrica == "publico" else "Sessões"
    base = alt.Chart(df_plot).encode(
        theta=alt.Theta(field="valor", type="quantitative", stack=True),
        color=alt.Color(
            "categoria:N", title=titulo,
            sort=list(CORES_ORIGEM.keys()),
            scale=alt.Scale(domain=list(CORES_ORIGEM.keys()),
                            range=list(CORES_ORIGEM.values())),
            legend=legenda_origem(title=titulo),
        ),
        tooltip=[
            alt.Tooltip("categoria:N", title=titulo),
            alt.Tooltip("valor_fmt:N", title=rotulo_metrica),
            alt.Tooltip("pct_fmt:N", title="% do total"),
        ],
    )
    pizza = base.mark_arc(innerRadius=0)
    rotulos = (
        base.mark_text(radius=110, size=13, color="white", fontWeight="bold")
        .encode(text=alt.Text("pct_fmt:N"))
    )
    return (pizza + rotulos).properties(height=280)


def grafico_donut_por_origem(df_origem_periodo, origem_alvo, metrica="publico"):
    df_plot = df_origem_periodo[df_origem_periodo["origem"] == origem_alvo].copy()
    if df_plot.empty:
        return None
    df_plot = traduz_periodo_df(df_plot)
    total = df_plot[metrica].sum()
    df_plot["pct"] = df_plot[metrica] / total * 100 if total else 0
    df_plot["valor_fmt"] = df_plot[metrica].apply(lambda v: fmt_br(v, 0))
    df_plot["pct_fmt"] = df_plot["pct"].apply(lambda v: fmt_br_pct(v, 1))
    rotulo_metrica = "Público" if metrica == "publico" else "Sessões"
    return (
        alt.Chart(df_plot)
        .mark_arc(innerRadius=60, outerRadius=120)
        .encode(
            theta=alt.Theta(field=metrica, type="quantitative", stack=True),
            color=alt.Color(
                "periodo:N", title="Faixa de horário",
                sort=ORDEM_PERIODO_ROTULO,
                scale=alt.Scale(domain=ORDEM_PERIODO_ROTULO,
                                range=[CORES_PERIODO[p] for p in ORDEM_PERIODO]),
                legend=alt.Legend(orient="right", title="Faixa de horário",
                                  labelColor=COR_FONTE_LEGENDA,
                                  titleColor=COR_FONTE_LEGENDA,
                                  symbolStrokeWidth=0),
            ),
            tooltip=[
                alt.Tooltip("periodo:N", title="Faixa de horário"),
                alt.Tooltip("valor_fmt:N", title=rotulo_metrica),
                alt.Tooltip("pct_fmt:N", title="% da origem"),
            ],
        )
        .properties(height=280)
    )


def grafico_barras_dia_por_hora(df: pd.DataFrame, metrica: str = "publico"):
    df_plot = df.copy()
    df_plot["dia"] = df_plot["dia"].astype(str)
    df_plot["hora_int"] = df_plot["hora"].astype(int)
    df_plot["hora_str"] = df_plot["hora_int"].apply(lambda h: f"{h:02d}h")
    horas_foco = list(CORES_HORA.keys())
    df_plot["hora_cat"] = df_plot["hora_int"].apply(
        lambda h: f"{h:02d}h" if h in horas_foco else "Outras horas"
    )
    totais_dia = df_plot.groupby("dia")[metrica].transform("sum")
    df_plot["total_dia_fmt"] = totais_dia.apply(lambda v: fmt_br(v, 0))
    df_plot["valor_fmt"] = df_plot[metrica].apply(lambda v: fmt_br(v, 0))
    df_plot["pct_dia"] = df_plot[metrica] / totais_dia.replace(0, pd.NA) * 100
    df_plot["pct_fmt"] = df_plot["pct_dia"].apply(lambda v: fmt_br_pct(v, 1))
    ordem_dias = ["Seg.", "Ter.", "Qua.", "Qui.", "Sex.", "Sáb.", "Dom."]
    rotulo_metrica = "Público" if metrica == "publico" else "Sessões"
    dominio_cores = [f"{h:02d}h" for h in horas_foco] + ["Outras horas"]
    range_cores = [CORES_HORA[h] for h in horas_foco] + [CORES_HORA_FORA]
    base = alt.Chart(df_plot).encode(
        x=alt.X("dia:N", title="Dia da semana", sort=ordem_dias,
                axis=eixo_x("Dia da semana", labelAngle=0)),
        y=alt.Y(f"{metrica}:Q", title=rotulo_metrica, stack="zero",
                axis=eixo_y(rotulo_metrica, label_expr=LABEL_EXPR_BR)),
        color=alt.Color(
            "hora_cat:N", title="Hora da sessão",
            sort=dominio_cores,
            scale=alt.Scale(domain=dominio_cores, range=range_cores),
            legend=alt.Legend(orient="bottom", title="Hora da sessão",
                              labelColor=COR_FONTE_LEGENDA,
                              titleColor=COR_FONTE_LEGENDA,
                              columns=6, symbolLimit=12, symbolStrokeWidth=0),
        ),
        order=alt.Order("hora_int:Q", sort="ascending"),
    )
    barras = base.mark_bar(stroke="#000000", strokeWidth=1.2).encode(
        tooltip=[
            alt.Tooltip("dia:N", title="Dia"),
            alt.Tooltip("hora_str:N", title="Hora"),
            alt.Tooltip("valor_fmt:N", title=rotulo_metrica),
            alt.Tooltip("pct_fmt:N", title="% do dia"),
            alt.Tooltip("total_dia_fmt:N", title=f"Total do dia ({rotulo_metrica})"),
        ],
    )
    df_foco = df_plot[df_plot["hora_int"].isin([17, 21])].copy()
    if not df_foco.empty:
        df_sorted = df_plot.sort_values(["dia", "hora_int"]).copy()
        df_sorted["acumulado"] = df_sorted.groupby("dia")[metrica].cumsum()
        df_sorted["centro"] = df_sorted["acumulado"] - df_sorted[metrica] / 2
        centros = df_sorted.set_index(["dia", "hora_int"])["centro"]
        df_foco["centro"] = df_foco.apply(
            lambda r: centros.get((r["dia"], r["hora_int"]), None), axis=1
        )
        df_foco = df_foco.dropna(subset=["centro"])
    rotulos = (
        alt.Chart(df_foco)
        .mark_text(fontSize=10, fontWeight="bold", color=COR_FONTE)
        .encode(x=alt.X("dia:N", sort=ordem_dias),
                y=alt.Y("centro:Q"),
                text=alt.Text("hora_str:N"))
    )
    return (barras + rotulos).properties(height=380)


def grafico_barras_share_dia_por_periodo(df, periodo_filtro, metrica="publico"):
    df_plot = df[df["periodo"] == periodo_filtro].copy()
    if df_plot.empty:
        return None
    df_plot = traduz_periodo_df(df_plot)
    df_plot["dia"] = df_plot["dia"].astype(str)
    total_dia = df_plot.groupby("dia")[metrica].transform("sum")
    df_plot["pct"] = df_plot[metrica] / total_dia.replace(0, pd.NA) * 100
    df_plot["pct_fmt"] = df_plot["pct"].apply(lambda v: fmt_br_pct(v, 1))
    df_plot["valor_fmt"] = df_plot[metrica].apply(lambda v: fmt_br(v, 0))
    df_plot["total_dia_fmt"] = total_dia.apply(lambda v: fmt_br(v, 0))
    ordem_dias = ["Seg.", "Ter.", "Qua.", "Qui.", "Sex.", "Sáb.", "Dom."]
    rotulo_metrica = "Público" if metrica == "publico" else "Sessões"
    return (
        alt.Chart(df_plot)
        .mark_bar(stroke="#000000", strokeWidth=0.5)
        .encode(
            x=alt.X("dia:N", title="Dia da semana", sort=ordem_dias,
                    axis=eixo_x("Dia da semana", labelAngle=0, labelFontSize=11)),
            y=alt.Y("pct:Q", title="% do público", stack="normalize",
                    axis=eixo_y("% do público", label_expr=LABEL_EXPR_BR_PCT_NORM)),
            color=alt.Color(
                "origem:N", title="Origem",
                sort=["Nacional", "Estrangeira"],
                scale=alt.Scale(domain=["Nacional", "Estrangeira"],
                                range=[CORES_ORIGEM["Nacional"], CORES_ORIGEM["Estrangeira"]]),
                legend=legenda_origem(orient="top", direction="horizontal", title=None),
            ),
            order=alt.Order("origem:N", sort="ascending"),
            tooltip=[
                alt.Tooltip("dia:N", title="Dia"),
                alt.Tooltip("periodo:N", title="Faixa de horário"),
                alt.Tooltip("origem:N", title="Origem"),
                alt.Tooltip("pct_fmt:N", title="% do dia"),
                alt.Tooltip("valor_fmt:N", title=rotulo_metrica),
                alt.Tooltip("total_dia_fmt:N", title=f"Total do dia ({rotulo_metrica})"),
            ],
        )
        .properties(height=380)
    )


def grafico_barras_100_origem_ano(where: str, metrica: str = "Público"):
    expr_metrica = "PUBLICO" if metrica == "Público" else "1"
    rotulo_eixo = "% do público" if metrica == "Público" else "% das sessões"
    sql = f"""
        SELECT
            EXTRACT(YEAR FROM DATA_EXIBICAO) AS ano,
            ORIGEM_OBRA AS origem,
            SUM({expr_metrica}) AS valor
        FROM bilheteria
        WHERE {where}
          AND ORIGEM_OBRA IN ({_lista_sql(ORIGENS_ESPERADAS)})
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
    totais_por_origem = df_long.groupby("origem")["valor"].sum().sort_values(ascending=True)
    ordem_origens = totais_por_origem.index.tolist()
    df_long["ano_str"] = df_long["ano"].astype(int).astype(str)
    return (
        alt.Chart(df_long)
        .mark_bar()
        .encode(
            x=alt.X("ano_str:N", title="Ano", axis=eixo_x("Ano", labelAngle=0)),
            y=alt.Y("pct:Q", title=rotulo_eixo, stack="normalize",
                    axis=eixo_y(rotulo_eixo, label_expr=LABEL_EXPR_BR_PCT_NORM)),
            color=alt.Color(
                "origem:N", title="Origem",
                sort=ordem_origens,
                scale=alt.Scale(domain=list(CORES_ORIGEM.keys()),
                                range=list(CORES_ORIGEM.values())),
                legend=legenda_origem(orient="bottom", direction="horizontal"),
            ),
            order=alt.Order("origem:N", sort="ascending"),
            tooltip=[
                alt.Tooltip("ano_str:N", title="Ano"),
                alt.Tooltip("origem:N", title="Origem"),
                alt.Tooltip("pct_fmt:N", title=f"% do {metrica.lower()} no ano"),
                alt.Tooltip("valor_fmt:N", title=metrica),
            ],
        )
        .properties(height=320)
    )


def grafico_linha_evolucao(serie, metrica="Público", granularidade="mes"):
    cols = [c for c in serie.columns if c.endswith(f"— {metrica}")]
    df_long = serie[cols].reset_index().melt(
        id_vars="periodo", var_name="serie", value_name="valor",
    )
    df_long["serie"] = df_long["serie"].str.replace(f" — {metrica}", "", regex=False)
    df_long = df_long.rename(columns={"periodo": "data"})
    df_long["valor_fmt"] = df_long["valor"].apply(lambda v: fmt_br(v, 0))
    df_long["data_fmt"] = _formata_data_coluna(df_long["data"], granularidade)

    zoom = alt.selection_interval(bind="scales", encodings=["x"])
    ordem_series = ["Total", "Nacional", "Estrangeira"]
    cores_series = {"Total": COR_TOTAL,
                    "Nacional": CORES_ORIGEM["Nacional"],
                    "Estrangeira": CORES_ORIGEM["Estrangeira"]}
    formato_x = FORMATO_EIXO_X.get(granularidade, "%d/%m/%Y")

    return (
        alt.Chart(df_long)
        .mark_line(point=True, strokeWidth=2.5)
        .encode(
            x=alt.X("data:T", axis=eixo_x(granularidade=granularidade, format=formato_x)),
            y=alt.Y("valor:Q", title=metrica,
                    axis=eixo_y(metrica, label_expr=LABEL_EXPR_BR)),
            color=alt.Color(
                "serie:N", title="Origem",
                sort=ordem_series,
                scale=alt.Scale(domain=ordem_series,
                                range=[cores_series[s] for s in ordem_series]),
                legend=legenda_origem(orient="bottom", direction="horizontal"),
            ),
            tooltip=[
                alt.Tooltip("data_fmt:N", title="Data"),
                alt.Tooltip("serie:N", title="Série"),
                alt.Tooltip("valor_fmt:N", title=metrica),
            ],
        )
        .add_params(zoom)
        .properties(height=360)
    )


def grafico_barras_empilhadas(serie, metrica="Público", granularidade="mes"):
    cols = [c for c in serie.columns
            if c.endswith(f"— {metrica}") and not c.startswith("Total")]
    df_long = serie[cols].reset_index().melt(
        id_vars="periodo", var_name="serie", value_name="valor",
    )
    df_long["serie"] = df_long["serie"].str.replace(f" — {metrica}", "", regex=False)
    df_long = df_long.rename(columns={"periodo": "data"})
    df_long["valor_fmt"] = df_long["valor"].apply(lambda v: fmt_br(v, 0))
    df_long["data_fmt"] = _formata_data_coluna(df_long["data"], granularidade)

    ordem_series = ["Nacional", "Estrangeira"]
    zoom = alt.selection_interval(bind="scales", encodings=["x"])
    formato_x = FORMATO_EIXO_X.get(granularidade, "%d/%m/%Y")

    return (
        alt.Chart(df_long)
        .mark_bar()
        .encode(
            x=alt.X("data:T", axis=eixo_x(granularidade=granularidade, format=formato_x)),
            y=alt.Y("valor:Q", title=metrica, stack="zero",
                    axis=eixo_y(metrica, label_expr=LABEL_EXPR_BR)),
            color=alt.Color(
                "serie:N", title="Origem",
                sort=ordem_series,
                scale=alt.Scale(domain=ordem_series,
                                range=[CORES_ORIGEM[s] for s in ordem_series]),
                legend=legenda_origem(orient="bottom", direction="horizontal"),
            ),
            order=alt.Order("serie:N", sort="ascending"),
            tooltip=[
                alt.Tooltip("data_fmt:N", title="Data"),
                alt.Tooltip("serie:N", title="Série"),
                alt.Tooltip("valor_fmt:N", title=metrica),
            ],
        )
        .add_params(zoom)
        .properties(height=360)
    )


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
        municipios = st.sidebar.multiselect("Município", options=carrega_municipios(ufs), default=[])
    complexos = []
    df_complexos = carrega_complexos(municipios if municipios else None)
    if not df_complexos.empty:
        opcoes_complexos = dict(zip(df_complexos["rotulo"], df_complexos["REGISTRO_COMPLEXO"]))
        rotulos_sel = st.sidebar.multiselect(
            "Complexo", options=list(opcoes_complexos.keys()), default=[],
            help="Deixe em branco para considerar todos os complexos.",
        )
        complexos = [opcoes_complexos[r] for r in rotulos_sel]
    exibidores = st.sidebar.multiselect(
        "Exibidor", options=carrega_exibidores(), default=[],
        help="Deixe em branco para considerar todos os exibidores.",
    )
    st.sidebar.subheader("Filmes")
    titulos = st.sidebar.multiselect(
        "Título", options=carrega_titulos(), default=[],
        help="Deixe em branco para considerar todos. Baseado em TITULO_PTBR.",
    )
    st.sidebar.subheader("Origem da obra")
    origens = st.sidebar.multiselect(
        "Origem", options=carrega_origens(), default=[],
        help="Deixe em branco para incluir todas as origens.",
    )
    st.sidebar.subheader("Faixa de horário")
    periodos_rotulos = st.sidebar.multiselect(
        "Faixa de horário", options=ORDEM_PERIODO_ROTULO, default=[],
        help="Deixe em branco para incluir todas as faixas.",
    )
    periodos = [ROTULO_PARA_PERIODO.get(r, r) for r in periodos_rotulos]
    st.sidebar.subheader("Dia da semana")
    dias = st.sidebar.multiselect(
        "Dia", options=carrega_dias_semana(), default=[],
        help="Deixe em branco para incluir todos os dias.",
    )
    st.sidebar.markdown("---")
    st.sidebar.caption(
        f"Base: **{meta['n_titulos']:,}** títulos · "
        f"**{meta['n_uf']}** UFs · "
        f"**{meta['n_exibidores']:,}** exibidores"
    )
    return {
        "data_ini": data_ini, "data_fim": data_fim, "ufs": ufs,
        "municipios": municipios, "complexos": complexos,
        "exibidores": exibidores, "titulos": titulos,
        "origens": origens, "periodos": periodos, "dias": dias,
    }


def main():
    st.title(
        "Estudo Exploratório sobre Exibição de Filmes em salas de cinema no "
        "Brasil e a aplicação de Cota de Telas"
    )
    st.caption(
        "Dashboard interativo de dados públicos sobre bilheteria diária das "
        "salas de exibição cinematográfica no Brasil disponibilizados pela "
        "Agência Nacional do Cinema (ANCINE)."
    )
    if not arquivo_existe():
        st.error(
            f"Parquet não encontrado em `{PARQUET_PADRAO}`.\n\n"
            "Rode antes:\n"
            "```\npython scripts/baixa_arquivos.py\npython scripts/criar_parquet.py\n```"
        )
        st.stop()

    df_checagem = query("""
        SELECT COUNT(*) AS n FROM bilheteria WHERE ORIGEM_OBRA = 'Não informado'
    """)
    n_nao_info = int(df_checagem.iloc[0]["n"]) if not df_checagem.empty else 0
    if n_nao_info > 0:
        st.warning(
            f"Há **{fmt_br(n_nao_info)}** registros com `ORIGEM_OBRA = 'Não informado'` "
            f"no Parquet — categoria que deveria ter sido eliminada pela geração. "
            f"Eles **não aparecem** nos gráficos de origem, mas contam no total. "
            f"Considere regenerar o Parquet com `python scripts/criar_parquet.py`."
        )

    meta = carrega_opcoes().iloc[0].to_dict()
    ufs_todas = carrega_ufs()
    filtros = render_sidebar(meta, ufs_todas)
    where = monta_where(filtros)

    k = kpis(where)
    pct_nacional = kpi_participacao_nacional(where)

    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("Público total", fmt_br_compacto(k["publico"]),
              help=f"Valor completo: {fmt_br(k['publico'], 0)}")
    c2.metric("Sessões", fmt_br_compacto(k["sessoes"]),
              help=f"Valor completo: {fmt_br(k['sessoes'], 0)}")
    c3.metric("Filmes", fmt_br_compacto(k["filmes"]),
              help=f"Valor completo: {fmt_br(k['filmes'], 0)}")
    c4.metric("Salas", fmt_br_compacto(k["salas"]),
              help=f"Valor completo: {fmt_br(k['salas'], 0)}")
    c5.metric("Exibidores", fmt_br_compacto(k["exibidores"]),
              help=f"Valor completo: {fmt_br(k['exibidores'], 0)}")
    c6.metric("Participação nacional", fmt_br_pct(pct_nacional, 1),
              help=f"Percentual exato: {fmt_br_pct(pct_nacional, 2)}")

    if k["dt_ini"] is None:
        st.warning("Nenhum registro para os filtros selecionados.")
        st.stop()

    st.caption(f"Período efetivo: {fmt_br_data(k['dt_ini'])} → {fmt_br_data(k['dt_fim'])}")
    st.markdown("---")

    st.subheader("🌎 Público por origem da obra")
    df_origem = por_origem(where)
    if not df_origem.empty:
        metrica_o = st.radio(
            "Métrica", options=["publico", "sessoes"],
            format_func=lambda x: "Público" if x == "publico" else "Sessões",
            horizontal=True, key="metrica_origem",
        )
        col_o1, col_o2 = st.columns([1, 1])
        with col_o1:
            st.dataframe(
                df_para_exibicao(df_origem,
                                 colunas_numericas=["publico", "sessoes", "filmes"]),
                use_container_width=True, hide_index=True,
                column_config={
                    "origem": "Origem",
                    "publico": st.column_config.TextColumn("Público"),
                    "sessoes": st.column_config.TextColumn("Sessões"),
                    "filmes": st.column_config.TextColumn("Filmes"),
                },
            )
        with col_o2:
            st.altair_chart(grafico_pizza_origem(df_origem, metrica_o, "Origem"),
                            use_container_width=True)

    st.markdown("---")

    st.subheader("📈 Evolução do público ou sessões")
    col_m, col_g = st.columns(2)
    with col_m:
        metrica_serie = st.radio(
            "Métrica", options=["Público", "Sessões"],
            index=0, horizontal=True, key="metrica_serie",
        )
    with col_g:
        granularidade = st.radio(
            "Unidade da Dimensão", options=["semana", "mes", "ano"],
            index=1, horizontal=True, key="gran_serie",
        )
    serie = serie_temporal_por_origem(where, granularidade)
    if not serie.empty:
        st.altair_chart(grafico_linha_evolucao(serie, metrica_serie, granularidade),
                        use_container_width=True)
        with st.expander("Ver tabela detalhada"):
            cols_metrica = [c for c in serie.columns if c.endswith(f"— {metrica_serie}")]
            df_tab = serie[cols_metrica].reset_index().rename(columns={"periodo": "data"})
            df_tab.columns = [c.replace(f" — {metrica_serie}", "") for c in df_tab.columns]
            df_tab["data"] = _formata_data_coluna(df_tab["data"], granularidade)
            st.dataframe(
                df_para_exibicao(df_tab,
                                 colunas_numericas=[c for c in df_tab.columns if c != "data"],
                                 casas=0),
                use_container_width=True, hide_index=True,
            )

    st.markdown("---")
    st.subheader("📊 Quantidade de público ou sessões por dimensão de tempo")
    col_mb, col_gb = st.columns(2)
    with col_mb:
        metrica_barras = st.radio(
            "Métrica", options=["Público", "Sessões"],
            index=0, horizontal=True, key="metrica_barras",
        )
    with col_gb:
        granularidade_barras = st.radio(
            "Unidade da Dimensão", options=["semana", "mes", "ano"],
            index=1, horizontal=True, key="gran_barras",
        )
    serie_barras = serie_temporal_por_origem(where, granularidade_barras)
    if not serie_barras.empty:
        st.altair_chart(
            grafico_barras_empilhadas(serie_barras, metrica_barras, granularidade_barras),
            use_container_width=True,
        )
        with st.expander("Ver tabela detalhada"):
            cols_tab = [c for c in serie_barras.columns
                        if c.endswith(f"— {metrica_barras}") and not c.startswith("Total")]
            df_tab_barras = serie_barras[cols_tab].reset_index().rename(columns={"periodo": "data"})
            df_tab_barras.columns = [c.replace(f" — {metrica_barras}", "") for c in df_tab_barras.columns]
            df_tab_barras["data"] = _formata_data_coluna(df_tab_barras["data"], granularidade_barras)
            st.dataframe(
                df_para_exibicao(df_tab_barras,
                                 colunas_numericas=[c for c in df_tab_barras.columns if c != "data"],
                                 casas=0),
                use_container_width=True, hide_index=True,
            )
    else:
        st.info("Sem dados para os filtros selecionados.")

    st.markdown("---")
    st.subheader("📊 Percentual do público de acordo com origem da obra por ano")
    metrica_comp = st.radio(
        "Métrica", options=["Público", "Sessões"], index=0,
        horizontal=True, key="metrica_composicao",
    )
    fig_100 = grafico_barras_100_origem_ano(where, metrica_comp)
    if fig_100 is not None:
        st.altair_chart(fig_100, use_container_width=True)
        with st.expander("Ver tabela detalhada"):
            expr_metrica = "PUBLICO" if metrica_comp == "Público" else "1"
            sql_comp = f"""
                SELECT
                    EXTRACT(YEAR FROM DATA_EXIBICAO) AS ano,
                    ORIGEM_OBRA AS origem,
                    SUM({expr_metrica}) AS valor
                FROM bilheteria
                WHERE {where}
                  AND ORIGEM_OBRA IN ({_lista_sql(ORIGENS_ESPERADAS)})
                GROUP BY EXTRACT(YEAR FROM DATA_EXIBICAO), ORIGEM_OBRA
                ORDER BY 1, 2
            """
            df_comp = query(sql_comp)
            if not df_comp.empty:
                df_comp["total_ano"] = df_comp.groupby("ano")["valor"].transform("sum")
                df_comp["pct_num"] = (
                    df_comp["valor"] / df_comp["total_ano"].replace(0, pd.NA) * 100
                )
                df_comp["ano"] = df_comp["ano"].astype(int)
                df_comp_fmt = df_comp.copy()
                df_comp_fmt["valor"] = df_comp_fmt["valor"].apply(fmt_br)
                df_comp_fmt["pct"] = df_comp_fmt["pct_num"].apply(lambda v: fmt_br_pct(v, 1))
                st.dataframe(
                    df_comp_fmt[["ano", "origem", "valor", "pct", "pct_num"]],
                    use_container_width=True, hide_index=True,
                    column_config={
                        "ano": "Ano",
                        "origem": "Origem",
                        "valor": st.column_config.TextColumn(
                            metrica_comp, help="Valor absoluto (formatado pt-BR)"
                        ),
                        "pct": st.column_config.TextColumn(
                            "% do ano", help="Percentual dentro do ano (formatado pt-BR)"
                        ),
                        "pct_num": st.column_config.NumberColumn(
                            "% do ano (numérico)", format="%.1f%%",
                            help="Percentual como número — permite Statistics do Streamlit."
                        ),
                    },
                )
    else:
        st.info("Sem dados para os filtros selecionados.")

    st.markdown("---")
    st.subheader("🕒 Público ou sessões por faixa de horário")
    df_origem_periodo = por_origem_e_periodo(where)
    if not df_origem_periodo.empty:
        metrica_p = st.radio(
            "Métrica", options=["publico", "sessoes"],
            format_func=lambda x: "Público" if x == "publico" else "Sessões",
            horizontal=True, key="metrica_periodo",
        )
        col_nac, col_est = st.columns(2)
        with col_nac:
            st.markdown("#### 🇧🇷 Nacional")
            fig_nac = grafico_donut_por_origem(df_origem_periodo, "Nacional", metrica_p)
            if fig_nac is not None:
                st.altair_chart(fig_nac, use_container_width=True)
                df_tab_nac = (
                    df_origem_periodo[df_origem_periodo["origem"] == "Nacional"]
                    .drop(columns=["origem"])
                    .sort_values("periodo", key=lambda s: s.map({p: i for i, p in enumerate(ORDEM_PERIODO)}))
                )
                df_tab_nac = traduz_periodo_df(df_tab_nac)
                st.dataframe(
                    df_para_exibicao(df_tab_nac, colunas_numericas=["publico", "sessoes"]),
                    use_container_width=True, hide_index=True,
                    column_config={
                        "periodo": "Faixa de horário",
                        "publico": st.column_config.TextColumn("Público"),
                        "sessoes": st.column_config.TextColumn("Sessões"),
                    },
                )
            else:
                st.info("Sem dados de Nacional para os filtros atuais.")
        with col_est:
            st.markdown("#### 🌍 Estrangeira")
            fig_est = grafico_donut_por_origem(df_origem_periodo, "Estrangeira", metrica_p)
            if fig_est is not None:
                st.altair_chart(fig_est, use_container_width=True)
                df_tab_est = (
                    df_origem_periodo[df_origem_periodo["origem"] == "Estrangeira"]
                    .drop(columns=["origem"])
                    .sort_values("periodo", key=lambda s: s.map({p: i for i, p in enumerate(ORDEM_PERIODO)}))
                )
                df_tab_est = traduz_periodo_df(df_tab_est)
                st.dataframe(
                    df_para_exibicao(df_tab_est, colunas_numericas=["publico", "sessoes"]),
                    use_container_width=True, hide_index=True,
                    column_config={
                        "periodo": "Faixa de horário",
                        "publico": st.column_config.TextColumn("Público"),
                        "sessoes": st.column_config.TextColumn("Sessões"),
                    },
                )
            else:
                st.info("Sem dados de Estrangeira para os filtros atuais.")
    else:
        st.info("Sem dados para os filtros selecionados.")

    st.markdown("---")
    st.subheader("📅 Público por dia da semana empilhado por hora da sessão")
    df_dia_hora = por_dia_semana_por_hora(where)
    if not df_dia_hora.empty:
        metrica_d = st.radio(
            "Métrica", options=["publico", "sessoes"],
            format_func=lambda x: "Público" if x == "publico" else "Sessões",
            horizontal=True, key="metrica_dia",
        )
        df_sem_hora = query(f"""
            SELECT COUNT(*) AS n FROM bilheteria
            WHERE {where} AND HORA_SESSAO IS NULL
        """)
        n_sem_hora = int(df_sem_hora.iloc[0]["n"]) if not df_sem_hora.empty else 0
        if n_sem_hora > 0:
            st.caption(f"⚠️ {fmt_br(n_sem_hora)} sessões sem hora válida não aparecem "
                       f"no gráfico (HORA_SESSAO nula).")
        col_d1, col_d2 = st.columns([2, 1])
        with col_d1:
            st.altair_chart(grafico_barras_dia_por_hora(df_dia_hora, metrica_d),
                            use_container_width=True)
        with col_d2:
            df_resumo = df_dia_hora.groupby("dia", as_index=False)[["publico", "sessoes"]].sum()
            ordem_dias = ["Seg.", "Ter.", "Qua.", "Qui.", "Sex.", "Sáb.", "Dom."]
            df_resumo["_ord"] = df_resumo["dia"].apply(lambda d: ordem_dias.index(d) if d in ordem_dias else 99)
            df_resumo = df_resumo.sort_values("_ord").drop(columns="_ord")
            st.dataframe(
                df_para_exibicao(df_resumo, colunas_numericas=["publico", "sessoes"]),
                use_container_width=True, hide_index=True,
                column_config={
                    "dia": "Dia",
                    "publico": st.column_config.TextColumn("Público"),
                    "sessoes": st.column_config.TextColumn("Sessões"),
                },
            )
        with st.expander("Ver tabela detalhada"):
            df_tab_dia = df_dia_hora.copy()
            df_tab_dia["hora"] = df_tab_dia["hora"].apply(lambda h: f"{int(h):02d}h")
            df_tab_dia = df_tab_dia.drop(columns=["dia_num"])
            st.dataframe(
                df_para_exibicao(df_tab_dia, colunas_numericas=["publico", "sessoes"]),
                use_container_width=True, hide_index=True,
            )
    else:
        st.info("Sem dados para os filtros selecionados.")

    st.markdown("---")
    st.subheader("📅 Percentual do público por faixa de horário e dia da semana")
    df_dia_origem_periodo = por_dia_semana_origem_periodo(where)
    if not df_dia_origem_periodo.empty:
        col_m1, col_m2 = st.columns(2)
        with col_m1:
            metrica_dp = st.radio(
                "Métrica", options=["publico", "sessoes"],
                format_func=lambda x: "Público" if x == "publico" else "Sessões",
                horizontal=True, key="metrica_dia_periodo",
            )
        with col_m2:
            periodo_dp = st.radio(
                "Faixa de horário", options=ORDEM_PERIODO,
                format_func=lambda p: ROTULO_PERIODO.get(p, p),
                index=2, horizontal=True, key="periodo_dia_share",
            )
        fig_share = grafico_barras_share_dia_por_periodo(
            df_dia_origem_periodo, periodo_dp, metrica_dp
        )
        if fig_share is not None:
            st.altair_chart(fig_share, use_container_width=True)
        else:
            st.info("Sem dados para o período selecionado.")
        with st.expander("Ver tabela detalhada"):
            df_tab_share = (
                df_dia_origem_periodo[df_dia_origem_periodo["periodo"] == periodo_dp]
                .drop(columns=["dia_num", "periodo"]).copy()
            )
            st.dataframe(
                df_para_exibicao(df_tab_share, colunas_numericas=["publico", "sessoes"]),
                use_container_width=True, hide_index=True,
            )
    else:
        st.info("Sem dados para os filtros selecionados.")

    st.markdown("---")
    st.subheader("🏆 Top filmes")
    df_top_filmes = top_filmes(where, 15)
    if not df_top_filmes.empty:
        df_top_filmes_fmt = df_top_filmes.copy()
        df_top_filmes_fmt["dt_ini"] = df_top_filmes_fmt["dt_ini"].apply(fmt_br_data)
        df_top_filmes_fmt["dt_fim"] = df_top_filmes_fmt["dt_fim"].apply(fmt_br_data)
        st.dataframe(
            df_para_exibicao(df_top_filmes_fmt, colunas_numericas=["publico", "sessoes"]),
            use_container_width=True, hide_index=True,
            column_config={
                "posicao": "Posição",
                "titulo": "Título",
                "origem": "Origem (principal)",
                "publico": st.column_config.TextColumn("Público"),
                "sessoes": st.column_config.TextColumn("Sessões"),
                "dt_ini": "Início da exibição",
                "dt_fim": "Fim da exibição",
            },
        )

    st.markdown("---")
    st.subheader("🏢 Top exibidores")
    df_top_exibidores = top_exibidores(where, 15)
    if not df_top_exibidores.empty:
        st.dataframe(
            df_para_exibicao(
                df_top_exibidores,
                colunas_numericas=["publico", "salas", "sessoes",
                                   "n_complexos", "n_estados", "n_municipios"],
            ),
            use_container_width=True, hide_index=True,
            column_config={
                "posicao": "Posição",
                "exibidor": "Exibidor",
                "publico": st.column_config.TextColumn("Público"),
                "salas": st.column_config.TextColumn("Salas"),
                "sessoes": st.column_config.TextColumn("Sessões"),
                "n_complexos": st.column_config.TextColumn("Complexos"),
                "n_estados": st.column_config.TextColumn("Estados"),
                "n_municipios": st.column_config.TextColumn("Municípios"),
            },
        )

    st.markdown("---")
    st.subheader("🔎 Detalhe dos registros")
    limite = st.slider("Máximo de linhas", 100, 1000, 200, step=100)
    df_detalhe = tabela_detalhe(where, limite)
    df_detalhe_fmt = df_para_exibicao(df_detalhe, casas=0)
    st.dataframe(df_detalhe_fmt, use_container_width=True, hide_index=True)
    st.caption(f"Exibindo até {fmt_br(limite)} linhas · {len(df_detalhe.columns)} colunas.")


if __name__ == "__main__":
    main()
