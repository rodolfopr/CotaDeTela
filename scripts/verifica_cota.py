"""
Dashboard Streamlit unificado — Aferição da Cota de Tela (2015–2025)
Base: bilheteria.parquet (DuckDB)

Regimes:
- R1 (2015–2019): dias por complexo.
- R2 (2020): dias por sala × grupo exibidor.
- R3 (2024–2025): percentual de sessões.
- R4 (2021–2023): sem obrigação legal.

Notas desta versão:
- memory_limit = 2GB; temp_directory para spill em disco.
- Opção A: a tabela `base` materializa apenas as colunas usadas pelos
  regimes (DATA_EXIBICAO, SESSAO, REGISTRO_SALA, CPB_ROE,
  REGISTRO_COMPLEXO, REGISTRO_GRUPO_EXIBIDOR, REGISTRO_EXIBIDOR,
  CNPJ_EXIBIDORA, RAZAO_SOCIAL_EXIBIDORA, UF_SALA_COMPLEXO,
  MUNICIPIO_SALA_COMPLEXO, HORA_SESSAO, origem_corrigida).
- Datas passadas como string 'YYYY-MM-DD' e convertidas com ?::DATE
  (evita DATE ? e DATE_TRUNC com parâmetro).
"""

from pathlib import Path

import altair as alt
import duckdb
import pandas as pd
import streamlit as st

# ============================================================================
# CONFIGURAÇÃO GERAL
# ============================================================================

PASTA_RAIZ = Path(__file__).resolve().parent.parent
PARQUET_PADRAO = PASTA_RAIZ / "data" / "bilheteria.parquet"
PREMIADOS_CSV = PASTA_RAIZ / "data" / "filmes_premiados.csv"
TEMP_DIR = "/tmp/duckdb_tmp"

CORES_SITUACAO = {"Cumprida": "#2E7D32", "Não cumprida": "#C62828"}
HORA_CORTE = 13
HORA_BONUS = 17

st.set_page_config(
    page_title="Cota de Tela — Aferição (2015–2025)",
    page_icon="🎬", layout="wide", initial_sidebar_state="expanded",
)


# ============================================================================
# TABELAS DOS ANEXOS
# ============================================================================

# R1 — Anexos de 2015 e 2016–2019
ANEXO_8386 = [  # 2015
    (1, 28, 3, 1), (2, 70, 4, 2), (3, 126, 5, 2),
    (4, 196, 6, 2), (5, 280, 8, 2), (6, 378, 9, 2),
    (7, 441, 11, 2.5), (8, 480, 12, 2.5), (9, 531, 14, 3),
    (10, 560, 15, 3), (11, 583, 17, 3), (12, 600, 18, 4),
    (13, 624, 20, 4), (14, 644, 21, 4), (15, 675, 23, 5),
    (16, 704, 24, 5), (17, 731, 24, 5), (18, 756, 24, 5),
    (19, 763, 24, 6), (20, 770, 24, 6),
]
ANEXO_8620 = [  # 2016–2019
    (1, 28, 3, 1), (2, 70, 4, 2), (3, 126, 5, 2),
    (4, 196, 6, 2), (5, 280, 8, 2), (6, 378, 9, 2),
    (7, 441, 11, 2.5), (8, 480, 12, 2.5), (9, 531, 14, 3),
    (10, 560, 15, 3), (11, 583, 17, 3), (12, 600, 18, 4),
    (13, 624, 20, 4), (14, 644, 21, 4), (15, 675, 23, 5),
    (16, 704, 24, 5), (17, 731, 24, 5), (18, 756, 24, 6),
    (19, 779, 24, 6), (20, 800, 24, 6),
]
ANEXO_III_R1 = {
    1: 3, 2: 4, 3: 5, 4: 6, 5: 8, 6: 9, 7: 11, 8: 12, 9: 14, 10: 15,
    11: 17, 12: 18, 13: 20, 14: 21, 15: 23, 16: 24, 17: 24, 18: 24,
    19: 24, 20: 24, ">20": 24,
}

# R2 — 2020
ANEXO_I_2020 = [
    (1, 1, 27.4), (2, 3, 28.2), (4, 5, 31.0), (6, 7, 32.9),
    (8, 9, 34.7), (10, 11, 36.5), (12, 13, 37.3), (14, 15, 38.1),
    (16, 17, 39.2), (18, 20, 40.8), (21, 30, 41.1), (31, 40, 42.5),
    (41, 50, 47.8), (51, 70, 49.3), (71, 80, 50.2), (81, 100, 51.1),
    (101, 200, 54.6), (201, 10_000, 57.3),
]
ANEXO_II_2020 = {1: 13.7, ">1": 27.4}
ANEXO_III_R2 = ANEXO_III_R1

# R3 — 2024 e 2025
ANEXO_I_R3 = [
    (1, 1, 7.5), (2, 3, 8.0), (4, 5, 8.5), (6, 7, 9.0),
    (8, 9, 9.5), (10, 11, 10.0), (12, 13, 10.5), (14, 15, 11.0),
    (16, 17, 11.5), (18, 20, 12.0), (21, 30, 12.5), (31, 40, 13.0),
    (41, 50, 13.5), (51, 70, 14.0), (71, 80, 14.5), (81, 100, 15.0),
    (101, 200, 15.5), (201, 10_000, 16.0),
]
ANEXO_II_2024 = {
    1: 3, 2: 4, 3: 5, 4: 6, 5: 8, 6: 9, 7: 11, 8: 12, 9: 14, 10: 15,
    11: 17, 12: 18, 13: 20, 14: 21, 15: 23, "16+": 24,
}
ANEXO_II_2025 = {
    1: 4, 2: 5, 3: 7, 4: 8, 5: 11, 6: 12, 7: 15, 8: 16,
    9: 19, 10: 20, 11: 23, 12: 24, 13: 27, 14: 28, 15: 31, "16+": 32,
}
ANEXO_III_2024 = {"1-2": None, "3+": 0.50}
ANEXO_III_2025 = {"1-2": None, "3-5": 0.66, "6+": 0.50}


# ============================================================================
# CONFIGURAÇÃO DOS ANOS
# ============================================================================

CONFIG_ANOS = {
    2015: {
        "regime": "R1", "decreto": "8.386/2014",
        "anexo": ANEXO_8386, "titulos": ANEXO_III_R1,
        "regra_mais20": lambda n: 770 + 7 * (n - 20),
        "obs": None,
    },
    2016: {
        "regime": "R1", "decreto": "8.620/2015",
        "anexo": ANEXO_8620, "titulos": ANEXO_III_R1,
        "regra_mais20": lambda n: 800 + 7 * (n - 20),
        "obs": None,
    },
    2017: {"regime": "R1", "decreto": "8.944/2016", "herda_de": 2016, "obs": None},
    2018: {"regime": "R1", "decreto": "9.256/2017", "herda_de": 2016, "obs": None},
    2019: {
        "regime": "R1", "decreto": "9.256/2017 (por analogia)",
        "herda_de": 2018, "obs": "sem_decreto_nota_oficial",
    },
    2020: {
        "regime": "R2", "decreto": "10.190/2019",
        "anexo_i": ANEXO_I_2020, "anexo_ii": ANEXO_II_2020,
        "titulos": ANEXO_III_R2, "obs": None,
    },
    2021: {"regime": "R4", "obs": "base_legal_expirada"},
    2022: {"regime": "R4", "obs": "base_legal_expirada"},
    2023: {"regime": "R4", "obs": "base_legal_expirada"},
    2024: {
        "regime": "R3", "decreto": "12.067/2024",
        "anexo_i": ANEXO_I_R3, "anexo_ii": ANEXO_II_2024,
        "anexo_iii": ANEXO_III_2024,
        "incentivos": {"pos17": 0.10, "premiado_pos17": 0.15, "semana_2_5": 0.025},
        "obs": None,
    },
    2025: {
        "regime": "R3", "decreto": "12.323/2024",
        "anexo_i": ANEXO_I_R3, "anexo_ii": ANEXO_II_2025,
        "anexo_iii": ANEXO_III_2025,
        "incentivos": {"pos17": 0.10, "premiado_pos17": 0.15, "semana_2_5": 0.025},
        "obs": None,
    },
}


def resolve_config(ano: int) -> dict:
    cfg = dict(CONFIG_ANOS[ano])
    if "herda_de" in cfg:
        base = resolve_config(cfg["herda_de"])
        for k, v in base.items():
            cfg.setdefault(k, v)
    return cfg


# ============================================================================
# FORMATAÇÃO PT-BR
# ============================================================================

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


def df_para_exibicao(df, colunas_numericas=None, casas: int = 0) -> pd.DataFrame:
    if colunas_numericas is None:
        colunas_numericas = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
    out = df.copy()
    for c in colunas_numericas:
        if c in out.columns:
            out[c] = out[c].apply(lambda v: fmt_br(v, casas))
    return out


# ============================================================================
# CONEXÃO
# ============================================================================

@st.cache_resource
def get_conexao():
    con = duckdb.connect()
    con.execute("SET memory_limit = '2GB';")
    con.execute("SET threads = 2;")
    con.execute("SET preserve_insertion_order = false;")
    con.execute(f"SET temp_directory = '{TEMP_DIR}';")
    return con


def query(sql: str, params=None) -> pd.DataFrame:
    con = get_conexao()
    if params is None:
        return con.sql(sql).df()
    return con.execute(sql, params).df()


# ============================================================================
# BASE COMUM — Opção A (apenas colunas usadas)
# ============================================================================

def materializa_base(ano: int) -> None:
    con = get_conexao()
    data_ini = f"{ano}-01-01"
    data_fim = f"{ano}-12-31"

    con.execute("""
        CREATE OR REPLACE TABLE base AS
        WITH dedup AS (
            SELECT
                DATA_EXIBICAO, SESSAO, REGISTRO_SALA, CPB_ROE,
                REGISTRO_COMPLEXO, REGISTRO_GRUPO_EXIBIDOR,
                REGISTRO_EXIBIDOR, CNPJ_EXIBIDORA, RAZAO_SOCIAL_EXIBIDORA,
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
            REGISTRO_EXIBIDOR, CNPJ_EXIBIDORA, RAZAO_SOCIAL_EXIBIDORA,
            UF_SALA_COMPLEXO, MUNICIPIO_SALA_COMPLEXO,
            HORA_SESSAO, origem_corrigida
        FROM limpa;
    """, [PARQUET_PADRAO.as_posix(), ano, data_ini, data_fim])


def materializa_filmes_premiados() -> None:
    con = get_conexao()
    con.execute("CREATE OR REPLACE TABLE filmes_premiados (cpb_roe VARCHAR);")
    if PREMIADOS_CSV.exists():
        df = pd.read_csv(PREMIADOS_CSV, dtype=str)
        if not df.empty and "cpb_roe" in df.columns:
            con.executemany("INSERT INTO filmes_premiados VALUES (?)",
                            [(c,) for c in df["cpb_roe"].dropna().unique()])


# ============================================================================
# REGIME R1 — DIAS POR COMPLEXO (2015–2019)
# ============================================================================

def calcula_r1(ano: int, cfg: dict) -> None:
    con = get_conexao()

    con.execute("""
        CREATE OR REPLACE TABLE anexo_r1 (
            salas INTEGER PRIMARY KEY, dias_minimos DOUBLE,
            titulos_minimos INTEGER, max_salas_mesmo_titulo DOUBLE
        );
    """)
    con.executemany("INSERT INTO anexo_r1 VALUES (?,?,?,?)", cfg["anexo"])

    regra_mais20 = cfg["regra_mais20"]
    con.execute(f"""
        CREATE OR REPLACE TABLE complexo_porte AS
        WITH salas AS (
            SELECT REGISTRO_COMPLEXO, COUNT(DISTINCT REGISTRO_SALA) AS n_salas
            FROM base GROUP BY REGISTRO_COMPLEXO
        )
        SELECT s.REGISTRO_COMPLEXO, s.n_salas,
               CASE WHEN s.n_salas > 20 THEN {regra_mais20(21)} + 7*(s.n_salas-21)
                    ELSE a.dias_minimos END AS dias_minimos,
               COALESCE(a.titulos_minimos, 24) AS titulos_minimos,
               CASE WHEN s.n_salas > 20 THEN 0.30*s.n_salas
                    ELSE a.max_salas_mesmo_titulo END AS max_salas_mesmo_titulo
        FROM salas s LEFT JOIN anexo_r1 a ON a.salas = LEAST(s.n_salas, 20);
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
    """, [HORA_CORTE])

    con.execute("""
        CREATE OR REPLACE TABLE cota_suplementar AS
        SELECT REGISTRO_COMPLEXO, SUM(excedente_salas) AS suplementar
        FROM excedente_diario GROUP BY REGISTRO_COMPLEXO;
    """)

    con.execute("""
        CREATE OR REPLACE TABLE dia_complexo AS
        SELECT REGISTRO_COMPLEXO, DATA_EXIBICAO,
               COUNT(*) FILTER (WHERE origem_corrigida='Nacional' AND HORA_SESSAO >= ?) AS nac,
               COUNT(*) FILTER (WHERE HORA_SESSAO >= ?) AS tot
        FROM base GROUP BY REGISTRO_COMPLEXO, DATA_EXIBICAO;
    """, [HORA_CORTE, HORA_CORTE])

    con.execute("""
        CREATE OR REPLACE TABLE dias_equivalentes AS
        SELECT REGISTRO_COMPLEXO,
               SUM(CASE WHEN tot > 0 AND nac = tot      THEN 1.0
                        WHEN tot > 0 AND nac * 2 >= tot THEN 0.5
                        ELSE 0.0 END) AS cumprido
        FROM dia_complexo GROUP BY REGISTRO_COMPLEXO;
    """)

    con.execute("""
        CREATE OR REPLACE TABLE titulos_nacionais AS
        SELECT REGISTRO_COMPLEXO, COUNT(DISTINCT CPB_ROE) AS titulos_nac
        FROM base
        WHERE origem_corrigida='Nacional' AND HORA_SESSAO >= ?
        GROUP BY REGISTRO_COMPLEXO;
    """, [HORA_CORTE])

    con.execute("""
        CREATE OR REPLACE TABLE afericao AS
        WITH local AS (
            SELECT REGISTRO_COMPLEXO,
                   ANY_VALUE(UF_SALA_COMPLEXO) AS UF,
                   ANY_VALUE(MUNICIPIO_SALA_COMPLEXO) AS MUNICIPIO
            FROM base GROUP BY REGISTRO_COMPLEXO
        )
        SELECT p.REGISTRO_COMPLEXO, l.UF, l.MUNICIPIO, p.n_salas,
               p.titulos_minimos, COALESCE(t.titulos_nac,0) AS titulos_nac,
               p.dias_minimos AS meta, COALESCE(s.suplementar,0) AS suplementar,
               COALESCE(d.cumprido,0) AS obtido,
               COALESCE(d.cumprido,0) - (p.dias_minimos + COALESCE(s.suplementar,0)) AS deficit,
               COALESCE(d.cumprido,0) >= (p.dias_minimos + COALESCE(s.suplementar,0)) AS cota_ok,
               COALESCE(t.titulos_nac,0) >= p.titulos_minimos AS diversidade_ok,
               'dias' AS unidade,
               CASE WHEN COALESCE(d.cumprido,0) >= (p.dias_minimos + COALESCE(s.suplementar,0))
                     AND COALESCE(t.titulos_nac,0) >= p.titulos_minimos
                    THEN 'Cumprida' ELSE 'Não cumprida' END AS situacao
        FROM complexo_porte p
        LEFT JOIN local l USING (REGISTRO_COMPLEXO)
        LEFT JOIN dias_equivalentes d USING (REGISTRO_COMPLEXO)
        LEFT JOIN cota_suplementar s USING (REGISTRO_COMPLEXO)
        LEFT JOIN titulos_nacionais t USING (REGISTRO_COMPLEXO);
    """)


# ============================================================================
# REGIME R2 — DIAS POR SALA × GRUPO (2020)
# ============================================================================

def calcula_r2(ano: int, cfg: dict) -> None:
    con = get_conexao()

    con.execute("""
        CREATE OR REPLACE TABLE anexo_i_r2 (
            faixa_inf INTEGER, faixa_sup INTEGER, obrigacao_por_sala DOUBLE
        );
    """)
    con.executemany("INSERT INTO anexo_i_r2 VALUES (?,?,?)", cfg["anexo_i"])

    con.execute("""
        CREATE OR REPLACE TABLE grupo_porte AS
        SELECT REGISTRO_GRUPO_EXIBIDOR, COUNT(DISTINCT REGISTRO_SALA) AS n_salas_grupo
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
        SELECT s.*, g.n_salas_grupo, a.obrigacao_por_sala,
               s.n_salas * a.obrigacao_por_sala AS obrigacao_bruta,
               CASE WHEN s.n_salas = 1 THEN 13.7 ELSE 27.4 END AS piso
        FROM salas s
        JOIN grupo_porte g USING (REGISTRO_GRUPO_EXIBIDOR)
        JOIN anexo_i_r2 a ON g.n_salas_grupo BETWEEN a.faixa_inf AND a.faixa_sup;
    """)

    con.execute("""
        CREATE OR REPLACE TABLE dia_complexo AS
        SELECT REGISTRO_COMPLEXO, DATA_EXIBICAO,
               COUNT(*) FILTER (WHERE origem_corrigida='Nacional' AND HORA_SESSAO >= ?) AS nac,
               COUNT(*) FILTER (WHERE HORA_SESSAO >= ?) AS tot,
               COUNT(*) FILTER (WHERE origem_corrigida='Nacional' AND HORA_SESSAO >= ?) AS nac_pos17
        FROM base GROUP BY REGISTRO_COMPLEXO, DATA_EXIBICAO;
    """, [HORA_CORTE, HORA_CORTE, HORA_BONUS])

    con.execute("""
        CREATE OR REPLACE TABLE dias_equivalentes AS
        SELECT REGISTRO_COMPLEXO,
               SUM(CASE WHEN tot > 0 AND nac = tot      THEN 1.0
                        WHEN tot > 0 AND nac * 2 >= tot THEN 0.5
                        ELSE 0.0 END) AS base,
               SUM(CASE WHEN tot > 0 AND nac = tot      THEN (nac_pos17 / NULLIF(nac,0)) * 0.2
                        WHEN tot > 0 AND nac * 2 >= tot THEN (nac_pos17 / NULLIF(nac,0)) * 0.1
                        ELSE 0.0 END) AS bonus
        FROM dia_complexo GROUP BY REGISTRO_COMPLEXO;
    """)

    con.execute("""
        CREATE OR REPLACE TABLE titulos_nacionais AS
        SELECT REGISTRO_COMPLEXO, COUNT(DISTINCT CPB_ROE) AS titulos_nac
        FROM base
        WHERE origem_corrigida='Nacional' AND HORA_SESSAO >= ?
        GROUP BY REGISTRO_COMPLEXO;
    """, [HORA_CORTE])

    con.execute("""
        CREATE OR REPLACE TABLE afericao AS
        WITH local AS (
            SELECT REGISTRO_COMPLEXO,
                   ANY_VALUE(UF_SALA_COMPLEXO) AS UF,
                   ANY_VALUE(MUNICIPIO_SALA_COMPLEXO) AS MUNICIPIO
            FROM base GROUP BY REGISTRO_COMPLEXO
        ),
        calc AS (
            SELECT p.REGISTRO_COMPLEXO, p.n_salas, p.n_salas_grupo,
                   p.obrigacao_por_sala, p.obrigacao_bruta, p.piso,
                   COALESCE(d.base,0) + COALESCE(d.bonus,0) AS obtido,
                   COALESCE(t.titulos_nac,0) AS titulos_nac,
                   GREATEST(p.obrigacao_bruta, p.piso) AS meta
            FROM complexo_porte p
            LEFT JOIN dias_equivalentes d USING (REGISTRO_COMPLEXO)
            LEFT JOIN titulos_nacionais t USING (REGISTRO_COMPLEXO)
        )
        SELECT c.*, l.UF, l.MUNICIPIO,
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
               'dias' AS unidade,
               CASE WHEN c.obtido >= c.meta AND c.titulos_nac >= (CASE WHEN c.n_salas <= 20 THEN
                    CASE c.n_salas
                        WHEN 1 THEN 3 WHEN 2 THEN 4 WHEN 3 THEN 5 WHEN 4 THEN 6
                        WHEN 5 THEN 8 WHEN 6 THEN 9 WHEN 7 THEN 11 WHEN 8 THEN 12
                        WHEN 9 THEN 14 WHEN 10 THEN 15 WHEN 11 THEN 17 WHEN 12 THEN 18
                        WHEN 13 THEN 20 WHEN 14 THEN 21 WHEN 15 THEN 23 WHEN 16 THEN 24
                        WHEN 17 THEN 24 WHEN 18 THEN 24 WHEN 19 THEN 24 WHEN 20 THEN 24
                    END ELSE 24 END)
                    THEN 'Cumprida' ELSE 'Não cumprida' END AS situacao
        FROM calc c LEFT JOIN local l USING (REGISTRO_COMPLEXO);
    """)


# ============================================================================
# REGIME R3 — % DE SESSÕES (2024–2025)
# ============================================================================

def proporcao_maxima_r3(n_salas: int, anexo_iii: dict) -> float | None:
    if n_salas <= 2:
        return None
    if "3-5" in anexo_iii and 3 <= n_salas <= 5:
        return anexo_iii["3-5"]
    if "3+" in anexo_iii and n_salas >= 3:
        return anexo_iii["3+"]
    if "6+" in anexo_iii and n_salas >= 6:
        return anexo_iii["6+"]
    return None


def calcula_r3(ano: int, cfg: dict) -> None:
    con = get_conexao()

    con.execute("""
        CREATE OR REPLACE TABLE anexo_i_r3 (
            faixa_inf INTEGER, faixa_sup INTEGER, pct_minimo DOUBLE
        );
    """)
    con.executemany("INSERT INTO anexo_i_r3 VALUES (?,?,?)", cfg["anexo_i"])

    con.execute("""
        CREATE OR REPLACE TABLE grupo_porte AS
        SELECT REGISTRO_GRUPO_EXIBIDOR, COUNT(DISTINCT REGISTRO_SALA) AS n_salas_grupo
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
        JOIN anexo_i_r3 a ON g.n_salas_grupo BETWEEN a.faixa_inf AND a.faixa_sup;
    """)

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
                   WHEN p.n_salas BETWEEN 3 AND 5 AND ? IS NOT NULL
                       THEN GREATEST(dt.sessoes_titulo - ? * tot.sessoes_dia, 0.0)
                   WHEN p.n_salas >= 6 AND ? IS NOT NULL
                       THEN GREATEST(dt.sessoes_titulo - ? * tot.sessoes_dia, 0.0)
                   ELSE 0.0
               END AS excedente_sessoes
        FROM dia_titulo dt
        JOIN dia_totais tot USING (REGISTRO_COMPLEXO, DATA_EXIBICAO)
        JOIN complexo_porte p USING (REGISTRO_COMPLEXO);
    """, [
        cfg["anexo_iii"].get("3-5"), cfg["anexo_iii"].get("3-5"),
        cfg["anexo_iii"].get("6+") or cfg["anexo_iii"].get("3+"),
        cfg["anexo_iii"].get("6+") or cfg["anexo_iii"].get("3+"),
    ])
    con.execute("""
        CREATE OR REPLACE TABLE cota_suplementar AS
        SELECT REGISTRO_COMPLEXO, SUM(excedente_sessoes) AS suplementar
        FROM excedente_sessoes GROUP BY REGISTRO_COMPLEXO;
    """)

    inc = cfg["incentivos"]
    con.execute("""
        CREATE OR REPLACE TABLE sessoes_pond AS
        SELECT b.REGISTRO_COMPLEXO, b.DATA_EXIBICAO, b.CPB_ROE,
               b.origem_corrigida, b.HORA_SESSAO,
               CASE WHEN fp.cpb_roe IS NOT NULL THEN TRUE ELSE FALSE END AS premiado,
               DATE_DIFF('week',
                   MIN(b.DATA_EXIBICAO) OVER (PARTITION BY b.REGISTRO_COMPLEXO, b.CPB_ROE),
                   b.DATA_EXIBICAO) + 1 AS semana_obra,
               CASE
                   WHEN b.origem_corrigida <> 'Nacional' THEN 0.0
                   ELSE 1.0
                     + CASE WHEN b.HORA_SESSAO >= ? THEN ? ELSE 0.0 END
                     + CASE WHEN b.HORA_SESSAO >= ? AND fp.cpb_roe IS NOT NULL
                            THEN ? ELSE 0.0 END
                     + CASE WHEN (DATE_DIFF('week',
                             MIN(b.DATA_EXIBICAO) OVER (PARTITION BY b.REGISTRO_COMPLEXO, b.CPB_ROE),
                             b.DATA_EXIBICAO) + 1) BETWEEN 2 AND 5
                            THEN ? ELSE 0.0 END
               END AS peso_sessao
        FROM base b LEFT JOIN filmes_premiados fp ON fp.cpb_roe = b.CPB_ROE;
    """, [HORA_BONUS, inc["pos17"], HORA_BONUS, inc["premiado_pos17"], inc["semana_2_5"]])

    con.execute("""
        CREATE OR REPLACE TABLE sessoes_complexo AS
        SELECT REGISTRO_COMPLEXO,
               COUNT(*) AS sessoes_totais,
               COUNT(*) FILTER (WHERE origem_corrigida='Nacional') AS sessoes_nacionais,
               SUM(peso_sessao) AS sessoes_pond
        FROM sessoes_pond GROUP BY REGISTRO_COMPLEXO;
    """)

    con.execute("""
        CREATE OR REPLACE TABLE titulos_nacionais AS
        SELECT REGISTRO_COMPLEXO, COUNT(DISTINCT CPB_ROE) AS titulos_nac
        FROM base
        WHERE origem_corrigida='Nacional' AND HORA_SESSAO >= ?
        GROUP BY REGISTRO_COMPLEXO;
    """, [HORA_CORTE])

    con.execute("""
        CREATE OR REPLACE TABLE anexo_ii_r3 (salas INTEGER PRIMARY KEY, titulos INTEGER);
    """)
    rows = [(k, v) for k, v in cfg["anexo_ii"].items() if isinstance(k, int)]
    con.executemany("INSERT INTO anexo_ii_r3 VALUES (?,?)", rows)
    titulos_16mais = cfg["anexo_ii"]["16+"]

    con.execute(f"""
        CREATE OR REPLACE TABLE afericao AS
        WITH local AS (
            SELECT REGISTRO_COMPLEXO,
                   ANY_VALUE(UF_SALA_COMPLEXO) AS UF,
                   ANY_VALUE(MUNICIPIO_SALA_COMPLEXO) AS MUNICIPIO
            FROM base GROUP BY REGISTRO_COMPLEXO
        ),
        calc AS (
            SELECT p.REGISTRO_COMPLEXO, p.n_salas, p.n_salas_grupo, p.pct_minimo,
                   s.sessoes_totais, s.sessoes_nacionais, s.sessoes_pond,
                   COALESCE(cs.suplementar, 0) AS suplementar,
                   COALESCE(t.titulos_nac, 0) AS titulos_nac,
                   CASE WHEN s.sessoes_totais > 0
                        THEN 100.0 * s.sessoes_pond / s.sessoes_totais ELSE 0.0 END AS pct_pond
            FROM complexo_porte p
            LEFT JOIN sessoes_complexo s USING (REGISTRO_COMPLEXO)
            LEFT JOIN cota_suplementar cs USING (REGISTRO_COMPLEXO)
            LEFT JOIN titulos_nacionais t USING (REGISTRO_COMPLEXO)
        )
        SELECT c.*, l.UF, l.MUNICIPIO,
               COALESCE(a2.titulos, {titulos_16mais}) AS titulos_minimos,
               c.pct_minimo AS meta,
               c.pct_pond AS obtido,
               c.pct_pond - c.pct_minimo AS deficit,
               (c.pct_pond >= c.pct_minimo
                OR (c.sessoes_nacionais + c.suplementar) >= (c.pct_minimo/100.0 * c.sessoes_totais)) AS cota_ok,
               c.titulos_nac >= COALESCE(a2.titulos, {titulos_16mais}) AS diversidade_ok,
               '% sessões' AS unidade,
               CASE WHEN (c.pct_pond >= c.pct_minimo
                     OR (c.sessoes_nacionais + c.suplementar) >= (c.pct_minimo/100.0 * c.sessoes_totais))
                     AND c.titulos_nac >= COALESCE(a2.titulos, {titulos_16mais})
                    THEN 'Cumprida' ELSE 'Não cumprida' END AS situacao
        FROM calc c
        LEFT JOIN local l USING (REGISTRO_COMPLEXO)
        LEFT JOIN anexo_ii_r3 a2 ON a2.salas = c.n_salas;
    """)


# ============================================================================
# DESPACHO POR REGIME
# ============================================================================

def calcula_afericao(ano: int) -> None:
    cfg = resolve_config(ano)
    materializa_base(ano)
    materializa_filmes_premiados()
    if cfg["regime"] == "R1":
        calcula_r1(ano, cfg)
    elif cfg["regime"] == "R2":
        calcula_r2(ano, cfg)
    elif cfg["regime"] == "R3":
        calcula_r3(ano, cfg)
    else:
        raise ValueError(f"Regime desconhecido: {cfg['regime']}")


# ============================================================================
# LISTAS DE FILTROS
# ============================================================================

@st.cache_data(show_spinner=False)
def carrega_ufs(_dummy: int = 0):
    return query(f"""
        SELECT DISTINCT UF_SALA_COMPLEXO AS uf FROM read_parquet('{PARQUET_PADRAO.as_posix()}')
        WHERE UF_SALA_COMPLEXO IS NOT NULL ORDER BY uf
    """)["uf"].tolist()


def carrega_municipios(ufs):
    if not ufs:
        return []
    lista = ",".join(f"'{u}'" for u in ufs)
    return query(f"""
        SELECT DISTINCT MUNICIPIO_SALA_COMPLEXO AS mun
        FROM read_parquet('{PARQUET_PADRAO.as_posix()}')
        WHERE UF_SALA_COMPLEXO IN ({lista}) ORDER BY mun
    """)["mun"].tolist()


def carrega_complexos(municipios=None):
    filtro = (
        f"AND MUNICIPIO_SALA_COMPLEXO IN ({','.join(repr(m) for m in municipios)})"
        if municipios else ""
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


# ============================================================================
# SIDEBAR
# ============================================================================

def render_sidebar():
    st.sidebar.title("🎬 Filtros")

    anos_disponiveis = sorted(CONFIG_ANOS.keys())
    ano = st.sidebar.selectbox("Ano de referência", anos_disponiveis,
                               index=len(anos_disponiveis) - 1)

    st.sidebar.subheader("Localização")
    ufs = st.sidebar.multiselect("UF", options=carrega_ufs(), default=[])
    municipios = st.sidebar.multiselect(
        "Município", options=carrega_municipios(ufs), default=[],
    ) if ufs else []

    complexos_sel = []
    df_complexos = carrega_complexos(municipios if municipios else None)
    if not df_complexos.empty:
        opcoes = dict(zip(df_complexos["rotulo"], df_complexos["REGISTRO_COMPLEXO"]))
        rotulos = st.sidebar.multiselect("Complexo", options=list(opcoes.keys()), default=[])
        complexos_sel = [opcoes[r] for r in rotulos]

    st.sidebar.subheader("Auditoria")
    somente_nao_conformes = st.sidebar.checkbox("Somente complexos em não conformidade", False)
    porte_min = st.sidebar.slider("Porte mínimo (nº de salas)", 1, 30, 1)

    return {
        "ano": ano, "ufs": ufs, "municipios": municipios,
        "complexos": complexos_sel,
        "somente_nao_conformes": somente_nao_conformes,
        "porte_min": porte_min,
    }


# ============================================================================
# GRÁFICOS
# ============================================================================

def grafico_scatter(df: pd.DataFrame, unidade: str):
    df_plot = df.copy()
    df_plot["meta_fmt"] = df_plot["meta"].apply(lambda v: fmt_br(v, 1))
    df_plot["obtido_fmt"] = df_plot["obtido"].apply(lambda v: fmt_br(v, 1))
    df_plot["deficit_fmt"] = df_plot["deficit"].apply(lambda v: fmt_br(v, 1))
    return (
        alt.Chart(df_plot)
        .mark_circle(size=90, opacity=0.75, stroke="#000", strokeWidth=0.3)
        .encode(
            x=alt.X("meta:Q", title=f"Meta ({unidade})"),
            y=alt.Y("obtido:Q", title=f"Obtido ({unidade})"),
            color=alt.Color("situacao:N", title="Situação",
                scale=alt.Scale(domain=list(CORES_SITUACAO.keys()),
                                range=list(CORES_SITUACAO.values()))),
            size=alt.Size("n_salas:Q", title="Salas", scale=alt.Scale(range=[30, 300])),
            tooltip=[
                alt.Tooltip("REGISTRO_COMPLEXO:N", title="Complexo"),
                alt.Tooltip("n_salas:Q", title="Salas"),
                alt.Tooltip("meta_fmt:N", title="Meta"),
                alt.Tooltip("obtido_fmt:N", title="Obtido"),
                alt.Tooltip("deficit_fmt:N", title="Déficit"),
                alt.Tooltip("situacao:N", title="Situação"),
            ],
        ).properties(height=420)
    )


def grafico_top_deficit(df: pd.DataFrame, unidade: str, top_n: int = 20):
    df_plot = (df[df["deficit"] < 0]
               .assign(deficit_abs=lambda d: -d["deficit"])
               .sort_values("deficit_abs", ascending=False).head(top_n).copy())
    if df_plot.empty:
        return None
    df_plot["rotulo"] = (df_plot["REGISTRO_COMPLEXO"].astype(str)
                         + " (" + df_plot["n_salas"].astype(str) + " salas)")
    df_plot["deficit_fmt"] = df_plot["deficit_abs"].apply(lambda v: fmt_br(v, 1))
    return (
        alt.Chart(df_plot).mark_bar(color=CORES_SITUACAO["Não cumprida"]).encode(
            y=alt.Y("rotulo:N", sort="-x", title="Complexo (salas)"),
            x=alt.X("deficit_abs:Q", title=f"Déficit ({unidade})"),
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
    df_plot["faixa"] = pd.cut(df_plot["n_salas"],
                              bins=[0, 1, 2, 4, 9, 19, 100],
                              labels=["1", "2", "3–4", "5–9", "10–19", "20+"])
    agg = df_plot.groupby(["faixa", "situacao"], observed=True).size().reset_index(name="complexos")
    return (
        alt.Chart(agg).mark_bar(stroke="#000", strokeWidth=0.4).encode(
            x=alt.X("faixa:N", title="Faixa de salas",
                    sort=["1", "2", "3–4", "5–9", "10–19", "20+"]),
            y=alt.Y("complexos:Q", title="Complexos", stack="zero"),
            color=alt.Color("situacao:N", title="Situação",
                scale=alt.Scale(domain=list(CORES_SITUACAO.keys()),
                                range=list(CORES_SITUACAO.values()))),
            tooltip=["faixa:N", "situacao:N", "complexos:Q"],
        ).properties(height=320)
    )


# ============================================================================
# MAIN
# ============================================================================

def main():
    st.title("🎬 Aferição da Cota de Tela — Brasil (2015–2025)")
    st.caption(
        "Dashboard unificado. Escolha o ano na barra lateral. Cada ano é "
        "calculado conforme o decreto vigente (ou ausência dele)."
    )

    if not PARQUET_PADRAO.exists():
        st.error(f"Parquet não encontrado em `{PARQUET_PADRAO}`.")
        st.stop()

    filtros = render_sidebar()
    ano = filtros["ano"]
    cfg = resolve_config(ano)

    if cfg["regime"] == "R4":
        st.warning(
            f"**{ano} — sem obrigação legal de Cota de Tela.** O art. 55 da MP "
            f"2.228-1/2001 expirou em 2021 e não houve decreto para {ano}. "
            f"A obrigação só foi restabelecida pela Lei 14.814/2024. "
            f"**Não há parâmetro normativo para aferição.**"
        )
        st.stop()

    if cfg.get("obs") == "sem_decreto_nota_oficial":
        st.warning(
            f"**{ano} — aplicação do Decreto {cfg['decreto']} por analogia.**\n\n"
            "A ANCINE registra que não houve decreto em 2019. A Secretaria Especial "
            "da Cultura, em nota oficial de 9/1/2019, sustentou que o Decreto 9.256/2017 "
            "seguiria vigente até ser substituído. Advogados consideraram a interpretação "
            "frágil. Os resultados abaixo são uma **aproximação**, não um comando "
            "normativo inequívoco."
        )

    st.info(
        f"**Ano {ano}** · Regime **{cfg['regime']}** · Decreto **{cfg.get('decreto', '—')}**"
    )

    calcula_afericao(ano)

    where = ["1=1"]
    if filtros["ufs"]:
        where.append(f"UF IN ({','.join(repr(u) for u in filtros['ufs'])})")
    if filtros["complexos"]:
        where.append(f"REGISTRO_COMPLEXO IN ({','.join(str(int(c)) for c in filtros['complexos'])})")
    where_sql = " AND ".join(where)

    df = query(f"SELECT * FROM afericao WHERE n_salas >= ? AND {where_sql}",
               [filtros["porte_min"]])
    if filtros["somente_nao_conformes"]:
        df = df[df["situacao"] == "Não cumprida"]
    if df.empty:
        st.warning("Nenhum complexo atende aos filtros selecionados.")
        st.stop()

    unidade = df["unidade"].iloc[0]
    n = len(df)
    cota_ok = int(df["cota_ok"].sum())
    div_ok = int(df["diversidade_ok"].sum())

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Complexos avaliados", fmt_br(n))
    c2.metric("Cota cumprida", f"{cota_ok} ({fmt_br_pct(100*cota_ok/n if n else 0)})")
    c3.metric("Diversidade cumprida", f"{div_ok} ({fmt_br_pct(100*div_ok/n if n else 0)})")
    c4.metric("Unidade da meta", unidade)

    st.markdown("---")
    st.subheader(f"📌 Aferição por complexo — obtido × meta ({unidade})")
    st.altair_chart(grafico_scatter(df, unidade), use_container_width=True)

    st.markdown("---")
    col_a, col_b = st.columns(2)
    with col_a:
        st.subheader("📉 Maiores déficits")
        fig = grafico_top_deficit(df, unidade)
        if fig is not None:
            st.altair_chart(fig, use_container_width=True)
        else:
            st.success("Nenhum complexo com déficit.")
    with col_b:
        st.subheader("📊 Situação por faixa de salas")
        st.altair_chart(grafico_por_porte(df), use_container_width=True)

    st.markdown("---")
    st.subheader("📋 Aferição por complexo")
    df_tab = df.sort_values(["situacao", "deficit"])
    st.dataframe(
        df_para_exibicao(df_tab, colunas_numericas=["meta", "obtido", "deficit"], casas=1),
        use_container_width=True, hide_index=True,
    )
    st.download_button(
        f"⬇️ Baixar aferição {ano} (CSV)",
        df_tab.to_csv(index=False).encode("utf-8"),
        file_name=f"afericao_cota_{ano}.csv", mime="text/csv",
    )


if __name__ == "__main__":
    main()