"""Cuánto te gusta cada pieza de la galería.

Un número del 1 al 5 por pieza —cinco corazones— guardado aparte, en
`borradores/.favoritos.json`. Aparte y no dentro de la carpeta de cada pieza
por dos razones: la galería se lee en caché con una huella de fechas de las
carpetas, y escribir un archivo dentro invalidaría esa caché en cada clic; y
así el gusto sobrevive a que la pieza se rehaga o se reimporte.

    favoritos.leer()                    → {"job/pieza": 4, ...}
    favoritos.poner("job/pieza", 4)     → lo marca (0 lo quita)
    favoritos.olvidar("job/pieza")      → cuando la pieza deja de existir
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
ARCHIVO = RAIZ / "borradores" / ".favoritos.json"

MAXIMO = 5           # cinco corazones, como toda la vida

_CANDADO = threading.Lock()
_CACHE: dict[str, int] | None = None


def _cargar() -> dict[str, int]:
    global _CACHE
    if _CACHE is not None:
        return _CACHE
    datos: dict[str, int] = {}
    if ARCHIVO.exists():
        try:
            crudo = json.loads(ARCHIVO.read_text(encoding="utf-8"))
            for pieza, nivel in crudo.items():
                # Se admite el formato viejo {"pieza": 4} y uno con más campos.
                if isinstance(nivel, dict):
                    nivel = nivel.get("nivel", 0)
                nivel = int(nivel)
                if nivel > 0:
                    datos[pieza] = min(nivel, MAXIMO)
        except (json.JSONDecodeError, ValueError, AttributeError, OSError):
            # Un archivo roto no puede tumbar el panel: se empieza de cero.
            datos = {}
    _CACHE = datos
    return datos


def _guardar(datos: dict[str, int]) -> None:
    ARCHIVO.parent.mkdir(parents=True, exist_ok=True)
    # Se escribe al lado y se renombra: si el panel se cae a mitad, el archivo
    # que queda es el de antes, entero, y no medio JSON ilegible.
    tmp = ARCHIVO.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(datos, ensure_ascii=False, indent=1),
                   encoding="utf-8")
    os.replace(tmp, ARCHIVO)


def leer() -> dict[str, int]:
    with _CANDADO:
        return dict(_cargar())


def nivel_de(pieza_id: str) -> int:
    with _CANDADO:
        return _cargar().get(pieza_id, 0)


def poner(pieza_id: str, nivel: int) -> int:
    """Marca la pieza. 0 la saca de favoritos."""
    nivel = max(0, min(int(nivel), MAXIMO))
    with _CANDADO:
        datos = _cargar()
        if nivel:
            datos[pieza_id] = nivel
        else:
            datos.pop(pieza_id, None)
        _guardar(datos)
    return nivel


def olvidar(pieza_id: str) -> None:
    """La pieza ya no está: se va también su marca, y las de sus hijas si es
    un encargo entero."""
    with _CANDADO:
        datos = _cargar()
        fuera = [k for k in datos
                 if k == pieza_id or k.startswith(f"{pieza_id}/")]
        if not fuera:
            return
        for k in fuera:
            datos.pop(k, None)
        _guardar(datos)
