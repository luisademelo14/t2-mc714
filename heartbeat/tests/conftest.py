import sys
from pathlib import Path

# Permite importar detector.py ao executar os testes a partir da raiz.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
