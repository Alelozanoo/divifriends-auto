"""Carga el .env de la raíz. Se importa lo primero, antes que ig/r2/cola.

En GitHub Actions no hay .env ni python-dotenv: las variables llegan por los
secrets del repo, así que la ausencia de la librería no es un error.
"""

from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent

try:
    from dotenv import load_dotenv
except ImportError:
    pass
else:
    load_dotenv(RAIZ / ".env")
