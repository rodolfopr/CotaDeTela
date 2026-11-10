"""
Módulo de consulta ao Parquet de bilheteria da ANCINE.

Expõe a função `obter_filmes_nacionais`, que retorna um DataFrame
com uma linha por obra nacional (identificada por CPB_ROE), agregando
métricas de exibição e público.
"""

from pathlib import Path
import duckdb

# --- Parâmetros padrão ---

PASTA_RAIZ = Path(__file__).resolve().parent.parent.parent
ARQUIVO_PARQUET_PADRAO = PASTA_RAIZ / "data" / "bilheteria.parquet"

def obter_filmes_nacionais(
    arquivo_parquet=None,
    *,
    con=None,
    verbose=False,
):
    """
    Retorna as obras nacionais distintas do Parquet de bilheteria da ANCINE.

    Cada linha representa uma obra (identificada por CPB_ROE), com métricas
    agregadas de exibição: período, sessões, dias, salas, público total e
    público médio por sessão.

    Parâmetros
    ----------
    arquivo_parquet : Path | str | None
        Caminho do Parquet gerado por `cria_parquet()`.
        Se None, usa `data/bilheteria.parquet` relativo à raiz do projeto.
    con : duckdb.DuckDBPyConnection | None
        Conexão DuckDB já aberta. Se fornecida, a função NÃO fecha a conexão
        ao final (o chamador é responsável por fechá-la). Se None, a função
        abre e fecha sua própria conexão.
    verbose : bool
        Se True, imprime um resumo ao final.

    Retorna
    -------
    pandas.DataFrame
        Colunas:
          - cpb_roe                    (object)
          - titulo_original            (object)
          - titulo_ptbr                (object)
          - primeira_exibicao          (datetime64[ns])
          - ultima_exibicao            (datetime64[ns])
          - total_sessoes              (int64)
          - dias_com_exibicao          (int64)
          - salas_distintas            (int64)
          - publico_total              (int64)
          - publico_medio_por_sessao   (int64)

    Raises
    ------
    FileNotFoundError
        Se o arquivo Parquet não existir.
    """
    # Resolve caminho do Parquet
    if arquivo_parquet is None:
        arquivo_parquet = ARQUIVO_PARQUET_PADRAO
    arquivo_parquet = Path(arquivo_parquet)

    if not arquivo_parquet.exists():
        raise FileNotFoundError(
            f"Parquet não encontrado: {arquivo_parquet}\n"
            "Rode o script de consolidação (cria_parquet) primeiro."
        )

    # Conexão: usa a fornecida ou abre uma própria
    con_local = con is None
    if con_local:
        con = duckdb.connect()

    try:
        df = con.sql(f"""
            SELECT
                "CPB_ROE"                        AS cpb_roe,
                ANY_VALUE("TITULO_ORIGINAL")     AS titulo_original,
                ANY_VALUE("TITULO_PTBR")         AS titulo_ptbr,
                MIN("DATA_EXIBICAO")             AS primeira_exibicao,
                MAX("DATA_EXIBICAO")             AS ultima_exibicao,
                COUNT(*)                         AS total_sessoes,
                COUNT(DISTINCT "DATA_EXIBICAO")  AS dias_com_exibicao,
                COUNT(DISTINCT ("REGISTRO_COMPLEXO", "REGISTRO_SALA"))
                                                 AS salas_distintas,
                SUM("PUBLICO")::BIGINT           AS publico_total,
                ROUND(SUM("PUBLICO")::DOUBLE / NULLIF(COUNT(*), 0))::BIGINT
                                                 AS publico_medio_por_sessao
            FROM '{arquivo_parquet}'
            WHERE "ORIGEM_OBRA" = 'Nacional'
            GROUP BY "CPB_ROE"
            ORDER BY primeira_exibicao ASC
        """).df()

        if verbose:
            print(f"Obras nacionais distintas: {len(df):,}")
            print(f"Parquet consultado: {arquivo_parquet}")
            if not df.empty:
                print("\nPrimeiras 5 obras:")
                print(df.head(5).to_string(index=False))

        return df

    finally:
        if con_local:
            con.close()


# --- Execução direta (para testar o módulo isoladamente) ---

if __name__ == "__main__":
    df = obter_filmes_nacionais(verbose=True)
    print(f"\nTotal de obras nacionais distintas: {len(df):,}")