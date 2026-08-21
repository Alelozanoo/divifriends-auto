"""Escanea posts/, normaliza los medios, los sube a R2 y llena cola.csv.

Convención de la carpeta posts/:

    foto.jpg          + foto.txt          -> post de imagen
    reel.mp4          + reel.txt          -> reel
    mi-carrusel/      (1.jpg, 2.jpg, …)   -> carrusel, caption en caption.txt
    stories/algo.jpg                      -> story (sin caption)

Se ejecuta en local, no en CI: es lo único que toca los archivos originales.
Las entradas ya publicadas nunca se reescriben.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import entorno  # noqa: E402,F401  (carga el .env)
import cola as q  # noqa: E402
import cuentas as reg  # noqa: E402
import almacen  # noqa: E402

RAIZ = Path(__file__).resolve().parent.parent
POSTS = RAIZ / "posts"
CACHE = RAIZ / ".medios"

IMAGENES = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".webp", ".tif", ".tiff"}
VIDEOS = {".mp4", ".mov", ".m4v"}

# Límites de Instagram para imágenes de feed.
RATIO_MIN, RATIO_MAX = 0.8, 1.91
ANCHO_MAX, ANCHO_MIN = 1440, 320

CAJA = tuple[int, int]
FEED_4_5: CAJA = (1080, 1350)
FEED_1_1: CAJA = (1080, 1080)
FEED_ANCHO: CAJA = (1080, 566)
VERTICAL: CAJA = (1080, 1920)

DIAS = {"lun": 0, "mar": 1, "mie": 2, "jue": 3, "vie": 4, "sab": 5, "dom": 6}


# --- utilidades ---------------------------------------------------------


def _orden_natural(p: Path):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", p.name)]


def _ejecutar(cmd: list[str]) -> None:
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"{cmd[0]} falló:\n{r.stderr[-1500:]}")


def _probe(ruta: Path) -> dict:
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-print_format", "json",
         "-show_streams", "-show_format", str(ruta)],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        return {}
    return json.loads(r.stdout or "{}")


def _pista(info: dict, tipo: str) -> dict:
    for s in info.get("streams", []):
        if s.get("codec_type") == tipo:
            return s
    return {}


# --- normalización ------------------------------------------------------


def normalizar_imagen(
    origen: Path, destino: Path, tipo: str = "IMAGE", caja: CAJA | None = None
) -> Path:
    """JPEG dentro de los límites de tamaño y ratio que acepta la API.

    Con `caja` se fuerza un formato exacto, que es lo que necesitan los
    carruseles: todos sus elementos tienen que compartir ratio.
    """
    if destino.exists():
        return destino
    destino.parent.mkdir(parents=True, exist_ok=True)

    # Con caja forzada nunca vale el escalado libre: el ratio tiene que salir
    # exacto o el carrusel vuelve a quedar descuadrado.
    forzada = caja is not None
    if caja:
        rango, ancho_max = (0.0, 0.0), caja[0]
    elif tipo == "STORY":
        # Las stories son a pantalla completa; el feed va en vertical 4:5.
        caja, rango, ancho_max = VERTICAL, (0.53, 0.60), 1080
    else:
        caja, rango, ancho_max = FEED_4_5, (RATIO_MIN, RATIO_MAX), ANCHO_MAX

    entrada = origen
    temporal = None
    if origen.suffix.lower() in {".heic", ".heif"} and shutil.which("sips"):
        # ffmpeg no siempre trae decodificador HEIC; en macOS sips sí.
        temporal = destino.with_suffix(".src.jpg")
        _ejecutar(["sips", "-s", "format", "jpeg", str(origen), "--out", str(temporal)])
        entrada = temporal

    v = _pista(_probe(entrada), "video")
    ancho, alto = int(v.get("width", 0)), int(v.get("height", 0))
    if not ancho or not alto:
        raise RuntimeError(f"no se pudieron leer las dimensiones de {origen.name}")
    ratio = ancho / alto

    if not forzada and rango[0] <= ratio <= rango[1]:
        filtro = f"scale='max({ANCHO_MIN},min({ancho_max},iw))':-1"
        cmd = ["ffmpeg", "-y", "-i", str(entrada), "-vf", filtro,
               "-frames:v", "1", "-q:v", "2", str(destino)]
    else:
        # Fuera de ratio: se encaja en la caja sobre un fondo desenfocado de la
        # propia imagen, que es lo que menos canta frente a barras negras.
        w, h = caja
        filtro = (
            f"[0:v]scale={w}:{h}:force_original_aspect_ratio=increase,"
            f"crop={w}:{h},gblur=sigma=40[bg];"
            f"[0:v]scale={w}:{h}:force_original_aspect_ratio=decrease[fg];"
            "[bg][fg]overlay=(W-w)/2:(H-h)/2"
        )
        cmd = ["ffmpeg", "-y", "-i", str(entrada), "-filter_complex", filtro,
               "-frames:v", "1", "-q:v", "2", str(destino)]

    _ejecutar(cmd)
    if temporal:
        temporal.unlink(missing_ok=True)
    return destino


def normalizar_video(origen: Path, destino: Path, max_seg: int | None = None) -> Path:
    """MP4 H.264/AAC con faststart. Solo recodifica si hace falta."""
    if destino.exists():
        return destino
    destino.parent.mkdir(parents=True, exist_ok=True)

    info = _probe(origen)
    v, a = _pista(info, "video"), _pista(info, "audio")
    duracion = float(info.get("format", {}).get("duration", 0) or 0)

    if duracion and duracion < 3:
        raise RuntimeError(f"{origen.name}: dura {duracion:.1f}s, el mínimo son 3s")

    recortar = bool(max_seg and duracion > max_seg)
    hay_que_recodificar = (
        recortar
        or v.get("codec_name") != "h264"
        or (a and a.get("codec_name") != "aac")
        or origen.suffix.lower() != ".mp4"
        or int(v.get("width", 0)) > 1080
    )

    if not hay_que_recodificar:
        shutil.copy2(origen, destino)
        return destino

    cmd = ["ffmpeg", "-y", "-i", str(origen)]
    if recortar:
        cmd += ["-t", str(max_seg)]
    cmd += [
        "-vf", "scale='min(1080,iw)':-2",
        "-c:v", "libx264", "-profile:v", "high", "-pix_fmt", "yuv420p",
        "-crf", "20", "-r", "30",
        "-c:a", "aac", "-b:a", "128k", "-ar", "44100",
        "-movflags", "+faststart", str(destino),
    ]
    _ejecutar(cmd)
    return destino


def caja_carrusel(archivos: list[Path]) -> CAJA:
    """Instagram recorta todo el carrusel al ratio del primer elemento.

    Se elige el formato estándar más cercano a ese primero y se encajan todos
    ahí, en vez de dejar que Instagram recorte los demás por su cuenta.
    """
    v = _pista(_probe(archivos[0]), "video")
    ancho, alto = int(v.get("width", 0)), int(v.get("height", 0))
    if not (ancho and alto):
        return FEED_4_5
    ratio = ancho / alto
    return min(
        (FEED_4_5, FEED_1_1, FEED_ANCHO), key=lambda c: abs(c[0] / c[1] - ratio)
    )


def preparar_medio(origen: Path, tipo: str, caja: CAJA | None = None) -> Path:
    salida = CACHE / origen.relative_to(POSTS).parent
    if origen.suffix.lower() in IMAGENES:
        return normalizar_imagen(origen, salida / f"{origen.stem}.jpg", tipo, caja)

    max_seg = 60 if tipo == "STORY" else 900
    listo = normalizar_video(origen, salida / f"{origen.stem}.mp4", max_seg)

    if tipo in ("REELS", "STORY"):
        v = _pista(_probe(listo), "video")
        alto = int(v.get("height", 0))
        if alto and int(v.get("width", 0)) / alto > 0.9:
            print(f"  ! {origen.name} es horizontal; en {tipo} se ve con franjas")
    return listo


# --- escaneo ------------------------------------------------------------


def _caption_de(ruta: Path) -> str:
    txt = ruta.with_suffix(".txt")
    return txt.read_text(encoding="utf-8").strip() if txt.exists() else ""


def escanear() -> list[dict]:
    """Devuelve las entradas encontradas en posts/, en orden estable."""
    entradas = []
    stories_dir = POSTS / "stories"

    for ruta in sorted(POSTS.iterdir(), key=_orden_natural):
        if ruta.name.startswith(".") or ruta.suffix.lower() == ".txt":
            continue

        if ruta.is_dir() and ruta != stories_dir:
            hijos = [
                h for h in sorted(ruta.iterdir(), key=_orden_natural)
                if h.suffix.lower() in IMAGENES | VIDEOS
            ]
            if len(hijos) < 2:
                print(f"  ! {ruta.name}: un carrusel necesita 2 o más, se salta")
                continue
            caption = ruta / "caption.txt"
            entradas.append({
                "id": ruta.name,
                "tipo": "CAROUSEL",
                "archivos": hijos[:10],
                "caption": caption.read_text(encoding="utf-8").strip()
                if caption.exists() else "",
            })
        elif ruta.is_file() and ruta.suffix.lower() in IMAGENES | VIDEOS:
            entradas.append({
                "id": ruta.stem,
                "tipo": "REELS" if ruta.suffix.lower() in VIDEOS else "IMAGE",
                "archivos": [ruta],
                "caption": _caption_de(ruta),
            })

    if stories_dir.is_dir():
        for ruta in sorted(stories_dir.iterdir(), key=_orden_natural):
            if ruta.suffix.lower() in IMAGENES | VIDEOS:
                entradas.append({
                    "id": f"story-{ruta.stem}",
                    "tipo": "STORY",
                    "archivos": [ruta],
                    "caption": "",
                })

    return entradas


# --- calendario ---------------------------------------------------------


def parsear_slots(texto: str) -> list[tuple[int, int, int]]:
    slots = []
    for trozo in texto.split(","):
        trozo = trozo.strip().lower()
        if not trozo:
            continue
        dia, _, hora = trozo.partition(" ")
        if dia[:3] not in DIAS:
            raise SystemExit(f"día no reconocido en «{trozo}» (usa lun/mar/mie/…)")
        h, _, m = hora.strip().partition(":")
        slots.append((DIAS[dia[:3]], int(h), int(m or 0)))
    if not slots:
        raise SystemExit("no se ha podido leer ningún slot")
    return slots


def calendario(desde: datetime, slots, cuantos: int) -> list[datetime]:
    """Genera las próximas `cuantos` fechas que caen en los slots dados."""
    fechas, dia = [], desde.replace(hour=0, minute=0, second=0, microsecond=0)
    while len(fechas) < cuantos:
        for wd, h, m in sorted(slots):
            if dia.weekday() != wd:
                continue
            cuando = dia.replace(hour=h, minute=m)
            if cuando > desde:
                fechas.append(cuando)
                if len(fechas) == cuantos:
                    break
        dia += timedelta(days=1)
    return fechas


# --- principal ----------------------------------------------------------


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--slots", default="lun 09:30, mie 09:30, vie 19:00",
                   help='franjas de publicación, p. ej. "lun 09:30, jue 19:00"')
    p.add_argument("--desde", help="primera fecha candidata (YYYY-MM-DD [HH:MM])")
    p.add_argument("--dry-run", action="store_true",
                   help="enseña lo que haría sin subir nada ni tocar la cola")
    p.add_argument("--cuenta", default=reg.POR_DEFECTO,
                   help="a qué cuenta van estos posts (ver cuentas.json)")
    args = p.parse_args()
    cuenta = reg.una(args.cuenta)

    entradas = escanear()
    if not entradas:
        raise SystemExit(f"No hay nada en {POSTS}")

    existentes = {e.id: e for e in q.leer()}
    nuevas = [e for e in entradas if e["id"] not in existentes]

    print(f"{len(entradas)} entradas en posts/, {len(nuevas)} sin programar "
          f"→ {cuenta.nombre}")
    if not nuevas:
        return

    desde = datetime.now(q.zona())
    if args.desde:
        crudo = args.desde if " " in args.desde else f"{args.desde} 00:00"
        desde = datetime.strptime(crudo, q.FORMATO_FECHA).replace(tzinfo=q.zona())

    fechas = calendario(desde, parsear_slots(args.slots), len(nuevas))

    if args.dry_run:
        for entrada, cuando in zip(nuevas, fechas):
            print(f"  {cuando:%a %d/%m %H:%M}  {entrada['tipo']:<8} {entrada['id']}")
        return

    for entrada, cuando in zip(nuevas, fechas):
        print(f"\n→ {entrada['id']} ({entrada['tipo']})")
        caja = (
            caja_carrusel(entrada["archivos"])
            if entrada["tipo"] == "CAROUSEL"
            else None
        )
        urls = []
        for archivo in entrada["archivos"]:
            listo = preparar_medio(archivo, entrada["tipo"], caja)
            # Cada marca en su carpeta del bucket: si algún día hay que
            # llevarse una cuenta a otro sitio, se sabe qué es suyo.
            url = almacen.subir(listo, prefijo=f"ig/{cuenta.slug}")
            print(f"    {archivo.name} → {url}")
            urls.append(url)

        existentes[entrada["id"]] = q.Entrada(
            id=entrada["id"],
            cuenta=cuenta.slug,
            tipo=entrada["tipo"],
            fecha=cuando.strftime(q.FORMATO_FECHA),
            estado=q.PENDIENTE,
            caption=entrada["caption"],
            urls=urls,
        )

    q.escribir(list(existentes.values()))
    print(f"\nCola actualizada: {q.COLA}")
    print("Revisa las fechas y los textos, y haz commit + push del CSV.")


if __name__ == "__main__":
    main()
