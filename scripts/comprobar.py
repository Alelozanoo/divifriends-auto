"""Revisión de que todo está en su sitio: .env, acceso a R2 y acceso a Instagram.

No publica nada y no imprime ningún secreto: de las credenciales solo enseña
longitud y un par de caracteres, lo justo para detectar un copiado a medias.

    python3 scripts/comprobar.py
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))

import entorno  # noqa: E402,F401  (carga el .env)

import os  # noqa: E402

OBLIGATORIAS = [
    "IG_USER_ID",
    "IG_ACCESS_TOKEN",
    "S3_ENDPOINT",
    "S3_ACCESS_KEY_ID",
    "S3_SECRET_ACCESS_KEY",
    "S3_BUCKET",
    "S3_PUBLIC_BASE",
]
SECRETAS = {"IG_ACCESS_TOKEN", "S3_SECRET_ACCESS_KEY", "S3_ACCESS_KEY_ID"}


def enmascarar(nombre: str, valor: str) -> str:
    if nombre not in SECRETAS:
        return valor
    return f"{valor[:4]}…{valor[-2:]}  ({len(valor)} caracteres)"


def revisar_entorno() -> bool:
    print("VARIABLES DE ENTORNO")
    todo_ok = True
    for nombre in OBLIGATORIAS:
        valor = (os.environ.get(nombre) or "").strip()
        if not valor:
            print(f"  ✗ {nombre} vacía")
            todo_ok = False
        else:
            print(f"  ✓ {nombre} = {enmascarar(nombre, valor)}")

    base = (os.environ.get("S3_PUBLIC_BASE") or "").strip()
    if base and not base.startswith("http"):
        print("  ! S3_PUBLIC_BASE debería empezar por https://")
        todo_ok = False
    if base.endswith("/"):
        print("  ! S3_PUBLIC_BASE sobra la barra final (se le quita sola, pero mejor)")
    return todo_ok


def revisar_almacen() -> bool:
    print("\nALMACÉN DE MEDIOS")
    import almacen

    prueba = Path(__file__).parent.parent / ".medios" / "_comprobacion.txt"
    prueba.parent.mkdir(parents=True, exist_ok=True)
    prueba.write_text(f"comprobacion {uuid.uuid4()}", encoding="utf-8")

    try:
        url = almacen.subir(prueba, prefijo="_test")
    except Exception as e:  # credenciales, bucket, permisos o red
        print(f"  ✗ no se ha podido subir: {type(e).__name__}: {str(e)[:200]}")
        if "EndpointConnectionError" in type(e).__name__:
            print("    No hay ruta hasta el endpoint. Si estás en España con")
            print("    Movistar/Orange/Vodafone, revisa que no sea un rango")
            print("    bloqueado — le pasa a Cloudflare R2.")
        return False
    print("  ✓ subida correcta")

    try:
        r = requests.get(url, timeout=30)
    except requests.RequestException as e:
        print(f"  ✗ la URL pública no responde: {e}")
        return False

    if r.status_code != 200:
        print(f"  ✗ la URL pública devuelve {r.status_code}")
        print("    Falta activar el acceso público del bucket (Settings →")
        print("    Falta hacer público el bucket, o S3_PUBLIC_BASE no es correcta.")
        return False

    print("  ✓ la URL pública responde 200 — Meta podrá descargar los medios")

    try:
        almacen.borrar(almacen.clave_de(prueba, prefijo="_test"))
        prueba.unlink(missing_ok=True)
    except Exception:
        pass
    return True


def revisar_instagram() -> bool:
    print("\nINSTAGRAM")
    import ig as api

    try:
        cliente = api.desde_entorno()
        cuenta = cliente._llamar("GET", cliente.ig_user_id, fields="username")
        print(f"  ✓ acceso a @{cuenta.get('username')}")
        usadas, total = cliente.cuota()
        print(f"  ✓ permiso de publicación ({usadas}/{total} en 24 h)")
        return True
    except Exception as e:
        print(f"  ✗ {type(e).__name__}: {str(e)[:250]}")
        return False


def main() -> None:
    resultados = [revisar_entorno()]
    if resultados[0]:
        resultados.append(revisar_almacen())
        resultados.append(revisar_instagram())

    print()
    if all(resultados):
        print("Todo listo. Ya se puede preparar la cola con prepare.py.")
    else:
        print("Hay algo sin resolver, mira las líneas con ✗.")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
