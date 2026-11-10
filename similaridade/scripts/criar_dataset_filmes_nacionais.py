"""
Enriquece o DataFrame de filmes nacionais com dados do TMDb (sinopse, pôster).
"""

import getpass
import os
import time
from pathlib import Path

import pandas as pd
import tmdbsimple as tmdb

# Importa a função do seu script existente
from obter_filmes_nacionais import obter_filmes_nacionais


# --- Configuração da API TMDb ---
# [AJUSTE] Chave lida de variável de ambiente ou pedida via getpass
# (não fica exposta no código nem no histórico do shell).
tmdb.API_KEY = os.environ.get("TMDB_API_KEY")

if not tmdb.API_KEY:
    print("Chave de API do TMDb não encontrada na variável TMDB_API_KEY.")
    tmdb.API_KEY = getpass.getpass(
        "Digite sua chave de API do TMDb (não será exibida): "
    ).strip()

if not tmdb.API_KEY:
    raise SystemExit("Nenhuma chave de API informada. Encerrando.")

tmdb.REQUESTS_TIMEOUT = 5  # segundos


# --- Caminhos ---
def _encontrar_pasta_similaridade(inicio: Path) -> Path:
    """Sobe a partir de `inicio` até encontrar um diretório chamado 'similaridade'."""
    for candidato in [inicio, *inicio.parents]:
        if candidato.name == "similaridade":
            return candidato
    raise FileNotFoundError(
        f"Não encontrei a pasta 'similaridade' subindo a partir de {inicio}"
    )


PASTA_SIMILARIDADE = _encontrar_pasta_similaridade(Path(__file__).resolve().parent)
ARQUIVO_SAIDA = PASTA_SIMILARIDADE / "data" / "filmes_nacionais_enriquecidos.parquet"


def buscar_id_tmdb(titulo_original: str, titulo_ptbr: str | None = None) -> int | None:
    """
    Tenta encontrar o ID de um filme no TMDb.
    Prioriza o título original; se não encontrar, tenta o título em português.
    """
    search = tmdb.Search()

    # Tentativa 1: Título original
    try:
        search.movie(query=titulo_original)
        if search.results:
            return search.results[0]["id"]
    except Exception as e:
        print(f"  Erro na busca por '{titulo_original}': {e}")

    # Tentativa 2: Título em português (se for diferente e existir)
    if titulo_ptbr and titulo_ptbr.strip() != titulo_original.strip():
        try:
            search.movie(query=titulo_ptbr)
            if search.results:
                return search.results[0]["id"]
        except Exception as e:
            print(f"  Erro na busca por '{titulo_ptbr}': {e}")

    return None


def criar_dataset_filmes_nacionais():
    """Orquestra o processo de enriquecimento e salva o resultado."""
    print("1. Obtendo filmes nacionais do Parquet de bilheteria...")
    df = obter_filmes_nacionais(verbose=True)

    if df.empty:
        print("Nenhum filme nacional encontrado. Encerrando.")
        return df

    # Listas para armazenar os novos dados
    sinopses: list[str | None] = []
    poster_paths: list[str | None] = []
    tmdb_ids: list[int | None] = []  # [AJUSTE] guardar o ID encontrado

    total = len(df)
    print(f"\n2. Buscando dados no TMDb para {total} filmes...")

    # [AJUSTE] Usar enumerate em vez de index do DataFrame
    # (o index pode não ser 0..n-1 se o DataFrame vier filtrado/ordenado).
    for i, (_, row) in enumerate(df.iterrows(), start=1):
        titulo_orig = row["titulo_original"]
        titulo_ptbr = row.get("titulo_ptbr")

        print(f"  [{i}/{total}] Processando: {titulo_orig}")

        tmdb_id = buscar_id_tmdb(titulo_orig, titulo_ptbr)

        sinopse = None
        poster_path = None

        if tmdb_id:
            try:
                # Busca detalhes do filme, solicitando o idioma português (pt-BR)
                movie = tmdb.Movies(tmdb_id)
                movie.info(language="pt-BR")
                sinopse = movie.overview
                poster_path = movie.poster_path
                print(
                    f"    -> Encontrado (ID: {tmdb_id}). "
                    f"Sinopse: {'Sim' if sinopse else 'Não'} | "
                    f"Pôster: {'Sim' if poster_path else 'Não'}"
                )
            except Exception as e:
                print(f"    -> Erro ao buscar detalhes para ID {tmdb_id}: {e}")
        else:
            print("    -> Não encontrado no TMDb.")

        sinopses.append(sinopse)
        poster_paths.append(poster_path)
        tmdb_ids.append(tmdb_id)

        # Pausa para respeitar o limite de requisições (aproximadamente 40/s)
        time.sleep(0.05)

    # 3. Adiciona as novas colunas ao DataFrame
    # [AJUSTE] Adiciona tmdb_id (útil para auditoria e para não repetir buscas)
    df["tmdb_id"] = tmdb_ids
    df["sinopse"] = sinopses
    df["poster_path"] = poster_paths

    # [AJUSTE] Monta a URL completa do pôster (campo derivado, mais útil no consumo)
    # O TMDb devolve caminho relativo (ex.: /abc.jpg); a base fica em image.tmdb.org.
    base_img = "https://image.tmdb.org/t/p/w500"
    df["poster_url"] = df["poster_path"].apply(
        lambda p: f"{base_img}{p}" if isinstance(p, str) and p else None
    )

    # 4. Salva o DataFrame enriquecido em um novo arquivo Parquet
    print(f"\n3. Salvando dados enriquecidos em: {ARQUIVO_SAIDA}")
    ARQUIVO_SAIDA.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(ARQUIVO_SAIDA, index=False)

    print("\nProcesso concluído!")
    print(f"Total de filmes processados: {len(df)}")
    print(f"Filmes com ID no TMDb: {df['tmdb_id'].notna().sum()}")
    print(f"Filmes com sinopse:   {df['sinopse'].notna().sum()}")
    print(f"Filmes com pôster:    {df['poster_path'].notna().sum()}")

    return df


if __name__ == "__main__":
    criar_dataset_filmes_nacionais()