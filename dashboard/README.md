# El dashboard

Un calendario local de todas las cuentas: qué sale, cuándo y de quién. Se
generan piezas desde aquí, se aprueban y se programan.

```bash
cd ~/ig-autopost && ./.venv/bin/python dashboard/servidor.py
```

Y abrir <http://127.0.0.1:8787>. Escucha solo en local a propósito: esta
máquina tiene el token de publicar y las llaves del bucket, y esto no lleva
contraseña.

## Cómo se usa

- **El calendario** enseña el mes entero con todas las cuentas a la vez. Cada
  marca lleva su color; se ocultan y se enseñan clicando en la lista de la
  izquierda. Los publicados salen en gris con un ✓, los que fallaron con un ⚠.
- **Clicar un post** abre el panel de la derecha: ahí se cambia la hora, se
  reescribe el texto o se quita de la cola. Lo ya publicado no se toca —
  cambiarlo aquí no cambiaría nada en Instagram.
- **Arrastrar un post a otro día** lo reprograma manteniendo la hora.
- **Cada cuenta tiene dos botones, Foto y Vídeo**, que son sus dos skills de
  `cuentas.json`. Se pulsa uno, se escribe la idea en una frase —o se deja en
  blanco y decide él— y Claude Code arranca en segundo plano con esa skill,
  contando lo que hace mientras trabaja. Se pueden tener varias marchando a la
  vez; lo que no conviene es dos de la misma cuenta, porque se pisarían los
  archivos del proyecto.
- **Lo generado no se publica solo.** Aterriza en `borradores/` y espera en la
  columna de la izquierda. Al clicarlo, el panel propone el primer hueco libre
  de esa cuenta y ofrece cuatro salidas:

  | | |
  |---|---|
  | **Me gusta · programar** | sube el medio al bucket y lo mete en la cola |
  | **Cambiar algo** | otra pasada tocando solo lo que le digas; en vídeo el audio se mantiene |
  | **Rediseñar** | lo rehace desde cero. En vídeo pregunta antes si se conserva el audio: volver a montar la voz cuesta mucho más que redibujar los planos. En foto va directo |
  | **Borrar** | se lleva la carpeta del borrador |

  El rediseño no tira lo anterior hasta que hay recambio: si Claude falla, te
  quedas con lo que había.

## Añadir una cuenta

1. En Meta: la cuenta tiene que ser profesional y estar vinculada a una Página.
   Página y cuenta de Instagram entran en el portafolio, y ahí se le asignan al
   mismo usuario del sistema que ya publica —junto con la propia app, que es lo
   que todo el mundo olvida—. No hace falta token nuevo.
2. En `cuentas.json`, una entrada más:

```json
"fitathome": {
  "nombre": "FITATHOME",
  "usuario": "fitathome.es",
  "ig_user_id": "1784144…",
  "color": "#C8FF3D",
  "skill_post": "fitathome-post",
  "franjas": ["09:00", "19:00"],
  "proyecto": "~/Desktop/FITATHOME"
}
```

`franjas` son las horas a las que suele publicar esa marca: de ahí sale el
hueco que propone el dashboard. `proyecto` es la carpeta desde la que se lanza
Claude para esa cuenta.

Si la cuenta es de un cliente y tiene su propio token, se añade al `.env` como
`IG_ACCESS_TOKEN_FITATHOME` (el slug en mayúsculas) y como secret del repo con
ese mismo nombre. Si no, usa el general.

## Las dos cosas que conviene saber

**La cola tiene dos escritores.** Este Mac y el cron de GitHub Actions. Por eso
cada cambio del panel trae antes la versión de GitHub, aplica el cambio sobre
ella y la sube; si el cron se ha adelantado, se repite el ciclo. La cola nunca
se fusiona como texto —git metería sus marcadores dentro del CSV y el archivo
dejaría de poder leerse—. Cuando algo no ha subido, el diodo de la esquina se
pone naranja: hasta que suba, el cron publica la versión antigua.

Y el panel **solo toca `cola.csv`**. Nunca hace `reset --hard` ni reescribe
commits que no sean suyos: si encuentra trabajo tuyo sin subir, no toca el
historial y lo dice. La primera versión sí lo hacía y se llevó por delante
cambios sin commitear de otros archivos del repo.

**Generar cuesta permisos.** Componer una imagen o un reel es shell, y en
segundo plano no hay nadie para dar permiso. Con el valor por defecto
(`acceptEdits`) Claude puede escribir archivos pero se quedará esperando en el
primer comando. Para que las skills funcionen de verdad hay que ponerlo en el
`.env`:

```
GENERADOR_PERMISOS=bypassPermissions
```

Eso le quita el freno de mano dentro de la carpeta del proyecto de esa cuenta.
Es una decisión consciente, no un valor por defecto.
