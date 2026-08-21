# ig-autopost

Programación y publicación automática en Instagram con la Graph API.

Tú dejas los archivos en `posts/`, un script los normaliza, los sube a
Cloudflare R2 y los escribe en `cola.csv` con su fecha. Un cron en GitHub
Actions se despierta cada 15 minutos, mira la cola y publica lo que toca.

```
posts/  →  prepare.py  →  bucket + cola.csv  →  [git push]  →  Actions  →  Instagram
   (en tu Mac)                                                (2 veces por hora)
```

Publica en **varias cuentas**: cada fila de la cola lleva la suya y el registro
de marcas está en [`cuentas.json`](cuentas.json). Un mismo token de usuario del
sistema vale para todas las cuentas cuyos activos tenga asignados; lo único que
cambia entre marcas es el id de Instagram.

Y hay un **panel local** para verlo y manejarlo todo desde un sitio —qué sale
cada día en cada cuenta, generar piezas nuevas con Claude, aprobarlas y
programarlas—: ver [`dashboard/`](dashboard/README.md).

```bash
./ver-calendario
```

La API de Instagram **no tiene programación nativa** —el `scheduled_publish_time`
es solo de Páginas de Facebook—, así que el calendario lo lleva la cola y el
cron. Y Meta descarga los medios desde una URL, no acepta archivos locales:
por eso hace falta R2.

---

## 1. La app de Meta

1. En [developers.facebook.com](https://developers.facebook.com/apps) crea una
   app de tipo **Business**.
2. Añade el producto **Instagram** → *API con inicio de sesión de Facebook*.
3. Tu cuenta de Instagram tiene que ser **Business o Creator** y estar
   vinculada a una Página de Facebook.

**Deja la app en modo desarrollo.** Mientras tú tengas rol de administrador,
puedes publicar en tus propias cuentas sin pasar App Review. La revisión solo
hace falta para publicar en cuentas de terceros.

Para **añadir una cuenta tuya** basta con meter su Página y su cuenta de
Instagram en el portafolio y asignárselas al mismo usuario del sistema —junto
con la app, que es lo que todo el mundo olvida—, y añadirla a `cuentas.json`.
No hace falta token nuevo. Para la **cuenta de un cliente**, su Business
Manager tiene que darte acceso de socio a esos dos activos, y ahí sí entra en
juego App Review: publicar en activos de terceros exige la app en modo Live con
`instagram_content_publish` aprobado.

## 2. El token

El login lo haces tú; los scripts no entran en tu cuenta de Meta. Hay dos vías.

### Usuario del sistema (recomendada)

No depende de tu cuenta personal, no hay popup de OAuth y el token no caduca.

1. [Business Manager](https://business.facebook.com/settings) → *Usuarios →
   Usuarios del sistema* → **Agregar**, rol administrador.
2. **Agregar activos**: tu Página y tu cuenta de Instagram, con control total.
3. **Generar nuevo token** con la app y estos permisos: `pages_show_list`,
   `pages_read_engagement`, `instagram_basic`, `instagram_content_publish`.

```bash
python3 scripts/setup_token.py --directo EL_TOKEN
```

### Graph API Explorer

1. Abre el [Graph API Explorer](https://developers.facebook.com/tools/explorer/),
   host `graph.facebook.com`, método `GET`, y elige tu app.
2. En *Usuario o página* elige **usuario**, marca los cuatro permisos de arriba
   y pulsa **Generate Access Token**. En el popup hay que marcar la Página y la
   cuenta de Instagram.
3. Con `META_APP_ID` y `META_APP_SECRET` en el `.env`:

   ```bash
   python3 scripts/setup_token.py EL_TOKEN_CORTO
   ```

En ambos casos el script te devuelve el `IG_USER_ID` y el `IG_ACCESS_TOKEN` de
cada cuenta. El token de Página resultante no caduca, pero se invalida si
cambias la contraseña o revocas los permisos de la app.

> Si el popup del Explorer sale **en blanco**: suele ser Safari con el bloqueo
> de seguimiento entre sitios, un bloqueador de anuncios, o que a la app le
> falta el producto *Inicio de sesión con Facebook para empresas* o la URL de
> política de privacidad en *Configuración → Básica*.

## 3. El almacén de medios

Los medios tienen que estar en una URL pública: Meta los descarga sin
autenticarse, no acepta que le mandes el archivo.

Vale cualquier almacén compatible con S3. Por defecto, **Backblaze B2**
(10 GB gratis, región europea):

1. Crea el bucket `ig-media` con visibilidad **Public**.
2. Apunta el **Endpoint** que te muestra (`s3.eu-central-003.backblazeb2.com`
   o el que te toque) y su región → `S3_ENDPOINT` y `S3_REGION`.
3. *Application Keys* → **Add a New Application Key**, restringida a ese bucket
   con permiso *Read and Write* → `S3_ACCESS_KEY_ID` y `S3_SECRET_ACCESS_KEY`.
4. Sube un archivo cualquiera y copia su **friendly URL** sin la parte final:
   queda como `https://f003.backblazeb2.com/file/ig-media` → `S3_PUBLIC_BASE`.

> **Cloudflare R2 no sirve desde España.** Los ISP españoles (Movistar, Orange,
> Vodafone) tienen bloqueados por orden judicial rangos de IP de Cloudflare, y
> `r2.cloudflarestorage.com` cae dentro: la conexión da «no route to host».
> Solo afecta a la subida desde tu Mac; Meta y GitHub Actions llegarían bien.
> Aun así no compensa, porque sin subida no hay nada que publicar.

## 4. Instalar

```bash
cd ~/ig-autopost && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
```

Copia `.env.example` a `.env` y rellénalo.

## 5. Cómo se organiza `posts/`

```
posts/
├── 01-verano.jpg          ← post de imagen
├── 01-verano.txt          ← su caption
├── 02-rutina.mp4          ← reel
├── 02-rutina.txt
├── 03-tips-espalda/       ← carrusel (2–10 archivos)
│   ├── 1.jpg
│   ├── 2.jpg
│   └── caption.txt
└── stories/
    └── promo.jpg          ← story (sin caption)
```

El nombre del archivo (o de la carpeta) es el **id** de la entrada. Renombrar
algo ya publicado hace que se vuelva a publicar, así que no los toques después.

## 6. Programar

Todos los comandos aceptan `--cuenta <slug>`; sin él van a la cuenta por
defecto de `cuentas.json`.


```bash
.venv/bin/python scripts/prepare.py --slots "lun 09:30, mie 09:30, vie 19:00" --dry-run
```

Enseña el calendario sin subir nada. Cuando cuadre, quita `--dry-run`: convierte
los medios, los sube a R2 y escribe `cola.csv`. Solo toca las entradas nuevas;
lo ya publicado no se reescribe nunca.

`cola.csv` se abre en Numbers o en el editor. Puedes cambiar a mano fechas,
textos y el `estado` (`pendiente`, `pausado`, `publicado`, `error`).

Publicar una entrada a mano, sin esperar a su fecha:

```bash
.venv/bin/python scripts/publish.py --solo 01-verano
```

## 7. El cron

```bash
git init && git add -A && git commit -m "primer commit"
```

Crea un repo **privado** en GitHub, haz push, y en *Settings → Secrets and
variables → Actions* añade `IG_USER_ID` y `IG_ACCESS_TOKEN`. El workflow ya está
en `.github/workflows/publish.yml`.

Actions necesita permiso de escritura para guardar el estado de la cola:
*Settings → Actions → General → Workflow permissions → Read and write*.

Con `workflow_dispatch` puedes lanzarlo a mano, con o sin `dry_run`.

---

## Lo que conviene saber

- **Cuota:** 50 publicaciones cada 24 h. `publish.py` la consulta antes de cada
  tanda y para si se agota.
- **Retraso del cron:** GitHub puede retrasar un cron programado varios minutos
  cuando hay carga. Un post de las 9:30 puede salir a las 9:40.
- **Posts muy atrasados:** si algo lleva más de 48 h sin salir, no se publica
  solo; queda en `pausado` para que decidas. Evita vaciar una semana de
  contenido de golpe si el cron estuvo caído.
- **Formatos:** `prepare.py` convierte a JPEG y a MP4 H.264/AAC con ffmpeg. Las
  imágenes fuera del ratio permitido (4:5 a 1.91:1) se encajan en 4:5 sobre un
  fondo desenfocado de la propia imagen.
- **Reels:** entre 3 s y 15 min. Meta tarda de 30 s a 2 min en procesarlos; el
  script espera al contenedor antes de publicar.
- **Lo que la API no deja hacer:** etiquetar colaboradores, música de la
  biblioteca de Instagram, encuestas en stories ni respuestas a comentarios con
  medios. Eso sigue siendo manual.
