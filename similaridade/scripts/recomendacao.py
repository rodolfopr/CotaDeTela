import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

def calcular_matriz_similaridade(caminho_parquet):
    # 1. Carrega os dados
    df = pd.read_parquet(caminho_parquet)
    
    # Remove filmes sem sinopse para evitar erros
    df = df.dropna(subset=['sinopse']).reset_index(drop=True)
    
    # 2. Vetorização TF-IDF (transforma texto em matriz numérica de importância de palavras)
    tfidf = TfidfVectorizer(stop_words='portuguese')
    matriz_tfidf = tfidf.fit_transform(df['sinopse'])
    
    # 3. Calcula a Similaridade de Cossenos entre todos os filmes
    matriz_similaridade = cosine_similarity(matriz_tfidf, matriz_tfidf)
    
    return df, matriz_similaridade

def recomendar_filmes(titulo, df, matriz_similaridade, top_n=5):
    """Retorna os top_n filmes mais similares com base no título original ou PT-BR."""
    # Encontra o índice do filme
    match = df[df['titulo_ptbr'].str.contains(titulo, case=False, na=False) | 
               df['titulo_original'].str.contains(titulo, case=False, na=False)]
    
    if match.empty:
        return f"Filme '{titulo}' não encontrado."
    
    idx = match.index[0]
    
    # Obtém as pontuações de similaridade para esse filme
    scores = list(enumerate(matriz_similaridade[idx]))
    
    # Ordena do mais similar para o menos similar (ignorando ele mesmo)
    scores = sorted(scores, key=lambda x: x[1], reverse=True)
    scores = scores[1:top_n+1]
    
    # Retorna os títulos recomendados
    filmes_recomendados = []
    for i, score in scores:
        nome = df.loc[i, 'titulo_ptbr'] or df.loc[i, 'titulo_original']
        filmes_recomendados.append((nome, score))
        
    return filmes_recomendados