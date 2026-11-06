"""
Consolida os CSVs de bilheteria da ANCINE em um único arquivo Parquet.

Transformações aplicadas durante a consolidação:
  - PAIS_OBRA              (corrigido via PAIS_OBRA_POR_CPB quando vazio)
  - ORIGEM_OBRA            (a partir de PAIS_OBRA)
  - TITULO_PTBR            (TITULO_BRASIL, com fallback em TITULO_ORIGINAL)
  - HORA_SESSAO            (a partir de SESSAO)
  - PERIODO_SESSAO         (a partir de HORA_SESSAO/SESSAO)
  - DIASEMANA_EXIBICAO     (a partir de DATA_EXIBICAO)
  - DIASEMANA_NUM_EXIBICAO (a partir de DATA_EXIBICAO, para ordenação)

Recorte aplicado:
  - DATA_EXIBICAO BETWEEN data_inicio AND data_fim (padrão: 2015-01-01 a 2025-12-31)

Exclusões aplicadas:
  - TITULO_ORIGINAL IN (TITULOS_EXCLUIDOS): registros de eventos que não
    são obras cinematográficas com país de origem (Mostras e Festivais,
    Shows e Musicais, Eventos Esportivos, Jogos Eletrônicos).

Observação sobre tipos e estrutura do SELECT:
  O read_csv usa all_varchar=true, então no nível do read_csv as colunas
  DATA_EXIBICAO e SESSAO ainda são VARCHAR.

  A consulta é organizada em dois níveis:

  1. Subselect (sobre o read_csv):
     - Aplica a tipagem (colunas_select) — incluindo strptime em
       DATA_EXIBICAO e SESSAO.
     - Aplica a correção de PAIS_OBRA via PAIS_OBRA_POR_CPB.
     - Filtra o recorte de data e a exclusão de títulos de evento.
     - Projeta também `filename` (necessário no nível externo).

  2. SELECT externo (sobre o subselect):
     - SESSAO e DATA_EXIBICAO já chegam tipadas (TIMESTAMP e DATE).
       Por isso as expressões derivadas NÃO reaplicam strptime.
     - Gera as colunas derivadas (ORIGEM_OBRA, TITULO_PTBR, HORA_SESSAO,
       PERIODO_SESSAO, DIASEMANA_*).
     - Usa `* EXCLUDE (filename)` para que a coluna técnica `filename`
       não vaze para o Parquet — apenas `arquivo_origem` sai.

Observação sobre TITULO_PTBR:
  TITULO_BRASIL e TITULO_ORIGINAL são preservados intactos no Parquet.
  TITULO_PTBR é uma coluna adicional, voltada ao consumo (dashboard),
  que resolve o título a exibir em português.
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

# [PAIS_OBRA_POR_CPB] Correções manuais de PAIS_OBRA por CPB_ROE
#
# Casos em que PAIS_OBRA veio vazio na fonte, mas o país é conhecido
# (identificado por auditoria cruzada com outras linhas do mesmo título).
# Aplicado ANTES de _expr_origem_obra(), de modo que ORIGEM_OBRA já
# reflita o valor corrigido.
#
# Chave: CPB_ROE (string, como vem do CSV)
# Valor: PAIS_OBRA a usar
PAIS_OBRA_POR_CPB = {
    "E2400142000000": "ESTADOS UNIDOS",
}

# [EXCLUSAO_EVENTOS] Títulos de evento excluídos do Parquet
#
# Registros com esses TITULO_ORIGINAL não são obras cinematográficas com
# país de origem — são eventos (mostras, shows, esportivos, e-sports).
# São removidos na origem, via WHERE, antes de qualquer transformação.
# Comparação normalizada (UPPER + TRIM) para tolerar variações de caixa
# e espaço na fonte. ATENÇÃO: UPPER preserva acentos — variações sem
# acento (ex.: 'JOGOS ELETRONICOS') não são capturadas.
TITULOS_EXCLUIDOS = (
    "MOSTRAS E FESTIVAIS",
    "SHOWS E MUSICAIS",
    "EVENTOS ESPORTIVOS",
    "JOGOS ELETRÔNICOS",
)

# --- Expressões de conversão reutilizáveis ---

# Usada APENAS no WHERE do subselect, onde DATA_EXIBICAO ainda é VARCHAR.
_EXPR_DATA_DT = 'strptime("DATA_EXIBICAO", \'%d/%m/%Y\')::DATE'


def _gerar_colunas_select(skip=()):
    """Gera a lista de colunas com CAST para os tipos corretos.

    Parâmetros
    ----------
    skip : iterable[str]
        Nomes de colunas a omitir da projeção. Usado para colunas que
        serão adicionadas depois com transformação, evitando alias
        duplicado no mesmo SELECT (ex.: PAIS_OBRA, que passa pelo mapa
        PAIS_OBRA_POR_CPB).
    """
    partes = []
    for nome, tipo in COLUNAS.items():
        if nome in skip:
            continue
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

    Avaliada no SELECT externo, onde "PAIS_OBRA" já chega corrigido
    pelo subselect (mapa PAIS_OBRA_POR_CPB).

    Observação: como os títulos de evento são excluídos na origem
    (TITULOS_EXCLUIDOS), não é preciso tratar caso especial aqui.
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


# [PAIS_OBRA_POR_CPB] Expressão que aplica o mapa de correção
def _expr_pais_obra_corrigido() -> str:
    """
    Expressão SQL que substitui PAIS_OBRA pelo valor de PAIS_OBRA_POR_CPB
    quando o CPB_ROE estiver no mapa.

    A regra é aplicada apenas quando PAIS_OBRA está vazio/nulo — se a
    fonte já trouxe um país, ele é preservado (o mapa é fallback, não
    sobrescrita).

    Avaliada no SUBSELECT, onde "PAIS_OBRA" e "CPB_ROE" ainda são colunas
    de origem do read_csv (não dependem de projeção prévia).
    """
    if not PAIS_OBRA_POR_CPB:
        return '"PAIS_OBRA"'

    cases = "\n            ".join(
        f'WHEN TRIM("CPB_ROE") = \'{cpb}\' THEN \'{pais}\''
        for cpb, pais in PAIS_OBRA_POR_CPB.items()
    )

    return f"""
        CASE
            WHEN "PAIS_OBRA" IS NOT NULL
             AND TRIM("PAIS_OBRA") <> ''
             AND UPPER(TRIM("PAIS_OBRA")) <> 'NULL'
            THEN "PAIS_OBRA"
            {cases}
            ELSE "PAIS_OBRA"
        END
    """.strip()


# [TITULO_PTBR] Expressão que gera o título a exibir em português
def _expr_titulo_ptbr() -> str:
    """
    Expressão SQL que gera TITULO_PTBR a partir de TITULO_BRASIL,
    usando TITULO_ORIGINAL como fallback quando TITULO_BRASIL
    estiver vazio/nulo.

    Considera vazio (mesma convenção de _expr_origem_obra):
      - NULL
      - string vazia
      - string só com espaços
      - literal 'NULL' textual

    Se ambos estiverem vazios, devolve '' (não propaga 'NULL' textual).
    TITULO_BRASIL e TITULO_ORIGINAL originais são preservados intactos.

    Avaliada no SELECT externo, onde TITULO_BRASIL e TITULO_ORIGINAL
    já chegam do subselect (VARCHAR).
    """
    brasil_vazio = """
        "TITULO_BRASIL" IS NULL
        OR TRIM("TITULO_BRASIL") = ''
        OR UPPER(TRIM("TITULO_BRASIL")) = 'NULL'
    """.strip()

    original_vazio = """
        "TITULO_ORIGINAL" IS NULL
        OR TRIM("TITULO_ORIGINAL") = ''
        OR UPPER(TRIM("TITULO_ORIGINAL")) = 'NULL'
    """.strip()

    return f"""
        CASE
            WHEN NOT ({brasil_vazio}) THEN "TITULO_BRASIL"
            WHEN NOT ({original_vazio}) THEN "TITULO_ORIGINAL"
            ELSE ''
        END
    """.strip()


def _expr_hora_sessao() -> str:
    """
    Extrai a hora cheia (0–23) de SESSAO.

    Avaliada no SELECT externo, onde SESSAO já foi convertida a TIMESTAMP
    pelo colunas_select. NÃO reaplicar strptime aqui.
    """
    return 'EXTRACT(HOUR FROM "SESSAO")'


def _expr_periodo_sessao() -> str:
    """
    Classifica a sessão em Madrugada/Matutino/Vespertino/Noturno.

    Faixas (hora cheia):
      00–05 -> Madrugada
      06–11 -> Matutino
      12–18 -> Vespertino
      19–23 -> Noturno
      NULL  -> Não informado

    Avaliada no SELECT externo, onde SESSAO já é TIMESTAMP.
    NÃO reaplicar strptime aqui.
    """
    hora = 'EXTRACT(HOUR FROM "SESSAO")'
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
    Mapeia DATA_EXIBICAO para a abreviação do dia da semana em português
    (Dom., Seg., Ter., Qua., Qui., Sex., Sáb.).

    Avaliada no SELECT externo, onde DATA_EXIBICAO já foi convertida a DATE
    pelo colunas_select. NÃO reaplicar strptime aqui.
    DATA_EXIBICAO nula/inválida -> 'Não informado'.
    """
    dia = 'DAYNAME("DATA_EXIBICAO")'
    return f"""
        CASE
            WHEN "DATA_EXIBICAO" IS NULL THEN 'Não informado'
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
    Dia da semana como número (0=Domingo, ..., 6=Sábado).

    Avaliada no SELECT externo, onde DATA_EXIBICAO já é DATE.
    NÃO reaplicar strptime aqui.
    DATA_EXIBICAO nula/inválida -> NULL.
    """
    return 'EXTRACT(DOW FROM "DATA_EXIBICAO")'


def _sql_filtro_titulos_excluidos() -> str:
    """
    Gera o predicado SQL de exclusão dos títulos de evento.

    Retorna 'TRUE' (sem filtro) quando TITULOS_EXCLUIDOS está vazio,
    evitando 'IN ()', que é sintaxe inválida.

    Avaliado no SUBSELECT, onde "TITULO_ORIGINAL" ainda é a coluna de
    origem do read_csv (VARCHAR).
    """
    if not TITULOS_EXCLUIDOS:
        return "TRUE"
    lista = ", ".join(f"'{t}'" for t in TITULOS_EXCLUIDOS)
    return f'UPPER(TRIM("TITULO_ORIGINAL")) NOT IN ({lista})'


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
        if TITULOS_EXCLUIDOS:
            print(f"Títulos excluídos: {', '.join(TITULOS_EXCLUIDOS)}")
        print(f"Memory limit: {memory_limit} | Threads: {threads}\n")

    # Conecta ao DuckDB
    con = duckdb.connect()
    con.execute(f"SET memory_limit = '{memory_limit}';")
    con.execute(f"SET threads = {threads};")
    con.execute("SET preserve_insertion_order = false;")
    con.execute(f"SET temp_directory = '{temp_dir}';")

    # Gera a lista de colunas com CAST (PAIS_OBRA é omitido e adicionado
    # depois, com a correção do mapa, para evitar alias duplicado)
    colunas_select = _gerar_colunas_select(skip={"PAIS_OBRA"})

    # [EXCLUSAO_EVENTOS] Predicado de exclusão (TRUE se lista vazia)
    filtro_exclusao = _sql_filtro_titulos_excluidos()

    try:
        con.execute(f"""
            COPY (
                SELECT
                    * EXCLUDE (filename),
                    {_expr_origem_obra()}            AS "ORIGEM_OBRA",
                    {_expr_titulo_ptbr()}            AS "TITULO_PTBR",
                    {_expr_hora_sessao()}            AS "HORA_SESSAO",
                    {_expr_periodo_sessao()}         AS "PERIODO_SESSAO",
                    {_expr_diasemana_exibicao()}     AS "DIASEMANA_EXIBICAO",
                    {_expr_diasemana_num_exibicao()} AS "DIASEMANA_NUM_EXIBICAO",
                    regexp_extract(filename, '([^/]+)$', 1) AS arquivo_origem,
                    regexp_extract(filename, '(\\d{{4}})-(\\d{{2}})-s(\\d{{2}})', 1) AS ano,
                    regexp_extract(filename, '(\\d{{4}})-(\\d{{2}})-s(\\d{{2}})', 2) AS mes,
                    regexp_extract(filename, '(\\d{{4}})-(\\d{{2}})-s(\\d{{2}})', 3) AS semana
                FROM (
                    SELECT
                        {colunas_select},
                        {_expr_pais_obra_corrigido()} AS "PAIS_OBRA",
                        filename
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
                      AND {filtro_exclusao}
                )
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

        # [EXCLUSAO_EVENTOS] Confirmar que os títulos excluídos não estão no Parquet
        if TITULOS_EXCLUIDOS:
            lista = ", ".join(f"'{t}'" for t in TITULOS_EXCLUIDOS)
            print("\nConfirmação de exclusão de títulos de evento:")
            df_excl = con.sql(f"""
                SELECT
                    UPPER(TRIM("TITULO_ORIGINAL")) AS titulo_norm,
                    COUNT(*) AS linhas
                FROM '{arquivo_parquet}'
                WHERE UPPER(TRIM("TITULO_ORIGINAL")) IN ({lista})
                GROUP BY titulo_norm
            """).df()
            if df_excl.empty:
                print("  OK — nenhum título de evento presente no Parquet.")
            else:
                print("  ATENÇÃO — títulos de evento ainda presentes:")
                print(df_excl.to_string(index=False))

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

        # [PAIS_OBRA_POR_CPB] Confirmar que a correção de PAIS_OBRA pegou
        if PAIS_OBRA_POR_CPB:
            lista_cpb = ", ".join(f"'{c}'" for c in PAIS_OBRA_POR_CPB)
            print("\nCorreção de PAIS_OBRA por CPB_ROE:")
            df_fix = con.sql(f"""
                SELECT
                    "CPB_ROE",
                    "PAIS_OBRA",
                    COUNT(*)       AS linhas,
                    SUM("PUBLICO") AS publico
                FROM '{arquivo_parquet}'
                WHERE "CPB_ROE" IN ({lista_cpb})
                GROUP BY "CPB_ROE", "PAIS_OBRA"
                ORDER BY "CPB_ROE"
            """).df()
            print(df_fix.to_string(index=False))

        # [TITULO_PTBR] Cobertura da regra de preenchimento de título
        print("\nCobertura de TITULO_PTBR:")
        df_ptbr = con.sql(f"""
            SELECT
                COUNT(*) FILTER (
                    WHERE "TITULO_PTBR" = "TITULO_ORIGINAL"
                      AND "TITULO_BRASIL" <> "TITULO_ORIGINAL"
                ) AS via_original,
                COUNT(*) FILTER (
                    WHERE "TITULO_PTBR" = "TITULO_BRASIL"
                      AND "TITULO_BRASIL" <> ''
                ) AS via_brasil,
                COUNT(*) FILTER (
                    WHERE "TITULO_PTBR" = ''
                ) AS ainda_vazios,
                COUNT(*) AS total
            FROM '{arquivo_parquet}'
        """).df()
        print(df_ptbr.to_string(index=False))

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