// Panel de publicación. Sin framework y sin compilar: se edita el archivo, se
// recarga y ya está. El estado llega entero por SSE en cada cambio, así que
// aquí no se guarda nada que no venga del servidor —salvo lo que el ojo tiene
// puesto encima: el mes, los canales apagados y lo seleccionado.
//
// LA REGLA: cada sección se repinta SOLO si sus datos han cambiado. Mientras
// Claude genera llega un estado por segundo, y reconstruir el DOM entero cada
// vez hacía parpadear el calendario, reiniciaba el vídeo del visor y borraba lo
// que estuvieras escribiendo. Por eso cada trozo lleva su firma y se compara
// antes de tocar nada.

const $ = (sel) => document.querySelector(sel);
const MESES = ['enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio',
  'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre'];

let estado = { cuentas: [], entradas: [], borradores: [], generando: [], git: {} };
let apagados = new Set(JSON.parse(localStorage.getItem('apagados') || '[]'));
let mes = new Date();
let elegido = null;               // {clase:'entrada'|'pieza', id}
let firmas = {};                  // lo último pintado de cada sección
let mesPintado = null;            // para animar la rejilla solo al cambiar de mes
let detallePendiente = false;     // llegó un cambio mientras se escribía
let vista = localStorage.getItem('vista') || 'calendario';
let filtroTipo = localStorage.getItem('filtroTipo') || 'todo';
let orden = localStorage.getItem('orden') || 'recientes';   // recientes | gusto
let hoja = 0;                     // qué página de la galería se está viendo
const POR_HOJA = 24;              // cien miniaturas de golpe se notan
let yaAvisadas = new Set();       // encargos cuyo «ya está» ya se ha enseñado
let terminadasEn = {};            // cuándo se vio acabar cada encargo
const RECREO = 6000;              // lo que se queda en pantalla al 100 %

// Repinta solo si los datos de esa sección son otros. `firma` es lo que la
// sección necesita para dibujarse: si es idéntico, el DOM ya está bien.
function siCambia(seccion, firma, pintarla) {
  const huella = JSON.stringify(firma);
  if (firmas[seccion] === huella) return false;
  firmas[seccion] = huella;
  pintarla();
  return true;
}

// El panel de detalle no se toca mientras se escribe en él: perder media frase
// del caption porque el cron ha publicado en otra cuenta es inaceptable.
function estoyEscribiendo() {
  const foco = document.activeElement;
  return foco && $('#detalle').contains(foco)
      && ['INPUT', 'TEXTAREA'].includes(foco.tagName);
}

const cuentaDe = (slug) => estado.cuentas.find((c) => c.slug === slug) || {};
const colorDe = (slug) => cuentaDe(slug).color || '#8891a3';
const nombreDe = (slug) => cuentaDe(slug).nombre || slug;
const clave = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
// Un reel importado no trae caption, y enseñar «divifriends-archivo-reels-
// adelanta» en la celda no dice nada. Se queda con la última parte del id.
const nombreLegible = (id) => {
  const cola = String(id).split('-').pop();
  return cola.charAt(0).toUpperCase() + cola.slice(1);
};

const esc = (t) => String(t ?? '').replace(/[&<>"]/g,
  (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

// ── conexión ─────────────────────────────────────────────────────────

function conectar() {
  const es = new EventSource('/api/eventos');
  es.onmessage = (ev) => { estado = JSON.parse(ev.data); pintar(); };
  es.onerror = () => {
    $('#enlace').innerHTML = '<span class="diodo mal"></span> enlace perdido';
  };
}

async function api(ruta, opciones = {}) {
  const r = await fetch(ruta, { headers: { 'Content-Type': 'application/json' }, ...opciones });
  if (!r.ok) {
    const cuerpo = await r.json().catch(() => ({}));
    alert(cuerpo.detail || `Error ${r.status}`);
    throw new Error(cuerpo.detail || r.status);
  }
  return r.json();
}

// ── pintado ──────────────────────────────────────────────────────────

function pintar() {
  // La cabecera son cuatro números y un diodo: barata y siempre al día.
  pintarCabecera();

  const apagadosF = [...apagados].sort();
  siCambia('canales', [estado.cuentas, contarPorCuenta(), apagadosF], pintarCanales);
  siCambia('trabajos', trabajosEnPantalla().map(
    (g) => [g.id, g.estado, g.modo, g.error, g.empezada, g.rehace, g.lineas]),
    pintarTrabajos);
  actualizarAvance();
  siCambia('piezas', [estado.borradores, apagadosF, elegido], pintarPiezas);
  siCambia('galeria', [galeriaVisible(), vista, filtroTipo, orden, hoja,
                       elegido && elegido.id], pintarGaleria);
  siCambia('calendario',
    [estado.entradas, apagadosF, mes.getFullYear(), mes.getMonth(),
     estado.cuentas.map((c) => [c.slug, c.color, c.nombre])],
    pintarCalendario);

  // La marca de lo seleccionado va aparte: cambiar de post no puede costar
  // reconstruir el mes entero.
  marcarElegido();
  pintarDetalle();
  avisarDeLoQueEstaListo();

  // El SSE calla cuando no hay nada trabajando, así que el bloque terminado
  // necesita un empujón para irse solo cuando se le acabe el recreo.
  if (estado.generando.some((g) => g.estado === 'hecho'
        && Date.now() - (terminadasEn[g.id] || 0) < RECREO)) {
    clearTimeout(pintar.repaso);
    pintar.repaso = setTimeout(pintar, RECREO + 120);
  }
}

// ── galería ──────────────────────────────────────────────────────────

// La galería y los favoritos son la misma vista con distinto filtro: el mismo
// mosaico, las mismas cartas, y arriba un botón más.
const enGaleria = () => vista === 'galeria' || vista === 'favoritos';
const cuantasFavoritas = () => estado.borradores.filter((b) => b.favorito).length;

function galeriaVisible() {
  const lista = estado.borradores.filter((b) => {
    if (apagados.has(b.cuenta)) return false;
    if (vista === 'favoritos' && !b.favorito) return false;
    if (filtroTipo === 'video') return b.es_video;
    if (filtroTipo === 'foto') return !b.es_video;
    return true;
  });
  // De cinco corazones a uno. El sort de JS es estable, así que dentro de cada
  // escalón se mantiene el orden de siempre: lo último generado, primero.
  if (orden === 'gusto') lista.sort((a, z) => (z.favorito || 0) - (a.favorito || 0));
  return lista;
}

// ── cuánto te gusta ──────────────────────────────────────────────────

// Cinco corazones. Clicar el que ya está puesto lo quita de favoritos: es el
// mismo gesto para poner y para desmarcar, sin un botón aparte.
function corazones(b, clase = '') {
  const n = b.favorito || 0;
  return `<div class="gusto ${clase} ${n ? 'marcado' : ''}" data-gusto="${esc(b.id)}"
               title="${n ? `Te gusta ${n} de 5` : 'Marcar como favorito'}">${
    [1, 2, 3, 4, 5].map((i) => `<button class="corazon ${i <= n ? 'lleno' : ''}"
        data-nivel="${i}" aria-label="${i} de 5">♥</button>`).join('')
  }</div>`;
}

function engancharCorazones(raiz) {
  raiz.querySelectorAll('[data-gusto]').forEach((caja) => {
    caja.querySelectorAll('.corazon').forEach((btn) => {
      btn.onclick = (ev) => {
        ev.stopPropagation();          // clicar un corazón no abre la pieza
        const id = caja.dataset.gusto;
        const pieza = estado.borradores.find((x) => x.id === id) || {};
        const pedido = Number(btn.dataset.nivel);
        const nivel = (pieza.favorito || 0) === pedido ? 0 : pedido;
        // Se pinta al momento y el servidor confirma después: esperar medio
        // segundo a que vuelva el SSE para ver el corazón encenderse es lo
        // que hace que una interfaz parezca lenta.
        pieza.favorito = nivel;
        caja.classList.toggle('marcado', nivel > 0);
        caja.querySelectorAll('.corazon').forEach((c) => {
          c.classList.toggle('lleno', Number(c.dataset.nivel) <= nivel);
        });
        api('/api/favorito', {
          method: 'POST', body: JSON.stringify({ pieza: id, nivel }),
        }).catch(() => {});
      };
    });
  });
}

// ── borrar del todo ──────────────────────────────────────────────────

const rutaCorta = (r) => String(r).replace(/^\/Users\/[^/]+\//, '~/');

// Se pregunta al servidor qué hay detrás ANTES de preguntar a nadie: enseñar
// la carpeta que se va es la diferencia entre confirmar y firmar a ciegas.
async function borrarPieza(b) {
  let fuera = [];
  try { fuera = (await api(`/api/rastro/${b.id}`)).rastro || []; } catch { return; }

  const aviso = fuera.length
    ? `¿Borro «${b.titulo}»?\n\nSe va la carpeta entera del borrador, y esto `
      + `se manda a la Papelera del Mac:\n\n${fuera.map(rutaCorta).join('\n')}`
    : `¿Borro «${b.titulo}»?\n\nSe va la carpeta entera del borrador.`;
  if (!confirm(aviso)) return;

  await api(`/api/borrador/${b.id}?originales=1`, { method: 'DELETE' });
  if (elegido && elegido.id === b.id) elegido = null;
  // El SSE trae el estado nuevo, pero la carta se va ya: el hueco vacío
  // confirma el borrado antes de que llegue nada.
  estado.borradores = estado.borradores.filter((x) => x.id !== b.id);
  pintar();
}

// Vídeos incluidos, la galería solo pide miniaturas: son unos kilobytes en vez
// de un mp4 entero, y el navegador no tiene que decodificar treinta vídeos.
function laminaDe(b, clase = '') {
  const medio = b.medios[0] || '';
  return `<img class="${clase}" src="/mini/${medio}" alt="" loading="lazy">`;
}

// El hueco de la carta se reserva con el aspecto de la pieza, así el mosaico
// no da saltos según van llegando las miniaturas.
function aspectoDe(b) {
  return b.ancho && b.alto ? `--aspecto:${b.ancho}/${b.alto}` : '';
}

function pintarGaleria() {
  $('#tablero').classList.toggle('oculto', vista !== 'calendario');
  $('#galeria').classList.toggle('oculto', !enGaleria());
  $('#v-calendario').classList.toggle('puesta', vista === 'calendario');
  $('#v-galeria').classList.toggle('puesta', vista === 'galeria');
  $('#v-favoritos').classList.toggle('puesta', vista === 'favoritos');
  $('#f-tipo').querySelectorAll('button').forEach((b) => {
    b.classList.toggle('puesto', b.dataset.tipo === filtroTipo);
  });
  $('#f-orden').querySelectorAll('button').forEach((b) => {
    b.classList.toggle('puesto', b.dataset.orden === orden);
  });
  if (!enGaleria()) return;

  const lista = galeriaVisible();
  const hojas = Math.max(1, Math.ceil(lista.length / POR_HOJA));
  hoja = Math.min(hoja, hojas - 1);
  const desde = hoja * POR_HOJA;
  const enPantalla = lista.slice(desde, desde + POR_HOJA);

  $('#f-cuenta-total').textContent = lista.length
    ? `${desde + 1}–${desde + enPantalla.length} de ${lista.length}`
      + (lista.length === estado.borradores.length ? '' : ` (${estado.borradores.length} en total)`)
    : '';
  pintarHojas(hojas);

  $('#mosaico').innerHTML = enPantalla.length ? enPantalla.map((b, i) => `
    <div class="carta ${elegido && elegido.id === b.id ? 'elegida' : ''}"
         data-carta="${esc(b.id)}" style="animation-delay:${Math.min(i * 14, 260)}ms">
      <div class="lamina" style="${aspectoDe(b)}">
        ${laminaDe(b)}
        <span class="insignia ${b.es_video ? 'video' : ''}">${b.es_video ? 'MP4' : 'IMG'}</span>
        <button class="tirar" data-tirar="${esc(b.id)}" title="Borrar del todo">✕</button>
        ${corazones(b)}
      </div>
      <div class="pie">
        <div class="tit">${esc(b.titulo)}</div>
        <div class="sub">
          <span class="testigo" style="background:${colorDe(b.cuenta)}"></span>
          ${esc(nombreDe(b.cuenta))}
        </div>
      </div>
    </div>`).join('') : `
    <div class="desierto">
      <b>${vista === 'favoritos' ? 'Aún no hay favoritos' : 'La galería está vacía'}</b>
      ${vista === 'favoritos'
        ? 'Pasa por encima de una pieza de la galería y dale a los corazones: los que marques se guardan aquí.'
        : filtroTipo === 'todo'
          ? 'Lo que generes y no programes en el momento se guarda aquí.'
          : 'No hay nada de ese tipo guardado.'}
    </div>`;

  $('#mosaico').querySelectorAll('[data-carta]').forEach((el) => {
    el.onclick = () => { elegido = { clase: 'pieza', id: el.dataset.carta }; pintar(); };
  });
  $('#mosaico').querySelectorAll('[data-tirar]').forEach((el) => {
    el.onclick = (ev) => {
      ev.stopPropagation();
      const b = estado.borradores.find((x) => x.id === el.dataset.tirar);
      if (b) borrarPieza(b);
    };
  });
  engancharCorazones($('#mosaico'));
}

// Las hojas: primera, última y las vecinas de la actual. Con veinte páginas no
// caben todas en la barra y tampoco hacen falta.
function pintarHojas(cuantas) {
  const caja = $('#hojas');
  if (cuantas <= 1) { caja.innerHTML = ''; return; }

  const quiero = new Set([0, cuantas - 1, hoja, hoja - 1, hoja + 1]);
  const numeros = [...quiero].filter((n) => n >= 0 && n < cuantas).sort((a, b) => a - b);

  let html = `<button data-hoja="${Math.max(0, hoja - 1)}"
                ${hoja === 0 ? 'disabled' : ''}>‹</button>`;
  let previo = null;
  numeros.forEach((n) => {
    if (previo !== null && n - previo > 1) html += '<span class="puntos">…</span>';
    html += `<button data-hoja="${n}" class="${n === hoja ? 'puesta' : ''}">${n + 1}</button>`;
    previo = n;
  });
  html += `<button data-hoja="${Math.min(cuantas - 1, hoja + 1)}"
             ${hoja === cuantas - 1 ? 'disabled' : ''}>›</button>`;
  caja.innerHTML = html;

  caja.querySelectorAll('[data-hoja]').forEach((b) => {
    b.onclick = () => {
      hoja = Number(b.dataset.hoja);
      $('.lienzo').scrollTop = 0;
      pintar();
    };
  });
}

// ── «ya está, ¿lo programas?» ────────────────────────────────────────

function avisarDeLoQueEstaListo() {
  const listas = estado.generando.filter(
    (g) => g.estado === 'hecho' && !yaAvisadas.has(g.id));
  if (!listas.length) return;
  const g = listas[0];
  yaAvisadas.add(g.id);

  const suyas = estado.borradores.filter((b) => b.id.startsWith(`${g.id}/`));
  if (!suyas.length) return;
  modalYaEsta(g, suyas);
}

function modalYaEsta(g, piezas) {
  const varias = piezas.length > 1;
  abrirModal(`
    <h2>Ya está · <b>${varias ? `${piezas.length} piezas` : 'una pieza'}</b></h2>
    <div class="ficha">${esc(nombreDe(g.cuenta))} · ${g.modo === 'anim' ? 'vídeo' : 'imagen'}</div>
    <div class="recien">
      ${piezas.map((p) => `<div class="lamina" data-mirar="${esc(p.id)}">${laminaDe(p)}</div>`).join('')}
    </div>
    <div class="ficha">${varias
      ? 'Pulsa una para verla y decidir.'
      : esc(piezas[0].caption.split('\n')[0].slice(0, 110))}</div>
    <div class="botonera">
      <button data-cerrar>Guardar en la galería</button>
      <button class="principal" id="y-programar">¿La programo?</button>
    </div>
  `, () => {
    // Programar = abrir la pieza con el hueco ya propuesto; el día se cambia ahí.
    const abrir = (id) => { cerrarModal(); elegido = { clase: 'pieza', id }; pintar(); };
    $('#cuerpo-modal').querySelectorAll('[data-mirar]').forEach((el) => {
      el.onclick = () => abrir(el.dataset.mirar);
    });
    $('#y-programar').onclick = () => abrir(piezas[0].id);
    if (varias) $('#y-programar').textContent = 'Ver la primera';
  });
}

function contarPorCuenta() {
  const n = {};
  estado.entradas.forEach((e) => {
    if (e.estado === 'pendiente') n[e.cuenta] = (n[e.cuenta] || 0) + 1;
  });
  return n;
}

function marcarElegido() {
  document.querySelectorAll('.emision.elegido').forEach((e) => e.classList.remove('elegido'));
  if (elegido && elegido.clase === 'entrada') {
    const el = $('#rejilla').querySelector(`[data-post="${CSS.escape(elegido.id)}"]`);
    if (el) el.classList.add('elegido');
  }
}

function pintarCabecera() {
  $('#mes-nombre').textContent = `${MESES[mes.getMonth()]} ${mes.getFullYear()}`;
  $('#reloj').textContent = estado.ahora || '';

  const enCola = estado.entradas.filter((e) => e.estado === 'pendiente').length;
  const vivos = estado.generando.filter((g) => g.estado === 'trabajando').length;
  $('#i-canales').textContent = String(estado.cuentas.length).padStart(2, '0');
  $('#i-cola').textContent = String(enCola).padStart(2, '0');
  $('#i-borradores').textContent = String(estado.borradores.length).padStart(2, '0');
  $('#v-cuantas').textContent = String(estado.borradores.length).padStart(2, '0');
  $('#v-favoritas').textContent = String(cuantasFavoritas()).padStart(2, '0');

  const gen = $('#i-generando');
  gen.textContent = String(vivos).padStart(2, '0');
  gen.classList.toggle('viva', vivos > 0);

  const g = estado.git || {};
  const mal = !g.conectado || g.sin_subir > 0;
  let texto = 'enlace estable';
  if (g.sin_subir > 0) texto = `${g.sin_subir} sin subir`;
  if (!g.conectado) texto = 'sin github';
  $('#enlace').innerHTML = `<span class="diodo ${mal ? 'mal' : ''}"></span> ${texto}`;
  $('#enlace').title = g.aviso || g.ultimo || '';
}

function pintarCanales() {
  $('#lista-canales').innerHTML = estado.cuentas.map((c) => {
    const n = estado.entradas.filter((e) => e.cuenta === c.slug && e.estado === 'pendiente').length;
    return `
      <div class="canal ${apagados.has(c.slug) ? 'apagado' : ''}">
        <div class="fila-nom" data-canal="${c.slug}">
          <span class="testigo" style="background:${c.color}"></span>
          <span class="nom">${esc(c.nombre)}</span>
          <span class="cifra">${String(n).padStart(2, '0')}</span>
        </div>
        <div class="mandos">
          <button data-generar="${c.slug}" data-modo="post"
                  ${c.skill_post ? '' : 'disabled title="sin skill de foto"'}>Foto</button>
          <button data-generar="${c.slug}" data-modo="anim"
                  ${c.skill_anim ? '' : 'disabled title="sin skill de vídeo"'}>Vídeo</button>
        </div>
      </div>`;
  }).join('') || '<div class="vacio">NADA EN CUENTAS.JSON</div>';

  $('#lista-canales').querySelectorAll('[data-canal]').forEach((el) => {
    el.onclick = () => {
      const s = el.dataset.canal;
      apagados.has(s) ? apagados.delete(s) : apagados.add(s);
      localStorage.setItem('apagados', JSON.stringify([...apagados]));
      pintar();
    };
  });
  $('#lista-canales').querySelectorAll('[data-generar]').forEach((b) => {
    b.onclick = () => modalGenerar(b.dataset.generar, b.dataset.modo);
  });
}

// Una generación terminada se queda unos segundos con la barra llena: si el
// bloque se esfumase al 90 % nunca verías el final de lo que estabas mirando.
function trabajosEnPantalla() {
  const ahora = Date.now();
  return estado.generando.filter((g) => {
    if (g.estado !== 'hecho') return true;
    terminadasEn[g.id] ??= ahora;
    return ahora - terminadasEn[g.id] < RECREO;
  });
}

function pintarTrabajos() {
  const vivos = trabajosEnPantalla();
  $('#lista-trabajos').innerHTML = vivos.length ? vivos.map((g) => {
    const roto = g.estado === 'error';
    const listo = g.estado === 'hecho';
    return `
      <div class="trabajo ${roto || listo ? 'parado' : ''}">
        <div class="cab">
          ${roto ? '<span style="color:var(--alarma)">✕</span>'
                 : (g.estado === 'hecho' ? '<span style="color:var(--senal)">✓</span>'
                                         : '<span class="aspa"></span>')}
          <strong>${esc(nombreDe(g.cuenta))}</strong>
          <span class="modo">${g.modo === 'anim' ? 'VÍDEO' : 'FOTO'}${g.rehace ? ' · 2ª' : ''}</span>
          <span class="crece"></span>
          <span class="cifra" style="font-size:10px;color:var(--apagado)">${g.empezada}</span>
        </div>
        ${roto ? '' : `
          <div class="avance">
            <div class="letrero">
              <span data-etiqueta="${esc(g.id)}">${esc(g.etiqueta || '')}</span>
              <span class="pct" data-pct="${esc(g.id)}">0%</span>
            </div>
            <div class="carril">
              <div class="relleno ${listo ? 'lleno' : ''}" data-barra="${esc(g.id)}"></div>
            </div>
          </div>`}
        ${roto ? `<div class="consola" style="color:var(--alarma)">${esc(g.error)}</div>`
               : `<div class="consola">${g.lineas.map((l) => `<div>${esc(l)}</div>`).join('')}</div>`}
      </div>`;
  }).join('') : '<div class="vacio">SIN ENCARGOS ACTIVOS</div>';

  document.querySelectorAll('.consola').forEach((c) => { c.scrollTop = c.scrollHeight; });
}

// La barra se mueve sola, sin rehacer el bloque: solo cambian el ancho y dos
// textos, así la transición del CSS la lleva suave de un valor al siguiente.
function actualizarAvance() {
  estado.generando.forEach((g) => {
    const barra = document.querySelector(`[data-barra="${CSS.escape(g.id)}"]`);
    if (!barra) return;
    barra.style.width = `${g.progreso || 0}%`;
    const pct = document.querySelector(`[data-pct="${CSS.escape(g.id)}"]`);
    if (pct) pct.textContent = `${g.progreso || 0}%`;
    const et = document.querySelector(`[data-etiqueta="${CSS.escape(g.id)}"]`);
    if (et) et.textContent = g.etiqueta || '';
  });
}

function pintarPiezas() {
  const lista = estado.borradores.filter((b) => !apagados.has(b.cuenta));
  $('#lista-piezas').innerHTML = lista.length ? lista.map((b) => {
    const medio = b.medios[0] || '';
    const sello = `<img class="sello" src="/mini/${medio}" alt="" loading="lazy">`;
    return `
      <div class="pieza ${elegido && elegido.id === b.id ? 'elegida' : ''}" data-pieza="${esc(b.id)}">
        ${sello}
        <div class="crece" style="min-width:0">
          <div class="tit">${esc(b.titulo)}</div>
          <div class="sub">${esc(nombreDe(b.cuenta))}</div>
        </div>
        <span class="insignia ${b.es_video ? 'video' : ''}">${b.es_video ? 'MP4' : 'IMG'}</span>
      </div>`;
  }).join('') : '<div class="vacio">SIN BORRADORES</div>';

  $('#lista-piezas').querySelectorAll('[data-pieza]').forEach((el) => {
    el.onclick = () => { elegido = { clase: 'pieza', id: el.dataset.pieza }; pintar(); };
  });
}

function pintarCalendario() {
  const primero = new Date(mes.getFullYear(), mes.getMonth(), 1);
  // La rejilla empieza en lunes: getDay() da 0 para domingo, así que se rota.
  const inicio = new Date(primero);
  inicio.setDate(1 - ((primero.getDay() + 6) % 7));

  const hoy = clave(new Date());
  const porDia = {};
  estado.entradas.filter((e) => !apagados.has(e.cuenta)).forEach((e) => {
    (porDia[e.fecha.slice(0, 10)] ||= []).push(e);
  });

  // Animar la rejilla en cada actualización de datos era el parpadeo. Solo se
  // anima cuando cambias de mes, que es cuando el movimiento significa algo.
  const clavaMes = `${mes.getFullYear()}-${mes.getMonth()}`;
  const animar = mesPintado !== clavaMes;
  mesPintado = clavaMes;

  let html = '';
  for (let i = 0; i < 42; i++) {
    const d = new Date(inicio);
    d.setDate(inicio.getDate() + i);
    const k = clave(d);
    const fuera = d.getMonth() !== mes.getMonth();
    const posts = (porDia[k] || []).sort((a, b) => a.fecha.localeCompare(b.fecha));
    html += `
      <div class="jornada ${fuera ? 'fuera' : ''} ${k === hoy ? 'hoy' : ''}"
           data-dia="${k}" style="${animar
             ? `animation-delay:${Math.min(i * 6, 220)}ms`
             : 'animation:none'}">
        <div class="num mono">${String(d.getDate()).padStart(2, '0')}</div>
        <div class="pila">
        ${posts.map((e) => `
          <div class="emision ${e.estado}"
               style="border-left-color:${colorDe(e.cuenta)}"
               draggable="${e.editable}" data-post="${esc(e.id)}">
            <div class="sello-hora">${e.fecha.slice(11)} · ${esc(nombreDe(e.cuenta))}</div>
            <div class="txt">${esc(e.caption || nombreLegible(e.id))}</div>
          </div>`).join('')}
        </div>
      </div>`;
  }
  $('#rejilla').innerHTML = html;

  $('#rejilla').querySelectorAll('[data-post]').forEach((el) => {
    el.onclick = () => { elegido = { clase: 'entrada', id: el.dataset.post }; pintar(); };
    el.ondragstart = (ev) => ev.dataTransfer.setData('text/plain', el.dataset.post);
  });
  $('#rejilla').querySelectorAll('[data-dia]').forEach((celda) => {
    // Pulsar el hueco de un día ofrece llenarlo; pulsar un post de dentro no.
    celda.onclick = (ev) => {
      if (ev.target.closest('.emision')) return;
      if (celda.dataset.dia < clave(new Date())) return;
      modalLlenarDia(celda.dataset.dia);
    };
    celda.classList.toggle('libre', celda.dataset.dia >= clave(new Date()));
    celda.ondragover = (ev) => { ev.preventDefault(); celda.classList.add('encima'); };
    celda.ondragleave = () => celda.classList.remove('encima');
    celda.ondrop = async (ev) => {
      ev.preventDefault();
      celda.classList.remove('encima');
      const id = ev.dataTransfer.getData('text/plain');
      const fila = estado.entradas.find((e) => e.id === id);
      if (!fila) return;
      // Se cambia el día y se respeta la hora: mover de sitio no es reprogramar.
      await api(`/api/entrada/${encodeURIComponent(id)}`, {
        method: 'PATCH',
        body: JSON.stringify({ fecha: `${celda.dataset.dia} ${fila.fecha.slice(11)}` }),
      });
    };
  });
}

// ── elegir cuándo sale ───────────────────────────────────────────────
//
// Antes era un campo de texto donde había que escribir «2026-09-20 21:00» de
// memoria y sin equivocarse. Aquí se ve el mes, qué días tiene ya algo esa
// cuenta —el punto de color— y las horas a las que suele publicar.

let cuando = { dia: '', hora: '', mes: new Date(), slug: '', para: '' };

const DIAS_ES = ['lunes', 'martes', 'miércoles', 'jueves', 'viernes', 'sábado', 'domingo'];

// `para` es de quién es la elección. Si el panel se repinta por otra cosa —el
// cron acaba de publicar en otra cuenta— la fecha que estabas eligiendo no se
// reinicia; solo cuando de verdad cambias de pieza.
function arrancarCuando(slug, valor, para) {
  if (cuando.para === para) { cuando.slug = slug; return; }
  const [dia, hora] = (valor || '').split(' ');
  cuando = { dia: dia || '', hora: hora || '', slug, para,
             mes: dia ? new Date(`${dia}T12:00:00`) : new Date() };
}

function valorCuando() {
  return cuando.dia && cuando.hora ? `${cuando.dia} ${cuando.hora}` : '';
}

function pintarCuando() {
  const caja = $('#cuando');
  if (!caja) return;

  const c = cuentaDe(cuando.slug);
  const franjas = c.franjas && c.franjas.length ? c.franjas : ['21:00'];
  const hoy = clave(new Date());
  const ahora = (estado.ahora || '').slice(11) || '00:00';

  // Qué tiene ya esta cuenta, para no amontonar dos cosas el mismo día.
  const ocupado = {};
  estado.entradas.filter((e) => e.cuenta === cuando.slug).forEach((e) => {
    (ocupado[e.fecha.slice(0, 10)] ||= []).push(e.fecha.slice(11));
  });

  const primero = new Date(cuando.mes.getFullYear(), cuando.mes.getMonth(), 1);
  const inicio = new Date(primero);
  inicio.setDate(1 - ((primero.getDay() + 6) % 7));

  let dias = '';
  for (let i = 0; i < 42; i++) {
    const d = new Date(inicio);
    d.setDate(inicio.getDate() + i);
    const k = clave(d);
    const fuera = d.getMonth() !== cuando.mes.getMonth();
    // El pasado no se puede programar; hoy solo si aún queda alguna franja.
    const pasado = k < hoy;
    const marca = ocupado[k]
      ? `<span class="ocupado" style="background:${c.color || 'var(--ambar)'}"></span>` : '';
    dias += `<button data-cuando-dia="${k}" ${pasado ? 'disabled' : ''}
      class="${fuera ? 'fuera' : ''} ${k === hoy ? 'hoy' : ''} ${k === cuando.dia ? 'puesto' : ''}"
      title="${ocupado[k] ? `ya hay algo a las ${ocupado[k].join(', ')}` : ''}"
      >${d.getDate()}${marca}</button>`;
  }

  const libre = !franjas.includes(cuando.hora) && cuando.hora;
  caja.innerHTML = `
    <div class="cuando-cab">
      <button data-mover="-1">‹</button>
      <strong>${MESES[cuando.mes.getMonth()]} ${cuando.mes.getFullYear()}</strong>
      <button data-mover="1">›</button>
    </div>
    <div class="cuando-semana">
      ${['l', 'm', 'x', 'j', 'v', 's', 'd'].map((x) => `<span>${x}</span>`).join('')}
    </div>
    <div class="cuando-dias">${dias}</div>
    <div class="cuando-horas">
      ${franjas.map((f) => `<button data-hora="${f}"
          class="${cuando.hora === f ? 'puesta' : ''}">${f}</button>`).join('')}
      <input type="time" id="hora-libre" value="${esc(cuando.hora)}"
             class="${libre ? 'puesta' : ''}" title="otra hora">
    </div>
    <div class="cuando-resumen">${resumenCuando(ocupado, ahora, hoy)}</div>
  `;

  caja.querySelectorAll('[data-mover]').forEach((b) => {
    b.onclick = () => {
      cuando.mes = new Date(cuando.mes.getFullYear(),
                            cuando.mes.getMonth() + Number(b.dataset.mover), 1);
      pintarCuando();
    };
  });
  caja.querySelectorAll('[data-cuando-dia]').forEach((b) => {
    b.onclick = () => { cuando.dia = b.dataset.cuandoDia; pintarCuando(); };
  });
  caja.querySelectorAll('[data-hora]').forEach((b) => {
    b.onclick = () => { cuando.hora = b.dataset.hora; pintarCuando(); };
  });
  const libreInput = $('#hora-libre');
  if (libreInput) {
    libreInput.onchange = () => {
      if (libreInput.value) { cuando.hora = libreInput.value; pintarCuando(); }
    };
  }
}

function resumenCuando(ocupado, ahora, hoy) {
  if (!cuando.dia || !cuando.hora) return 'Elige el día y la hora.';
  const d = new Date(`${cuando.dia}T12:00:00`);
  const texto = `<b>${DIAS_ES[(d.getDay() + 6) % 7]} ${d.getDate()} de `
              + `${MESES[d.getMonth()]}</b> a las <b>${cuando.hora}</b>`;
  let pega = '';
  if (cuando.dia === hoy && cuando.hora <= ahora) {
    pega = 'esa hora ya ha pasado';
  } else if ((ocupado[cuando.dia] || []).includes(cuando.hora)) {
    pega = 'ya hay otro a esa hora';
  } else if (ocupado[cuando.dia]) {
    pega = `ese día ya sale otro a las ${ocupado[cuando.dia].join(', ')}`;
  }
  return texto + (pega ? `<span class="aviso-choque">${pega}</span>` : '');
}

// ── panel de detalle ─────────────────────────────────────────────────

function pintarDetalle() {
  const marco = $('#marco');
  if (!elegido) {
    marco.classList.remove('con-detalle');
    firmas.detalle = null;
    return;
  }
  const esPieza = elegido.clase === 'pieza';
  const dato = esPieza
    ? estado.borradores.find((b) => b.id === elegido.id)
    : estado.entradas.find((e) => e.id === elegido.id);
  if (!dato) {
    elegido = null;
    marco.classList.remove('con-detalle');
    firmas.detalle = null;
    return;
  }
  marco.classList.add('con-detalle');

  // Con el cursor dentro de un campo no se reconstruye nada: se apunta que
  // queda pendiente y se pinta cuando salgas.
  if (estoyEscribiendo()) { detallePendiente = true; return; }
  detallePendiente = false;

  siCambia('detalle', [elegido.clase, elegido.id, dato],
           () => (esPieza ? detallePieza(dato) : detalleEntrada(dato)));
}

function visorDe(rutas, base) {
  if (!rutas.length) return '';
  const uno = (r) => (base ? `${base}/${r}` : r);
  if (rutas.length > 1) {
    return `<div class="tira">${rutas.map((r) =>
      `<img src="${uno(r)}" alt="" loading="lazy">`).join('')}</div>`;
  }
  return /\.(mp4|mov|m4v)$/i.test(rutas[0])
    ? `<video class="visor" src="${uno(rutas[0])}" controls loop></video>`
    : `<img class="visor" src="${uno(rutas[0])}" alt="">`;
}

function detalleEntrada(e) {
  const publicado = e.estado === 'publicado';
  $('#detalle').innerHTML = `
    <div class="cabecera">
      <span class="testigo" style="background:${colorDe(e.cuenta)};margin-top:5px"></span>
      <div class="crece" style="min-width:0">
        <h2>${esc(nombreDe(e.cuenta))}</h2>
        <div class="ficha">${e.tipo} · ${esc(e.id)}</div>
      </div>
      <button class="icono" id="cerrar">✕</button>
    </div>

    ${e.estado === 'error' ? `<div class="alerta">${esc(e.nota)}</div>` : ''}
    ${publicado ? '<div class="nota">Publicado. Lo que se toque aquí ya no cambia nada en Instagram.</div>' : ''}
    ${e.estado === 'pausado' ? `<div class="alerta">En pausa: ${esc(e.nota)}. Cambia la fecha para devolverlo a la cola.</div>` : ''}

    ${visorDe(e.urls, '')}

    <label>Cuándo sale</label>
    ${publicado
      ? `<div class="nota mono" style="margin:0">${esc(e.fecha)}</div>`
      : '<div class="cuando" id="cuando"></div>'}

    <label>Texto del post</label>
    <textarea id="d-caption" ${publicado ? 'disabled' : ''}>${esc(e.caption)}</textarea>

    ${publicado ? '' : `
      <div class="botonera">
        <button class="principal" id="d-guardar">Guardar</button>
        <button class="peligro" id="d-borrar">Quitar</button>
      </div>`}
  `;
  $('#cerrar').onclick = cerrarDetalle;
  if (publicado) return;

  arrancarCuando(e.cuenta, e.fecha, e.id);
  pintarCuando();

  $('#d-guardar').onclick = () => {
    const fecha = valorCuando();
    if (!fecha) { alert('Elige el día y la hora.'); return; }
    return api(`/api/entrada/${encodeURIComponent(e.id)}`, {
      method: 'PATCH',
      body: JSON.stringify({ fecha, caption: $('#d-caption').value }),
    });
  };
  $('#d-borrar').onclick = async () => {
    if (!confirm('¿Lo quito de la cola? El medio sigue en el bucket.')) return;
    await api(`/api/entrada/${encodeURIComponent(e.id)}`, { method: 'DELETE' });
    elegido = null;
  };
}

function detallePieza(b) {
  $('#detalle').innerHTML = `
    <div class="cabecera">
      <span class="testigo" style="background:${colorDe(b.cuenta)};margin-top:5px"></span>
      <div class="crece" style="min-width:0">
        <h2>${esc(b.titulo)}</h2>
        <div class="ficha">${esc(nombreDe(b.cuenta))} · ${b.tipo}${b.con_audio ? ' · CON AUDIO' : ''}</div>
      </div>
      <button class="icono" id="cerrar">✕</button>
    </div>

    ${visorDe(b.medios, '/borradores')}
    ${b.brief ? `<div class="nota">La idea que se pidió: ${esc(b.brief)}</div>` : ''}

    <div class="fila-gusto">
      <label>Cuánto te gusta</label>
      ${corazones(b, 'grande')}
    </div>

    <label>Cuándo lo saco</label>
    <div class="cuando" id="cuando"></div>

    <label>Texto del post</label>
    <textarea id="b-caption">${esc(b.caption)}</textarea>

    <div class="botonera">
      <button class="principal" id="b-programar">Me gusta · programar</button>
    </div>
    <div class="botonera">
      <button id="b-retocar">Cambiar algo</button>
      <button id="b-rehacer">Rediseñar</button>
      <button class="peligro" id="b-tirar">Borrar</button>
    </div>
  `;
  $('#cerrar').onclick = cerrarDetalle;

  arrancarCuando(b.cuenta, '', b.id);
  pintarCuando();

  // El hueco se propone solo, pero sin pisar lo que ya hayas elegido tú.
  if (!cuando.dia) {
    api('/api/hueco', { method: 'POST', body: JSON.stringify({ cuenta: b.cuenta }) })
      .then((r) => {
        // Si mientras llegaba la respuesta has cambiado de pieza o ya has
        // elegido tú un día, la propuesta se descarta.
        if (cuando.para !== b.id || cuando.dia) return;
        const [dia, hora] = (r.fecha || '').split(' ');
        cuando.dia = dia || '';
        cuando.hora = hora || '';
        if (dia) cuando.mes = new Date(`${dia}T12:00:00`);
        pintarCuando();
      });
  }

  $('#b-programar').onclick = async () => {
    const fecha = valorCuando();
    if (!fecha) { alert('Elige el día y la hora.'); return; }
    const boton = $('#b-programar');
    boton.disabled = true;
    boton.textContent = 'Subiendo el medio…';
    try {
      await api('/api/programar', {
        method: 'POST',
        body: JSON.stringify({ pieza: b.id, fecha,
                               caption: $('#b-caption').value, tipo: b.tipo }),
      });
      cuando.para = '';
      elegido = null;
    } finally { boton.disabled = false; boton.textContent = 'Me gusta · programar'; }
  };
  $('#b-retocar').onclick = () => modalRetocar(b);
  $('#b-rehacer').onclick = () => pedirRediseño(b);
  $('#b-tirar').onclick = () => borrarPieza(b);
  engancharCorazones($('#detalle'));
}

function cerrarDetalle() { elegido = null; pintar(); }

// ── modales ──────────────────────────────────────────────────────────

function abrirModal(html, enganchar) {
  $('#cuerpo-modal').innerHTML = html;
  $('#telon').classList.remove('oculto');
  $('#cuerpo-modal').querySelectorAll('[data-cerrar]').forEach((b) => { b.onclick = cerrarModal; });
  if (enganchar) enganchar();
}
function cerrarModal() { $('#telon').classList.add('oculto'); }
$('#telon').onclick = (ev) => { if (ev.target === $('#telon')) cerrarModal(); };

function avisoCli(c, modo) {
  if (!estado.cli_claude) {
    return `<div class="alerta">Falta el CLI de Claude Code. Instálalo con
      <code>npm install -g @anthropic-ai/claude-code</code> y vuelve a intentarlo.</div>`;
  }
  // Con acceptEdits Claude escribe archivos pero no ejecuta nada, así que la
  // pieza nunca llega a componerse. Mejor decirlo aquí que gastar el encargo.
  if (!estado.puede_ejecutar) {
    return `<div class="alerta">Claude no va a poder componer la pieza: está en
      <code>${esc(estado.permisos || '')}</code> y así no puede ejecutar comandos
      ni leer las referencias de la skill. Añade
      <code>GENERADOR_PERMISOS=bypassPermissions</code> al <code>.env</code> y
      reinicia el panel.</div>`;
  }
  const skill = modo === 'anim' ? c.skill_anim : c.skill_post;
  return skill ? '' : `<div class="alerta">${esc(c.nombre)} no tiene skill de
    ${modo === 'anim' ? 'vídeo' : 'foto'} declarada en cuentas.json.</div>`;
}

function modalGenerar(slug, modo) {
  const c = cuentaDe(slug);
  const skill = modo === 'anim' ? c.skill_anim : c.skill_post;
  abrirModal(`
    <h2>Nuevo encargo · <b>${modo === 'anim' ? 'VÍDEO' : 'FOTO'}</b></h2>
    <div class="ficha">${esc(c.nombre)} · @${esc(c.usuario)}${skill ? ` · /${esc(skill)}` : ''}</div>
    ${avisoCli(c, modo)}
    <label>La idea</label>
    <textarea id="m-brief" style="min-height:92px"
      placeholder="Una frase basta. «La cena de cumpleaños en la que uno no bebe y paga lo mismo.» Déjalo vacío y decide él."></textarea>
    <label>Cuántas piezas</label>
    <select id="m-cuantos"><option>1</option><option>2</option><option>3</option></select>
    <div class="botonera">
      <button data-cerrar>Cancelar</button>
      <button class="principal" id="m-lanzar"
        ${skill && estado.cli_claude && estado.puede_ejecutar ? '' : 'disabled'}>Generar</button>
    </div>
  `, () => {
    $('#m-brief').focus();
    $('#m-lanzar').onclick = async () => {
      await api('/api/generar', {
        method: 'POST',
        body: JSON.stringify({ cuenta: slug, modo, brief: $('#m-brief').value,
                               cuantos: Number($('#m-cuantos').value) }),
      });
      cerrarModal();
    };
  });
}

function modalRetocar(b) {
  abrirModal(`
    <h2>Cambiar <b>algo</b></h2>
    <div class="ficha">${esc(b.titulo)} · ${esc(nombreDe(b.cuenta))}</div>
    <div class="nota">Se conserva la pieza y se toca solo lo que digas. En vídeo,
      el audio se mantiene.</div>
    <label>Qué hay que cambiar</label>
    <textarea id="r-que" style="min-height:88px"
      placeholder="«El texto del final que sea más corto.» · «Que el ticket entre más despacio.»"></textarea>
    <div class="botonera">
      <button data-cerrar>Cancelar</button>
      <button class="principal" id="r-lanzar">Cambiarlo</button>
    </div>
  `, () => {
    $('#r-que').focus();
    $('#r-lanzar').onclick = async () => {
      const que = $('#r-que').value.trim();
      if (!que) { $('#r-que').focus(); return; }
      await api('/api/rehacer', {
        method: 'POST',
        body: JSON.stringify({ pieza: b.id, instruccion: que, entero: false,
                               mantener_audio: true }),
      });
      cerrarModal();
      elegido = null;
    };
  });
}

// Rediseñar es rehacerla desde cero. En vídeo hay que decidir antes qué pasa
// con el audio: volver a montar la voz cuesta mucho más que redibujar planos.
function pedirRediseño(b) {
  if (!b.es_video) {
    lanzarRediseño(b, false);
    return;
  }
  let mantener = b.con_audio;
  abrirModal(`
    <h2>Rediseñar el <b>vídeo</b></h2>
    <div class="ficha">${esc(b.titulo)} · ${esc(nombreDe(b.cuenta))}</div>
    <div class="nota">Se rehace desde cero: otra composición, otro recurso, otra
      forma de contarlo.</div>
    ${b.con_audio ? `
      <label>¿Mantenemos el audio?</label>
      <div class="palanca" id="p-audio">
        <button data-si="1" class="puesto">Sí, el mismo</button>
        <button data-si="0">No, de nuevo</button>
      </div>
      <div class="ficha" style="margin-top:7px" id="p-nota">
        Se reaprovecha la pista del mp4 y la animación se cuadra contra ella.
      </div>`
      : '<div class="ficha">Este vídeo no lleva pista de audio.</div>'}
    <div class="botonera">
      <button data-cerrar>Cancelar</button>
      <button class="principal" id="p-lanzar">Rediseñar</button>
    </div>
  `, () => {
    const palanca = $('#p-audio');
    if (palanca) {
      palanca.querySelectorAll('button').forEach((bt) => {
        bt.onclick = () => {
          mantener = bt.dataset.si === '1';
          palanca.querySelectorAll('button').forEach((o) => o.classList.remove('puesto'));
          bt.classList.add('puesto');
          $('#p-nota').textContent = mantener
            ? 'Se reaprovecha la pista del mp4 y la animación se cuadra contra ella.'
            : 'Se genera una voz nueva; los tiempos se rehacen enteros.';
        };
      });
    }
    $('#p-lanzar').onclick = () => { cerrarModal(); lanzarRediseño(b, mantener); };
  });
}

async function lanzarRediseño(b, mantenerAudio) {
  await api('/api/rehacer', {
    method: 'POST',
    body: JSON.stringify({ pieza: b.id, instruccion: '', entero: true,
                           mantener_audio: mantenerAudio }),
  });
  elegido = null;
  pintar();
}

// ── llenar un día desde el calendario ────────────────────────────────
//
// Al revés que el flujo normal: aquí primero eliges el día —pulsándolo— y
// luego qué sacar ese día, de todo lo que tengas guardado.

let eleccionDia = { dia: '', hora: '', pieza: '', tipo: 'todo' };

function modalLlenarDia(dia) {
  const d = new Date(`${dia}T12:00:00`);
  const yaHay = estado.entradas.filter((e) => e.fecha.startsWith(dia)
                                           && !apagados.has(e.cuenta));
  eleccionDia = { dia, hora: '', pieza: '', tipo: 'todo' };

  abrirModal(`
    <h2>Programar el <b>${DIAS_ES[(d.getDay() + 6) % 7]} ${d.getDate()} de ${MESES[d.getMonth()]}</b></h2>
    <div class="ficha" id="e-estado"></div>
    ${yaHay.length ? `<div class="nota" style="margin-top:10px">Ese día ya sale
      ${yaHay.length === 1 ? 'una pieza' : `${yaHay.length} piezas`}:
      ${esc(yaHay.map((e) => `${e.fecha.slice(11)} ${nombreDe(e.cuenta)}`).join(' · '))}.</div>` : ''}

    <div class="barra-elegir">
      <span class="et">Hora</span>
      <div class="palanca" id="e-horas"></div>
      <span class="crece"></span>
      <span class="et">Mostrar</span>
      <div class="palanca" id="e-tipo">
        <button data-tipo="todo" class="puesto">Todo</button>
        <button data-tipo="foto">Imagen</button>
        <button data-tipo="video">Vídeo</button>
      </div>
    </div>

    <div class="escaparate"><div class="mosaico" id="e-mosaico"></div></div>

    <div class="botonera">
      <button data-cerrar>Cancelar</button>
      <button class="principal" id="e-programar" disabled>Programar aquí</button>
    </div>
  `, () => {
    $('#e-tipo').querySelectorAll('button').forEach((b) => {
      b.onclick = () => { eleccionDia.tipo = b.dataset.tipo; pintarEleccion(); };
    });
    $('#e-programar').onclick = programarElegida;
    pintarEleccion();
  });
}

function piezasParaElegir() {
  return estado.borradores.filter((b) => {
    if (apagados.has(b.cuenta)) return false;
    if (eleccionDia.tipo === 'video') return b.es_video;
    if (eleccionDia.tipo === 'foto') return !b.es_video;
    return true;
  });
}

function pintarEleccion() {
  const elegida = estado.borradores.find((b) => b.id === eleccionDia.pieza);

  // Las horas son las de la cuenta de la pieza; sin pieza aún, las de las
  // cuentas que estés mirando.
  const franjas = [...new Set(
    (elegida ? [cuentaDe(elegida.cuenta)]
             : estado.cuentas.filter((c) => !apagados.has(c.slug)))
      .flatMap((c) => c.franjas || []))].sort();
  if (!eleccionDia.hora && franjas.length) eleccionDia.hora = franjas[0];

  $('#e-horas').innerHTML = franjas.map((f) => `<button data-h="${f}"
      class="${eleccionDia.hora === f ? 'puesto' : ''}">${f}</button>`).join('')
    || '<button disabled>sin franjas</button>';
  $('#e-horas').querySelectorAll('[data-h]').forEach((b) => {
    b.onclick = () => { eleccionDia.hora = b.dataset.h; pintarEleccion(); };
  });

  $('#e-tipo').querySelectorAll('button').forEach((b) => {
    b.classList.toggle('puesto', b.dataset.tipo === eleccionDia.tipo);
  });

  const lista = piezasParaElegir();
  $('#e-mosaico').innerHTML = lista.length ? lista.map((b) => `
    <div class="carta ${b.id === eleccionDia.pieza ? 'elegida' : ''}"
         data-elegir="${esc(b.id)}" style="animation:none">
      <div class="lamina" style="${aspectoDe(b)}">
        ${laminaDe(b)}
        <span class="insignia ${b.es_video ? 'video' : ''}">${b.es_video ? 'MP4' : 'IMG'}</span>
      </div>
      <div class="pie"><div class="tit">${esc(b.titulo)}</div>
        <div class="sub">${esc(nombreDe(b.cuenta))}</div></div>
    </div>`).join('')
    : '<div class="desierto"><b>Nada guardado de ese tipo</b>Genera algo o cambia el filtro.</div>';

  $('#e-mosaico').querySelectorAll('[data-elegir]').forEach((el) => {
    el.onclick = () => { eleccionDia.pieza = el.dataset.elegir; pintarEleccion(); };
  });

  const listo = Boolean(elegida && eleccionDia.hora);
  $('#e-programar').disabled = !listo;
  $('#e-estado').textContent = elegida
    ? `${elegida.titulo} · ${nombreDe(elegida.cuenta)} · ${eleccionDia.hora}`
    : `${lista.length} piezas guardadas — elige una`;
}

async function programarElegida() {
  const pieza = estado.borradores.find((b) => b.id === eleccionDia.pieza);
  if (!pieza) return;
  const boton = $('#e-programar');
  boton.disabled = true;
  boton.textContent = 'Subiendo el medio…';
  try {
    await api('/api/programar', {
      method: 'POST',
      body: JSON.stringify({ pieza: pieza.id,
                             fecha: `${eleccionDia.dia} ${eleccionDia.hora}`,
                             caption: pieza.caption, tipo: pieza.tipo }),
    });
    cerrarModal();
  } finally { boton.disabled = false; boton.textContent = 'Programar aquí'; }
}

// ── navegación ───────────────────────────────────────────────────────

function cambiarVista(cual) {
  if (cual !== vista) hoja = 0;
  vista = cual;
  localStorage.setItem('vista', cual);
  pintar();
}
$('#v-calendario').onclick = () => cambiarVista('calendario');
$('#v-galeria').onclick = () => cambiarVista('galeria');
$('#v-favoritos').onclick = () => cambiarVista('favoritos');
$('#f-tipo').querySelectorAll('button').forEach((b) => {
  b.onclick = () => {
    filtroTipo = b.dataset.tipo;
    localStorage.setItem('filtroTipo', filtroTipo);
    hoja = 0;
    pintar();
  };
});
$('#f-orden').querySelectorAll('button').forEach((b) => {
  b.onclick = () => {
    orden = b.dataset.orden;
    localStorage.setItem('orden', orden);
    hoja = 0;
    pintar();
  };
});

$('#mes-atras').onclick = () => { mes.setMonth(mes.getMonth() - 1); pintar(); };
$('#mes-alante').onclick = () => { mes.setMonth(mes.getMonth() + 1); pintar(); };
$('#mes-hoy').onclick = () => { mes = new Date(); pintar(); };
document.addEventListener('keydown', (ev) => {
  if (ev.key !== 'Escape') return;
  if (!$('#telon').classList.contains('oculto')) { cerrarModal(); return; }
  cerrarDetalle();
});

document.addEventListener('focusout', () => {
  // El focusout llega antes de que el foco aterrice en el siguiente elemento;
  // un respiro y ya se sabe si sigues dentro de un campo o no.
  setTimeout(() => { if (detallePendiente && !estoyEscribiendo()) pintar(); }, 0);
});

fetch('/api/estado').then((r) => r.json()).then((e) => { estado = e; pintar(); });
conectar();
