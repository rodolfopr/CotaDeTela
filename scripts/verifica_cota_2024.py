"""
Dashboard Streamlit — Aferição da Cota de Tela 2024 (Decreto nº 12.067/2024)
Norma operacional: IN nº 170/2024 (+ IN nº 172/2025 para incentivos)
Base: bilheteria.parquet (DuckDB)

Mudanças estruturais em relação a 2015–2020:
- Métrica em % de SESSÕES (não mais dias) — Anexo I, por grupo exibidor.
- Diversidade: Anexo II (títulos mínimos por complexo).
- Cota suplementar: Anexo III (proporção diária máxima de sessões de um
  mesmo título; excedente soma à obrigação anual).
- Incentivos (IN 172/2025): sessões após 17h (+0,10) e premiadas após 17h (+0,15).

Notas desta versão:
- Caminho do Parquet resolvido com fallback.
- Sem TEMP_DIR: o DuckDB usa o diretório temporário padrão.
- memory_limit = 2GB; threads = 2; preserve_insertion_order = false.
- Opção A: `base` materializa apenas as colunas usadas.
- Datas como 'YYYY-MM-DD' convertidas com ?::DATE.
- A aferição é cacheada por (data_ini, data_fim) via @st.cache_data.
- set_page_config dentro de main() para permitir importação por app.py.
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
PREMIADOS_CSV = PARQUET_PADRAO.parent / "filmes_premiados.csv"

CORES_SITUACAO = {"Cumprida": "#2E7D32", "Não cumprida": "#C62828"}
HORA_BONUS = 17


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


# --- Anexo I: % mínimo de sessões por grupo exibidor (Decreto 12.067/2024) ---
ANEXO_I_2024 = [
    (1, 1, 7.5), (2, 3, 8.0), (4, 5, 8.5), (6, 7, 9.0),
    (8, 9, 9.5), (10, 11, 10.0), (12, 13, 10.5), (14, 15, 11.0),
    (16, 17, 11.5), (18, 20, 12.0), (21, 30, 12.5), (31, 40, 13.0),
    (41, 50, 13.5), (51, 70, 14.0), (71, 80, 14.5), (81, 100, 15.0),
    (101, 200, 15.5), (201, 10_000, 16.0),
]

# --- Anexo II: títulos mínimos por complexo (Decreto 12.067/2024) ---
ANEXO_II_2024 = {
    1: 3, 2: 4, 3: 5, 4: 6, 5: 8, 6: 9, 7: 11, 8: 12, 9: 14, 10: 15,
    11: 17, 12: 18, 13: 20, 14: 21, 15: 23, "16+": 24,
}

# --- Anexo III: proporção diária máxima de sessões de um mesmo título ---
# 1-2 salas: isento; 3+ salas: 50%
PROPORCAO_MAXIMA_3_MAIS = 0.50


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


def materializa_premiados() -> None:
    con = get_conexao()
    con.execute("CREATE OR REPLACE TABLE filmes_premiados (cpb_roe VARCHAR);")
    if PREMIADOS_CSV.exists():
        df = pd.read_csv(PREMIADOS_CSV, dtype=str)
        if not df.empty and "cpb_roe" in df.columns:
            con.executemany("INSERT INTO filmes_premiados VALUES (?)",
                            [(c,) for c in df["cpb_roe"].dropna().unique()])


# --- Materialização da aferição R3 (% de sessões) ---
def calcula_afericao_r3(data_ini: str, data_fim: str) -> None:
    con = get_conexao()
    ano_ref = int(data_ini[:4])

    materializa_base(data_ini, data_fim, ano_ref)
    materializa_premiados()

    n_base = con.execute("SELECT COUNT(*) FROM base").fetchone()[0]
    if n_base == 0:
        raise RuntimeError(
            f"Sem registros em `base` para {data_ini} a {data_fim} (ano={ano_ref})."
        )

    # 0) Anexo I
    con.execute("""
        CREATE OR REPLACE TABLE anexo_i_2024 (
            faixa_inf INTEGER, faixa_sup INTEGER, pct_minimo DOUBLE
        );
    """)
    con.executemany("INSERT INTO anexo_i_2024 VALUES (?,?,?)", ANEXO_I_2024)

    # 1) Porte do grupo e do complexo
    con.execute("""
        CREATE OR REPLACE TABLE grupo_porte AS
        SELECT REGISTRO_GRUPO_EXIBIDOR,
               COUNT(DISTINCT REGISTRO_SALA) AS n_salas_grupo
        FROM base GROUP BY REGISTRO_GRUPO_EXIBIDOR;
    """)

    con.execute("""
        CREATE OR REPLACE TABLE complexo_porte AS
        WITH salas AS (
            SELECT REGISTRO_COMPLEXO,
                   ANY_VALUE(REGISTRO_GRUPO_EXIBIDOR) AS REGISTRO_GRUPO_EXIBIDOR,
                   COUNT(DISTINCT REGISTRO_SALA) AS n_salas
            FROM base GROUP BY REGISTRO_COMPLEXO
        )
        SELECT s.*, g.n_salas_grupo, a.pct_minimo
        FROM salas s
        JOIN grupo_porte g USING (REGISTRO_GRUPO_EXIBIDOR)
        JOIN anexo_i_2024 a ON g.n_salas_grupo BETWEEN a.faixa_inf AND a.faixa_sup;
    """)

    # 2) Cota suplementar (Anexo III): excedente diário de sessões de um mesmo título
    con.execute("""
        CREATE OR REPLACE TABLE dia_titulo AS
        SELECT REGISTRO_COMPLEXO, DATA_EXIBICAO, CPB_ROE, COUNT(*) AS sessoes_titulo
        FROM base GROUP BY REGISTRO_COMPLEXO, DATA_EXIBICAO, CPB_ROE;
    """)
    con.execute("""
        CREATE OR REPLACE TABLE dia_totais AS
        SELECT REGISTRO_COMPLEXO, DATA_EXIBICAO, COUNT(*) AS sessoes_dia
        FROM base GROUP BY REGISTRO_COMPLEXO, DATA_EXIBICAO;
    """)
    con.execute("""
        CREATE OR REPLACE TABLE excedente_sessoes AS
        SELECT dt.REGISTRO_COMPLEXO, dt.DATA_EXIBICAO, dt.CPB_ROE,
               dt.sessoes_titulo, tot.sessoes_dia, p.n_salas,
               CASE
                   WHEN p.n_salas <= 2 THEN 0.0
                   ELSE GREATEST(dt.sessoes_titulo - ? * tot.sessoes_dia, 0.0)
               END AS excedente_sessoes
        FROM dia_titulo dt
        JOIN dia_totais tot USING (REGISTRO_COMPLEXO, DATA_EXIBICAO)
        JOIN complexo_porte p USING (REGISTRO_COMPLEXO);
    """, [PROPORCAO_MAXIMA_3_MAIS])
    con.execute("""
        CREATE OR REPLACE TABLE cota_suplementar AS
        SELECT REGISTRO_COMPLEXO, SUM(excedente_sessoes) AS sessoes_suplementares
        FROM excedente_sessoes GROUP BY REGISTRO_COMPLEXO;
    """)

    # 3) Sessões com incentivos (IN 172/2025)
    # +0,10 para sessões nacionais após 17h; +0,15 para premiadas após 17h
    con.execute("""
        CREATE OR REPLACE TABLE sessoes_pond AS
        SELECT b.REGISTRO_COMPLEXO, b.DATA_EXIBICAO, b.CPB_ROE,
               b.origem_corrigida, b.HORA_SESSAO,
               CASE WHEN fp.cpb_roe IS NOT NULL THEN TRUE ELSE FALSE END AS premiado,
               CASE
                   WHEN b.origem_corrigida <> 'Nacional' THEN 0.0
                   ELSE 1.0
                     + CASE WHEN b.HORA_SESSAO >= ? THEN 0.10 ELSE 0.0 END
                     + CASE WHEN b.HORA_SESSAO >= ? AND fp.cpb_roe IS NOT NULL
                            THEN 0.15 ELSE 0.0 END
               END AS peso_sessao
        FROM base b
        LEFT JOIN filmes_premiados fp ON fp.cpb_roe = b.CPB_ROE;
    """, [HORA_BONUS, HORA_BONUS])

    # 4) Sessões por complexo
    con.execute("""
        CREATE OR REPLACE TABLE sessoes_complexo AS
        SELECT REGISTRO_COMPLEXO,
               COUNT(*) AS sessoes_totais,
               COUNT(*) FILTER (WHERE origem_corrigida='Nacional') AS sessoes_nacionais,
               SUM(peso_sessao) AS sessoes_pond
        FROM sessoes_pond GROUP BY REGISTRO_COMPLEXO;
    """)

    # 5) Títulos nacionais
    con.execute("""
        CREATE OR REPLACE TABLE titulos_nacionais AS
        SELECT REGISTRO_COMPLEXO, COUNT(DISTINCT CPB_ROE) AS titulos_nac
        FROM base
        WHERE origem_corrigida='Nacional'
        GROUP BY REGISTRO_COMPLEXO;
    """)

    # 6) Aferição final
    con.execute("""
        CREATE OR REPLACE TABLE afericao AS
        WITH local AS (
            SELECT REGISTRO_COMPLEXO,
                   ANY_VALUE(UF_SALA_COMPLEXO) AS UF_SALA_COMPLEXO,
                   ANY_VALUE(MUNICIPIO_SALA_COMPLEXO) AS MUNICIPIO_SALA_COMPLEXO
            FROM base GROUP BY REGISTRO_COMPLEXO
        ),
        calc AS (
            SELECT p.REGISTRO_COMPLEXO, p.n_salas, p.n_salas_grupo, p.pct_minimo,
                   s.sessoes_totais, s.sessoes_nacionais, s.sessoes_pond,
                   COALESCE(cs.sessoes_suplementares, 0) AS suplementar,
                   COALESCE(t.titulos_nac, 0) AS titulos_nac,
                   CASE WHEN s.sessoes_totais > 0
                        THEN 100.0 * s.sessoes_pond / s.sessoes_totais ELSE 0.0 END AS pct_pond
            FROM complexo_porte p
            LEFT JOIN sessoes_complexo s USING (REGISTRO_COMPLEXO)
            LEFT JOIN cota_suplementar cs USING (REGISTRO_COMPLEXO)
            LEFT JOIN titulos_nacionais t USING (REGISTRO_COMPLEXO)
        )
        SELECT c.*, l.UF_SALA_COMPLEXO, l.MUNICIPIO_SALA_COMPLEXO,
               CASE WHEN c.n_salas <= 15 THEN
                    CASE c.n_salas
                        WHEN 1 THEN 3 WHEN 2 THEN 4 WHEN 3 THEN 5 WHEN 4 THEN 6
                        WHEN 5 THEN 8 WHEN 6 THEN 9 WHEN 7 THEN 11 WHEN 8 THEN 12
                        WHEN 9 THEN 14 WHEN 10 THEN 15 WHEN 11 THEN 17 WHEN 12 THEN 18
                        WHEN 13 THEN 20 WHEN 14 THEN 21 WHEN 15 THEN 23
                    END ELSE 24 END AS titulos_minimos,
               c.pct_minimo AS meta,
               c.pct_pond AS obtido,
               c.pct_pond - c.pct_minimo AS deficit,
               (c.pct_pond >= c.pct_minimo
                OR (c.sessoes_nacionais + c.suplementar) >= (c.pct_minimo/100.0 * c.sessoes_totais)) AS cota_ok,
               c.titulos_nac >= (CASE WHEN c.n_salas <= 15 THEN
                    CASE c.n_salas
                        WHEN 1 THEN 3 WHEN 2 THEN 4 WHEN 3 THEN 5 WHEN 4 THEN 6
                        WHEN 5 THEN 8 WHEN 6 THEN 9 WHEN 7 THEN 11 WHEN 8 THEN 12
                        WHEN 9 THEN 14 WHEN 10 THEN 15 WHEN 11 THEN 17 WHEN 12 THEN 18
                        WHEN 13 THEN 20 WHEN 14 THEN 21 WHEN 15 THEN 23
                    END ELSE 24 END) AS diversidade_ok,
               CASE WHEN (c.pct_pond >= c.pct_minimo
                     OR (c.sessoes_nacionais + c.suplementar) >= (c.pct_minimo/100.0 * c.sessoes_totais))
                     AND c.titulos_nac >= (CASE WHEN c.n_salas <= 15 THEN
                        CASE c.n_salas
                            WHEN 1 THEN 3 WHEN 2 THEN 4 WHEN 3 THEN 5 WHEN 4 THEN 6
                            WHEN 5 THEN 8 WHEN 6 THEN 9 WHEN 7 THEN 11 WHEN 8 THEN 12
                            WHEN 9 THEN 14 WHEN 10 THEN 15 WHEN 11 THEN 17 WHEN 12 THEN 18
                            WHEN 13 THEN 20 WHEN 14 THEN 21 WHEN 15 THEN 23
                        END ELSE 24 END)
                    THEN 'Cumprida' ELSE 'Não cumprida' END AS situacao
        FROM calc c
        LEFT JOIN local l USING (REGISTRO_COMPLEXO);
    """)


@st.cache_data(show_spinner="Calculando aferição 2024...")
def afericao_2024(data_ini: str, data_fim: str) -> pd.DataFrame:
    calcula_afericao_r3(data_ini, data_fim)
    return get_conexao().sql("SELECT * FROM afericao").df()


# --- Listas de filtros ---
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
    st.sidebar.title("🎬 Filtros — Cota 2024")

    st.sidebar.subheader("Período")
    col1, col2 = st.sidebar.columns(2)
    data_ini = col1.date_input(
        "De", value=pd.Timestamp("2024-01-01").date(),
        min_value=pd.Timestamp("2024-01-01").date(),
        max_value=pd.Timestamp("2024-12-31").date(),
    )
    data_fim = col2.date_input(
        "Até", value=pd.Timestamp("2024-12-31").date(),
        min_value=pd.Timestamp("2024-01-01").date(),
        max_value=pd.Timestamp("2024-12-31").date(),
    )
    st.sidebar.caption(
        "⚠️ A cota é **anual**. Alterar o período filtra as sessões, "
        "mas o Anexo de 2024 pressupõe o ano inteiro."
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
        )
        complexos_sel = [opcoes[r] for r in rotulos]

    st.sidebar.subheader("Auditoria")
    somente_nao_conformes = st.sidebar.checkbox(
        "Somente complexos em não conformidade", value=False,
    )
    porte_min = st.sidebar.slider(
        "Porte mínimo (nº de salas do complexo)", 1, 30, 1,
    )

    return {
        "data_ini": data_ini, "data_fim": data_fim,
        "ufs": ufs, "municipios": municipios, "complexos": complexos_sel,
        "somente_nao_conformes": somente_nao_conformes,
        "porte_min": porte_min,
    }


# --- Gráficos Altair ---
def grafico_scatter_afericao(df: pd.DataFrame):
    df_plot = df.copy()
    df_plot["meta_fmt"] = df_plot["meta"].apply(lambda v: fmt_br(v, 1))
    df_plot["obtido_fmt"] = df_plot["obtido"].apply(lambda v: fmt_br(v, 2))
    df_plot["deficit_fmt"] = df_plot["deficit"].apply(lambda v: fmt_br(v, 2))

    pontos = (
        alt.Chart(df_plot)
        .mark_circle(size=90, opacity=0.75, stroke="#000", strokeWidth=0.3)
        .encode(
            x=alt.X("meta:Q", title="Meta (% sessões nacionais — Anexo I)"),
            y=alt.Y("obtido:Q", title="% nacional ponderado (com incentivos)"),
            color=alt.Color(
                "situacao:N", title="Situação",
                scale=alt.Scale(domain=list(CORES_SITUACAO.keys()),
                                range=list(CORES_SITUACAO.values())),
            ),
            size=alt.Size("n_salas:Q", title="Salas", scale=alt.Scale(range=[30, 300])),
            tooltip=[
                alt.Tooltip("REGISTRO_COMPLEXO:N", title="Complexo"),
                alt.Tooltip("n_salas:Q", title="Salas do complexo"),
                alt.Tooltip("n_salas_grupo:Q", title="Salas do grupo"),
                alt.Tooltip("meta_fmt:N", title="Meta"),
                alt.Tooltip("obtido_fmt:N", title="% obtido"),
                alt.Tooltip("situacao:N", title="Situação"),
            ],
        )
    )
    max_val = float(max(df_plot["meta"].max(), df_plot["obtido"].max()))
    diagonal = (
        alt.Chart(pd.DataFrame({"x": [0, max_val], "y": [0, max_val]}))
        .mark_line(color="#9E9E9E", strokeDash=[4, 4])
        .encode(x="x:Q", y="y:Q")
    )
    return (pontos + diagonal).properties(height=420)


def grafico_top_deficit(df: pd.DataFrame, top_n: int = 20):
    df_plot = (
        df[df["deficit"] < 0]
        .assign(deficit_abs=lambda d: -d["deficit"])
        .sort_values("deficit_abs", ascending=False)
        .head(top_n).copy()
    )
    if df_plot.empty:
        return None
    df_plot["rotulo"] = (
        df_plot["REGISTRO_COMPLEXO"].astype(str)
        + " (" + df_plot["n_salas"].astype(str) + " salas)"
    )
    df_plot["deficit_fmt"] = df_plot["deficit_abs"].apply(lambda v: fmt_br(v, 2))
    return (
        alt.Chart(df_plot)
        .mark_bar(color=CORES_SITUACAO["Não cumprida"])
        .encode(
            y=alt.Y("rotulo:N", sort="-x", title="Complexo (salas)"),
            x=alt.X("deficit_abs:Q", title="Déficit (pontos percentuais)"),
            tooltip=[
                alt.Tooltip("REGISTRO_COMPLEXO:N", title="Complexo"),
                alt.Tooltip("n_salas:Q", title="Salas"),
                alt.Tooltip("meta:Q", title="Meta (%)", format=".1f"),
                alt.Tooltip("obtido:Q", title="Obtido (%)", format=".2f"),
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


# --- Main ---
def main():
    st.set_page_config(
        page_title="Cota de Tela 2024 — Decreto 12.067/2024",
        page_icon="🎬",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    st.title("🎬 Aferição da Cota de Tela 2024 — Decreto nº 12.067/2024")
    st.info(
        "**Novo modelo em 2024.** A cota passa a ser medida em **percentual de sessões** "
        "(Anexo I), por complexo, em função do tamanho do **grupo exibidor**. "
        "Há **diversidade de títulos** por complexo (Anexo II) e **cota suplementar** "
        "quando um mesmo título ocupa mais de **50%** das sessões diárias de um complexo "
        "com **3+ salas** (Anexo III). **Incentivos** (IN 172/2025): sessões após 17h "
        "(+0,10) e premiadas após 17h (+0,15) recebem peso extra."
    )
    st.caption(
        "Base legal: Lei nº 14.814/2024 + Decreto nº 12.067/2024 + IN nº 170/2024 "
        "(alterações pela IN nº 172/2025)."
    )

    if not PARQUET_PADRAO.exists():
        st.error(
            f"Parquet não encontrado em `{PARQUET_PADRAO}`.\n\n"
            f"Execute antes: `python scripts/baixa_arquivos.py` e "
            f"`python scripts/criar_parquet.py`."
        )
        st.stop()

    filtros = render_sidebar()

    try:
        df_full = afericao_2024(
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
    cota_ok = int(df["cota_ok"].sum())
    div_ok = int(df["diversidade_ok"].sum())
    sessoes_tot = df["sessoes_totais"].sum()
    sessoes_pond = df["sessoes_pond"].sum()
    pct_geral = 100 * sessoes_pond / sessoes_tot if sessoes_tot else 0

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Complexos avaliados", fmt_br(n))
    c2.metric("Cota cumprida", f"{cota_ok} ({fmt_br_pct(100 * cota_ok / n if n else 0)})")
    c3.metric("Diversidade cumprida", f"{div_ok} ({fmt_br_pct(100 * div_ok / n if n else 0)})")
    c4.metric("Sessões totais", fmt_br(sessoes_tot))
    c5.metric("% nacional ponderado", fmt_br_pct(pct_geral, 2))

    st.markdown("---")
    st.subheader("📌 Aferição por complexo — % nacional × meta")
    st.caption(
        "Cada ponto é um complexo. Acima da diagonal = cota cumprida. "
        "Tamanho = nº de salas. Meta = % do Anexo I conforme porte do grupo."
    )
    st.altair_chart(grafico_scatter_afericao(df), use_container_width=True)

    st.markdown("---")
    col_a, col_b = st.columns(2)
    with col_a:
        st.subheader("📉 Maiores déficits (% pontos)")
        fig_def = grafico_top_deficit(df)
        if fig_def is not None:
            st.altair_chart(fig_def, use_container_width=True)
        else:
            st.success("Nenhum complexo com déficit de %.")
    with col_b:
        st.subheader("📊 Situação por faixa de salas")
        st.altair_chart(grafico_por_porte(df), use_container_width=True)

    st.markdown("---")
    st.subheader("📋 Aferição por complexo")
    colunas = ["REGISTRO_COMPLEXO", "UF_SALA_COMPLEXO", "MUNICIPIO_SALA_COMPLEXO",
               "n_salas", "n_salas_grupo", "pct_minimo",
               "sessoes_totais", "sessoes_nacionais", "sessoes_pond",
               "pct_pond", "suplementar", "titulos_nac", "titulos_minimos",
               "diversidade_ok", "situacao"]
    df_tab = df[colunas].sort_values(["situacao", "pct_pond"])
    st.dataframe(
        df_para_exibicao(
            df_tab,
            colunas_numericas=["pct_minimo", "pct_pond", "suplementar"],
            casas=2,
        ),
        use_container_width=True, hide_index=True,
        column_config={
            "REGISTRO_COMPLEXO": "Complexo",
            "UF_SALA_COMPLEXO": "UF",
            "MUNICIPIO_SALA_COMPLEXO": "Município",
            "n_salas": "Salas complexo",
            "n_salas_grupo": "Salas grupo",
            "pct_minimo": "Meta (%)",
            "sessoes_totais": "Sessões totais",
            "sessoes_nacionais": "Sessões nac.",
            "sessoes_pond": "Sessões pond.",
            "pct_pond": "% nacional pond.",
            "suplementar": "Suplementar",
            "titulos_nac": "Títulos nac.",
            "titulos_minimos": "Títulos mín.",
            "diversidade_ok": "Diversidade OK",
            "situacao": "Situação",
        },
    )

    st.download_button(
        "⬇️ Baixar aferição 2024 (CSV)",
        df_tab.to_csv(index=False).encode("utf-8"),
        file_name="afericao_cota_2024.csv",
        mime="text/csv",
    )

    st.markdown("---")
    st.subheader("🔎 Detalhe por complexo (sessões e incentivos)")
    complexo_sel = st.selectbox(
        "Complexo",
        options=df["REGISTRO_COMPLEXO"].astype(int).tolist(),
        format_func=lambda c: (
            f"{c} — "
            f"{df.loc[df['REGISTRO_COMPLEXO'] == c, 'MUNICIPIO_SALA_COMPLEXO'].iloc[0]}/"
            f"{df.loc[df['REGISTRO_COMPLEXO'] == c, 'UF_SALA_COMPLEXO'].iloc[0]}"
        ),
    )
    df_det = query("""
        SELECT DATA_EXIBICAO, CPB_ROE, origem_corrigida,
               COUNT(*) AS sessoes,
               SUM(peso_sessao) AS sessoes_pond
        FROM sessoes_pond
        WHERE REGISTRO_COMPLEXO = ?
        GROUP BY DATA_EXIBICAO, CPB_ROE, origem_corrigida
        ORDER BY DATA_EXIBICAO, CPB_ROE
    """, [complexo_sel])
    if df_det.empty:
        st.info("Sem sessões registradas para o complexo selecionado.")
    else:
        st.dataframe(
            df_para_exibicao(df_det, colunas_numericas=["sessoes", "sessoes_pond"], casas=2),
            use_container_width=True, hide_index=True,
        )


if __name__ == "__main__":
    main()