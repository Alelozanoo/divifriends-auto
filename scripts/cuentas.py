"""El registro de cuentas de Instagram donde publicamos.

Los ids de Instagram no son secretos —son públicos en el perfil— así que viven
en `cuentas.json`, dentro del repo, y se pueden editar a mano. El token sí lo
es y sigue llegando por el entorno.

Un mismo token de usuario del sistema publica en todas las cuentas cuyos
activos tenga asignados, así que lo normal es que `IG_ACCESS_TOKEN` valga para
todas. Para una cuenta de cliente con token propio, se define
`IG_ACCESS_TOKEN_<SLUG>` y esa cuenta lo usa en vez del general.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
REGISTRO = RAIZ / "cuentas.json"

# La cuenta con la que nació el proyecto. Las filas de cola.csv anteriores al
# multicuenta no llevan columna `cuenta`, y sin esto se quedarían huérfanas.
POR_DEFECTO = "divifriends"


@dataclass
class Cuenta:
    slug: str
    nombre: str
    usuario: str
    ig_user_id: str
    color: str = "#888888"
    skill_post: str = ""
    skill_anim: str = ""
    franjas: tuple[str, ...] = ("21:00",)
    proyecto: str = ""

    @property
    def token(self) -> str:
        """El token propio de la cuenta, o el general del usuario del sistema."""
        propio = os.environ.get(f"IG_ACCESS_TOKEN_{self.slug.upper().replace('-', '_')}")
        return propio or os.environ.get("IG_ACCESS_TOKEN", "")


def _cargar() -> dict[str, Cuenta]:
    if not REGISTRO.exists():
        raise SystemExit(f"Falta el registro de cuentas en {REGISTRO}")
    crudo = json.loads(REGISTRO.read_text(encoding="utf-8"))
    return {
        slug: Cuenta(
            slug=slug,
            nombre=d.get("nombre", slug),
            usuario=d.get("usuario", ""),
            ig_user_id=str(d["ig_user_id"]),
            color=d.get("color", "#888888"),
            skill_post=d.get("skill_post", ""),
            skill_anim=d.get("skill_anim", ""),
            franjas=tuple(d.get("franjas") or ("21:00",)),
            proyecto=d.get("proyecto", ""),
        )
        for slug, d in crudo.items()
    }


def todas() -> dict[str, Cuenta]:
    return _cargar()


def una(slug: str) -> Cuenta:
    registro = _cargar()
    if slug not in registro:
        conocidas = ", ".join(sorted(registro)) or "ninguna"
        raise SystemExit(f"No conozco la cuenta «{slug}». Registradas: {conocidas}")
    return registro[slug]
