// Panel de publicación. Sin framework y sin compilar: se edita el archivo, se
// recarga y ya está. El estado llega entero por SSE en cada cambio, así que
// aquí no se guarda nada que no venga del servidor —salvo lo que el ojo tiene
// puesto encima: el mes, los canales apagados y lo seleccionado.

const $ = (sel) => document.querySelector(sel);
const MESES = ['enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio',
  'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre'];

let estado = { cuentas: [], entradas: [], borradores: [], generando: [], git: {} };
let apagados = new Set(JSON.parse(localStorage.getItem('apagados') || '[]'));
let mes = new Date();
let elegido = null;               // {clase:'entrada'|'pieza', id}

const cuentaDe = (slug) => estado.cuentas.find((c) => c.slug === slug) || {};
const colorDe = (slug) => cuentaDe(slug).color || '#8891a3';
const nombreDe = (slug) => cuentaDe(slug).nombre || slug;
const clave = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
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
  pintarCabecera();
  pintarCanales();
  pintarTrabajos();
  pintarPiezas();
  pintarCalendario();
  pintarDetalle();
}

function pintarCabecera() {
  $('#mes-nombre').textContent = `${MESES[mes.getMonth()]} ${mes.getFullYear()}`;
  $('#reloj').textContent = estado.ahora || '';

  const enCola = estado.entradas.filter((e) => e.estado === 'pendiente').length;
  const vivos = estado.generando.filter((g) => g.estado === 'trabajando').length;
  $('#i-canales').textContent = String(estado.cuentas.length).padStart(2, '0');
  $('#i-cola').textContent = String(enCola).padStart(2, '0');
  $('#i-borradores').textContent = String(estado.borradores.length).padStart(2, '0');
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

function pintarTrabajos() {
  const vivos = estado.generando.filter((g) => g.estado !== 'hecho');
  $('#lista-trabajos').innerHTML = vivos.length ? vivos.map((g) => {
    const roto = g.estado === 'error';
    return `
      <div class="trabajo ${roto ? 'parado' : ''}">
        <div class="cab">
          ${roto ? '<span style="color:var(--alarma)">✕</span>' : '<span class="aspa"></span>'}
          <strong>${esc(nombreDe(g.cuenta))}</strong>
          <span class="modo">${g.modo === 'anim' ? 'VÍDEO' : 'FOTO'}${g.rehace ? ' · 2ª' : ''}</span>
          <span class="crece"></span>
          <span class="cifra" style="font-size:10px;color:var(--apagado)">${g.empezada}</span>
        </div>
        ${roto ? `<div class="consola" style="color:var(--alarma)">${esc(g.error)}</div>`
               : `<div class="consola">${g.lineas.map((l) => `<div>${esc(l)}</div>`).join('')}</div>`}
      </div>`;
  }).join('') : '<div class="vacio">SIN ENCARGOS ACTIVOS</div>';

  document.querySelectorAll('.consola').forEach((c) => { c.scrollTop = c.scrollHeight; });
}

function pintarPiezas() {
  const lista = estado.borradores.filter((b) => !apagados.has(b.cuenta));
  $('#lista-piezas').innerHTML = lista.length ? lista.map((b) => {
    const medio = b.medios[0] || '';
    const sello = b.es_video
      ? `<video class="sello" src="/borradores/${medio}" muted></video>`
      : `<img class="sello" src="/borradores/${medio}" alt="">`;
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

  let html = '';
  for (let i = 0; i < 42; i++) {
    const d = new Date(inicio);
    d.setDate(inicio.getDate() + i);
    const k = clave(d);
    const fuera = d.getMonth() !== mes.getMonth();
    const posts = (porDia[k] || []).sort((a, b) => a.fecha.localeCompare(b.fecha));
    html += `
      <div class="jornada ${fuera ? 'fuera' : ''} ${k === hoy ? 'hoy' : ''}"
           data-dia="${k}" style="animation-delay:${Math.min(i * 6, 220)}ms">
        <div class="num mono">${String(d.getDate()).padStart(2, '0')}</div>
        <div class="pila">
        ${posts.map((e) => `
          <div class="emision ${e.estado} ${elegido && elegido.id === e.id ? 'elegido' : ''}"
               style="border-left-color:${colorDe(e.cuenta)}"
               draggable="${e.editable}" data-post="${esc(e.id)}">
            <div class="sello-hora">${e.fecha.slice(11)} · ${esc(nombreDe(e.cuenta))}</div>
            <div class="txt">${esc(e.caption || e.id)}</div>
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

// ── panel de detalle ─────────────────────────────────────────────────

function pintarDetalle() {
  const marco = $('#marco');
  if (!elegido) { marco.classList.remove('con-detalle'); return; }
  const esPieza = elegido.clase === 'pieza';
  const dato = esPieza
    ? estado.borradores.find((b) => b.id === elegido.id)
    : estado.entradas.find((e) => e.id === elegido.id);
  if (!dato) { elegido = null; marco.classList.remove('con-detalle'); return; }
  marco.classList.add('con-detalle');
  esPieza ? detallePieza(dato) : detalleEntrada(dato);
}

function visorDe(rutas, base) {
  if (!rutas.length) return '';
  const uno = (r) => (base ? `${base}/${r}` : r);
  if (rutas.length > 1) {
    return `<div class="tira">${rutas.map((r) => `<img src="${uno(r)}" alt="">`).join('')}</div>`;
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
    <input id="d-fecha" value="${esc(e.fecha)}" ${publicado ? 'disabled' : ''}>

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

  $('#d-guardar').onclick = () => api(`/api/entrada/${encodeURIComponent(e.id)}`, {
    method: 'PATCH',
    body: JSON.stringify({ fecha: $('#d-fecha').value.trim(), caption: $('#d-caption').value }),
  });
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

    <label>Cuándo lo saco</label>
    <input id="b-fecha" placeholder="buscando hueco…">

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

  // El hueco se propone solo: casi siempre es el que quieres, y si no, se edita.
  api('/api/hueco', { method: 'POST', body: JSON.stringify({ cuenta: b.cuenta }) })
    .then((r) => { const c = $('#b-fecha'); if (c && !c.value) c.value = r.fecha; });

  $('#b-programar').onclick = async () => {
    const boton = $('#b-programar');
    boton.disabled = true;
    boton.textContent = 'Subiendo el medio…';
    try {
      await api('/api/programar', {
        method: 'POST',
        body: JSON.stringify({ pieza: b.id, fecha: $('#b-fecha').value.trim(),
                               caption: $('#b-caption').value, tipo: b.tipo }),
      });
      elegido = null;
    } finally { boton.disabled = false; boton.textContent = 'Me gusta · programar'; }
  };
  $('#b-retocar').onclick = () => modalRetocar(b);
  $('#b-rehacer').onclick = () => pedirRediseño(b);
  $('#b-tirar').onclick = async () => {
    if (!confirm('¿Lo borro? Se va la carpeta entera del borrador.')) return;
    await api(`/api/borrador/${b.id}`, { method: 'DELETE' });
    elegido = null;
  };
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
      <button class="principal" id="m-lanzar" ${skill && estado.cli_claude ? '' : 'disabled'}>Generar</button>
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

// ── navegación ───────────────────────────────────────────────────────

$('#mes-atras').onclick = () => { mes.setMonth(mes.getMonth() - 1); pintar(); };
$('#mes-alante').onclick = () => { mes.setMonth(mes.getMonth() + 1); pintar(); };
$('#mes-hoy').onclick = () => { mes = new Date(); pintar(); };
document.addEventListener('keydown', (ev) => {
  if (ev.key !== 'Escape') return;
  if (!$('#telon').classList.contains('oculto')) { cerrarModal(); return; }
  cerrarDetalle();
});

fetch('/api/estado').then((r) => r.json()).then((e) => { estado = e; pintar(); });
conectar();
