import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

def calcular_matriz_similaridade(caminho_parquet):
    print("Lendo o arquivo parquet com fastparquet...")
    df = pd.read_parquet(caminho_parquet, engine='fastparquet')
    
    # Remove filmes sem sinopse para evitar erros
    df = df.dropna(subset=['sinopse']).reset_index(drop=True)
    
    # Cria a coluna padronizada de exibição (priorizando o título em português)
    df['titulo_exibicao'] = df['titulo_ptbr'].fillna(df['titulo_original'])
    
    print("Vetorizando as sinopses (TF-IDF)...")
    tfidf = TfidfVectorizer()
    matriz_tfidf = tfidf.fit_transform(df['sinopse'])
    
    print("Calculando a matriz de similaridade de cossenos...")
    matriz_similaridade = cosine_similarity(matriz_tfidf, matriz_tfidf)
    
    return df, matriz_similaridade

def recomendar_filmes(titulo_exibicao, df, matriz_similaridade, top_n=5):
    match = df[df['titulo_exibicao'] == titulo_exibicao]
    
    if match.empty:
        return []
    
    idx = match.index[0]
    scores = list(enumerate(matriz_similaridade[idx]))
    scores = sorted(scores, key=lambda x: x[1], reverse=True)
    scores = scores[1:top_n+1]
    
    filmes_recomendados = []
    for i, score in scores:
        row = df.loc[i]
        filmes_recomendados.append({
            'titulo': row['titulo_exibicao'],
            'sinopse': row['sinopse'],
            'score': score
        })
        
    return filmes_recomendados

def obter_detalhes_filme(titulo_exibicao, df):
    match = df[df['titulo_exibicao'] == titulo_exibicao]
    if match.empty:
        return None
    return match.iloc[0]