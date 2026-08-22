"""Lanzar a Claude Code para que invente una pieza, sin salir del dashboard.

Cada cuenta declara dos skills en cuentas.json: la de foto y la de vídeo. El
dashboard elige una, le pasa la idea y arranca un `claude -p` en segundo plano
dentro de la carpeta del proyecto de esa marca. Lo que Claude va contando se
retransmite a la interfaz mientras trabaja, para no mirar una ruleta durante
tres minutos.

La pieza NO entra en la cola al generarse: aterriza en `borradores/<job>/<n>/`
y ahí espera aprobación. Programar es un acto aparte, y por dos razones: así
apruebas antes de que salga nada, y así tres generaciones a la vez no se pisan
escribiendo el mismo CSV.

Desde el borrador se puede pedir un retoque o un rediseño entero, que no es más
que otra generación con el encargo anterior de contexto. En vídeo, rediseñar
pregunta antes si se conserva el audio: volver a montar la voz cuesta mucho más
que volver a dibujar los planos.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import threading
import time
import uuid

import favoritos
import miniaturas
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
BORRADORES = RAIZ / "borradores"

IMAGENES = {".jpg", ".jpeg", ".png", ".webp"}
VIDEOS = {".mp4", ".mov", ".m4v"}

# Con `acceptEdits` Claude escribe archivos solo, pero cualquier comando de
# shell se queda esperando un permiso que en segundo plano nadie va a dar —y
# componer una imagen o un reel es justamente shell—. `bypassPermissions` lo
# suelta del todo. Se elige en el .env, a conciencia, no por defecto.
PERMISOS = os.environ.get("GENERADOR_PERMISOS", "acceptEdits")

FOTO, VIDEO = "post", "anim"

# Claude Code no dice por dónde va, así que el avance se deduce de lo que hace:
# cada fase tiene un suelo y un techo, y dentro de una fase la barra sigue
# subiendo despacio con el reloj para que no parezca colgada. Nunca llega al
# 100 % por su cuenta: el 100 es haber dejado la pieza en su carpeta.
#
#   (peso mínimo, techo, etiqueta)
FASES = {
    "arranque":   (2, 10, "arrancando"),
    "skill":     (10, 24, "leyendo la skill"),
    "componer":  (24, 52, "componiendo la pieza"),
    "render":    (52, 80, "renderizando"),
    "revisar":   (80, 90, "revisando el resultado"),
    "entregar":  (90, 97, "dejándolo en borradores"),
}

# Cada cuántos segundos sube un punto mientras no cambie la fase.
RITMO = 4.0

_RENDER = ("ffmpeg", "shoot-reel", "node ", "playwright", "render", "capturar",
           "convert", "sips", "ffprobe")
_COMPONER = (".html", ".py", ".js", ".mjs", ".css", ".txt", ".json", ".svg")
_MEDIOS = (".jpg", ".jpeg", ".png", ".webp", ".mp4", ".mov")


def _fase_de(herramienta: str, detalle: str) -> str | None:
    """Qué está haciendo Claude, a ojo de lo que toca."""
    d = detalle.lower()
    if "borradores/" in d:
        return "entregar"
    if herramienta == "Skill" or "/skills/" in d or "referencias/" in d:
        return "skill"
    if herramienta == "Bash" and any(x in d for x in _RENDER):
        return "render"
    if herramienta in ("Write", "Edit", "NotebookEdit"):
        return "render" if d.endswith(_MEDIOS) else "componer"
    if herramienta == "Read":
        return "revisar" if d.endswith(_MEDIOS) else "skill"
    if herramienta == "Bash":
        return "componer"
    return None


def cli() -> str | None:
    """Dónde está el ejecutable de Claude Code, si es que está."""
    for candidato in (
        shutil.which("claude"),
        str(Path.home() / ".claude/local/claude"),
        str(Path.home() / ".local/bin/claude"),
        "/opt/homebrew/bin/claude",
        "/usr/local/bin/claude",
    ):
        if candidato and Path(candidato).exists():
            return candidato
    return None


_AUDIO_SABIDO: dict[tuple, bool] = {}


def tiene_audio(ruta: Path) -> bool:
    """Si el vídeo lleva pista de sonido. Sin ffprobe, se asume que no.

    La respuesta se guarda por archivo: el panel relee los borradores en cada
    latido, y arrancar un ffprobe por vídeo y por segundo mientras Claude
    trabaja se nota en el ventilador.
    """
    if not shutil.which("ffprobe"):
        return False
    try:
        st = ruta.stat()
    except OSError:
        return False
    marca = (str(ruta), st.st_mtime_ns, st.st_size)
    if marca in _AUDIO_SABIDO:
        return _AUDIO_SABIDO[marca]
    # stdin cerrado: ffprobe lo lee si se lo dejas y se queda colgado.
    r = subprocess.run(
        ["ffprobe", "-v", "quiet", "-select_streams", "a", "-show_entries",
         "stream=codec_type", "-of", "csv=p=0", str(ruta)],
        capture_output=True, text=True, timeout=20, stdin=subprocess.DEVNULL,
    )
    _AUDIO_SABIDO[marca] = "audio" in r.stdout
    return _AUDIO_SABIDO[marca]


# Lo que dice Claude Code cuando el modo de permisos le corta las manos. Sin
# esto, una generación bloqueada acababa en «terminó sin dejar ninguna pieza»,
# que es verdad pero no dice nada de por qué.
# Quedarse sin cuota a mitad de un encargo sale por aquí, y sin esto acababa
# en «Claude salió con código 1 y sin dejar nada»: verdad, pero te deja
# buscando un fallo que no existe.
SEÑAS_DE_CUOTA = (
    "session limit",
    "usage limit",
    "rate limit",
    "límite de uso",
)

SEÑAS_DE_BLOQUEO = (
    "requested permissions",
    "haven't granted it yet",
    "bloqueada por permisos",
    "permission denied by",
    "no tengo permiso",
)


@dataclass
class Generacion:
    id: str
    cuenta: str
    brief: str
    cuantos: int
    modo: str = FOTO                   # post (foto) | anim (vídeo)
    estado: str = "arrancando"         # arrancando | trabajando | hecho | error
    lineas: list[str] = field(default_factory=list)
    piezas: list[dict] = field(default_factory=list)
    empezada: str = ""
    error: str = ""
    rehace: str = ""                   # id de la pieza que viene a sustituir
    fase: str = "arranque"
    bloqueada: bool = False            # a Claude le faltaron permisos
    sin_cuota: str = ""                # se acabó el plan a mitad
    suelo: int = 2                     # progreso al entrar en la fase
    desde: float = field(default_factory=time.monotonic)

    def entrar_en(self, fase: str) -> None:
        """Solo se avanza: si Claude vuelve a leer algo, la barra no retrocede."""
        if fase not in FASES or FASES[fase][0] < FASES[self.fase][0]:
            return
        if fase == self.fase:
            return
        self.suelo = max(self.progreso, FASES[fase][0])
        self.fase = fase
        self.desde = time.monotonic()

    @property
    def progreso(self) -> int:
        if self.estado == "hecho":
            return 100
        if self.estado == "error":
            return 0
        _, techo, _ = FASES[self.fase]
        andado = int((time.monotonic() - self.desde) / RITMO)
        return max(0, min(techo, self.suelo + andado))

    @property
    def etiqueta(self) -> str:
        return FASES[self.fase][2]

    @property
    def carpeta(self) -> Path:
        return BORRADORES / self.id


EN_CURSO: dict[str, Generacion] = {}
_avisar = lambda: None                 # el servidor engancha aquí su SSE


# --- el encargo ---------------------------------------------------------

def _guardar_encargo(gen: Generacion, extra: dict | None = None) -> None:
    """Deja constancia de qué se pidió, para poder rehacerlo después."""
    gen.carpeta.mkdir(parents=True, exist_ok=True)
    (gen.carpeta / "encargo.json").write_text(json.dumps({
        "cuenta": gen.cuenta, "modo": gen.modo, "brief": gen.brief,
        "cuando": datetime.now().isoformat(timespec="seconds"),
        **(extra or {}),
    }, ensure_ascii=False, indent=1), encoding="utf-8")


def _encargo_de(job: str) -> dict:
    ficha = BORRADORES / job / "encargo.json"
    if not ficha.exists():
        return {}
    try:
        return json.loads(ficha.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _prompt(cuenta, gen: Generacion, contexto: str = "") -> str:
    destino = gen.carpeta
    skill = cuenta.skill_anim if gen.modo == VIDEO else cuenta.skill_post
    encargo = gen.brief.strip() or "Tú decides el tema; que sea de lo mejorcito."
    varias = gen.cuantos > 1
    formato = (("vídeos verticales 9:16" if varias else "vídeo vertical 9:16")
               if gen.modo == VIDEO
               else ("piezas de imagen para el feed" if varias
                     else "pieza de imagen para el feed"))

    return f"""Necesito {gen.cuantos} {formato} para el Instagram de \
{cuenta.nombre} (@{cuenta.usuario}).

La idea: {encargo}

{f'Usa la skill {skill}.' if skill else ''}
{contexto}
DÓNDE DEJARLO — esto es un encargo lanzado desde el dashboard, así que:
- NO toques cola.csv y NO programes nada. Programar lo hago yo desde el dashboard.
- Haz tu trabajo donde lo haces siempre; al terminar, COPIA el resultado a
  {destino}/1/ (y {destino}/2/, … si son varias piezas).
- Dentro de cada carpeta numerada:
    · el medio terminado ({'el .mp4 final, con el sonido ya montado si lleva'
                           if gen.modo == VIDEO else
                           'la imagen .jpg o .png; si es carrusel, 1.jpg, 2.jpg… en orden'})
    · caption.txt con el texto del post tal cual va a Instagram
    · ficha.json con {{"tipo": "{'REELS' if gen.modo == VIDEO else 'IMAGE|CAROUSEL'}", \
"titulo": "tres palabras"}}
- Cuando termines, dime en una línea qué has hecho. Nada de resúmenes largos.
"""


# --- lectura de lo generado ---------------------------------------------

def _leer_piezas(job: str, cuenta_slug: str = "") -> list[dict]:
    carpeta = BORRADORES / job
    piezas = []
    if not carpeta.exists():
        return piezas
    encargo = _encargo_de(job)
    for sub in sorted(carpeta.iterdir()):
        if not sub.is_dir():
            continue
        medios = sorted(
            p for p in sub.iterdir()
            if p.suffix.lower() in IMAGENES | VIDEOS and not p.name.startswith(".")
        )
        if not medios:
            continue
        ficha = {}
        if (sub / "ficha.json").exists():
            try:
                ficha = json.loads((sub / "ficha.json").read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                pass
        caption = ""
        if (sub / "caption.txt").exists():
            caption = (sub / "caption.txt").read_text(encoding="utf-8").strip()

        tipo = ficha.get("tipo") or _adivinar_tipo(medios)
        es_video = medios[0].suffix.lower() in VIDEOS
        # El aspecto va en los datos para que la carta reserve su hueco antes
        # de que llegue la imagen: si no, la galería baila mientras carga.
        ancho, alto = miniaturas.medidas(medios[0])
        piezas.append({
            "id": f"{job}/{sub.name}",
            "cuenta": encargo.get("cuenta") or cuenta_slug,
            "modo": VIDEO if es_video else FOTO,
            "brief": encargo.get("brief", ""),
            "tipo": tipo,
            "titulo": ficha.get("titulo") or sub.name,
            "caption": caption,
            "medios": [str(m.relative_to(BORRADORES)) for m in medios],
            "es_video": es_video,
            "con_audio": es_video and tiene_audio(medios[0]),
            "ancho": ancho, "alto": alto,
        })
    return piezas


def _adivinar_tipo(medios: list[Path]) -> str:
    if len(medios) > 1:
        return "CAROUSEL"
    return "REELS" if medios[0].suffix.lower() in VIDEOS else "IMAGE"


# Leer la galería entera cuesta unos milisegundos por pieza —abrir su ficha,
# su caption, medir el archivo—, y el panel la pide en cada latido. Se guarda
# el resultado y se comprueba con una huella de fechas, que es un puñado de
# scandir y no depende de cuántas piezas haya dentro.
_GALERIA: tuple[tuple, list[dict]] | None = None


def _huella() -> tuple:
    if not BORRADORES.exists():
        return ()
    marcas = []
    for job in sorted(BORRADORES.iterdir()):
        if not job.is_dir() or job.name.startswith("."):
            continue
        try:
            marcas.append((job.name, job.stat().st_mtime_ns))
            marcas.extend((f"{job.name}/{p.name}", p.stat().st_mtime_ns)
                          for p in sorted(job.iterdir()) if p.is_dir())
        except OSError:
            continue
    return tuple(marcas)


def borradores_en_disco(cuenta_slug: str | None = None) -> list[dict]:
    """Todo lo generado que sigue sin programar, también de sesiones pasadas."""
    global _GALERIA
    if not BORRADORES.exists():
        return []

    huella = _huella()
    if _GALERIA is None or _GALERIA[0] != huella:
        # Lo último primero: lo que acabas de generar tiene que abrir la
        # galería, no quedar sepultado detrás de cien piezas del archivo.
        jobs = [c for c in BORRADORES.iterdir()
                if c.is_dir() and not c.name.startswith(".")]
        jobs.sort(key=lambda c: c.stat().st_mtime, reverse=True)

        piezas = []
        for carpeta in jobs:
            piezas.extend(_leer_piezas(carpeta.name, carpeta.name.rsplit("-", 3)[0]))
        _GALERIA = (huella, piezas)

    # El gusto se pega al vuelo, fuera de la caché: darle a un corazón no puede
    # obligar a releer la galería entera, y la huella son fechas de carpetas
    # que un favorito no toca.
    gusto = favoritos.leer()
    return [{**p, "favorito": gusto.get(p["id"], 0)} for p in _GALERIA[1]
            if not cuenta_slug or p["cuenta"] == cuenta_slug]


def una_pieza(pieza_id: str) -> dict | None:
    job = pieza_id.split("/")[0]
    pieza = next((p for p in _leer_piezas(job) if p["id"] == pieza_id), None)
    if pieza is not None:
        pieza["favorito"] = favoritos.nivel_de(pieza_id)
    return pieza


# --- ejecución ----------------------------------------------------------

def _correr(gen: Generacion, cuenta, contexto: str = "") -> None:
    ejecutable = cli()
    if not ejecutable:
        gen.estado = "error"
        gen.error = ("No encuentro el CLI de Claude Code. Instálalo con "
                     "`npm install -g @anthropic-ai/claude-code`.")
        _avisar()
        return

    cwd = Path(os.path.expanduser(cuenta.proyecto or str(RAIZ)))
    if not cwd.exists():
        cwd = RAIZ

    cmd = [ejecutable, "-p", _prompt(cuenta, gen, contexto),
           "--output-format", "stream-json", "--verbose",
           "--permission-mode", PERMISOS]

    gen.estado = "trabajando"
    _avisar()
    try:
        proc = subprocess.Popen(
            cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1,
        )
    except OSError as err:
        gen.estado, gen.error = "error", str(err)
        _avisar()
        return

    for linea in proc.stdout:
        bajo = linea.lower()
        if any(x in bajo for x in SEÑAS_DE_CUOTA):
            gen.sin_cuota = _cuando_vuelve(linea)
        if any(x in bajo for x in SEÑAS_DE_BLOQUEO):
            gen.bloqueada = True
        legible, fase = _resumir(linea)
        if fase:
            gen.entrar_en(fase)
        if legible:
            gen.lineas.append(legible)
            del gen.lineas[:-120]
        if legible or fase:
            _avisar()

    proc.wait()
    gen.piezas = _leer_piezas(gen.id, gen.cuenta)
    if not gen.piezas:
        gen.estado = "error"
        gen.error = _por_que_nada(gen, cwd, proc.returncode)
    else:
        gen.estado = "hecho"
        # El rediseño solo se lleva por delante al anterior cuando hay recambio:
        # si falla, más vale quedarse con lo que había que con las manos vacías.
        if gen.rehace:
            descartar(gen.rehace)
    _avisar()


def _cuando_vuelve(linea: str) -> str:
    """La hora de reseteo que Claude Code mete en el aviso, si viene."""
    hallado = re.search(r"resets?\s+([0-9]{1,2}[:.][0-9]{2}\s*(?:am|pm)?)", linea, re.I)
    return hallado.group(1).strip() if hallado else ""


def _por_que_nada(gen: Generacion, cwd: Path, codigo: int) -> str:
    """Explicar una generación vacía mirando qué se quedó a medias."""
    if gen.sin_cuota:
        return (f"Se acabó la cuota de tu plan de Claude a mitad del encargo. "
                f"Vuelve a intentarlo a partir de las {gen.sin_cuota}.")
    if gen.bloqueada or PERMISOS != "bypassPermissions":
        return (
            "Claude no ha podido ejecutar nada: con GENERADOR_PERMISOS="
            f"«{PERMISOS}» puede escribir archivos, pero no lanzar los comandos "
            "que componen la imagen o el reel, ni leer las referencias de la "
            "skill, ni escribir fuera de la carpeta del proyecto. Pon "
            "GENERADOR_PERMISOS=bypassPermissions en el .env y reinicia el panel."
        )

    # A veces la pieza existe pero se quedó en la carpeta de trabajo.
    rastros = sorted(cwd.glob(f"**/*{gen.id}*"))
    if rastros:
        return (f"Terminó sin dejar la pieza en borradores/, pero hay trabajo "
                f"suyo en {rastros[0].parent}. Míralo antes de repetir el encargo.")

    if codigo:
        return f"Claude salió con código {codigo} y sin dejar nada"
    return "Terminó sin dejar ninguna pieza en la carpeta de borradores"


def _resumir(linea: str) -> tuple[str, str | None]:
    """De la riada de stream-json: la línea legible y en qué fase va.

    Devuelve (texto para la consola, fase deducida o None).
    """
    linea = linea.strip()
    if not linea:
        return "", None
    if not linea.startswith("{"):
        return linea[:200], None
    try:
        ev = json.loads(linea)
    except json.JSONDecodeError:
        return "", None

    if ev.get("type") == "assistant":
        for bloque in ev.get("message", {}).get("content", []):
            if bloque.get("type") == "text" and bloque.get("text", "").strip():
                return bloque["text"].strip()[:300], None
            if bloque.get("type") == "tool_use":
                nombre = bloque.get("name", "")
                entrada = bloque.get("input", {})
                detalle = str(entrada.get("file_path") or entrada.get("command")
                              or entrada.get("skill") or entrada.get("description")
                              or "")
                return (f"· {nombre} {detalle[:120]}".strip(),
                        _fase_de(nombre, detalle))
    if ev.get("type") == "result":
        coste = ev.get("total_cost_usd")
        return f"— terminado{f' ({coste:.2f} $)' if coste else ''}", "entregar"
    return "", None


def _nuevo_id(slug: str) -> str:
    return f"{slug}-{datetime.now():%m%d-%H%M}-{uuid.uuid4().hex[:4]}"


def lanzar(cuenta, brief: str, cuantos: int, modo: str = FOTO) -> Generacion:
    gen = Generacion(
        id=_nuevo_id(cuenta.slug), cuenta=cuenta.slug, brief=brief,
        cuantos=max(1, min(cuantos, 5)),
        modo=VIDEO if modo == VIDEO else FOTO,
        empezada=datetime.now().strftime("%H:%M"),
    )
    EN_CURSO[gen.id] = gen
    _guardar_encargo(gen)
    threading.Thread(target=_correr, args=(gen, cuenta), daemon=True).start()
    return gen


def rehacer(cuenta, pieza_id: str, instruccion: str, entero: bool,
            mantener_audio: bool) -> Generacion:
    """Otra pasada sobre una pieza: un retoque, o rehacerla desde cero."""
    anterior = una_pieza(pieza_id)
    if anterior is None:
        raise ValueError(f"No encuentro el borrador «{pieza_id}»")

    gen = Generacion(
        id=_nuevo_id(cuenta.slug), cuenta=cuenta.slug,
        brief=anterior["brief"] or instruccion, cuantos=1,
        modo=anterior["modo"], empezada=datetime.now().strftime("%H:%M"),
        rehace=pieza_id,
    )
    EN_CURSO[gen.id] = gen
    _guardar_encargo(gen, {"rehace": pieza_id, "instruccion": instruccion,
                           "entero": entero, "mantener_audio": mantener_audio})

    vieja = BORRADORES / pieza_id
    partes = [
        "",
        "ESTO ES UNA SEGUNDA PASADA. La versión anterior está en "
        f"{vieja} (el medio, su caption.txt y su ficha.json).",
    ]
    if entero:
        partes.append(
            "Rehaz la pieza DESDE CERO: otra composición, otro recurso gráfico, "
            "otra forma de contarlo. Que no se parezca a la anterior — si al "
            "terminar recuerda a lo que había, está mal. Vale conservar la idea "
            "y el copy si funcionaban."
        )
    else:
        partes.append(f"Cambia solo esto y deja el resto como está: {instruccion}")

    if anterior["es_video"]:
        if mantener_audio and anterior["con_audio"]:
            partes.append(
                "MANTÉN EL AUDIO tal cual: extrae la pista del mp4 anterior y "
                "móntala en el nuevo sin volver a generar la voz. Cuadra los "
                "tiempos de la animación contra ese audio, no al revés."
            )
        elif anterior["con_audio"]:
            partes.append("El audio va de nuevo: no reutilices el de la versión anterior.")
    partes.append("")

    threading.Thread(target=_correr, args=(gen, cuenta, "\n".join(partes)),
                     daemon=True).start()
    return gen


# Carpetas que jamás se borran enteras aunque el rastro apunte a ellas: son
# almacenes con trabajo de otras piezas dentro, no la carpeta de un post.
INTOCABLES = {
    Path.home(), Path.home() / "Desktop", Path.home() / "Documents",
    Path.home() / "Downloads", Path.home() / "Movies", Path.home() / "Pictures",
    Path.home() / "Desktop" / "Divi",
    Path.home() / "Desktop" / "Divi" / "Reels",
    Path.home() / "Desktop" / "Divi" / "Piezas",
    RAIZ, RAIZ / "posts", BORRADORES,
}


def _carpeta_suya(original: Path, nombre_pieza: str) -> bool:
    """¿La carpeta donde vive el original es de esta pieza y de nadie más?

    Un reel importado de Divi/Reels/45-tres-cosas/ entra en la galería con ese
    mismo nombre: la carpeta es suya entera —el html, el audio, los montajes—
    y borrar solo el mp4 dejaría la chatarra. Una imagen de «Piezas/Instagram
    que me gustan/» comparte carpeta con otras cincuenta: ahí se va el archivo
    y nada más.
    """
    carpeta = original.parent
    if carpeta in INTOCABLES or carpeta == Path(carpeta.anchor):
        return False
    if len(carpeta.parts) <= len(Path.home().parts) + 1:
        return False
    if carpeta in RAIZ.parents or carpeta == RAIZ:
        return False
    return carpeta.name == nombre_pieza


def rastro_de(pieza_id: str) -> list[str]:
    """Qué queda en el Mac detrás de una pieza, fuera de borradores/.

    Lo importado de Divi son enlaces simbólicos: la carpeta del borrador es un
    puñado de atajos y el vídeo de verdad sigue en su sitio. Esto devuelve ese
    sitio, para poder enseñarlo antes de borrar y para poder llevárselo.
    """
    carpeta = (BORRADORES / pieza_id).resolve()
    if BORRADORES.resolve() not in carpeta.parents or not carpeta.is_dir():
        return []

    fuera: list[Path] = []
    for hijo in sorted(carpeta.iterdir()):
        if not hijo.is_symlink():
            continue                      # lo generado aquí ya se va con la carpeta
        try:
            original = hijo.resolve(strict=True)
        except OSError:
            continue                      # enlace roto: el original ya no está
        if BORRADORES.resolve() in original.parents:
            continue
        if _carpeta_suya(original, carpeta.name):
            fuera.append(original.parent)
        else:
            fuera.append(original)
            # El .txt hermano es el caption de ese post, no de otro.
            hermano = original.with_suffix(".txt")
            if hermano.exists():
                fuera.append(hermano)

    vistos, limpio = set(), []
    for ruta in fuera:
        if ruta not in vistos and not any(p in vistos for p in ruta.parents):
            vistos.add(ruta)
            limpio.append(str(ruta))
    return limpio


def _a_la_papelera(ruta: Path) -> bool:
    """Mover, no destruir: «borrar del Mac» tiene que poder deshacerse.

    La Papelera de verdad, la de ~/.Trash, con un sufijo si ya hay algo con ese
    nombre. Nada de rm -rf sobre carpetas de trabajo del Escritorio.
    """
    papelera = Path.home() / ".Trash"
    try:
        papelera.mkdir(exist_ok=True)
        destino = papelera / ruta.name
        n = 2
        while destino.exists():
            destino = papelera / f"{ruta.stem} {n}{ruta.suffix}"
            n += 1
        shutil.move(str(ruta), str(destino))
        return True
    except (OSError, shutil.Error):
        return False


def descartar(pieza_id: str, con_original: bool = False) -> list[str]:
    """Se lleva la carpeta del borrador. Con `con_original`, también lo que
    esa pieza tenga fuera: el reel entero de Divi se va a la Papelera."""
    destino = (BORRADORES / pieza_id).resolve()
    if BORRADORES.resolve() not in destino.parents:
        raise ValueError("ruta fuera de borradores/")

    llevados = []
    if con_original:
        for ruta in rastro_de(pieza_id):
            if _a_la_papelera(Path(ruta)):
                llevados.append(ruta)

    shutil.rmtree(destino, ignore_errors=True)
    favoritos.olvidar(pieza_id)
    # Si el job se queda sin piezas, se lleva también su encargo.
    job = destino.parent
    if job != BORRADORES.resolve() and job.exists():
        if not any(p.is_dir() for p in job.iterdir()):
            shutil.rmtree(job, ignore_errors=True)
            favoritos.olvidar(job.name)
    return llevados
