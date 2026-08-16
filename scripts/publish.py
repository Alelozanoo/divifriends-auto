"""Publica lo que toca según cola.csv. Esto es lo que corre en el cron.

No sube archivos ni toca posts/: solo lee las URLs que prepare.py ya dejó en
la cola. Si una entrada falla, se marca y se sigue con la siguiente.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import entorno  # noqa: E402,F401  (carga el .env)
import cola as q  # noqa: E402
import ig as api  # noqa: E402

# Si un post lleva más de esto sin salir, no se publica solo: algo se rompió
# y sacar de golpe una semana de contenido atrasado es peor que no sacarlo.
RETRASO_MAX = timedelta(hours=48)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--max", type=int, default=3,
                   help="máximo de publicaciones en esta pasada (por defecto 3)")
    p.add_argument("--dry-run", action="store_true",
                   help="enseña qué publicaría sin llamar a la API")
    p.add_argument("--solo", help="publica esa entrada por id, ignorando la fecha")
    args = p.parse_args()

    entradas = q.leer()
    if not entradas:
        raise SystemExit(f"No hay cola en {q.COLA}")

    ahora = datetime.now(q.zona())

    if args.solo:
        pendientes = [e for e in entradas if e.id == args.solo]
        if not pendientes:
            raise SystemExit(f"No existe la entrada «{args.solo}» en la cola")
    else:
        pendientes = [e for e in entradas if e.vencida(ahora)]

        atrasadas = [e for e in pendientes if ahora - e.cuando > RETRASO_MAX]
        for e in atrasadas:
            retraso = (ahora - e.cuando).days
            e.estado = q.PAUSADO
            e.nota = f"{retraso}d de retraso, en pausa; repróg. la fecha para sacarlo"
            print(f"⏸  {e.id}: {e.nota}")
        pendientes = [e for e in pendientes if e not in atrasadas]

    if not pendientes:
        print(f"Nada que publicar ({ahora:%d/%m %H:%M}).")
        if args.solo is None:
            q.escribir(entradas)
        return

    pendientes = sorted(pendientes, key=lambda e: e.fecha)[: args.max]

    if args.dry_run:
        for e in pendientes:
            print(f"  {e.fecha}  {e.tipo:<8} {e.id}  ({len(e.urls)} medio/s)")
            print(f"      {e.caption[:120]}")
        return

    ig = api.desde_entorno()
    usadas, limite = ig.cuota()
    print(f"Cuota de Instagram: {usadas}/{limite} en las últimas 24 h")

    for e in pendientes:
        # Las stories no gastan la cuota del feed, así que siguen saliendo
        # aunque los posts se hayan quedado sin hueco.
        if e.tipo != "STORY" and usadas >= limite:
            print(f"⏭  {e.id}: cuota agotada, se queda pendiente")
            continue

        print(f"\n→ {e.id} ({e.tipo}, programado {e.fecha})")
        try:
            e.ig_media_id = api.publicar(ig, e.tipo, e.urls, e.caption)
            e.estado = q.PUBLICADO
            e.nota = f"publicado {ahora:%Y-%m-%d %H:%M}"
            if e.tipo != "STORY":
                usadas += 1
            print(f"   publicado, media id {e.ig_media_id}")
        except api.IGError as err:
            e.estado = q.ERROR
            e.nota = str(err)[:300]
            print(f"   ERROR: {e.nota}")

    q.escribir(entradas)


if __name__ == "__main__":
    main()
