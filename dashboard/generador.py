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
import shutil
import subprocess
import threading
import uuid
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


def tiene_audio(ruta: Path) -> bool:
    """Si el vídeo lleva pista de sonido. Sin ffprobe, se asume que no."""
    if not shutil.which("ffprobe"):
        return False
    r = subprocess.run(
        ["ffprobe", "-v", "quiet", "-select_streams", "a", "-show_entries",
         "stream=codec_type", "-of", "csv=p=0", str(ruta)],
        capture_output=True, text=True, timeout=30,
    )
    return "audio" in r.stdout


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
        })
    return piezas


def _adivinar_tipo(medios: list[Path]) -> str:
    if len(medios) > 1:
        return "CAROUSEL"
    return "REELS" if medios[0].suffix.lower() in VIDEOS else "IMAGE"


def borradores_en_disco(cuenta_slug: str | None = None) -> list[dict]:
    """Todo lo generado que sigue sin programar, también de sesiones pasadas."""
    piezas = []
    if not BORRADORES.exists():
        return piezas
    for carpeta in sorted(BORRADORES.iterdir(), reverse=True):
        if not carpeta.is_dir():
            continue
        slug = carpeta.name.rsplit("-", 3)[0]
        if cuenta_slug and slug != cuenta_slug:
            continue
        piezas.extend(_leer_piezas(carpeta.name, slug))
    return piezas


def una_pieza(pieza_id: str) -> dict | None:
    job = pieza_id.split("/")[0]
    return next((p for p in _leer_piezas(job) if p["id"] == pieza_id), None)


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
        legible = _resumir(linea)
        if legible:
            gen.lineas.append(legible)
            del gen.lineas[:-120]
            _avisar()

    proc.wait()
    gen.piezas = _leer_piezas(gen.id, gen.cuenta)
    if not gen.piezas:
        gen.estado = "error"
        gen.error = (f"Claude salió con código {proc.returncode} y sin dejar nada"
                     if proc.returncode else
                     "Terminó sin dejar ninguna pieza en la carpeta de borradores")
    else:
        gen.estado = "hecho"
        # El rediseño solo se lleva por delante al anterior cuando hay recambio:
        # si falla, más vale quedarse con lo que había que con las manos vacías.
        if gen.rehace:
            descartar(gen.rehace)
    _avisar()


def _resumir(linea: str) -> str:
    """De la riada de stream-json, solo lo que se entiende de un vistazo."""
    linea = linea.strip()
    if not linea:
        return ""
    if not linea.startswith("{"):
        return linea[:200]
    try:
        ev = json.loads(linea)
    except json.JSONDecodeError:
        return ""

    if ev.get("type") == "assistant":
        for bloque in ev.get("message", {}).get("content", []):
            if bloque.get("type") == "text" and bloque.get("text", "").strip():
                return bloque["text"].strip()[:300]
            if bloque.get("type") == "tool_use":
                nombre = bloque.get("name", "")
                entrada = bloque.get("input", {})
                detalle = (entrada.get("file_path") or entrada.get("description")
                           or entrada.get("command") or entrada.get("skill") or "")
                return f"· {nombre} {str(detalle)[:120]}".strip()
    if ev.get("type") == "result":
        coste = ev.get("total_cost_usd")
        return f"— terminado{f' ({coste:.2f} $)' if coste else ''}"
    return ""


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


def descartar(pieza_id: str) -> None:
    destino = (BORRADORES / pieza_id).resolve()
    if BORRADORES.resolve() not in destino.parents:
        raise ValueError("ruta fuera de borradores/")
    shutil.rmtree(destino, ignore_errors=True)
    # Si el job se queda sin piezas, se lleva también su encargo.
    job = destino.parent
    if job != BORRADORES.resolve() and job.exists():
        if not any(p.is_dir() for p in job.iterdir()):
            shutil.rmtree(job, ignore_errors=True)
