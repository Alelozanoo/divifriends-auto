"""Subida de medios a un almacén compatible con S3, y URLs públicas.

Sirve para Backblaze B2, Cloudflare R2, AWS S3 o cualquier otro con API de S3:
lo único que cambia es S3_ENDPOINT y S3_REGION.

La clave del objeto incluye el hash del contenido, así que volver a preparar
la misma carpeta no vuelve a subir nada ni cambia las URLs ya en la cola.
"""

from __future__ import annotations

import hashlib
import mimetypes
import os
from pathlib import Path

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

OBLIGATORIAS = (
    "S3_ENDPOINT",
    "S3_ACCESS_KEY_ID",
    "S3_SECRET_ACCESS_KEY",
    "S3_BUCKET",
    "S3_PUBLIC_BASE",
)

_cliente = None


def cliente():
    global _cliente
    if _cliente is None:
        faltan = [v for v in OBLIGATORIAS if not os.environ.get(v)]
        if faltan:
            raise SystemExit(f"Faltan variables del almacén: {', '.join(faltan)}")
        _cliente = boto3.client(
            "s3",
            endpoint_url=os.environ["S3_ENDPOINT"].rstrip("/"),
            aws_access_key_id=os.environ["S3_ACCESS_KEY_ID"],
            aws_secret_access_key=os.environ["S3_SECRET_ACCESS_KEY"],
            # Sin límites explícitos, un endpoint inalcanzable deja el proceso
            # colgado minutos reintentando en vez de fallar y decir por qué.
            config=Config(
                signature_version="s3v4",
                region_name=os.environ.get("S3_REGION", "auto"),
                connect_timeout=15,
                read_timeout=120,
                retries={"max_attempts": 3, "mode": "standard"},
            ),
        )
    return _cliente


def _hash(ruta: Path) -> str:
    h = hashlib.sha256()
    with ruta.open("rb") as f:
        for bloque in iter(lambda: f.read(1 << 20), b""):
            h.update(bloque)
    return h.hexdigest()[:16]


def clave_de(ruta: Path, prefijo: str = "ig") -> str:
    return f"{prefijo}/{_hash(ruta)}{ruta.suffix.lower()}"


def subir(ruta: Path, prefijo: str = "ig") -> str:
    """Sube el archivo si no está ya y devuelve su URL pública."""
    bucket = os.environ["S3_BUCKET"]
    base = os.environ["S3_PUBLIC_BASE"].rstrip("/")
    clave = clave_de(ruta, prefijo)
    s3 = cliente()

    try:
        s3.head_object(Bucket=bucket, Key=clave)
    except ClientError as e:
        if e.response["Error"]["Code"] not in ("404", "NoSuchKey", "403"):
            raise
        tipo = mimetypes.guess_type(ruta.name)[0] or "application/octet-stream"
        s3.upload_file(
            str(ruta),
            bucket,
            clave,
            ExtraArgs={"ContentType": tipo, "CacheControl": "public, max-age=31536000"},
        )

    return f"{base}/{clave}"


def borrar(clave: str) -> None:
    cliente().delete_object(Bucket=os.environ["S3_BUCKET"], Key=clave)
