"""
Executa os scripts do projeto na ordem correta e, ao final,
sobe o dashboard Streamlit.
"""

import subprocess
import sys
from pathlib import Path

PASTA_SRC = Path(__file__).resolve().parent / "scripts"

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


def roda_dashboard():
    dashboard = PASTA_SRC / "dashboard_basico.py"
    print(f"\n{'=' * 60}")
    print(f"  Subindo: dashboard_basico.py")
    print(f"{'=' * 60}\n")

    subprocess.run(
        [sys.executable, "-m", "streamlit", "run", str(dashboard)],
    )


if __name__ == "__main__":
    for script in SCRIPTS:
        roda_script(script)

    roda_dashboard()