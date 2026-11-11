import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

def calcular_matriz_similaridade(caminho_parquet):
    print("Lendo o arquivo parquet com fastparquet...")
    df = pd.read_parquet(caminho_parquet, engine='fastparquet')
    
    # Remove filmes sem sinopse para evitar erros
    df = df.dropna(subset=['sinopse']).reset_index(drop=True)
    
    print("Vetorizando as sinopses (TF-IDF)...")
    tfidf = TfidfVectorizer()
    matriz_tfidf = tfidf.fit_transform(df['sinopse'])
    
    print("Calculando a matriz de similaridade de cossenos...")
    matriz_similaridade = cosine_similarity(matriz_tfidf, matriz_tfidf)
    
    return df, matriz_similaridade

def recomendar_filmes(titulo, df, matriz_similaridade, top_n=5):
    match = df[df['titulo_ptbr'].str.contains(titulo, case=False, na=False) | 
               df['titulo_original'].str.contains(titulo, case=False, na=False)]
    
    if match.empty:
        return f"Filme '{titulo}' não encontrado."
    
    idx = match.index[0]
    scores = list(enumerate(matriz_similaridade[idx]))
    scores = sorted(scores, key=lambda x: x[1], reverse=True)
    scores = scores[1:top_n+1]
    
    filmes_recomendados = []
    for i, score in scores:
        nome = df.loc[i, 'titulo_ptbr'] if 'titulo_ptbr' in df.columns and pd.notna(df.loc[i, 'titulo_ptbr']) else df.loc[i, 'titulo_original']
        filmes_recomendados.append((nome, score))
        
    return filmes_recomendados
