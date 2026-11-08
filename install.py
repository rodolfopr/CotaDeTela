"""
Script de instalação / preparação do projeto CotaDeTela.

Executa os scripts na ordem correta:
  1. baixa os dados de bilheteria da ANCINE
  2. carrega e lista os CSVs
  3. verifica o schema dos arquivos
  4. consolida tudo em data/bilheteria.parquet

Após a execução, o dashboard pode ser iniciado manualmente com:
    streamlit run scripts/dashboard_basico.py
"""

import subprocess
import sys
from pathlib import Path

PASTA_RAIZ = Path(__file__).resolve().parent
PASTA_SRC = PASTA_RAIZ / "scripts"

SCRIPTS = [
    "baixa_arquivos.py",
    "carrega_arquivos.py",
    "verifica_arquivos.py",
    "criar_parquet.py",
]


def roda_script(nome):
    caminho = PASTA_SRC / nome
    print(f"\n{'=' * 60}")
    print(f"  Rodando: {nome}")
    print(f"{'=' * 60}\n")

    resultado = subprocess.run([sys.executable, str(caminho)])
    if resultado.returncode != 0:
        print(f"\nERRO em {nome} (código {resultado.returncode})")
        sys.exit(resultado.returncode)


def main():
    print("Iniciando instalação / preparação dos dados...\n")

    for script in SCRIPTS:
        roda_script(script)

    print(f"\n{'=' * 60}")
    print("  Instalação concluída com sucesso!")
    print("  Para abrir o dashboard, execute:")
    print("    streamlit run scripts/dashboard_basico.py")
    print(f"{'=' * 60}\n")


if __name__ == "__main__":
    main()