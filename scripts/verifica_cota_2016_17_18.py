"""
Dashboard Streamlit — Aferição da Cota de Tela 2016–2018
Decretos: 8.620/2015 (2016), 8.944/2016 (2017), 9.256/2017 (2018)
Norma operacional: IN nº 88/2010 (alterada pela IN nº 117/2014)
Base: bilheteria.parquet (DuckDB)

Regime comum (R1 — dias por complexo):
- Art. 1º: dias mínimos + títulos mínimos por porte (Anexo idêntico nos 3 anos).
- Art. 2º: cota suplementar = soma dos excedentes diários de salas.
- IN 88/2010 (arts. 9º-10): dia completo / meio dia, sessões após 13h.
- IN 117/2014: aferição a partir das 13h.

Anexo (idêntico em 2016, 2017 e 2018):
  1→28, 2→70, 3→126, 4→196, 5→280, 6→378, 7→441, 8→480, 9→531,
  10→560, 11→583, 12→600, 13→624, 14→644, 15→675, 16→704,
  17→731, 18→756, 19→779, 20→800; >20 → 800 + 7*(n-20).

Notas desta versão:
- Caminho do Parquet resolvido com fallback.
- Sem TEMP_DIR: o DuckDB usa o diretório temporário padrão.
- memory_limit = 2GB; threads = 2; preserve_insertion_order = false.
- Opção A: `base` materializa apenas as colunas usadas.
- Datas como 'YYYY-MM-DD' convertidas com ?::DATE.
- A aferição é cacheada por (ano, data_ini, data_fim) via @st.cache_data.
- set_page_config dentro de main() para permitir importação por app.py.
- Scatter com linha de referência y = x.
"""

from pathlib import Path

import altair as alt
import duckdb
import pandas as pd
import streamlit as st

# --- Resolução do caminho do Parquet ---
def _resolver_parquet() -> Path:
    raiz = Path(__file__).resolve().parent.parent.parent
    candidatos = [
        raiz / "data" / "bilheteria.parquet",
        Path.cwd() / "data" / "bilheteria.parquet",
        Path.cwd().parent / "data" / "bilheteria.parquet",
    ]
    for c in candidatos:
        if c.exists():
            return c
    return candidatos[0]


PARQUET_PADRAO = _resolver_parquet()

CORES_SITUACAO = {
    "Cumprida": "#2E7D32",
    "Não cumprida": "#C62828",
}

# --- Configuração por ano (mesmo Anexo, decretos distintos) ---
CONFIG_ANOS = {
    2016: {"decreto": "8.620/2015"},
    2017: {"decreto": "8.944/2016"},
    2018: {"decreto": "9.256/2017"},
}

ANEXO_COMUM = [
    (1, 28, 3, 1), (2, 70, 4, 2), (3, 126, 5, 2),
    (4, 196, 6, 2), (5, 280, 8, 2), (6, 378, 9, 2),
    (7, 441, 11, 2.5), (8, 480, 12, 2.5), (9, 531, 14, 3),
    (10, 560, 15, 3), (11, 583, 17, 3), (12, 600, 18, 4),
    (13, 624, 20, 4), (14, 644, 21, 4), (15, 675, 23, 5),
    (16, 704, 24, 5), (17, 731, 24, 5), (18, 756, 24, 6),
    (19, 779, 24, 6), (20, 800, 24, 6),
]


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


def df_para_exibicao(df: pd.DataFrame, colunas_numericas=None, casas: int = 0) -> pd.DataFrame:
    if colunas_numericas is None:
        colunas_numericas = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
    out = df.copy()
    for c in colunas_numericas:
        if c in out.columns:
            out[c] = out[c].apply(lambda v: fmt_br(v, casas))
    return out


# --- Conexão / query ---
@st.cache_resource
def get_conexao():
    con = duckdb.connect()
    con.execute("SET memory_limit = '2GB';")
    con.execute("SET threads = 2;")
    con.execute("SET preserve_insertion_order = false;")
    return con


def query(sql: str, params=None) -> pd.DataFrame:
    con = get_conexao()
    if params is None:
        return con.sql(sql).df()
    return con.execute(sql, params).df()


# --- Materialização da base (Opção A) ---
def materializa_base(data_ini: str, data_fim: str, ano_ref: int) -> None:
    con = get_conexao()
    con.execute("""
        CREATE OR REPLACE TABLE base AS
        WITH dedup AS (
            SELECT
                DATA_EXIBICAO, SESSAO, REGISTRO_SALA, CPB_ROE,
                REGISTRO_COMPLEXO, REGISTRO_GRUPO_EXIBIDOR,
                UF_SALA_COMPLEXO, MUNICIPIO_SALA_COMPLEXO,
                PAIS_OBRA, HORA_SESSAO,
                ROW_NUMBER() OVER (
                    PARTITION BY DATA_EXIBICAO, SESSAO, REGISTRO_SALA, CPB_ROE
                    ORDER BY arquivo_origem
                ) AS rn
            FROM read_parquet(?)
            WHERE ano = ?
              AND DATA_EXIBICAO BETWEEN ?::DATE AND ?::DATE
        ),
        limpa AS (
            SELECT *,
                CASE
                    WHEN UPPER(TRIM(COALESCE(PAIS_OBRA,''))) LIKE '%BRASIL%' THEN 'Nacional'
                    WHEN UPPER(TRIM(COALESCE(CPB_ROE,''))) LIKE 'B%'        THEN 'Nacional'
                    WHEN COALESCE(TRIM(PAIS_OBRA),'') IN ('','NULL')        THEN 'Não informado'
                    ELSE 'Estrangeira'
                END AS origem_corrigida
            FROM dedup WHERE rn = 1
        )
        SELECT
            DATA_EXIBICAO, SESSAO, REGISTRO_SALA, CPB_ROE,
            REGISTRO_COMPLEXO, REGISTRO_GRUPO_EXIBIDOR,
            UF_SALA_COMPLEXO, MUNICIPIO_SALA_COMPLEXO,
            HORA_SESSAO, origem_corrigida
        FROM limpa;
    """, [PARQUET_PADRAO.as_posix(), ano_ref, data_ini, data_fim])


# --- Materialização da aferição (R1, idempotente) ---
def calcula_afericao_r1(data_ini: str, data_fim: str, hora_corte: int = 13) -> None:
    con = get_conexao()
    ano_ref = int(data_ini[:4])

    materializa_base(data_ini, data_fim, ano_ref)

    n_base = con.execute("SELECT COUNT(*) FROM base").fetchone()[0]
    if n_base == 0:
        raise RuntimeError(
            f"Sem registros em `base` para {data_ini} a {data_fim} (ano={ano_ref})."
        )

    con.execute("""
        CREATE OR REPLACE TABLE anexo_r1 (
            salas INTEGER PRIMARY KEY,
            dias_minimos DOUBLE,
            titulos_minimos INTEGER,
            max_salas_mesmo_titulo DOUBLE
        );
    """)
    con.executemany("INSERT INTO anexo_r1 VALUES (?,?,?,?)", ANEXO_COMUM)

    con.execute("""
        CREATE OR REPLACE TABLE complexo_porte AS
        WITH salas AS (
            SELECT REGISTRO_COMPLEXO, COUNT(DISTINCT REGISTRO_SALA) AS n_salas
            FROM base GROUP BY REGISTRO_COMPLEXO
        )
        SELECT s.REGISTRO_COMPLEXO, s.n_salas,
               CASE WHEN s.n_salas > 20 THEN 800 + 7*(s.n_salas-20)
                    ELSE a.dias_minimos END AS dias_minimos,
               COALESCE(a.titulos_minimos, 24) AS titulos_minimos,
               CASE WHEN s.n_salas > 20 THEN 0.30*s.n_salas
                    ELSE a.max_salas_mesmo_titulo END AS max_salas_mesmo_titulo
        FROM salas s
        LEFT JOIN anexo_r1 a ON a.salas = LEAST(s.n_salas, 20);
    """)

    con.execute("""
        CREATE OR REPLACE TABLE excedente_diario AS
        WITH salas_por_titulo AS (
            SELECT REGISTRO_COMPLEXO, DATA_EXIBICAO, CPB_ROE,
                   COUNT(DISTINCT REGISTRO_SALA) AS salas_titulo
            FROM base WHERE HORA_SESSAO >= ?
            GROUP BY REGISTRO_COMPLEXO, DATA_EXIBICAO, CPB_ROE
        )
        SELECT s.REGISTRO_COMPLEXO, s.DATA_EXIBICAO, s.CPB_ROE, s.salas_titulo,
               GREATEST(s.salas_titulo - p.max_salas_mesmo_titulo, 0) AS excedente_salas
        FROM salas_por_titulo s JOIN complexo_porte p USING (REGISTRO_COMPLEXO);
    """, [hora_corte])

    con.execute("""
        CREATE OR REPLACE TABLE cota_suplementar AS
        SELECT REGISTRO_COMPLEXO, SUM(excedente_salas) AS dias_suplementares
        FROM excedente_diario GROUP BY REGISTRO_COMPLEXO;
    """)

    con.execute("""
        CREATE OR REPLACE TABLE dia_complexo AS
        SELECT REGISTRO_COMPLEXO, DATA_EXIBICAO,
               COUNT(*) FILTER (WHERE origem_corrigida='Nacional' AND HORA_SESSAO >= ?) AS nac,
               COUNT(*) FILTER (WHERE HORA_SESSAO >= ?) AS tot
        FROM base GROUP BY REGISTRO_COMPLEXO, DATA_EXIBICAO;
    """, [hora_corte, hora_corte])

    con.execute("""
        CREATE OR REPLACE TABLE dias_equivalentes AS
        SELECT REGISTRO_COMPLEXO,
               SUM(CASE
                   WHEN tot > 0 AND nac = tot      THEN 1.0
                   WHEN tot > 0 AND nac * 2 >= tot THEN 0.5
                   ELSE 0.0
               END) AS dias_cumpridos
        FROM dia_complexo GROUP BY REGISTRO_COMPLEXO;
    """)

    con.execute("""
        CREATE OR REPLACE TABLE titulos_nacionais AS
        SELECT REGISTRO_COMPLEXO, COUNT(DISTINCT CPB_ROE) AS titulos_nac
        FROM base
        WHERE origem_corrigida='Nacional' AND HORA_SESSAO >= ?
        GROUP BY REGISTRO_COMPLEXO;
    """, [hora_corte])

    con.execute("""
        CREATE OR REPLACE TABLE afericao AS
        WITH local AS (
            SELECT REGISTRO_COMPLEXO,
                   ANY_VALUE(UF_SALA_COMPLEXO) AS UF_SALA_COMPLEXO,
                   ANY_VALUE(MUNICIPIO_SALA_COMPLEXO) AS MUNICIPIO_SALA_COMPLEXO
            FROM base GROUP BY REGISTRO_COMPLEXO
        )
        SELECT
            p.REGISTRO_COMPLEXO,
            l.UF_SALA_COMPLEXO, l.MUNICIPIO_SALA_COMPLEXO,
            p.n_salas, p.dias_minimos, p.titulos_minimos,
            COALESCE(d.dias_cumpridos, 0) AS dias_cumpridos,
            COALESCE(s.dias_suplementares, 0) AS dias_suplementares,
            p.dias_minimos + COALESCE(s.dias_suplementares, 0) AS meta_dias,
            COALESCE(d.dias_cumpridos, 0) >= p.dias_minimos + COALESCE(s.dias_suplementares, 0) AS cota_dias_cumprida,
            COALESCE(t.titulos_nac, 0) >= p.titulos_minimos AS diversidade_cumprida,
            COALESCE(t.titulos_nac, 0) AS titulos_nac,
            COALESCE(d.dias_cumpridos, 0) - (p.dias_minimos + COALESCE(s.dias_suplementares, 0)) AS deficit_dias,
            CASE
                WHEN COALESCE(d.dias_cumpridos, 0) >= p.dias_minimos + COALESCE(s.dias_suplementares, 0)
                 AND COALESCE(t.titulos_nac, 0) >= p.titulos_minimos
                THEN 'Cumprida' ELSE 'Não cumprida'
            END AS situacao
        FROM complexo_porte p
        LEFT JOIN local l USING (REGISTRO_COMPLEXO)
        LEFT JOIN dias_equivalentes d USING (REGISTRO_COMPLEXO)
        LEFT JOIN cota_suplementar s USING (REGISTRO_COMPLEXO)
        LEFT JOIN titulos_nacionais t USING (REGISTRO_COMPLEXO);
    """)


@st.cache_data(show_spinner="Calculando aferição...")
def afericao_r1(ano: int, data_ini: str, data_fim: str) -> pd.DataFrame:
    calcula_afericao_r1(data_ini, data_fim)
    return get_conexao().sql("SELECT * FROM afericao").df()


# --- Listas de filtros em cascata ---
@st.cache_data(show_spinner=False)
def carrega_ufs(_dummy: int = 0):
    return query(f"""
        SELECT DISTINCT UF_SALA_COMPLEXO AS uf FROM read_parquet('{PARQUET_PADRAO.as_posix()}')
        WHERE UF_SALA_COMPLEXO IS NOT NULL ORDER BY uf
    """)["uf"].tolist()


@st.cache_data(show_spinner=False)
def carrega_municipios(ufs_tuple: tuple):
    if not ufs_tuple:
        return []
    lista = ",".join(f"'{u}'" for u in ufs_tuple)
    return query(f"""
        SELECT DISTINCT MUNICIPIO_SALA_COMPLEXO AS mun
        FROM read_parquet('{PARQUET_PADRAO.as_posix()}')
        WHERE UF_SALA_COMPLEXO IN ({lista}) ORDER BY mun
    """)["mun"].tolist()


@st.cache_data(show_spinner=False)
def carrega_complexos(municipios_tuple: tuple = ()):
    filtro = (
        f"AND MUNICIPIO_SALA_COMPLEXO IN ({','.join(repr(m) for m in municipios_tuple)})"
        if municipios_tuple else ""
    )
    df = query(f"""
        SELECT DISTINCT REGISTRO_COMPLEXO, MUNICIPIO_SALA_COMPLEXO, UF_SALA_COMPLEXO
        FROM read_parquet('{PARQUET_PADRAO.as_posix()}')
        WHERE REGISTRO_COMPLEXO IS NOT NULL {filtro}
        ORDER BY UF_SALA_COMPLEXO, MUNICIPIO_SALA_COMPLEXO
    """)
    if df.empty:
        return df.assign(rotulo=[])
    df["rotulo"] = df.apply(
        lambda r: f"{int(r['REGISTRO_COMPLEXO'])} — {r['MUNICIPIO_SALA_COMPLEXO']}/{r['UF_SALA_COMPLEXO']}",
        axis=1,
    )
    return df[["REGISTRO_COMPLEXO", "rotulo"]]


# --- Sidebar ---
def render_sidebar():
    st.sidebar.title("🎬 Filtros — Cota 2016–2018")

    ano = st.sidebar.selectbox(
        "Ano de referência", sorted(CONFIG_ANOS.keys()), index=2,
    )
    decreto = CONFIG_ANOS[ano]["decreto"]
    st.sidebar.caption(f"Decreto vigente em {ano}: **{decreto}**")

    st.sidebar.subheader("Período")
    col1, col2 = st.sidebar.columns(2)
    data_ini = col1.date_input(
        "De", value=pd.Timestamp(f"{ano}-01-01").date(),
        min_value=pd.Timestamp(f"{ano}-01-01").date(),
        max_value=pd.Timestamp(f"{ano}-12-31").date(),
    )
    data_fim = col2.date_input(
        "Até", value=pd.Timestamp(f"{ano}-12-31").date(),
        min_value=pd.Timestamp(f"{ano}-01-01").date(),
        max_value=pd.Timestamp(f"{ano}-12-31").date(),
    )
    st.sidebar.caption(
        "⚠️ A cota é **anual**. Alterar o período aqui filtra as sessões "
        "consideradas, mas o Anexo pressupõe o ano inteiro. "
        "Use os filtros de UF/complexo para recortes válidos."
    )

    st.sidebar.subheader("Localização")
    ufs = st.sidebar.multiselect("UF", options=carrega_ufs(), default=[])
    municipios = st.sidebar.multiselect(
        "Município", options=carrega_municipios(tuple(ufs)), default=[],
    ) if ufs else []

    complexos_sel = []
    df_complexos = carrega_complexos(tuple(municipios) if municipios else ())
    if not df_complexos.empty:
        opcoes = dict(zip(df_complexos["rotulo"], df_complexos["REGISTRO_COMPLEXO"]))
        rotulos = st.sidebar.multiselect(
            "Complexo", options=list(opcoes.keys()), default=[],
            help="Deixe em branco para considerar todos os complexos.",
        )
        complexos_sel = [opcoes[r] for r in rotulos]

    st.sidebar.subheader("Auditoria")
    somente_nao_conformes = st.sidebar.checkbox(
        "Somente complexos em não conformidade", value=False,
    )
    porte_min = st.sidebar.slider(
        "Porte mínimo (nº de salas)", min_value=1, max_value=30, value=1,
    )

    return {
        "ano": ano, "data_ini": data_ini, "data_fim": data_fim,
        "ufs": ufs, "municipios": municipios, "complexos": complexos_sel,
        "somente_nao_conformes": somente_nao_conformes,
        "porte_min": porte_min,
    }


# --- Gráficos Altair ---
def grafico_scatter_afericao(df: pd.DataFrame):
    df_plot = df.copy()
    df_plot["deficit_fmt"] = df_plot["deficit_dias"].apply(lambda v: fmt_br(v, 1))
    df_plot["cumprido_fmt"] = df_plot["dias_cumpridos"].apply(lambda v: fmt_br(v, 1))
    df_plot["meta_fmt"] = df_plot["meta_dias"].apply(lambda v: fmt_br(v, 1))

    pontos = (
        alt.Chart(df_plot)
        .mark_circle(size=90, opacity=0.75, stroke="#000", strokeWidth=0.3)
        .encode(
            x=alt.X("meta_dias:Q", title="Meta de dias (Anexo + suplementar)"),
            y=alt.Y("dias_cumpridos:Q", title="Dias cumpridos (equivalentes)"),
            color=alt.Color(
                "situacao:N", title="Situação",
                scale=alt.Scale(domain=list(CORES_SITUACAO.keys()),
                                range=list(CORES_SITUACAO.values())),
            ),
            size=alt.Size("n_salas:Q", title="Salas", scale=alt.Scale(range=[30, 300])),
            tooltip=[
                alt.Tooltip("REGISTRO_COMPLEXO:N", title="Complexo"),
                alt.Tooltip("n_salas:Q", title="Salas"),
                alt.Tooltip("meta_fmt:N", title="Meta (dias)"),
                alt.Tooltip("cumprido_fmt:N", title="Cumprido (dias)"),
                alt.Tooltip("deficit_fmt:N", title="Déficit (dias)"),
                alt.Tooltip("situacao:N", title="Situação"),
            ],
        )
    )
    max_val = float(max(df_plot["meta_dias"].max(), df_plot["dias_cumpridos"].max()))
    diagonal = (
        alt.Chart(pd.DataFrame({"x": [0, max_val], "y": [0, max_val]}))
        .mark_line(color="#9E9E9E", strokeDash=[4, 4])
        .encode(x="x:Q", y="y:Q")
    )
    return (pontos + diagonal).properties(height=420)


def grafico_top_deficit(df: pd.DataFrame, top_n: int = 20):
    df_plot = (
        df[df["deficit_dias"] < 0]
        .assign(deficit_abs=lambda d: -d["deficit_dias"])
        .sort_values("deficit_abs", ascending=False)
        .head(top_n).copy()
    )
    if df_plot.empty:
        return None
    df_plot["rotulo"] = (
        df_plot["REGISTRO_COMPLEXO"].astype(str)
        + " (" + df_plot["n_salas"].astype(str) + " salas)"
    )
    df_plot["deficit_fmt"] = df_plot["deficit_abs"].apply(lambda v: fmt_br(v, 1))
    return (
        alt.Chart(df_plot)
        .mark_bar(color=CORES_SITUACAO["Não cumprida"])
        .encode(
            y=alt.Y("rotulo:N", sort="-x", title="Complexo (salas)"),
            x=alt.X("deficit_abs:Q", title="Déficit de dias"),
            tooltip=[
                alt.Tooltip("REGISTRO_COMPLEXO:N", title="Complexo"),
                alt.Tooltip("n_salas:Q", title="Salas"),
                alt.Tooltip("meta_dias:Q", title="Meta", format=".1f"),
                alt.Tooltip("dias_cumpridos:Q", title="Cumprido", format=".1f"),
                alt.Tooltip("deficit_fmt:N", title="Déficit"),
            ],
        ).properties(height=max(300, 20 * len(df_plot)))
    )


def grafico_por_porte(df: pd.DataFrame):
    df_plot = df.copy()
    df_plot["faixa"] = pd.cut(
        df_plot["n_salas"],
        bins=[0, 1, 2, 4, 9, 19, 100],
        labels=["1", "2", "3–4", "5–9", "10–19", "20+"],
    )
    agg = (
        df_plot.groupby(["faixa", "situacao"], observed=True)
        .size().reset_index(name="complexos")
    )
    return (
        alt.Chart(agg)
        .mark_bar(stroke="#000", strokeWidth=0.4)
        .encode(
            x=alt.X("faixa:N", title="Faixa de salas",
                    sort=["1", "2", "3–4", "5–9", "10–19", "20+"]),
            y=alt.Y("complexos:Q", title="Complexos", stack="zero"),
            color=alt.Color(
                "situacao:N", title="Situação",
                scale=alt.Scale(domain=list(CORES_SITUACAO.keys()),
                                range=list(CORES_SITUACAO.values())),
            ),
            tooltip=["faixa:N", "situacao:N", "complexos:Q"],
        ).properties(height=320)
    )


def grafico_top_suplementar(excedente: pd.DataFrame, top_n: int = 15):
    if excedente.empty:
        return None
    agg = (
        excedente.groupby("REGISTRO_COMPLEXO", as_index=False)["excedente_salas"]
        .sum().sort_values("excedente_salas", ascending=False).head(top_n)
    )
    agg["rotulo"] = agg["REGISTRO_COMPLEXO"].astype(str)
    return (
        alt.Chart(agg)
        .mark_bar(color="#6A1B9A")
        .encode(
            y=alt.Y("rotulo:N", sort="-x", title="Complexo"),
            x=alt.X("excedente_salas:Q", title="Dias suplementares acumulados"),
            tooltip=["rotulo:N", alt.Tooltip("excedente_salas:Q", format=".1f")],
        ).properties(height=max(300, 20 * len(agg)))
    )


# --- Main ---
def main():
    st.set_page_config(
        page_title="Cota de Tela 2016–2018",
        page_icon="🎬",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    filtros = render_sidebar()
    ano = filtros["ano"]
    decreto = CONFIG_ANOS[ano]["decreto"]

    st.title(f"🎬 Aferição da Cota de Tela {ano} — Decreto nº {decreto}")
    st.caption(
        f"Cálculo da obrigatoriedade de exibição de obras brasileiras em {ano}, "
        f"conforme Anexo do Decreto {decreto} e IN 88/2010 (alterada pela IN 117/2014). "
        "Métrica em **dias equivalentes**, sessões a partir das 13h. "
        "Anexo idêntico em 2016, 2017 e 2018."
    )

    if not PARQUET_PADRAO.exists():
        st.error(
            f"Parquet não encontrado em `{PARQUET_PADRAO}`.\n\n"
            f"Caminho esperado a partir da raiz do projeto: `data/bilheteria.parquet`.\n"
            f"Execute antes: `python scripts/baixa_arquivos.py` e "
            f"`python scripts/criar_parquet.py`."
        )
        st.stop()

    try:
        df_full = afericao_r1(
            ano,
            filtros["data_ini"].isoformat(),
            filtros["data_fim"].isoformat(),
        )
    except RuntimeError as e:
        st.error(str(e))
        st.stop()

    if df_full.empty:
        st.warning("A aferição não retornou complexos. Verifique o Parquet e o período.")
        st.stop()

    df = df_full.copy()
    if filtros["ufs"]:
        df = df[df["UF_SALA_COMPLEXO"].isin(filtros["ufs"])]
    if filtros["complexos"]:
        df = df[df["REGISTRO_COMPLEXO"].isin(filtros["complexos"])]
    df = df[df["n_salas"] >= filtros["porte_min"]]
    if filtros["somente_nao_conformes"]:
        df = df[df["situacao"] == "Não cumprida"]

    if df.empty:
        st.warning("Nenhum complexo atende aos filtros selecionados.")
        st.stop()

    n = len(df)
    cota_ok = int(df["cota_dias_cumprida"].sum())
    div_ok = int(df["diversidade_cumprida"].sum())
    dias_tot = df["dias_cumpridos"].sum()
    suplem_tot = df["dias_suplementares"].sum()

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Complexos avaliados", fmt_br(n))
    c2.metric("Cota cumprida", f"{cota_ok} ({fmt_br_pct(100 * cota_ok / n if n else 0)})")
    c3.metric("Diversidade cumprida", f"{div_ok} ({fmt_br_pct(100 * div_ok / n if n else 0)})")
    c4.metric("Dias equivalentes (soma)", fmt_br(dias_tot, 1))
    c5.metric("Dias suplementares (soma)", fmt_br(suplem_tot, 1))

    st.markdown("---")
    st.subheader("📌 Aferição por complexo — dias cumpridos × meta")
    st.caption(
        "Cada ponto é um complexo. Acima da diagonal = cota cumprida. "
        "Tamanho do ponto = nº de salas. Meta = dias do Anexo + dias suplementares."
    )
    st.altair_chart(grafico_scatter_afericao(df), use_container_width=True)

    st.markdown("---")
    col_a, col_b = st.columns(2)
    with col_a:
        st.subheader("📉 Maiores déficits de dias")
        fig_def = grafico_top_deficit(df)
        if fig_def is not None:
            st.altair_chart(fig_def, use_container_width=True)
        else:
            st.success("Nenhum complexo com déficit de dias nos filtros atuais.")
    with col_b:
        st.subheader("📊 Situação por faixa de salas")
        st.altair_chart(grafico_por_porte(df), use_container_width=True)

    st.markdown("---")
    st.subheader("➕ Cota suplementar (art. 2º) — excedente diário de salas")
    ids = ",".join(str(int(c)) for c in df["REGISTRO_COMPLEXO"])
    excedente = query(f"""
        SELECT * FROM excedente_diario
        WHERE excedente_salas > 0
          AND REGISTRO_COMPLEXO IN ({ids})
    """)
    if excedente.empty:
        st.info("Nenhum complexo apresentou excedente de salas com o mesmo título.")
    else:
        col_s1, col_s2 = st.columns([1, 1])
        with col_s1:
            fig_sup = grafico_top_suplementar(excedente)
            if fig_sup is not None:
                st.altair_chart(fig_sup, use_container_width=True)
        with col_s2:
            st.markdown("**Detalhe dos excedentes (top 100)**")
            df_exc = excedente.sort_values("excedente_salas", ascending=False).head(100)
            st.dataframe(
                df_para_exibicao(df_exc,
                                 colunas_numericas=["salas_titulo", "excedente_salas"],
                                 casas=1),
                use_container_width=True, hide_index=True,
            )

    st.markdown("---")
    st.subheader("📋 Aferição por complexo")
    colunas = ["REGISTRO_COMPLEXO", "UF_SALA_COMPLEXO", "MUNICIPIO_SALA_COMPLEXO",
               "n_salas", "dias_minimos", "titulos_minimos",
               "dias_cumpridos", "dias_suplementares", "meta_dias",
               "deficit_dias", "titulos_nac", "situacao"]
    df_tab = df[colunas].sort_values(["situacao", "deficit_dias"])
    st.dataframe(
        df_para_exibicao(
            df_tab,
            colunas_numericas=["dias_minimos", "dias_cumpridos",
                               "dias_suplementares", "meta_dias",
                               "deficit_dias"],
            casas=1,
        ),
        use_container_width=True, hide_index=True,
        column_config={
            "REGISTRO_COMPLEXO": "Complexo",
            "UF_SALA_COMPLEXO": "UF",
            "MUNICIPIO_SALA_COMPLEXO": "Município",
            "n_salas": "Salas",
            "dias_minimos": "Dias mín. (Anexo)",
            "titulos_minimos": "Títulos mín.",
            "dias_cumpridos": "Dias cumpridos",
            "dias_suplementares": "Dias suplem.",
            "meta_dias": "Meta total",
            "deficit_dias": "Déficit",
            "titulos_nac": "Títulos nac.",
            "situacao": "Situação",
        },
    )

    st.download_button(
        f"⬇️ Baixar aferição {ano} (CSV)",
        df_tab.to_csv(index=False).encode("utf-8"),
        file_name=f"afericao_cota_{ano}.csv",
        mime="text/csv",
    )

    st.markdown("---")
    st.subheader("🔎 Detalhe dia a dia por complexo")
    complexo_sel = st.selectbox(
        "Complexo",
        options=df["REGISTRO_COMPLEXO"].astype(int).tolist(),
        format_func=lambda c: (
            f"{c} — "
            f"{df.loc[df['REGISTRO_COMPLEXO'] == c, 'MUNICIPIO_SALA_COMPLEXO'].iloc[0]}/"
            f"{df.loc[df['REGISTRO_COMPLEXO'] == c, 'UF_SALA_COMPLEXO'].iloc[0]}"
        ),
    )
    df_dia = query("""
        SELECT DATA_EXIBICAO, nac, tot,
               CASE WHEN tot > 0 AND nac = tot      THEN 1.0
                    WHEN tot > 0 AND nac * 2 >= tot THEN 0.5
                    ELSE 0.0 END AS dias_eq
        FROM dia_complexo
        WHERE REGISTRO_COMPLEXO = ?
        ORDER BY DATA_EXIBICAO
    """, [complexo_sel])
    if df_dia.empty:
        st.info("Sem sessões registradas para o complexo selecionado.")
    else:
        st.caption(
            f"{len(df_dia)} dias com sessões · "
            f"soma de dias equivalentes: {fmt_br(df_dia['dias_eq'].sum(), 1)}"
        )
        st.dataframe(
            df_para_exibicao(df_dia, colunas_numericas=["dias_eq"], casas=1),
            use_container_width=True, hide_index=True,
        )


if __name__ == "__main__":
    main()