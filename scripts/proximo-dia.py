"""¿Para qué día toca programar el lote siguiente?

La regla: el primer día que no tenga nada en la cola. Si hoy está libre, hoy
—y solo en las franjas que aún no han pasado—. Si hay siete días programados,
el octavo.

    python3 scripts/proximo-dia.py                    # la cuenta por defecto
    python3 scripts/proximo-dia.py fitathome          # otra cuenta
    python3 scripts/proximo-dia.py fitathome --json   # para consumir
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import entorno  # noqa: E402,F401  (carga el .env)
import cola as q  # noqa: E402
import cuentas as reg  # noqa: E402


def calcular(slug: str = reg.POR_DEFECTO):
    # Las franjas de cada marca están en cuentas.json: una cuenta llena no
    # tapa el hueco de otra, así que la cola se mira cuenta por cuenta.
    cuenta = reg.una(slug)
    entradas = [e for e in q.leer() if e.cuenta == slug]
    ahora = datetime.now(q.zona())
    ocupados = {e.fecha[:10] for e in entradas}
    FRANJAS = list(cuenta.franjas)

    dia = ahora.date()
    while True:
        clave = dia.isoformat()
        if clave not in ocupados:
            libres = FRANJAS
            if dia == ahora.date():
                # Hoy solo valen las franjas que no han pasado todavía.
                libres = [f for f in FRANJAS
                          if datetime.strptime(f, "%H:%M").time() > ahora.time()]
            if libres:
                return clave, libres, sorted(ocupados)
        dia += timedelta(days=1)


def main() -> None:
    resto = [a for a in sys.argv[1:] if not a.startswith("--")]
    slug = resto[0] if resto else reg.POR_DEFECTO
    cuenta = reg.una(slug)
    dia, libres, ocupados = calcular(slug)
    if "--json" in sys.argv:
        print(json.dumps({"cuenta": slug, "dia": dia, "franjas": libres,
                          "dias_ocupados": ocupados}, ensure_ascii=False))
        return

    fecha = datetime.strptime(dia, "%Y-%m-%d")
    dias_es = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
    print(f"{cuenta.nombre} — días ya programados: {len(ocupados)}"
          + (f" (hasta el {ocupados[-1]})" if ocupados else ""))
    print(f"Toca programar el {dias_es[fecha.weekday()]} {fecha:%d/%m/%Y}")
    print(f"Franjas libres: {', '.join(libres)}")
    if len(libres) < len(cuenta.franjas):
        print("(hoy ya han pasado algunas franjas)")


if __name__ == "__main__":
    main()
