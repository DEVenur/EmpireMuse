"""Raiz do projeto, calculada num lugar só para nenhum teste depender da profundidade da sua pasta."""

from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
