"""Cliente de la Instagram Graph API para publicar contenido.

Dos pasos siempre: se crea un contenedor con el medio, y cuando Meta termina
de procesarlo se publica. Los vídeos tardan, así que hay que esperar al
contenedor antes de publicar.
"""

from __future__ import annotations

import os
import time

import requests

BASE = os.environ.get("IG_GRAPH_BASE", "https://graph.facebook.com/v26.0")

LISTO = "FINISHED"
FALLIDOS = {"ERROR", "EXPIRED"}


class IGError(RuntimeError):
    """Error de la Graph API con el mensaje de Meta ya extraído."""


class Instagram:
    def __init__(self, ig_user_id: str, token: str):
        self.ig_user_id = ig_user_id
        self.token = token
        self.http = requests.Session()

    # --- transporte ---------------------------------------------------

    def _llamar(self, metodo: str, path: str, **params) -> dict:
        params = {k: v for k, v in params.items() if v is not None}
        params["access_token"] = self.token
        url = f"{BASE}/{path}"

        if metodo == "POST":
            r = self.http.post(url, data=params, timeout=120)
        else:
            r = self.http.get(url, params=params, timeout=60)

        try:
            cuerpo = r.json()
        except ValueError:
            raise IGError(f"HTTP {r.status_code}, respuesta no JSON: {r.text[:300]}")

        if "error" in cuerpo:
            e = cuerpo["error"]
            detalle = " | ".join(
                filter(None, [
                    f"{e.get('type')} code={e.get('code')}"
                    f"/{e.get('error_subcode', '-')}",
                    e.get("message"),
                    e.get("error_user_msg"),
                ])
            )
            raise IGError(detalle)
        return cuerpo

    # --- primitivas ---------------------------------------------------

    def contenedor(self, **campos) -> str:
        """Crea un contenedor de medio y devuelve su id."""
        return self._llamar("POST", f"{self.ig_user_id}/media", **campos)["id"]

    def estado(self, contenedor_id: str) -> tuple[str, str]:
        r = self._llamar("GET", contenedor_id, fields="status_code,status")
        return r.get("status_code", "DESCONOCIDO"), r.get("status", "")

    def esperar(self, contenedor_id: str, timeout: int = 600, intervalo: int = 5):
        """Bloquea hasta que Meta acaba de procesar el medio."""
        limite = time.monotonic() + timeout
        while True:
            codigo, detalle = self.estado(contenedor_id)
            if codigo == LISTO:
                return
            if codigo in FALLIDOS:
                raise IGError(f"el contenedor quedó en {codigo}: {detalle}")
            if time.monotonic() > limite:
                raise IGError(f"timeout tras {timeout}s, sigue en {codigo}")
            time.sleep(intervalo)

    def publicar_contenedor(self, creation_id: str) -> str:
        r = self._llamar(
            "POST", f"{self.ig_user_id}/media_publish", creation_id=creation_id
        )
        return r["id"]

    def cuota(self) -> tuple[int, int]:
        """(publicaciones usadas, límite) en la ventana móvil de 24 h."""
        r = self._llamar(
            "GET",
            f"{self.ig_user_id}/content_publishing_limit",
            fields="config,quota_usage",
        )
        d = (r.get("data") or [{}])[0]
        config = d.get("config") or {}
        return int(d.get("quota_usage", 0)), int(config.get("quota_total", 50))


# --- publicación por formato -------------------------------------------


def _es_video(url: str) -> bool:
    return url.lower().split("?")[0].endswith((".mp4", ".mov", ".m4v"))


def publicar_imagen(ig: Instagram, url: str, caption: str) -> str:
    cid = ig.contenedor(image_url=url, caption=caption)
    ig.esperar(cid, timeout=180)
    return ig.publicar_contenedor(cid)


def publicar_reel(
    ig: Instagram, url: str, caption: str, portada: str | None = None
) -> str:
    cid = ig.contenedor(
        media_type="REELS",
        video_url=url,
        caption=caption,
        cover_url=portada,
        share_to_feed="true",
    )
    ig.esperar(cid, timeout=900)
    return ig.publicar_contenedor(cid)


def publicar_carrusel(ig: Instagram, urls: list[str], caption: str) -> str:
    if not 2 <= len(urls) <= 10:
        raise IGError(f"un carrusel lleva entre 2 y 10 elementos, hay {len(urls)}")

    hijos = []
    for url in urls:
        if _es_video(url):
            hijos.append(
                ig.contenedor(
                    media_type="VIDEO", video_url=url, is_carousel_item="true"
                )
            )
        else:
            hijos.append(ig.contenedor(image_url=url, is_carousel_item="true"))

    for hijo in hijos:
        ig.esperar(hijo, timeout=900)

    padre = ig.contenedor(
        media_type="CAROUSEL", children=",".join(hijos), caption=caption
    )
    ig.esperar(padre, timeout=300)
    return ig.publicar_contenedor(padre)


def publicar_story(ig: Instagram, url: str) -> str:
    campos = {"media_type": "STORIES"}
    campos["video_url" if _es_video(url) else "image_url"] = url
    cid = ig.contenedor(**campos)
    ig.esperar(cid, timeout=600)
    return ig.publicar_contenedor(cid)


def publicar(ig: Instagram, tipo: str, urls: list[str], caption: str) -> str:
    """Despacha según el tipo de la cola. Devuelve el id del post publicado."""
    tipo = tipo.upper()
    if tipo == "IMAGE":
        return publicar_imagen(ig, urls[0], caption)
    if tipo == "REELS":
        return publicar_reel(ig, urls[0], caption)
    if tipo == "CAROUSEL":
        return publicar_carrusel(ig, urls, caption)
    if tipo == "STORY":
        return publicar_story(ig, urls[0])
    raise IGError(f"tipo desconocido: {tipo}")


def desde_entorno() -> Instagram:
    faltan = [v for v in ("IG_USER_ID", "IG_ACCESS_TOKEN") if not os.environ.get(v)]
    if faltan:
        raise SystemExit(f"Faltan variables de entorno: {', '.join(faltan)}")
    return Instagram(os.environ["IG_USER_ID"], os.environ["IG_ACCESS_TOKEN"])
