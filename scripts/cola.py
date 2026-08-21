"""Lectura y escritura de cola.csv, el calendario editable de publicaciones.

Una sola cola para todas las cuentas: la columna `cuenta` dice de quién es
cada fila. Tener un CSV por marca obligaría a abrir cinco archivos para
saber qué sale mañana, que es justo lo que el calendario viene a resolver.
"""

from __future__ import annotations

import csv
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import cuentas as reg

RAIZ = Path(__file__).resolve().parent.parent
COLA = RAIZ / "cola.csv"

COLUMNAS = ["id", "cuenta", "tipo", "fecha", "estado", "caption", "urls",
            "ig_media_id", "nota"]
FORMATO_FECHA = "%Y-%m-%d %H:%M"

PENDIENTE = "pendiente"
PUBLICADO = "publicado"
ERROR = "error"
PAUSADO = "pausado"


def zona() -> ZoneInfo:
    return ZoneInfo(os.environ.get("TZ_LOCAL", "Europe/Madrid"))


@dataclass
class Entrada:
    id: str
    tipo: str
    fecha: str
    cuenta: str = reg.POR_DEFECTO
    estado: str = PENDIENTE
    caption: str = ""
    urls: list[str] = field(default_factory=list)
    ig_media_id: str = ""
    nota: str = ""

    @property
    def cuando(self) -> datetime:
        return datetime.strptime(self.fecha, FORMATO_FECHA).replace(tzinfo=zona())

    def vencida(self, ahora: datetime | None = None) -> bool:
        return self.estado == PENDIENTE and self.cuando <= (
            ahora or datetime.now(zona())
        )


def leer(ruta: Path = COLA) -> list[Entrada]:
    if not ruta.exists():
        return []
    crudo = ruta.read_text(encoding="utf-8")
    # Si alguien fusiona la cola a mano y deja los marcadores dentro, más vale
    # plantarse aquí que dejar que el cron publique lo que salga de eso.
    if crudo.lstrip().startswith("<<<<<<<") or "\n<<<<<<< " in crudo:
        raise SystemExit(
            f"{ruta} tiene marcadores de conflicto de git: arréglalo a mano "
            f"antes de seguir (o recupera la versión de GitHub)."
        )
    with ruta.open(newline="", encoding="utf-8") as f:
        return [
            Entrada(
                id=fila.get("id") or "",
                cuenta=fila.get("cuenta") or reg.POR_DEFECTO,
                tipo=fila["tipo"],
                fecha=fila["fecha"],
                estado=fila.get("estado") or PENDIENTE,
                caption=fila.get("caption", ""),
                urls=[u for u in (fila.get("urls") or "").split("|") if u],
                ig_media_id=fila.get("ig_media_id", ""),
                nota=fila.get("nota", ""),
            )
            for fila in csv.DictReader(f)
        ]


def escribir(entradas: list[Entrada], ruta: Path = COLA) -> None:
    entradas = sorted(entradas, key=lambda e: (e.fecha, e.cuenta, e.id))
    with ruta.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNAS)
        w.writeheader()
        for e in entradas:
            w.writerow(
                {
                    "id": e.id,
                    "cuenta": e.cuenta,
                    "tipo": e.tipo,
                    "fecha": e.fecha,
                    "estado": e.estado,
                    "caption": e.caption,
                    "urls": "|".join(e.urls),
                    "ig_media_id": e.ig_media_id,
                    "nota": e.nota,
                }
            )
