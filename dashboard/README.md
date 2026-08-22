# El dashboard

Un calendario local de todas las cuentas: qué sale, cuándo y de quién. Se
generan piezas desde aquí, se aprueban y se programan.

```bash
cd ~/Developer/ig-autopost && ./.venv/bin/python dashboard/servidor.py
```

Y abrir <http://127.0.0.1:8787>. O, sin terminal, la app **«Panel de
Instagram»** del Escritorio: mira si el panel está en marcha, lo arranca si no,
espera a que conteste y abre el navegador. Si el puerto lo tiene ocupado otro
programa, pregunta antes de cerrar nada. Escucha solo en local a propósito: esta
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
- **Pulsar un día vacío** abre la galería en una ventana para llenarlo: eliges
  la hora entre las franjas de la cuenta, filtras por imagen o vídeo, clicas la
  pieza y se programa ahí mismo. Es el camino inverso al normal —primero el
  hueco, después qué sacar— y es el bueno cuando lo que quieres es tapar un
  día suelto del calendario.
- **Cada cuenta tiene dos botones, Foto y Vídeo**, que son sus dos skills de
  `cuentas.json`. Se pulsa uno, se escribe la idea en una frase —o se deja en
  blanco y decide él— y Claude Code arranca en segundo plano con esa skill,
  contando lo que hace mientras trabaja. Se pueden tener varias marchando a la
  vez; lo que no conviene es dos de la misma cuenta, porque se pisarían los
  archivos del proyecto.
- **Al terminar salta el aviso**: «ya está», con lo que ha salido. O lo
  programas ahí mismo —se abre con el primer hueco libre propuesto, y el día se
  cambia si no te vale— o lo guardas en la galería y decides otro día.
- **La galería** es la otra vista, arriba junto al calendario: todo lo generado
  y sin programar, en mosaico, filtrable por imagen o vídeo (y por cuenta, con
  el filtro del lateral). Nada se pierde por no decidir en el momento. Va por
  hojas de 24 y cada pieza se ve con su forma —el reel vertical, el post
  cuadrado—, no recortada a una plantilla común.
- **Lo generado no se publica solo.** Aterriza en `borradores/` y espera. Al
  clicar una pieza —en la galería o en la lista lateral— el panel propone el
  primer hueco libre de esa cuenta y ofrece cuatro salidas:

  | | |
  |---|---|
  | **Me gusta · programar** | sube el medio al bucket y lo mete en la cola. El día y la hora se eligen en el calendario de al lado: viene propuesto el primer hueco libre de esa cuenta, y se cambia clicando otro día o una de sus franjas. Los días que ya tienen algo de esa cuenta llevan un punto de su color, y avisa si la hora choca |
  | **Cambiar algo** | otra pasada tocando solo lo que le digas; en vídeo el audio se mantiene |
  | **Rediseñar** | lo rehace desde cero. En vídeo pregunta antes si se conserva el audio: volver a montar la voz cuesta mucho más que redibujar los planos. En foto va directo |
  | **Borrar** | se lleva la carpeta del borrador **y el original del Mac**, a la Papelera. Antes de preguntar enseña exactamente qué se va |

  El rediseño no tira lo anterior hasta que hay recambio: si Claude falla, te
  quedas con lo que había.

## Favoritos

Cada pieza lleva **cinco corazones**: en la carta de la galería, al pasar por
encima, y en el panel de detalle junto a «cuánto te gusta». Se clica el corazón
hasta donde llegue el gusto; clicar el que ya está puesto la saca de favoritos.

- **La carpeta de favoritos** es el tercer botón de arriba, junto a Calendario
  y Galería: el mismo mosaico con solo lo marcado, y el número al lado. Los
  filtros de imagen/vídeo y de cuenta siguen valiendo dentro.
- **El orden** se elige en la barra de filtros: *Recientes* —lo último
  generado primero, como siempre— o *Más me gustan*, de cinco corazones a uno.
  Dentro de cada escalón se mantiene el orden de siempre. Vale en las dos
  vistas y se recuerda.
- Se guarda en `borradores/.favoritos.json`, fuera de la carpeta de cada pieza
  a propósito: la galería se lee en caché con una huella de fechas de las
  carpetas, y escribir dentro invalidaría esa caché en cada clic.

## Borrar de verdad

La papelera de la carta —arriba a la izquierda, al pasar por encima— y el botón
**Borrar** del detalle hacen lo mismo: se llevan la carpeta de la pieza en
`borradores/` **y lo que esa pieza tenga fuera**. Antes de preguntar, el panel
consulta qué hay detrás y lo enseña en el aviso: no se firma a ciegas.

Lo de fuera son los originales de Divi, que la galería enlaza en vez de copiar:

- Si la carpeta del original es de esa pieza y de nadie más
  —`Divi/Reels/45-tres-cosas/`—, **se va la carpeta entera** con su HTML, su
  audio y sus montajes. Borrar solo el mp4 dejaría la chatarra.
- Si el archivo comparte carpeta con otros cincuenta —`Piezas/Instagram que me
  gustan/`—, **se va solo el archivo** y su `.txt` de caption.
- Y nunca una carpeta de la lista de intocables (`Divi`, `Reels`, `Piezas`,
  `posts`, el Escritorio, la carpeta de usuario…), pase lo que pase.

**Todo va a la Papelera del Mac, no al vacío.** Un clic en un panel no puede
destruir una carpeta de trabajo sin red.

## Dónde vive cada cosa

```
~/Developer/ig-autopost/
  borradores/          ← LA GALERÍA. Todo lo que se ve en el panel sin programar
    .favoritos.json      cuánto te gusta cada pieza, de 1 a 5
    <encargo>/         ← una carpeta por encargo (o por lote importado)
      encargo.json       qué se pidió: cuenta, si era foto o vídeo, la idea
      <pieza>/
        el medio         .jpg/.png/.mp4 — o un enlace al original
        caption.txt      el texto tal cual va a Instagram
        ficha.json       {"tipo": "...", "titulo": "..."}
  cola.csv             ← lo YA programado. De aquí tira el cron
  posts/               ← la vía antigua, la de prepare.py. Sigue funcionando
```

Programar una pieza la saca de `borradores/` y la mete en `cola.csv`, subiendo
antes el medio al bucket —Instagram descarga de una URL, no acepta archivos—.
Por eso lo que está en la galería no ocupa sitio en el bucket hasta que lo
apruebas.

`borradores/` está en el `.gitignore`: la galería es de este Mac. Lo que viaja
a GitHub es la cola, que es lo único que el cron necesita.

## Traerse lo que ya estaba hecho

```bash
./.venv/bin/python dashboard/importar.py --seco   # qué entraría
./.venv/bin/python dashboard/importar.py          # a la galería
```

Recorre `~/Desktop/Divi/Reels/`, `Divi/Piezas/` y `posts/`, y deja cada pieza en
la galería con su texto si lo encuentra —los captions de las imágenes están en
`posts/`, junto a los PNG—. De cada reel se queda con el montaje `-son.mp4`
cuando existe, que es el que lleva el audio. Una carpeta de imágenes numeradas
entra como carrusel, no como diez posts sueltos.

**Enlaza, no copia.** Son 90 MB de vídeo cuyos originales ya están ordenados en
Divi, y tener dos copias que se separan con el tiempo es peor que no tenerlas.
Borrar una pieza desde el panel se lleva el enlace; el original de Divi no se
toca nunca. Se puede volver a lanzar cuantas veces haga falta: lo que ya está
en la galería o en la cola no vuelve a entrar.

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

## Por qué la galería va rápida

Con cien piezas dentro, pedir los archivos originales son 139 MB y treinta y
cinco vídeos que el navegador tiene que decodificar para enseñar un fotograma.
Se notaba. Ahora:

- **Miniaturas.** Cada pieza se reduce una vez a un JPEG de 480 px en
  `borradores/.miniaturas/` —de los vídeos se saca un fotograma con ffmpeg— y
  eso es lo único que pide la galería. Una hoja pasa de 74 MB a 0,3 MB. Se
  rehacen solas si cambia el original, y el servidor las deja hechas al
  arrancar para que la primera visita no espere.
- **Hojas de 24.** Y el aspecto de cada pieza viaja en los datos, así que la
  carta reserva su hueco antes de que llegue la imagen y el mosaico no baila.
- **La galería se lee una vez.** Abrir la ficha y medir el archivo de cada
  pieza costaba 28 ms por latido; ahora se guarda el resultado y se comprueba
  con una huella de fechas de las carpetas: 0,85 ms.

Si algo se ve raro, se puede tirar la caché —se rehace sola—:

```bash
rm -rf ~/Developer/ig-autopost/borradores/.miniaturas
```

## El panel no parpadea

Cada sección se repinta solo si sus datos han cambiado. Importa porque mientras
Claude genera llega un estado por segundo: reconstruirlo todo cada vez hacía
temblar el calendario, reiniciaba el vídeo que estuvieras viendo y borraba lo
que estuvieras escribiendo. Ahora la consola de generación se mueve sola y el
resto se queda quieto, y con el cursor dentro de un campo no se toca el panel
de detalle hasta que sales.

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
