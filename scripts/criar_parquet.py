"""
Consolida os CSVs de bilheteria da ANCINE em um único arquivo Parquet.

Transformações aplicadas durante a consolidação:
  - ORIGEM_OBRA            (a partir de PAIS_OBRA)
  - HORA_SESSAO            (a partir de SESSAO)
  - PERIODO_SESSAO         (a partir de HORA_SESSAO/SESSAO)
  - DIASEMANA_EXIBICAO     (a partir de DATA_EXIBICAO)
  - DIASEMANA_NUM_EXIBICAO (a partir de DATA_EXIBICAO, para ordenação)

Recorte aplicado:
  - DATA_EXIBICAO BETWEEN data_inicio AND data_fim (padrão: 2015-01-01 a 2025-12-31)

Observação sobre tipos:
  Como o read_csv usa all_varchar=true, no nível do SELECT as colunas
  SESSAO e DATA_EXIBICAO ainda são VARCHAR. Por isso, as expressões que
  dependem delas fazem a conversão explícita com strptime(...)::TIPO,
  em vez de referenciar o alias já tipado do SELECT.
"""

import sys
from pathlib import Path

import duckdb

from carrega_arquivos import carrega_arquivos, SEPARADOR, ENCODING

# --- Parâmetros padrão ---

PASTA_RAIZ = Path(__file__).resolve().parent.parent
PASTA_DADOS = PASTA_RAIZ / "data"
NOME_PARQUET = "bilheteria.parquet"

# --- Tipagem explícita das colunas ---

COLUNAS = {
    "DATA_EXIBICAO": "DATE",
    "SESSAO": "TIMESTAMP",
    "TITULO_ORIGINAL": "VARCHAR",
    "TITULO_BRASIL": "VARCHAR",
    "CPB_ROE": "VARCHAR",
    "AUDIO": "VARCHAR",
    "LEGENDADA": "VARCHAR",
    "PAIS_OBRA": "VARCHAR",
    "REGISTRO_SALA": "BIGINT",
    "NOME_SALA": "VARCHAR",
    "PUBLICO": "BIGINT",
    "REGISTRO_GRUPO_EXIBIDOR": "BIGINT",
    "REGISTRO_EXIBIDOR": "BIGINT",
    "REGISTRO_COMPLEXO": "BIGINT",
    "MUNICIPIO_SALA_COMPLEXO": "VARCHAR",
    "UF_SALA_COMPLEXO": "VARCHAR",
    "RAZAO_SOCIAL_EXIBIDORA": "VARCHAR",
    "CNPJ_EXIBIDORA": "VARCHAR",
}

# --- Expressões de conversão reutilizáveis ---

_EXPR_SESSAO_TS = 'strptime("SESSAO", \'%d/%m/%Y %H:%M:%S\')::TIMESTAMP'
_EXPR_DATA_DT = 'strptime("DATA_EXIBICAO", \'%d/%m/%Y\')::DATE'


def _gerar_colunas_select():
    """Gera a lista de colunas com CAST para os tipos corretos."""
    partes = []
    for nome, tipo in COLUNAS.items():
        if tipo == "DATE":
            partes.append(f'strptime("{nome}", \'%d/%m/%Y\')::DATE AS "{nome}"')
        elif tipo == "TIMESTAMP":
            partes.append(f'strptime("{nome}", \'%d/%m/%Y %H:%M:%S\')::TIMESTAMP AS "{nome}"')
        elif tipo in ("BIGINT", "INTEGER"):
            partes.append(f'CAST("{nome}" AS {tipo}) AS "{nome}"')
        else:
            partes.append(f'"{nome}"')
    return ",\n            ".join(partes)


# --- Expressões das transformações ---

def _expr_origem_obra() -> str:
    """
    Expressão SQL que classifica a obra em Nacional/Estrangeira/Não informado.

    Regras:
      - PAIS_OBRA nulo, vazio ou literal 'NULL' -> 'Não informado'
      - PAIS_OBRA contendo 'BRASIL'             -> 'Nacional'
      - demais casos                            -> 'Estrangeira'
    """
    return """
        CASE
            WHEN "PAIS_OBRA" IS NULL
                 OR TRIM("PAIS_OBRA") = ''
                 OR UPPER(TRIM("PAIS_OBRA")) = 'NULL'
                THEN 'Não informado'
            WHEN UPPER("PAIS_OBRA") LIKE '%BRASIL%'
                THEN 'Nacional'
            ELSE 'Estrangeira'
        END
    """.strip()


def _expr_hora_sessao() -> str:
    """
    Expressão SQL que extrai a hora cheia (0–23) da coluna SESSAO.
    Converte explicitamente SESSAO (VARCHAR no nível do SELECT) para TIMESTAMP.
    """
    return f'EXTRACT(HOUR FROM {_EXPR_SESSAO_TS})'


def _expr_periodo_sessao() -> str:
    """
    Expressão SQL que classifica a sessão em Madrugada/Matutino/Vespertino/Noturno.

    Faixas (hora cheia):
      00–05 -> Madrugada
      06–11 -> Matutino
      12–18 -> Vespertino
      19–23 -> Noturno
      NULL  -> Não informado

    Repete a conversão + extração porque o SQL padrão não permite
    referenciar o alias HORA_SESSAO no mesmo SELECT.
    """
    hora = f'EXTRACT(HOUR FROM {_EXPR_SESSAO_TS})'
    return f"""
        CASE
            WHEN {hora} IS NULL THEN 'Não informado'
            WHEN {hora} BETWEEN 0  AND 5  THEN 'Madrugada'
            WHEN {hora} BETWEEN 6  AND 11 THEN 'Matutino'
            WHEN {hora} BETWEEN 12 AND 18 THEN 'Vespertino'
            WHEN {hora} BETWEEN 19 AND 23 THEN 'Noturno'
            ELSE 'Não informado'
        END
    """.strip()


def _expr_diasemana_exibicao() -> str:
    """
    Expressão SQL que mapeia DATA_EXIBICAO para a abreviação do dia
    da semana em português (Dom., Seg., Ter., Qua., Qui., Sex., Sáb.).

    Converte explicitamente DATA_EXIBICAO (VARCHAR no nível do SELECT) para DATE.
    DATA_EXIBICAO nula/inválida -> 'Não informado'.
    """
    dia = f'DAYNAME({_EXPR_DATA_DT})'
    return f"""
        CASE
            WHEN {_EXPR_DATA_DT} IS NULL THEN 'Não informado'
            WHEN {dia} = 'Sunday'    THEN 'Dom.'
            WHEN {dia} = 'Monday'    THEN 'Seg.'
            WHEN {dia} = 'Tuesday'   THEN 'Ter.'
            WHEN {dia} = 'Wednesday' THEN 'Qua.'
            WHEN {dia} = 'Thursday'  THEN 'Qui.'
            WHEN {dia} = 'Friday'    THEN 'Sex.'
            WHEN {dia} = 'Saturday'  THEN 'Sáb.'
            ELSE 'Não informado'
        END
    """.strip()


def _expr_diasemana_num_exibicao() -> str:
    """
    Expressão SQL que devolve o dia da semana como número (0–6),
    seguindo a convenção do DuckDB: 0=Domingo, 1=Segunda, ..., 6=Sábado.

    Usada para ordenar corretamente os dias no dashboard, já que a
    abreviação textual não ordena na sequência da semana.
    DATA_EXIBICAO nula/inválida -> NULL.
    """
    return f'EXTRACT(DOW FROM {_EXPR_DATA_DT})'


# --- Função principal ---

def cria_parquet(
    pasta_csv=None,
    arquivo_parquet=None,
    separador=SEPARADOR,
    encoding=ENCODING,
    memory_limit="4GB",
    threads=2,
    data_inicio="2015-01-01",
    data_fim="2025-12-31",
    verbose=True,
):
    """
    Consolida todos os CSVs de uma pasta em um único arquivo Parquet.

    Parâmetros
    ----------
    pasta_csv : Path | str | None
        Pasta com os CSVs. Se None, usa a pasta padrão do projeto.
    arquivo_parquet : Path | str | None
        Caminho do Parquet de saída. Se None, usa data/bilheteria.parquet.
    separador : str
        Separador dos CSVs. Padrão: ";".
    encoding : str
        Encoding dos CSVs. Padrão: "utf-8".
    memory_limit : str
        Limite de memória do DuckDB. Padrão: "4GB".
    threads : int
        Número de threads. Padrão: 2.
    data_inicio : str
        Data inicial (inclusive) do recorte, no formato 'YYYY-MM-DD'.
        Padrão: '2015-01-01'.
    data_fim : str
        Data final (inclusive) do recorte, no formato 'YYYY-MM-DD'.
        Padrão: '2025-12-31'.
    verbose : bool
        Se True, imprime progresso.

    Retorna
    -------
    Path
        Caminho do arquivo Parquet gerado.
    """
    # Localiza os arquivos
    arquivos = carrega_arquivos(pasta_csv=pasta_csv, verbose=verbose)

    # Define destino
    if arquivo_parquet is None:
        arquivo_parquet = PASTA_DADOS / NOME_PARQUET
    arquivo_parquet = Path(arquivo_parquet)
    arquivo_parquet.parent.mkdir(parents=True, exist_ok=True)

    # Remove Parquet anterior, se existir
    if arquivo_parquet.exists():
        if verbose:
            print(f"\nRemovendo Parquet anterior: {arquivo_parquet}")
        arquivo_parquet.unlink()

    # Pasta onde estão os CSVs
    pasta = Path(arquivos[0]).parent

    # Diretório de spill
    temp_dir = Path("/tmp/duckdb_temp")
    temp_dir.mkdir(parents=True, exist_ok=True)

    if verbose:
        print(f"\nConsolidando {len(arquivos)} arquivos em Parquet...")
        print(f"Recorte: DATA_EXIBICAO BETWEEN {data_inicio} AND {data_fim}")
        print(f"Memory limit: {memory_limit} | Threads: {threads}\n")

    # Conecta ao DuckDB
    con = duckdb.connect()
    con.execute(f"SET memory_limit = '{memory_limit}';")
    con.execute(f"SET threads = {threads};")
    con.execute("SET preserve_insertion_order = false;")
    con.execute(f"SET temp_directory = '{temp_dir}';")

    # Gera a lista de colunas com CAST
    colunas_select = _gerar_colunas_select()

    try:
        con.execute(f"""
            COPY (
                SELECT
                    {colunas_select},
                    {_expr_origem_obra()}           AS "ORIGEM_OBRA",
                    {_expr_hora_sessao()}           AS "HORA_SESSAO",
                    {_expr_periodo_sessao()}        AS "PERIODO_SESSAO",
                    {_expr_diasemana_exibicao()}    AS "DIASEMANA_EXIBICAO",
                    {_expr_diasemana_num_exibicao()} AS "DIASEMANA_NUM_EXIBICAO",
                    regexp_extract(filename, '([^/]+)$', 1) AS arquivo_origem,
                    regexp_extract(filename, '(\\d{{4}})-(\\d{{2}})-s(\\d{{2}})', 1) AS ano,
                    regexp_extract(filename, '(\\d{{4}})-(\\d{{2}})-s(\\d{{2}})', 2) AS mes,
                    regexp_extract(filename, '(\\d{{4}})-(\\d{{2}})-s(\\d{{2}})', 3) AS semana
                FROM read_csv(
                    '{pasta}/*.csv',
                    delim='{separador}',
                    header=true,
                    union_by_name=true,
                    filename=true,
                    all_varchar=true
                )
                WHERE {_EXPR_DATA_DT}
                      BETWEEN DATE '{data_inicio}' AND DATE '{data_fim}'
            ) TO '{arquivo_parquet}' (FORMAT PARQUET, COMPRESSION SNAPPY)
        """)
    except Exception as e:
        con.close()
        raise RuntimeError(f"Falha ao consolidar: {e}")

    # Verificação
    total = con.sql(f"SELECT COUNT(*) FROM '{arquivo_parquet}'").fetchone()[0]

    if total == 0:
        con.close()
        raise RuntimeError(
            f"Nenhuma linha dentro do recorte {data_inicio} a {data_fim}. "
            "Verifique o formato de DATA_EXIBICAO nos CSVs."
        )

    if verbose:
        print(f"Total de linhas: {total:,}")

        print("\nLinhas por ano:")
        df_anos = con.sql(f"""
            SELECT ano, COUNT(*) AS linhas
            FROM '{arquivo_parquet}'
            GROUP BY ano
            ORDER BY ano
        """).df()
        print(df_anos.to_string(index=False))

        print("\nDistribuição por ORIGEM_OBRA:")
        df_origem = con.sql(f"""
            SELECT
                "ORIGEM_OBRA",
                COUNT(*) AS linhas,
                SUM("PUBLICO") AS publico
            FROM '{arquivo_parquet}'
            GROUP BY "ORIGEM_OBRA"
            ORDER BY publico DESC
        """).df()
        print(df_origem.to_string(index=False))

        print("\nDistribuição por HORA_SESSAO:")
        df_hora = con.sql(f"""
            SELECT
                "HORA_SESSAO",
                COUNT(*) AS linhas,
                SUM("PUBLICO") AS publico
            FROM '{arquivo_parquet}'
            GROUP BY "HORA_SESSAO"
            ORDER BY "HORA_SESSAO"
        """).df()
        print(df_hora.to_string(index=False))

        print("\nDistribuição por PERIODO_SESSAO:")
        df_periodo = con.sql(f"""
            SELECT
                "PERIODO_SESSAO",
                COUNT(*) AS linhas,
                SUM("PUBLICO") AS publico
            FROM '{arquivo_parquet}'
            GROUP BY "PERIODO_SESSAO"
            ORDER BY publico DESC
        """).df()
        print(df_periodo.to_string(index=False))

        print("\nDistribuição por DIASEMANA_EXIBICAO (ordenado por número):")
        df_dia = con.sql(f"""
            SELECT
                "DIASEMANA_NUM_EXIBICAO",
                "DIASEMANA_EXIBICAO",
                COUNT(*) AS linhas,
                SUM("PUBLICO") AS publico
            FROM '{arquivo_parquet}'
            GROUP BY "DIASEMANA_NUM_EXIBICAO", "DIASEMANA_EXIBICAO"
            ORDER BY "DIASEMANA_NUM_EXIBICAO"
        """).df()
        print(df_dia.to_string(index=False))

        print("\nChecagem HORA_SESSAO x PERIODO_SESSAO:")
        df_check = con.sql(f"""
            SELECT
                "HORA_SESSAO",
                "PERIODO_SESSAO",
                COUNT(*) AS linhas
            FROM '{arquivo_parquet}'
            GROUP BY "HORA_SESSAO", "PERIODO_SESSAO"
            ORDER BY "HORA_SESSAO"
        """).df()
        print(df_check.to_string(index=False))

        print("\nAmostra:")
        df_amostra = con.sql(f"""
            SELECT * FROM '{arquivo_parquet}' LIMIT 3
        """).df()
        print(df_amostra.to_string(index=False))

        print("\nSchema:")
        df_schema = con.sql(f"DESCRIBE SELECT * FROM '{arquivo_parquet}'").df()
        print(df_schema.to_string(index=False))

    con.close()

    # Resumo
    tamanho_mb = arquivo_parquet.stat().st_size / (1024 * 1024)

    if verbose:
        print(f"\nParquet salvo: {arquivo_parquet}")
        print(f"Tamanho:       {tamanho_mb:.2f} MB")

    return arquivo_parquet


# --- Execução direta ---

if __name__ == "__main__":
    try:
        arquivo = cria_parquet()
        print(f"\nConcluído: {arquivo}")

    except (FileNotFoundError, RuntimeError) as e:
        print(f"\nERRO: {e}")
        sys.exit(1)