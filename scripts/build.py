from stlitepack import pack
from pathlib import Path

PASTA_RAIZ = Path(__file__).resolve().parent.parent
ARQUIVO_APP = PASTA_RAIZ / "scripts/dashboard_comparacao.py"
PASTA_SITE = PASTA_RAIZ / "site"

# Empacota o app "app.py" e gera um index.html na pasta "docs"

pack(
    app_file = ARQUIVO_APP,
    output_dir = PASTA_SITE
)