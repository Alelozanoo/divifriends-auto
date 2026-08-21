"""Mantener cola.csv a salvo teniendo dos escritores: este Mac y GitHub Actions.

El workflow hace commit sobre la cola cada vez que publica. Si el dashboard
escribe sin mirar, el push choca y hay que reconciliar.

**La cola nunca se fusiona como texto.** Se probó y sale mal: git mete sus
marcadores `<<<<<<<` dentro del CSV y a partir de ahí la cola no se puede ni
leer —el cron se encuentra un archivo roto—. Un CSV cuyas filas se reordenan
solas no es fusionable línea a línea. Lo que se hace es fusionar por filas:
traer la versión buena del remoto, releer la cola de cero, aplicar el cambio
encima y subir; si el remoto ha avanzado otra vez, se repite el ciclo.

**Y nunca se toca nada que no sea la cola.** La primera versión resolvía los
choques con `git reset --hard origin/main`, y eso se llevó por delante trabajo
sin commitear de otros archivos del repo — el árbol entero volvió al remoto.
Aquí solo se mueve HEAD con `--soft` (que deja el árbol intacto) y solo cuando
todo lo que hay por encima del remoto son commits del propio dashboard; el
único archivo que se sobrescribe a la fuerza es `cola.csv`.
"""

from __future__ import annotations

import subprocess
import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

RAIZ = Path(__file__).resolve().parent.parent

# Todo lo que toca git pasa por aquí: dos peticiones del navegador a la vez no
# pueden dejar el repo a medias.
_CERROJO = threading.RLock()

INTENTOS = 3
AUTOR = "ig-dashboard"
MIOS = ("cola.csv", "cuentas.json")


@dataclass
class Estado:
    conectado: bool = True
    ultimo: str = ""
    aviso: str = ""
    pendiente_de_subir: int = 0
    historial: list[str] = field(default_factory=list)


ESTADO = Estado()


def _git(*args: str, permitir_fallo: bool = False) -> str:
    r = subprocess.run(
        ["git", *args], cwd=RAIZ, capture_output=True, text=True, timeout=90
    )
    if r.returncode and not permitir_fallo:
        raise RuntimeError((r.stderr or r.stdout).strip()[:400])
    return (r.stdout + r.stderr).strip()


def _anotar(linea: str) -> None:
    ESTADO.ultimo = f"{datetime.now():%H:%M:%S} {linea}"
    ESTADO.historial.append(ESTADO.ultimo)
    del ESTADO.historial[:-40]


def hay_remoto() -> bool:
    with _CERROJO:
        return bool(_git("remote", permitir_fallo=True))


def _rama() -> str:
    return _git("rev-parse", "--abbrev-ref", "HEAD", permitir_fallo=True) or "main"


def _solo_commits_del_dashboard() -> bool:
    """Si todo lo que hay por encima del remoto lo escribió este dashboard.

    Mientras sea así, deshacer esos commits es inofensivo: se rehacen en el
    acto. En cuanto hay un commit de Alejandro por medio, aquí no se toca HEAD.
    """
    salida = _git("log", f"origin/{_rama()}..HEAD", "--format=%an",
                  permitir_fallo=True)
    autores = [a for a in salida.splitlines() if a.strip()]
    return all(a.strip() == AUTOR for a in autores)


def _traer() -> bool:
    """Pone la cola en la versión del remoto sin tocar el resto del árbol."""
    if not hay_remoto():
        return False
    antes = _git("rev-parse", "HEAD", permitir_fallo=True)
    _git("fetch", "--quiet", "origin")
    remoto = f"origin/{_rama()}"

    if _git("rev-parse", "HEAD", permitir_fallo=True) == _git(
            "rev-parse", remoto, permitir_fallo=True):
        return False

    if not _solo_commits_del_dashboard():
        # Hay trabajo propio sin subir. Ni se mueve HEAD ni se pisa nada: se
        # avisa y el dashboard sigue escribiendo en local.
        ESTADO.aviso = ("Tienes commits sin subir en este repo, así que no toco "
                        "el historial. Sube tú y el panel volverá a sincronizar.")
        _anotar("hay commits propios sin subir, no sincronizo")
        return False

    # --soft mueve solo el puntero: lo que esté sin commitear se queda donde
    # está. Y de todo el árbol, la cola es lo único que se trae a la fuerza.
    _git("reset", "--soft", remoto, permitir_fallo=True)
    _git("checkout", remoto, "--", "cola.csv", permitir_fallo=True)
    _git("reset", "--quiet", "--", *MIOS, permitir_fallo=True)
    return _git("rev-parse", "HEAD", permitir_fallo=True) != antes


def traer() -> bool:
    with _CERROJO:
        try:
            movido = _traer()
        except RuntimeError as err:
            ESTADO.conectado = False
            ESTADO.aviso = f"No pude traer de GitHub: {str(err)[:160]}"
            return False
        ESTADO.conectado = True
        if movido:
            ESTADO.aviso = ""
            _anotar("bajados cambios de GitHub")
        return movido


def con_la_cola(mutador: Callable[[list], list], mensaje: str):
    """Aplica un cambio sobre la cola y lo sube, reintentando si el remoto se mueve.

    `mutador` recibe la cola recién leída del remoto y devuelve cómo debe
    quedar. Se puede llamar más de una vez: tiene que ser repetible y no debe
    guardar nada por su cuenta.
    """
    import sys
    sys.path.insert(0, str(RAIZ / "scripts"))
    import cola as q

    with _CERROJO:
        ultimo_error = ""
        for intento in range(INTENTOS):
            try:
                _traer()
            except RuntimeError as err:
                ultimo_error = str(err)

            entradas = mutador(q.leer())
            q.escribir(entradas)

            try:
                if _git("status", "--porcelain", "--", *MIOS):
                    _git("add", *MIOS)
                    _git("-c", f"user.name={AUTOR}",
                         "-c", "user.email=ig-dashboard@local",
                         "commit", "--only", "-m", f"cola: {mensaje}", "--", *MIOS)
            except RuntimeError as err:
                ESTADO.aviso = f"No pude guardar el cambio: {str(err)[:160]}"
                return entradas

            if not hay_remoto():
                _anotar(f"guardado en local — {mensaje}")
                return entradas

            try:
                _git("push")
            except RuntimeError as err:
                ultimo_error = str(err)
                _anotar(f"push rechazado, reintento {intento + 1}/{INTENTOS}")
                continue

            ESTADO.conectado = True
            ESTADO.aviso = ""
            ESTADO.pendiente_de_subir = 0
            _anotar(f"subido — {mensaje}")
            return entradas

        ESTADO.conectado = False
        ESTADO.pendiente_de_subir = _sin_subir()
        ESTADO.aviso = (
            f"El cambio está guardado aquí pero no ha subido a GitHub "
            f"({ultimo_error[:120]}). Hasta que suba, el cron publicará la "
            f"versión antigua."
        )
        return q.leer()


def _sin_subir() -> int:
    salida = _git("rev-list", "--count", "@{u}..HEAD", permitir_fallo=True)
    return int(salida) if salida.isdigit() else 0


def refrescar_estado() -> Estado:
    with _CERROJO:
        ESTADO.pendiente_de_subir = _sin_subir()
    return ESTADO
