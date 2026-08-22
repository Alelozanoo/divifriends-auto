"""Miniaturas para la galería, hechas una vez y guardadas.

La galería pedía los archivos originales: PNG de dos megas y mp4 enteros con
`preload="metadata"` para sacarles un fotograma. Con cien piezas eso son
cientos de megas y treinta y cinco decodificaciones de vídeo cada vez que
abres la pestaña, y se nota.

Aquí cada pieza se reduce una vez a un JPEG de 480 px y se guarda en
`borradores/.miniaturas/`. Se rehace sola si el original cambia, porque la
clave lleva el tamaño y la fecha del archivo dentro.
"""

from __future__ import annotations

import hashlib
import shutil
import subprocess
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
BORRADORES = RAIZ / "borradores"
CACHE = BORRADORES / ".miniaturas"

ANCHO = 480
VIDEOS = {".mp4", ".mov", ".m4v"}

# ffmpeg y ffprobe se comen la entrada estándar si se la dejas: heredarla
# cuelga el proceso hasta que salta el timeout, y con ello el hilo que estaba
# leyendo la galería. Todas las llamadas van con stdin cerrado.

# (ancho, alto) de cada original, para que la carta reserve su hueco con el
# aspecto bueno antes de que la imagen llegue.
_MEDIDAS: dict[tuple, tuple[int, int]] = {}


def _marca(ruta: Path) -> tuple | None:
    try:
        st = ruta.stat()
    except OSError:
        return None
    return (str(ruta), st.st_mtime_ns, st.st_size)


def medidas(ruta: Path) -> tuple[int, int]:
    """(ancho, alto) del original. (0, 0) si no se puede saber."""
    marca = _marca(ruta)
    if marca is None:
        return (0, 0)
    if marca in _MEDIDAS:
        return _MEDIDAS[marca]

    tam = (0, 0)
    if ruta.suffix.lower() in VIDEOS:
        if shutil.which("ffprobe"):
            r = subprocess.run(
                ["ffprobe", "-v", "quiet", "-select_streams", "v:0",
                 "-show_entries", "stream=width,height", "-of", "csv=p=0:s=x",
                 str(ruta)], capture_output=True, text=True, timeout=20,
                stdin=subprocess.DEVNULL)
            partes = r.stdout.strip().split("x")
            if len(partes) >= 2 and all(p.isdigit() for p in partes[:2]):
                tam = (int(partes[0]), int(partes[1]))
    else:
        try:
            from PIL import Image
            with Image.open(ruta) as im:
                tam = im.size
        except Exception:
            tam = (0, 0)

    _MEDIDAS[marca] = tam
    return tam


def _clave(ruta: Path) -> str:
    marca = _marca(ruta)
    return hashlib.sha256(str(marca).encode()).hexdigest()[:20]


def mini(ruta: Path) -> Path | None:
    """La miniatura de ese medio, generándola si hace falta."""
    if not ruta.is_file():
        return None
    CACHE.mkdir(parents=True, exist_ok=True)
    destino = CACHE / f"{_clave(ruta)}.jpg"
    if destino.exists():
        return destino

    try:
        if ruta.suffix.lower() in VIDEOS:
            if not shutil.which("ffmpeg"):
                return None
            # Un fotograma con algo dentro: al arrancar suele estar en negro.
            subprocess.run(
                ["ffmpeg", "-v", "error", "-nostdin", "-ss", "0.8", "-i", str(ruta),
                 "-frames:v", "1", "-vf", f"scale={ANCHO}:-2",
                 "-q:v", "4", "-y", str(destino)],
                check=True, timeout=60, capture_output=True,
                stdin=subprocess.DEVNULL)
        else:
            from PIL import Image
            with Image.open(ruta) as im:
                im = im.convert("RGB")
                im.thumbnail((ANCHO, ANCHO * 3), Image.LANCZOS)
                im.save(destino, "JPEG", quality=82, optimize=True)
    except Exception:
        if destino.exists():
            destino.unlink()
        return None
    return destino if destino.exists() else None


def limpiar() -> int:
    """Tira la caché entera. Se rehace sola."""
    if not CACHE.exists():
        return 0
    cuantas = len(list(CACHE.glob("*.jpg")))
    shutil.rmtree(CACHE, ignore_errors=True)
    return cuantas
