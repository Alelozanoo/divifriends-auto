"""Lectura y escritura de cola.csv, el calendario editable de publicaciones."""

from __future__ import annotations

import csv
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

RAIZ = Path(__file__).resolve().parent.parent
COLA = RAIZ / "cola.csv"

COLUMNAS = ["id", "tipo", "fecha", "estado", "caption", "urls", "ig_media_id", "nota"]
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
    with ruta.open(newline="", encoding="utf-8") as f:
        return [
            Entrada(
                id=fila["id"],
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
    entradas = sorted(entradas, key=lambda e: e.fecha)
    with ruta.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNAS)
        w.writeheader()
        for e in entradas:
            w.writerow(
                {
                    "id": e.id,
                    "tipo": e.tipo,
                    "fecha": e.fecha,
                    "estado": e.estado,
                    "caption": e.caption,
                    "urls": "|".join(e.urls),
                    "ig_media_id": e.ig_media_id,
                    "nota": e.nota,
                }
            )
