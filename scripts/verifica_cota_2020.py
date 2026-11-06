"""
Dashboard Streamlit — Aferição da Cota de Tela 2020 (Decreto nº 10.190/2019)
Norma operacional: IN nº 151/2020
Base: bilheteria.parquet (DuckDB)

Mudanças estruturais em relação a 2015–2018:
- Cota por SALA, em função do tamanho do GRUPO EXIBIDOR (Anexo I).
- Piso intransferível por complexo (Anexo II): 13,7 (1 sala) / 27,4 (>1 sala).
- Bônus de 20% para sessões nacionais após as 17h (art. 1º, §4º).
- Diversidade: Anexo III (idêntica à de 2016–2018).

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

CORES_SITUACAO = {
    "Cumprida": "#2E7D32",
    "Não cumprida": "#C62828",
}


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


# --- Anexo I: obrigação por sala (dias), conforme tamanho do GRUPO ---
# (faixa_inf, faixa_sup, obrigacao_por_sala)
ANEXO_I_2020 = [
    (1, 1, 27.4), (2, 3, 28.2), (4, 5, 31.0), (6, 7, 32.9),
    (8, 9, 34.7), (10, 11, 36.5), (12, 13, 37.3), (14, 15, 38.1),
    (16, 17, 39.2), (18, 20, 40.8), (21, 30, 41.1), (31, 40, 42.5),
    (41, 50, 47.8), (51, 70, 49.3), (71, 80, 50.2), (81, 100, 51.1),
    (101, 200, 54.6), (201, 10_000, 57.3),
]

# --- Anexo II: piso intransferível por complexo (dias) ---
PISO_1_SALA = 13.7
PISO_MAIS_1 = 27.4


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


# --- Materialização da aferição R2 (dias por sala × grupo) ---
def calcula_afericao_r2(data_ini: str, data_fim: str,
                        hora_corte: int = 13,
                        hora_bonus: int = 17) -> None:
    con = get_conexao()
    ano_ref = int(data_ini[:4])

    materializa_base(data_ini, data_fim, ano_ref)

    n_base = con.execute("SELECT COUNT(*) FROM base").fetchone()[0]
    if n_base == 0:
        raise RuntimeError(
            f"Sem registros em `base` para {data_ini} a {data_fim} (ano={ano_ref})."
        )

    # 0) Anexo I
    con.execute("""
        CREATE OR REPLACE TABLE anexo_i_2020 (
            faixa_inf INTEGER, faixa_sup INTEGER, obrigacao_por_sala DOUBLE
        );
    """)
    con.executemany("INSERT INTO anexo_i_2020 VALUES (?,?,?)", ANEXO_I_2020)

    # 1) Porte do GRUPO exibidor
    con.execute("""
        CREATE OR REPLACE TABLE grupo_porte AS
        SELECT REGISTRO_GRUPO_EXIBIDOR,
               COUNT(DISTINCT REGISTRO_SALA) AS n_salas_grupo
        FROM base GROUP BY REGISTRO_GRUPO_EXIBIDOR;
    """)

    # 2) Porte do COMPLEXO + obrigação bruta + piso
    con.execute("""
        CREATE OR REPLACE TABLE complexo_porte AS
        WITH salas AS (
            SELECT REGISTRO_COMPLEXO,
                   ANY_VALUE(REGISTRO_GRUPO_EXIBIDOR) AS REGISTRO_GRUPO_EXIBIDOR,
                   COUNT(DISTINCT REGISTRO_SALA) AS n_salas
            FROM base GROUP BY REGISTRO_COMPLEXO
        )
        SELECT s.*, g.n_salas_grupo, a.obrigacao_por_sala,
               s.n_salas * a.obrigacao_por_sala AS obrigacao_bruta,
               CASE WHEN s.n_salas = 1 THEN ? ELSE ? END AS piso
        FROM salas s
        JOIN grupo_porte g USING (REGISTRO_GRUPO_EXIBIDOR)
        JOIN anexo_i_2020 a
          ON g.n_salas_grupo BETWEEN a.faixa_inf AND a.faixa_sup;
    """, [PISO_1_SALA, PISO_MAIS_1])

    # 3) Dia × complexo (IN 88/2010 arts. 9º-10 + bônus 17h)
    con.execute("""
        CREATE OR REPLACE TABLE dia_complexo AS
        SELECT REGISTRO_COMPLEXO, DATA_EXIBICAO,
               COUNT(*) FILTER (WHERE origem_corrigida='Nacional' AND HORA_SESSAO >= ?) AS nac,
               COUNT(*) FILTER (WHERE HORA_SESSAO >= ?) AS tot,
               COUNT(*) FILTER (WHERE origem_corrigida='Nacional' AND HORA_SESSAO >= ?) AS nac_pos17
        FROM base GROUP BY REGISTRO_COMPLEXO, DATA_EXIBICAO;
    """, [hora_corte, hora_corte, hora_bonus])

    # 4) Dias equivalentes com bônus de 20% pós-17h
    con.execute("""
        CREATE OR REPLACE TABLE dias_equivalentes AS
        SELECT REGISTRO_COMPLEXO,
               SUM(CASE
                   WHEN tot > 0 AND nac = tot      THEN 1.0
                   WHEN tot > 0 AND nac * 2 >= tot THEN 0.5
                   ELSE 0.0
               END) AS dias_base,
               SUM(CASE
                   WHEN tot > 0 AND nac = tot      THEN (nac_pos17 / NULLIF(nac,0)) * 0.2
                   WHEN tot > 0 AND nac * 2 >= tot THEN (nac_pos17 / NULLIF(nac,0)) * 0.1
                   ELSE 0.0
               END) AS dias_bonus
        FROM dia_complexo GROUP BY REGISTRO_COMPLEXO;
    """)

    # 5) Títulos nacionais
    con.execute("""
        CREATE OR REPLACE TABLE titulos_nacionais AS
        SELECT REGISTRO_COMPLEXO, COUNT(DISTINCT CPB_ROE) AS titulos_nac
        FROM base
        WHERE origem_corrigida='Nacional' AND HORA_SESSAO >= ?
        GROUP BY REGISTRO_COMPLEXO;
    """, [hora_corte])

    # 6) Aferição final (com UF/município)
    con.execute("""
        CREATE OR REPLACE TABLE afericao AS
        WITH local AS (
            SELECT REGISTRO_COMPLEXO,
                   ANY_VALUE(UF_SALA_COMPLEXO) AS UF_SALA_COMPLEXO,
                   ANY_VALUE(MUNICIPIO_SALA_COMPLEXO) AS MUNICIPIO_SALA_COMPLEXO
            FROM base GROUP BY REGISTRO_COMPLEXO
        ),
        calc AS (
            SELECT p.REGISTRO_COMPLEXO, p.n_salas, p.n_salas_grupo,
                   p.obrigacao_por_sala, p.obrigacao_bruta, p.piso,
                   COALESCE(d.dias_base,0) + COALESCE(d.dias_bonus,0) AS obtido,
                   COALESCE(t.titulos_nac,0) AS titulos_nac,
                   GREATEST(p.obrigacao_bruta, p.piso) AS meta
            FROM complexo_porte p
            LEFT JOIN dias_equivalentes d USING (REGISTRO_COMPLEXO)
            LEFT JOIN titulos_nacionais t USING (REGISTRO_COMPLEXO)
        )
        SELECT c.*, l.UF_SALA_COMPLEXO, l.MUNICIPIO_SALA_COMPLEXO,
               CASE WHEN c.n_salas <= 20 THEN
                    CASE c.n_salas
                        WHEN 1 THEN 3 WHEN 2 THEN 4 WHEN 3 THEN 5 WHEN 4 THEN 6
                        WHEN 5 THEN 8 WHEN 6 THEN 9 WHEN 7 THEN 11 WHEN 8 THEN 12
                        WHEN 9 THEN 14 WHEN 10 THEN 15 WHEN 11 THEN 17 WHEN 12 THEN 18
                        WHEN 13 THEN 20 WHEN 14 THEN 21 WHEN 15 THEN 23 WHEN 16 THEN 24
                        WHEN 17 THEN 24 WHEN 18 THEN 24 WHEN 19 THEN 24 WHEN 20 THEN 24
                    END ELSE 24 END AS titulos_minimos,
               c.obtido - c.meta AS deficit,
               c.obtido >= c.meta AS cota_ok,
               c.titulos_nac >= (CASE WHEN c.n_salas <= 20 THEN
                    CASE c.n_salas
                        WHEN 1 THEN 3 WHEN 2 THEN 4 WHEN 3 THEN 5 WHEN 4 THEN 6
                        WHEN 5 THEN 8 WHEN 6 THEN 9 WHEN 7 THEN 11 WHEN 8 THEN 12
                        WHEN 9 THEN 14 WHEN 10 THEN 15 WHEN 11 THEN 17 WHEN 12 THEN 18
                        WHEN 13 THEN 20 WHEN 14 THEN 21 WHEN 15 THEN 23 WHEN 16 THEN 24
                        WHEN 17 THEN 24 WHEN 18 THEN 24 WHEN 19 THEN 24 WHEN 20 THEN 24
                    END ELSE 24 END) AS diversidade_ok,
               CASE WHEN c.obtido >= c.meta AND c.titulos_nac >= (CASE WHEN c.n_salas <= 20 THEN
                    CASE c.n_salas
                        WHEN 1 THEN 3 WHEN 2 THEN 4 WHEN 3 THEN 5 WHEN 4 THEN 6
                        WHEN 5 THEN 8 WHEN 6 THEN 9 WHEN 7 THEN 11 WHEN 8 THEN 12
                        WHEN 9 THEN 14 WHEN 10 THEN 15 WHEN 11 THEN 17 WHEN 12 THEN 18
                        WHEN 13 THEN 20 WHEN 14 THEN 21 WHEN 15 THEN 23 WHEN 16 THEN 24
                        WHEN 17 THEN 24 WHEN 18 THEN 24 WHEN 19 THEN 24 WHEN 20 THEN 24
                    END ELSE 24 END)
                    THEN 'Cumprida' ELSE 'Não cumprida' END AS situacao
        FROM calc c
        LEFT JOIN local l USING (REGISTRO_COMPLEXO);
    """)


@st.cache_data(show_spinner="Calculando aferição 2020...")
def afericao_2020(data_ini: str, data_fim: str) -> pd.DataFrame:
    calcula_afericao_r2(data_ini, data_fim)
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
    st.sidebar.title("🎬 Filtros — Cota 2020")

    st.sidebar.subheader("Período")
    col1, col2 = st.sidebar.columns(2)
    data_ini = col1.date_input(
        "De", value=pd.Timestamp("2020-01-01").date(),
        min_value=pd.Timestamp("2020-01-01").date(),
        max_value=pd.Timestamp("2020-12-31").date(),
    )
    data_fim = col2.date_input(
        "Até", value=pd.Timestamp("2020-12-31").date(),
        min_value=pd.Timestamp("2020-01-01").date(),
        max_value=pd.Timestamp("2020-12-31").date(),
    )
    st.sidebar.caption(
        "⚠️ A cota é **anual**. Alterar o período filtra as sessões, "
        "mas o Anexo de 2020 pressupõe o ano inteiro. "
        "Use UF/complexo para recortes válidos."
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
        "data_ini": data_ini, "data_fim": data_fim,
        "ufs": ufs, "municipios": municipios, "complexos": complexos_sel,
        "somente_nao_conformes": somente_nao_conformes,
        "porte_min": porte_min,
    }


# --- Gráficos Altair ---
def grafico_scatter_afericao(df: pd.DataFrame):
    df_plot = df.copy()
    df_plot["deficit_fmt"] = df_plot["deficit"].apply(lambda v: fmt_br(v, 1))
    df_plot["obtido_fmt"] = df_plot["obtido"].apply(lambda v: fmt_br(v, 1))
    df_plot["meta_fmt"] = df_plot["meta"].apply(lambda v: fmt_br(v, 1))

    pontos = (
        alt.Chart(df_plot)
        .mark_circle(size=90, opacity=0.75, stroke="#000", strokeWidth=0.3)
        .encode(
            x=alt.X("meta:Q", title="Meta de dias (Anexo I × salas, com piso)"),
            y=alt.Y("obtido:Q", title="Dias cumpridos (com bônus 17h)"),
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
                alt.Tooltip("obrigacao_por_sala:Q", title="Obrig. por sala", format=".1f"),
                alt.Tooltip("meta_fmt:N", title="Meta (dias)"),
                alt.Tooltip("obtido_fmt:N", title="Obtido (dias)"),
                alt.Tooltip("deficit_fmt:N", title="Déficit (dias)"),
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
                alt.Tooltip("meta:Q", title="Meta", format=".1f"),
                alt.Tooltip("obtido:Q", title="Obtido", format=".1f"),
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
            x=alt.X("faixa:N", title="Faixa de salas do complexo",
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
        page_title="Cota de Tela 2020 — Decreto 10.190/2019",
        page_icon="🎬",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    st.title("🎬 Aferição da Cota de Tela 2020 — Decreto nº 10.190/2019")
    st.info(
        "**Novo modelo em 2020.** A cota passa a ser calculada **por sala**, em função do "
        "tamanho do **grupo exibidor** (Anexo I), com **piso intransferível por complexo** "
        "(Anexo II: 13,7 dias para 1 sala; 27,4 dias para mais de 1 sala) e **bônus de 20%** "
        "para sessões nacionais após as 17h (art. 1º, §4º). A diversidade de títulos (Anexo III) "
        "permanece idêntica à dos decretos de 2016–2018."
    )
    st.caption(
        "Métrica em **dias equivalentes** (dia completo = 1,0; meio dia = 0,5), sessões a partir "
        "das 13h, com peso extra para sessões nacionais após as 17h."
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
        df_full = afericao_2020(
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
    obtido_tot = df["obtido"].sum()
    meta_tot = df["meta"].sum()

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Complexos avaliados", fmt_br(n))
    c2.metric("Cota cumprida", f"{cota_ok} ({fmt_br_pct(100 * cota_ok / n if n else 0)})")
    c3.metric("Diversidade cumprida", f"{div_ok} ({fmt_br_pct(100 * div_ok / n if n else 0)})")
    c4.metric("Dias obtidos (soma)", fmt_br(obtido_tot, 1))
    c5.metric("Meta total (soma)", fmt_br(meta_tot, 1))

    st.markdown("---")
    st.subheader("📌 Aferição por complexo — obtido × meta (dias)")
    st.caption(
        "Cada ponto é um complexo. Acima da diagonal = cota cumprida. "
        "Tamanho = nº de salas. Meta = Anexo I × salas, com piso do Anexo II."
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
            st.success("Nenhum complexo com déficit de dias.")
    with col_b:
        st.subheader("📊 Situação por faixa de salas")
        st.altair_chart(grafico_por_porte(df), use_container_width=True)

    st.markdown("---")
    st.subheader("📋 Aferição por complexo")
    colunas = ["REGISTRO_COMPLEXO", "UF_SALA_COMPLEXO", "MUNICIPIO_SALA_COMPLEXO",
               "n_salas", "n_salas_grupo", "obrigacao_por_sala", "obrigacao_bruta",
               "piso", "meta", "obtido", "deficit", "titulos_nac", "titulos_minimos",
               "diversidade_ok", "situacao"]
    df_tab = df[colunas].sort_values(["situacao", "deficit"])
    st.dataframe(
        df_para_exibicao(
            df_tab,
            colunas_numericas=["obrigacao_por_sala", "obrigacao_bruta",
                               "piso", "meta", "obtido", "deficit"],
            casas=1,
        ),
        use_container_width=True, hide_index=True,
        column_config={
            "REGISTRO_COMPLEXO": "Complexo",
            "UF_SALA_COMPLEXO": "UF",
            "MUNICIPIO_SALA_COMPLEXO": "Município",
            "n_salas": "Salas complexo",
            "n_salas_grupo": "Salas grupo",
            "obrigacao_por_sala": "Obrig./sala (Anexo I)",
            "obrigacao_bruta": "Obrig. bruta",
            "piso": "Piso (Anexo II)",
            "meta": "Meta (dias)",
            "obtido": "Obtido (dias)",
            "deficit": "Déficit",
            "titulos_nac": "Títulos nac.",
            "titulos_minimos": "Títulos mín.",
            "diversidade_ok": "Diversidade OK",
            "situacao": "Situação",
        },
    )

    st.download_button(
        "⬇️ Baixar aferição 2020 (CSV)",
        df_tab.to_csv(index=False).encode("utf-8"),
        file_name="afericao_cota_2020.csv",
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
        SELECT DATA_EXIBICAO, nac, tot, nac_pos17,
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
            f"{len(df_dia)} dias com sessões · soma de dias equivalentes: "
            f"{fmt_br(df_dia['dias_eq'].sum(), 1)}"
        )
        st.dataframe(
            df_para_exibicao(df_dia, colunas_numericas=["dias_eq"], casas=1),
            use_container_width=True, hide_index=True,
        )


if __name__ == "__main__":
    main()