"""Convierte el token que has generado en el navegador en las credenciales finales.

Tú generas el token (yo no entro en tu cuenta de Meta). El script lo inspecciona,
lo canjea por uno de larga duración si hace falta, y te dice el IG_USER_ID y el
IG_ACCESS_TOKEN de cada cuenta de Instagram conectada.

    python3 scripts/setup_token.py EL_TOKEN
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))

import entorno  # noqa: E402,F401  (carga el .env)
from ig import BASE  # noqa: E402

NECESARIOS = {
    "pages_show_list",
    "pages_read_engagement",
    "instagram_basic",
    "instagram_content_publish",
}


def pedir(path: str, **params) -> dict:
    r = requests.get(f"{BASE}/{path}", params=params, timeout=60).json()
    if "error" in r:
        raise SystemExit(f"Meta devolvió: {r['error'].get('message')}")
    return r


def inspeccionar(token: str) -> dict | None:
    """Datos del token según Meta, o None si no se puede consultar."""
    try:
        r = requests.get(
            f"{BASE}/debug_token",
            params={"input_token": token, "access_token": token},
            timeout=60,
        ).json()
    except requests.RequestException:
        return None
    return None if "error" in r else r.get("data")


def informar(info: dict) -> bool:
    """Imprime el diagnóstico y devuelve si el token ya es permanente."""
    caduca = info.get("expires_at", 0)
    print(f"Tipo de token: {info.get('type', '?')}")

    if not caduca:
        print("Caducidad:     no caduca")
    else:
        cuando = datetime.fromtimestamp(caduca, timezone.utc)
        restante = cuando - datetime.now(timezone.utc)
        horas = restante.total_seconds() / 3600
        print(f"Caducidad:     {cuando:%d/%m/%Y %H:%M} UTC ({horas:.0f} h)")

    faltan = NECESARIOS - set(info.get("scopes", []))
    if faltan:
        print(f"\n⚠  Le faltan permisos: {', '.join(sorted(faltan))}")
        print("   Vuelve a generarlo marcándolos, o esto fallará al publicar.\n")

    return not caduca


def comprobar_cuenta(ig_id: str, token: str) -> None:
    """Verifica el acceso directo a una cuenta de Instagram concreta.

    Es la vía cuando la cuenta pertenece a un portafolio empresarial y ya
    conoces su ID: no hace falta llegar a ella a través de la Página.
    """
    cuenta = requests.get(
        f"{BASE}/{ig_id}",
        params={"fields": "username,name", "access_token": token},
        timeout=60,
    ).json()

    if "error" in cuenta:
        print(f"No se puede acceder a la cuenta {ig_id}.")
        print(f"Meta dice: {cuenta['error'].get('message')}\n")
        print("Casi siempre significa que el usuario del sistema no tiene esa\n"
              "cuenta de Instagram asignada como activo, o no con control total.")
        raise SystemExit(1)

    print(f"Acceso correcto a @{cuenta.get('username')}")

    limite = requests.get(
        f"{BASE}/{ig_id}/content_publishing_limit",
        params={"fields": "config,quota_usage", "access_token": token},
        timeout=60,
    ).json()

    if "error" in limite:
        print(f"\n⚠  Se lee la cuenta pero no la cuota de publicación:\n"
              f"   {limite['error'].get('message')}\n"
              "   Suele faltar el permiso instagram_content_publish.")
    else:
        d = (limite.get("data") or [{}])[0]
        usadas = d.get("quota_usage", 0)
        total = (d.get("config") or {}).get("quota_total", 50)
        print(f"Permiso de publicación confirmado ({usadas}/{total} en 24 h)")

    print(f"\nPara el .env:\n\nIG_USER_ID={ig_id}\nIG_ACCESS_TOKEN={token}")


def diagnosticar(token: str) -> None:
    """Por qué el token no ve Páginas. Meta lo dice en los granular_scopes."""
    print("Ese token no ve ninguna Página. Mirando por qué:\n")

    yo = requests.get(
        f"{BASE}/me", params={"fields": "id,name", "access_token": token}, timeout=60
    ).json()
    if "error" not in yo:
        print(f"El token es de: {yo.get('name')} ({yo.get('id')})")

    info = inspeccionar(token) or {}
    granulares = {g.get("scope"): g.get("target_ids") for g in
                  info.get("granular_scopes", [])}

    if "pages_show_list" not in set(info.get("scopes", [])):
        print("\nNo lleva pages_show_list. Sin ese permiso la API no puede\n"
              "listar tus Páginas. Genera el token otra vez marcándolo.")
        return

    objetivos = granulares.get("pages_show_list")
    if objetivos:
        print(f"\npages_show_list está concedido, y solo para: {objetivos}")
        print("Pero /me/accounts no las devuelve: revisa que sigas siendo\n"
              "administrador de esa Página.")
    else:
        print("\npages_show_list está concedido pero sin ninguna Página asociada.")
        print("Es lo típico cuando en el popup de Meta pasas de largo la pantalla\n"
              "de «¿a qué activos das acceso?» sin marcar nada, o cuando la Página\n"
              "pertenece a un portafolio empresarial que no seleccionaste ahí.")

    print(
        "\nLo más rápido es dejar de pelearse con el popup y usar un usuario del\n"
        "sistema en Business Manager: le asignas la Página y la cuenta de\n"
        "Instagram como activos, generas el token y lo pasas con --directo.\n"
        "Ese además no caduca nunca."
    )


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("token", help="el token que acabas de generar")
    p.add_argument(
        "--directo",
        action="store_true",
        help="no canjearlo aunque parezca corto (tokens de usuario del sistema)",
    )
    p.add_argument(
        "--ig-id",
        help="ID de la cuenta de Instagram, si ya lo sabes: comprueba el acceso "
        "contra ella en vez de buscarla a través de las Páginas",
    )
    args = p.parse_args()

    info = inspeccionar(args.token)
    if info:
        permanente = informar(info)
    else:
        print("No se ha podido inspeccionar el token; se asume que es corto.")
        permanente = False
    print()

    if args.directo or permanente:
        largo = args.token
        print("Se usa tal cual, no hace falta canjearlo.\n")
    else:
        app_id = os.environ.get("META_APP_ID")
        app_secret = os.environ.get("META_APP_SECRET")
        if not (app_id and app_secret):
            raise SystemExit(
                "Este token caduca y hay que canjearlo, así que necesito\n"
                "META_APP_ID y META_APP_SECRET en el .env (los tienes en la app,\n"
                "en Configuración → Básica)."
            )
        largo = pedir(
            "oauth/access_token",
            grant_type="fb_exchange_token",
            client_id=app_id,
            client_secret=app_secret,
            fb_exchange_token=args.token,
        )["access_token"]
        print("Canjeado por uno de larga duración (60 días).\n")

    if args.ig_id:
        comprobar_cuenta(args.ig_id, largo)
        return

    paginas = pedir(
        "me/accounts",
        fields="name,id,access_token,instagram_business_account{id,username}",
        access_token=largo,
    ).get("data", [])

    if not paginas:
        diagnosticar(largo)
        raise SystemExit(1)

    encontradas = 0
    for pagina in paginas:
        ig = pagina.get("instagram_business_account")
        print(f"Página: {pagina['name']} ({pagina['id']})")
        if not ig:
            print("   sin cuenta de Instagram vinculada\n")
            continue
        encontradas += 1
        print(f"   Instagram: @{ig.get('username')}")
        print(f"   IG_USER_ID={ig['id']}")
        print(f"   IG_ACCESS_TOKEN={pagina['access_token']}\n")

    if not encontradas:
        raise SystemExit(
            "Ninguna de esas Páginas tiene cuenta de Instagram vinculada.\n"
            "La cuenta tiene que ser Business o Creator y estar conectada a la\n"
            "Página desde los ajustes de Instagram."
        )

    print(
        "Copia el IG_USER_ID y el IG_ACCESS_TOKEN de la cuenta que quieras al .env\n"
        "y a los secrets del repo. El token de Página derivado de uno de larga\n"
        "duración no caduca, pero se invalida si cambias la contraseña de Facebook\n"
        "o revocas los permisos de la app."
    )


if __name__ == "__main__":
    main()
