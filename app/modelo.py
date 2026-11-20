"""Lógica del monitor (sin ventana, para poder probarla).

Junta los estados que anota el faro (estado/<cliSessionId>.json) con los datos de la app de
escritorio (%APPDATA%/Claude/claude-code-sessions/**/local_*.json: título, link, cuándo miraste
el chat) y arma la lista que muestra Claudito. Los chats de Codex llegan con la misma forma desde codex.py
(claves 'codex:<id>', con su propio link y origen).
"""
import glob
import json
import os
import time

ESTADO_DIR = os.environ.get('MONITOR_CLAUDE_ESTADO', os.path.join(os.path.expanduser('~'), '.claudito', 'estado'))
# shortcut: también se lee la carpeta del nombre anterior, donde siguen escribiendo los hooks instalados antes del
# cambio de nombre (otras apps con su copia del plugin, chats abiertos de antes); revisar cuando nadie escriba ahí.
ESTADO_VIEJO = os.path.join(os.path.expanduser('~'), '.clawd-monitor', 'estado')
ESTADO_DIRS = [ESTADO_DIR] if 'MONITOR_CLAUDE_ESTADO' in os.environ else [ESTADO_DIR, ESTADO_VIEJO]
APP_DIR = os.path.join(os.environ.get('APPDATA', ''), 'Claude', 'claude-code-sessions')
LINK = 'claude://claude.ai/epitaxy/{}'

ORIGENES = {'claude': 'Claude', 'codex': 'Codex', 'opencode': 'Opencode'}   # cómo se muestra cada origen
ORDEN = {'esperando': 0, 'terminada': 1, 'trabajando': 2, 'quieta': 3}   # quieta: fijada sin novedades
COLGADA_S = 3 * 3600        # "trabajando" sin novedades hace 3 h: probablemente se cortó
OLVIDO_S = 24 * 3600        # nada de hace más de 24 h aparece


def _json(ruta):
    try:
        with open(ruta, encoding='utf-8-sig') as f:
            return json.load(f)
    except Exception:
        return None


_cache = {}                 # ruta -> ((mtime, tamaño), resultado ya procesado)


def _leer_si_cambio(ruta, procesar):
    """procesar(json) solo si el archivo cambió desde la última lectura; si no, lo guardado.
    Claudito relee estos archivos cada pocos segundos y casi nunca cambian."""
    try:
        st = os.stat(ruta)
    except OSError:
        return None
    firma = (st.st_mtime, st.st_size)
    previo = _cache.get(ruta)
    if previo and previo[0] == firma:
        return previo[1]
    res = procesar(_json(ruta))
    _cache[ruta] = (firma, res)
    return res


def _podar(patron, rutas):
    """Saca de la caché los archivos de ese patrón que ya no existen."""
    vivas = set(rutas)
    for ruta in [r for r in _cache if r.startswith(patron) and r not in vivas]:
        del _cache[ruta]


def _estado(d):
    return d if d and d.get('session_id') and d.get('estado') in ORDEN else None


def leer_estados(estado_dir=None):
    """Estados anotados por el faro; si un chat figura en más de una carpeta, gana el más nuevo."""
    out = {}
    for carpeta in [estado_dir] if estado_dir else ESTADO_DIRS:
        rutas = glob.glob(os.path.join(carpeta, '*.json'))
        for ruta in rutas:
            d = _leer_si_cambio(ruta, _estado)
            if d and d.get('desde', 0) >= out.get(d['session_id'], {}).get('desde', 0):
                out[d['session_id']] = dict(d)
        _podar(carpeta, rutas)
    return out


def sin_app(estados, app):
    """Ids anotados por el faro que la app de Claude no conoce: pueden ser chats de Codex, que también
    corre los hooks de este plugin cuando lo tiene instalado."""
    return [s for s, e in estados.items() if not e.get('app_id') and s not in app]


def _es_id_codex(sid):
    """Codex usa UUID versión 7 (01a1f9fd-7364-…); Claude Code, versión 4."""
    partes = sid.split('-')
    return len(partes) == 5 and len(partes[2]) == 4 and partes[2][0] == '7'


def unir_codex(estados, codex_estados, codex_app, prefijo='codex:'):
    """Junta los estados del faro con los de Codex. Lo que el faro anotó para un chat de Codex pasa a
    su clave 'codex:<id>' (así toma título, link y origen de Codex); si hay dos estados del mismo chat
    queda el más nuevo (el faro sabe además cuándo Codex espera un permiso)."""
    out = dict(codex_estados)
    for sid, e in estados.items():
        clave = prefijo + sid
        if clave not in codex_app:
            if not e.get('app_id') and _es_id_codex(sid):
                continue                 # tarea interna de Codex (ej. sus sugerencias): no es un chat
            out[sid] = e
            continue
        previo = out.get(clave)
        if previo is None or e.get('desde', 0) >= previo.get('desde', 0):
            out[clave] = {**e, 'session_id': clave, 'origen': 'codex'}
    return out


def _chat_app(d):
    if not d or not d.get('cliSessionId'):
        return None
    return d['cliSessionId'], {
        'app_id': d.get('sessionId'),
        'titulo': d.get('title') or '',
        'foco': (d.get('lastFocusedAt') or 0) / 1000,
        'archivado': bool(d.get('isArchived')),
    }


def leer_app(app_dir=APP_DIR):
    """cliSessionId -> datos del chat en la app (título, id para el link, foco, archivado).
    Son ~200 archivos y ~60 MB: se relee solo el que cambió."""
    out = {}
    rutas = glob.glob(os.path.join(app_dir, '*', '*', 'local_*.json'))
    for ruta in rutas:
        res = _leer_si_cambio(ruta, _chat_app)
        if res:
            out[res[0]] = dict(res[1])
    _podar(app_dir, rutas)
    return out


def armar(estados, app, vistos, ahora=None, fijados=None):
    """Lista de chats a mostrar: primero las fijadas, después esperando, terminadas sin ver, trabajando.

    vistos: {session_id: momento} de chats que marcaste como vistos o quitaste de la lista desde el monitor;
    vuelven a aparecer cuando cambian de estado (desde más nuevo).
    fijados: {session_id: momento} de chats que fijaste en Claudito. Siempre aparecen (salvo archivados),
    aunque ya los hayas visto o tengan más de 24 h; sin nada pendiente quedan como 'quieta'.
    """
    ahora = ahora if ahora is not None else time.time()
    fijados = fijados or {}
    filas = []
    for sid in set(estados) | set(fijados):
        e = estados.get(sid) or {}
        a = app.get(sid, {})
        fijada = sid in fijados
        if a.get('archivado'):
            continue
        if not e and not a:
            continue                     # fijada que ya no existe en ningún lado
        estado = e.get('estado') or 'quieta'
        desde = float(e.get('desde') or a.get('foco') or fijados.get(sid) or 0)
        if not fijada and ahora - desde > OLVIDO_S:
            continue
        if not fijada and estado != 'terminada' and sid in vistos and vistos[sid] >= desde:
            continue                     # la quitaste de la lista: vuelve cuando cambie de estado
        if estado == 'terminada':
            # vista si abriste el chat después de que terminó, o la marcaste en el monitor
            if a.get('foco', 0) > desde + 1 or vistos.get(sid, 0) >= desde:
                if not fijada:
                    continue
                estado = 'quieta'
        colgada = estado == 'trabajando' and ahora - desde > COLGADA_S
        titulo = a.get('titulo') or e.get('pedido') or os.path.basename(e.get('cwd') or '') or sid[:8]
        app_id = a.get('app_id') or e.get('app_id')
        link = a.get('link') or (LINK.format(app_id) if app_id else None)
        filas.append({
            'sid': sid,
            'estado': estado,
            'titulo': titulo,
            'detalle': e.get('detalle') or '',
            'desde': desde,
            'link': link,
            'colgada': colgada,
            'fijada': fijada,
            'origen': a.get('origen') or e.get('origen') or 'claude',
        })
    filas.sort(key=lambda f: (not f['fijada'], ORDEN[f['estado']], f['colgada'], -f['desde']))
    return filas


def recientes(app, fijados, limite=12):
    """Chats de la app (no archivados ni ya fijados), del último mirado al más viejo, para fijar desde el menú."""
    lista = [(sid, a) for sid, a in app.items()
             if not a.get('archivado') and sid not in fijados and (a.get('app_id') or a.get('link'))]
    lista.sort(key=lambda x: -x[1].get('reciente', x[1].get('foco', 0)))
    return [(sid, a.get('titulo') or sid[:8], a.get('origen') or 'claude') for sid, a in lista[:limite]]


def contar(filas):
    c = {'trabajando': 0, 'esperando': 0, 'terminada': 0}
    for f in filas:
        if not f['colgada'] and f['estado'] in c:
            c[f['estado']] += 1
    return c


def novedades(antes, ahora_filas):
    """Qué sonido tocar: 'esperando' si un chat empezó a esperar, 'terminada' si uno terminó."""
    previos = {f['sid']: (f['estado'], f['desde']) for f in antes}
    sonido = None
    for f in ahora_filas:
        if previos.get(f['sid']) == (f['estado'], f['desde']):
            continue
        if f['estado'] == 'esperando':
            return 'esperando'           # el más urgente gana
        if f['estado'] == 'terminada':
            sonido = 'terminada'
    return sonido


def hace(desde, ahora=None):
    s = max(0, int((ahora if ahora is not None else time.time()) - desde))
    if s < 60:
        return 'recién'
    if s < 3600:
        return f'hace {s // 60} min'
    return f'hace {s // 3600} h {s % 3600 // 60:02d}'
