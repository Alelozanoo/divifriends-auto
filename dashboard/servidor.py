"""El dashboard: un calendario de todas las cuentas, en local.

    ./.venv/bin/python dashboard/servidor.py      →  http://127.0.0.1:8787

Escucha solo en 127.0.0.1 a propósito: la máquina tiene el token de publicar y
las llaves del bucket, y esto no lleva contraseña ninguna.

La fuente de verdad sigue siendo cola.csv en el repo. El dashboard nunca la
edita a ciegas: trae de GitHub antes de tocarla y sube justo después, para no
pelearse con el cron que publica.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import threading
from datetime import datetime, timedelta
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "scripts"))
sys.path.insert(0, str(RAIZ / "dashboard"))

import entorno  # noqa: E402,F401  (carga el .env con el token y el bucket)
import cola as q  # noqa: E402
import cuentas as reg  # noqa: E402
import almacen  # noqa: E402
import prepare  # noqa: E402

import favoritos  # noqa: E402
import generador  # noqa: E402
import miniaturas  # noqa: E402
import sincro  # noqa: E402

from fastapi import Body, FastAPI, HTTPException  # noqa: E402
from fastapi.responses import FileResponse, StreamingResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

ESTATICO = RAIZ / "dashboard" / "estatico"
BORRADORES = RAIZ / "borradores"

app = FastAPI(title="ig-dashboard")

# Cada cambio sube el contador; el navegador solo repinta cuando se mueve.
_VERSION = 0
_CANDADO = threading.Lock()


def tocado() -> None:
    global _VERSION
    with _CANDADO:
        _VERSION += 1


generador._avisar = tocado


# --- lectura -----------------------------------------------------------

def _serializar(e: q.Entrada) -> dict:
    return {
        "id": e.id, "cuenta": e.cuenta, "tipo": e.tipo, "fecha": e.fecha,
        "estado": e.estado, "caption": e.caption, "urls": e.urls,
        "ig_media_id": e.ig_media_id, "nota": e.nota,
        "editable": e.estado != q.PUBLICADO,
    }


def _estado_completo() -> dict:
    est = sincro.refrescar_estado()
    return {
        "version": _VERSION,
        "cuentas": [
            {"slug": c.slug, "nombre": c.nombre, "usuario": c.usuario,
             "color": c.color, "franjas": list(c.franjas),
             "skill_post": c.skill_post, "skill_anim": c.skill_anim,
             "puede_generar": bool(c.skill_post or c.skill_anim)}
            for c in reg.todas().values()
        ],
        "entradas": [_serializar(e) for e in q.leer()],
        "borradores": generador.borradores_en_disco(),
        "generando": [
            {"id": g.id, "cuenta": g.cuenta, "estado": g.estado, "modo": g.modo,
             "lineas": g.lineas[-14:], "error": g.error, "empezada": g.empezada,
             "brief": g.brief, "rehace": g.rehace, "piezas": len(g.piezas),
             "progreso": g.progreso, "etiqueta": g.etiqueta}
            for g in generador.EN_CURSO.values()
        ],
        "git": {"conectado": est.conectado, "aviso": est.aviso,
                "ultimo": est.ultimo, "sin_subir": est.pendiente_de_subir},
        "cli_claude": bool(generador.cli()),
        "permisos": generador.PERMISOS,
        "puede_ejecutar": generador.PERMISOS == "bypassPermissions",
        "ahora": datetime.now(q.zona()).strftime("%Y-%m-%d %H:%M"),
    }


@app.get("/api/estado")
def estado() -> dict:
    return _estado_completo()


@app.get("/api/eventos")
async def eventos():
    """SSE: el navegador se entera de cada cambio sin preguntar."""
    async def flujo():
        visto = -1
        while True:
            # Con algo generando se manda estado cada segundo aunque no haya
            # novedades: la barra avanza con el reloj dentro de cada fase, y si
            # Claude se pasa un minuto pensando parecería colgada.
            trabajando = any(g.estado == "trabajando"
                             for g in generador.EN_CURSO.values())
            if _VERSION != visto or trabajando:
                visto = _VERSION
                yield f"data: {json.dumps(_estado_completo(), ensure_ascii=False)}\n\n"
            await asyncio.sleep(1)

    return StreamingResponse(flujo(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})


# --- escritura sobre la cola -------------------------------------------

def _mirar(entrada_id: str) -> q.Entrada:
    """La fila tal y como está ahora mismo, ya sincronizada, para validar."""
    sincro.traer()
    fila = next((e for e in q.leer() if e.id == entrada_id), None)
    if fila is None:
        raise HTTPException(404, f"No existe la entrada «{entrada_id}»")
    return fila


@app.patch("/api/entrada/{entrada_id}")
def editar(entrada_id: str, cambios: dict = Body(...)) -> dict:
    if _mirar(entrada_id).estado == q.PUBLICADO:
        raise HTTPException(409, "Ese post ya está publicado en Instagram: "
                                 "cambiarlo aquí no lo cambia allí")
    if "fecha" in cambios:
        try:
            datetime.strptime(cambios["fecha"], q.FORMATO_FECHA)
        except (ValueError, TypeError):
            raise HTTPException(400, "La fecha va como 2026-08-25 21:00")

    def aplicar(entradas: list[q.Entrada]) -> list[q.Entrada]:
        fila = next((e for e in entradas if e.id == entrada_id), None)
        # Si entre el clic y el push el cron lo ha publicado, gana el cron:
        # está en Instagram y aquí solo habría un CSV discrepante.
        if fila is None or fila.estado == q.PUBLICADO:
            return entradas
        for campo in ("fecha", "caption", "tipo", "cuenta", "estado"):
            if campo in cambios:
                setattr(fila, campo, cambios[campo])
        # Reprogramar algo que se pausó por atrasado tiene que devolverlo a la
        # cola; si no, se queda en pausa para siempre sin decir por qué.
        if "fecha" in cambios and fila.estado in (q.PAUSADO, q.ERROR):
            fila.estado, fila.nota = q.PENDIENTE, ""
        return entradas

    resultado = sincro.con_la_cola(aplicar, f"editado {entrada_id}")
    tocado()
    fila = next((e for e in resultado if e.id == entrada_id), None)
    if fila is None:
        raise HTTPException(409, "La entrada ha desaparecido de la cola")
    if fila.estado == q.PUBLICADO:
        raise HTTPException(409, "El cron lo ha publicado mientras lo editabas: "
                                 "el cambio no se ha aplicado")
    return _serializar(fila)


@app.delete("/api/entrada/{entrada_id}")
def borrar(entrada_id: str) -> dict:
    if _mirar(entrada_id).estado == q.PUBLICADO:
        raise HTTPException(409, "Ya está publicado: bórralo desde Instagram")

    def aplicar(entradas: list[q.Entrada]) -> list[q.Entrada]:
        return [e for e in entradas
                if e.id != entrada_id or e.estado == q.PUBLICADO]

    sincro.con_la_cola(aplicar, f"borrado {entrada_id}")
    tocado()
    return {"borrado": entrada_id}


# --- de borrador a cola -------------------------------------------------

@app.post("/api/programar")
def programar(datos: dict = Body(...)) -> dict:
    """Sube los medios del borrador al bucket y lo mete en la cola."""
    pieza_id = datos.get("pieza")
    fecha = datos.get("fecha", "")
    caption = (datos.get("caption") or "").strip()

    pieza = next((p for p in generador.borradores_en_disco()
                  if p["id"] == pieza_id), None)
    if pieza is None:
        raise HTTPException(404, f"No encuentro el borrador «{pieza_id}»")
    try:
        datetime.strptime(fecha, q.FORMATO_FECHA)
    except ValueError:
        raise HTTPException(400, "La fecha va como 2026-08-25 21:00")

    cuenta = reg.una(pieza["cuenta"])
    tipo = datos.get("tipo") or pieza["tipo"]
    rutas = [BORRADORES / m for m in pieza["medios"]]

    # Mismo tratamiento que prepare.py: Instagram rechaza lo que se sale de
    # ratio o de ancho, y un borrador recién generado no tiene por qué cumplir.
    caja = prepare.caja_carrusel(rutas) if tipo == "CAROUSEL" else None
    urls = []
    for ruta in rutas:
        try:
            listo = prepare.preparar_medio(ruta, tipo, caja)
        except Exception as err:
            raise HTTPException(422, f"No pude preparar «{ruta.name}» para "
                                     f"Instagram: {err}") from err
        try:
            urls.append(almacen.subir(listo, prefijo=f"ig/{cuenta.slug}"))
        except Exception as err:
            raise HTTPException(502, f"No pude subir «{ruta.name}» al bucket: "
                                     f"{err}") from err

    base = pieza_id.split("/")[0].replace(f"{cuenta.slug}-", "")
    nuevo_id = f"{cuenta.slug}-{base}-{pieza_id.split('/')[-1]}"

    def aplicar(entradas: list[q.Entrada]) -> list[q.Entrada]:
        # El mutador puede repetirse si el remoto se mueve: añadir dos veces la
        # misma pieza sacaría el post duplicado en Instagram.
        entradas = [e for e in entradas if e.id != nuevo_id]
        entradas.append(q.Entrada(
            id=nuevo_id, cuenta=cuenta.slug, tipo=tipo, fecha=fecha,
            estado=q.PENDIENTE, caption=caption or pieza["caption"], urls=urls,
        ))
        return entradas

    sincro.con_la_cola(aplicar, f"programado {nuevo_id} para el {fecha}")
    tocado()
    generador.descartar(pieza_id)
    return {"id": nuevo_id, "urls": urls}


@app.delete("/api/borrador/{pieza_id:path}")
def descartar_borrador(pieza_id: str, originales: bool = False) -> dict:
    """Tira la pieza. Con `?originales=1` se lleva también lo que tenga fuera.

    Lo de fuera va a la Papelera, no al vacío: la galería enlaza los originales
    de Divi, y una carpeta de trabajo con su HTML y su voz no se destruye sin
    red por un clic en un panel.
    """
    llevados = generador.descartar(pieza_id, con_original=originales)
    tocado()
    return {"descartado": pieza_id, "papelera": llevados}


@app.get("/api/rastro/{pieza_id:path}")
def rastro(pieza_id: str) -> dict:
    """Qué queda en el Mac detrás de esta pieza, para poder avisar antes."""
    return {"rastro": generador.rastro_de(pieza_id)}


# --- favoritos ----------------------------------------------------------

@app.post("/api/favorito")
def favorito(datos: dict = Body(...)) -> dict:
    """Cuánto te gusta una pieza, de 1 a 5. Con 0 sale de favoritos."""
    pieza_id = datos.get("pieza", "")
    if generador.una_pieza(pieza_id) is None:
        raise HTTPException(404, f"No encuentro el borrador «{pieza_id}»")
    nivel = favoritos.poner(pieza_id, datos.get("nivel", 0))
    tocado()
    return {"pieza": pieza_id, "nivel": nivel}


# --- generación ---------------------------------------------------------

@app.post("/api/generar")
def generar(datos: dict = Body(...)) -> dict:
    cuenta = reg.una(datos.get("cuenta", ""))
    modo = datos.get("modo", generador.FOTO)
    skill = cuenta.skill_anim if modo == generador.VIDEO else cuenta.skill_post
    if not skill:
        raise HTTPException(400, f"{cuenta.nombre} no tiene skill de "
                                 f"{'vídeo' if modo == generador.VIDEO else 'foto'} "
                                 f"en cuentas.json")
    gen = generador.lanzar(cuenta, datos.get("brief", ""),
                           int(datos.get("cuantos", 1)), modo)
    tocado()
    return {"id": gen.id}


@app.post("/api/rehacer")
def rehacer(datos: dict = Body(...)) -> dict:
    """Otra pasada sobre un borrador: un retoque suelto o rehacerlo entero."""
    pieza_id = datos.get("pieza", "")
    pieza = generador.una_pieza(pieza_id)
    if pieza is None:
        raise HTTPException(404, f"No encuentro el borrador «{pieza_id}»")

    entero = bool(datos.get("entero"))
    instruccion = (datos.get("instruccion") or "").strip()
    if not entero and not instruccion:
        raise HTTPException(400, "Dime qué hay que cambiar")

    gen = generador.rehacer(
        reg.una(pieza["cuenta"]), pieza_id, instruccion, entero,
        bool(datos.get("mantener_audio")),
    )
    tocado()
    return {"id": gen.id}


@app.post("/api/hueco")
def hueco(datos: dict = Body(...)) -> dict:
    """El primer día y franja libres de esa cuenta, para proponerlo al programar."""
    cuenta = reg.una(datos.get("cuenta", ""))
    ocupadas = {e.fecha for e in q.leer() if e.cuenta == cuenta.slug}
    ahora = datetime.now(q.zona())
    dia = ahora.date()
    for _ in range(60):
        for franja in cuenta.franjas:
            candidata = f"{dia.isoformat()} {franja}"
            if candidata in ocupadas:
                continue
            if datetime.strptime(candidata, q.FORMATO_FECHA).replace(
                    tzinfo=q.zona()) <= ahora:
                continue
            return {"fecha": candidata}
        dia += timedelta(days=1)
    return {"fecha": f"{dia.isoformat()} {cuenta.franjas[0]}"}


# --- estáticos y medios -------------------------------------------------

@app.get("/mini/{ruta:path}")
def miniatura(ruta: str):
    """La versión pequeña de un medio. La galería solo pide de estas."""
    pedida = os.path.normpath(os.path.join(str(BORRADORES), ruta))
    if not pedida.startswith(str(BORRADORES) + os.sep):
        raise HTTPException(404, "No existe")
    pequeña = miniaturas.mini(Path(pedida))
    if pequeña is None:
        raise HTTPException(404, "No se pudo generar")
    return FileResponse(pequeña, headers={"Cache-Control": "public, max-age=86400"})


@app.get("/borradores/{ruta:path}")
def medio_local(ruta: str):
    """Sirve un medio de la galería, siga o no un enlace simbólico.

    Lo importado de Divi son enlaces a los originales, así que aquí no se puede
    resolver la ruta antes de comprobarla: `resolve()` saltaría al destino real
    —fuera de borradores/— y todo daría 404. Lo que se valida es la ruta
    pedida, normalizada, que es por donde podría colarse un «..»; el enlace en
    sí lo pone el importador, no quien navega.
    """
    pedida = os.path.normpath(os.path.join(str(BORRADORES), ruta))
    if not pedida.startswith(str(BORRADORES) + os.sep):
        raise HTTPException(404, "No existe")
    destino = Path(pedida)
    if not destino.is_file():
        raise HTTPException(404, "No existe")
    return FileResponse(destino)


@app.get("/")
def raiz():
    return FileResponse(ESTATICO / "index.html")


app.mount("/estatico", StaticFiles(directory=ESTATICO), name="estatico")


def _calentar_miniaturas() -> None:
    """Deja hechas las miniaturas que falten, sin bloquear el arranque.

    Vale la pena hacerlo aquí: la primera vez son cien ffmpeg y, si se hicieran
    a demanda, la galería tardaría en pintarse justo el día que la estrenas.
    """
    hechas = 0
    for pieza in generador.borradores_en_disco():
        for medio in pieza["medios"]:
            if miniaturas.mini(BORRADORES / medio):
                hechas += 1
    if hechas:
        print(f"  {hechas} miniaturas listas")
        tocado()


def _vigilar_github() -> None:
    """Cada minuto se mira si el cron ha publicado algo, para que el calendario
    lo refleje sin tener que recargar."""
    while True:
        if sincro.traer():
            tocado()
        threading.Event().wait(60)


if __name__ == "__main__":
    import uvicorn

    # El 8787 de siempre, salvo que alguien pida otro: sirve para levantar una
    # segunda copia sin pelearse con la que ya está abierta.
    puerto = int(os.environ.get("PANEL_PUERTO", "8787"))

    threading.Thread(target=_vigilar_github, daemon=True).start()
    threading.Thread(target=_calentar_miniaturas, daemon=True).start()
    print(f"\n  Dashboard en  →  http://127.0.0.1:{puerto}\n")
    uvicorn.run(app, host="127.0.0.1", port=puerto, log_level="warning")
