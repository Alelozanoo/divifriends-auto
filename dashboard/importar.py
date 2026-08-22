"""Meter en la galería lo que ya estaba hecho antes de que existiera el panel.

En ~/Desktop/Divi hay años de trabajo repartido por carpetas: los reels en
`Reels/<nombre>/`, las imágenes en `Piezas/…`, y los textos de esas imágenes en
`ig-autopost/posts/` junto a los PNG. Esto lo recorre y lo deja visible en la
galería, cada pieza con su texto si lo tiene.

    ./.venv/bin/python dashboard/importar.py            # a la galería
    ./.venv/bin/python dashboard/importar.py --seco     # solo enseña qué haría

**Los medios se enlazan, no se copian.** Son 90 MB de vídeo y sus originales ya
están ordenados en Divi; duplicarlos sería tener dos verdades.

Eso sí: borrar una pieza desde el panel **sí se lleva el original**, a la
Papelera del Mac —la carpeta entera del reel cuando la carpeta es suya y solo
suya—. Limpiar la galería es limpiar el archivo, no dejar los 90 MB huérfanos
detrás. A la Papelera y no al vacío, para que se pueda deshacer.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "scripts"))
sys.path.insert(0, str(RAIZ / "dashboard"))

import cola as q          # noqa: E402
import cuentas as reg     # noqa: E402
import generador as gen   # noqa: E402

DIVI = Path.home() / "Desktop" / "Divi"

# De dónde sale cada cosa. La etiqueta da nombre al lote dentro de la galería.
VIDEOS = DIVI / "Reels"
IMAGENES = [
    (RAIZ / "posts", "posts"),
    (DIVI / "Piezas" / "DiviFriends-Lote-41", "lote-41"),
    (DIVI / "Piezas" / "Instagram que me gustan", "favoritos"),
]

EXT_IMAGEN = {".png", ".jpg", ".jpeg", ".webp"}


def _titulo(nombre: str) -> str:
    """De «45-tres-cosas» a «Tres cosas»."""
    limpio = re.sub(r"^\d+[-_]?", "", nombre).replace("-", " ").replace("_", " ")
    limpio = re.sub(r"^DiviFriends ?(Reel)? ?", "", limpio, flags=re.I).strip()
    return (limpio[:1].upper() + limpio[1:]) if limpio else nombre


def _caption_de(medio: Path) -> str:
    """El .txt hermano, lo busque donde lo busque."""
    for candidato in (medio.with_suffix(".txt"),
                      RAIZ / "posts" / f"{medio.stem}.txt"):
        if candidato.exists():
            return candidato.read_text(encoding="utf-8").strip()
    return ""


def _mejor_video(carpeta: Path) -> Path | None:
    """El montaje con sonido manda; el mudo solo si no hay otro."""
    con_son = sorted(carpeta.glob("*-son.mp4"))
    if con_son:
        return con_son[0]
    sueltos = [p for p in sorted(carpeta.glob("*.mp4")) if not p.name.endswith("-son.mp4")]
    return sueltos[0] if sueltos else None


def _ya_en_la_cola() -> set[str]:
    """Nombres base de lo que ya está programado o publicado: no vuelve a entrar."""
    vistos = set()
    for e in q.leer():
        vistos.add(e.id)
        for url in e.urls:
            vistos.add(Path(url).stem)
    return vistos


def _asentar(destino: Path, medios: list[Path], titulo: str, caption: str,
             tipo: str, seco: bool) -> None:
    if seco:
        return
    destino.mkdir(parents=True, exist_ok=True)
    for orden, medio in enumerate(medios, 1):
        # Con varios, el nombre numerado fija el orden del carrusel.
        nombre = f"{orden:02d}{medio.suffix}" if len(medios) > 1 else medio.name
        enlace = destino / nombre
        if enlace.is_symlink() or enlace.exists():
            enlace.unlink()
        enlace.symlink_to(medio)
    (destino / "caption.txt").write_text(caption, encoding="utf-8")
    (destino / "ficha.json").write_text(
        json.dumps({"tipo": tipo, "titulo": titulo}, ensure_ascii=False),
        encoding="utf-8")


def _encargo(job: Path, cuenta: str, modo: str, de_donde: str, seco: bool) -> None:
    if seco:
        return
    job.mkdir(parents=True, exist_ok=True)
    (job / "encargo.json").write_text(json.dumps({
        "cuenta": cuenta, "modo": modo,
        "brief": f"importado de {de_donde}",
    }, ensure_ascii=False, indent=1), encoding="utf-8")


def importar(slug: str, seco: bool = False) -> dict:
    cuenta = reg.una(slug)
    fuera = _ya_en_la_cola()
    resumen = {"reels": 0, "imagenes": 0, "carruseles": 0, "saltados": 0}

    # ── vídeos ─────────────────────────────────────────────────────────
    if VIDEOS.is_dir():
        job = gen.BORRADORES / f"{slug}-archivo-reels"
        _encargo(job, slug, gen.VIDEO, "Divi/Reels", seco)
        for carpeta in sorted(VIDEOS.iterdir()):
            if not carpeta.is_dir():
                continue
            medio = _mejor_video(carpeta)
            if medio is None:
                continue
            if medio.stem in fuera or carpeta.name in fuera:
                resumen["saltados"] += 1
                continue
            destino = job / carpeta.name
            if destino.exists():
                resumen["saltados"] += 1
                continue
            _asentar(destino, [medio], _titulo(carpeta.name),
                     _caption_de(medio), "REELS", seco)
            resumen["reels"] += 1
            print(f"  reel      {carpeta.name:<24} ← {medio.name}")

    # ── imágenes ───────────────────────────────────────────────────────
    for origen, etiqueta in IMAGENES:
        if not origen.is_dir():
            continue
        job = gen.BORRADORES / f"{slug}-archivo-{etiqueta}"
        _encargo(job, slug, gen.FOTO, f"{origen.name}", seco)

        for hijo in sorted(origen.iterdir()):
            if hijo.name.startswith("."):
                continue

            # Una carpeta de imágenes numeradas es un carrusel, no diez posts.
            if hijo.is_dir():
                partes = [p for p in sorted(hijo.iterdir())
                          if p.suffix.lower() in EXT_IMAGEN]
                if not 2 <= len(partes) <= 10:
                    continue
                if hijo.name in fuera or (job / hijo.name).exists():
                    resumen["saltados"] += 1
                    continue
                _asentar(job / hijo.name, partes, _titulo(hijo.name),
                         _caption_de(hijo / hijo.name), "CAROUSEL", seco)
                resumen["carruseles"] += 1
                print(f"  carrusel  {hijo.name:<24} ({len(partes)} imágenes)")
                continue

            if hijo.suffix.lower() not in EXT_IMAGEN:
                continue
            if hijo.stem in fuera or (job / hijo.stem).exists():
                resumen["saltados"] += 1
                continue
            _asentar(job / hijo.stem, [hijo], _titulo(hijo.stem),
                     _caption_de(hijo), "IMAGE", seco)
            resumen["imagenes"] += 1
            print(f"  imagen    {hijo.stem:<24} ← {etiqueta}")

    return resumen


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cuenta", default=reg.POR_DEFECTO)
    p.add_argument("--seco", action="store_true",
                   help="enseña qué entraría sin tocar nada")
    args = p.parse_args()

    print(f"Importando a la galería de {reg.una(args.cuenta).nombre}"
          f"{' (en seco)' if args.seco else ''}:\n")
    r = importar(args.cuenta, args.seco)
    print(f"\n  {r['reels']} reels · {r['imagenes']} imágenes · "
          f"{r['carruseles']} carruseles"
          f"{f' · {r[chr(115)+chr(97)+chr(108)+chr(116)+chr(97)+chr(100)+chr(111)+chr(115)]} ya estaban' if r['saltados'] else ''}")


if __name__ == "__main__":
    main()
