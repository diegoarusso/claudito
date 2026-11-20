"""Lector de chats de Codex para Claudito. SOLO LECTURA: nunca escribe en la carpeta de Codex.

De ~/.codex/state_5.sqlite (abierta en modo solo lectura) saca título, archivado, si está sin leer
y la ruta del historial de cada chat. Del final de ese historial (.jsonl) saca el estado:
el último task_started sin task_complete = trabajando; task_complete = terminada.
Codex no deja rastro de "esperando tu aprobación", así que ese estado no se muestra para Codex.
Los chats que Codex importa de Claude Code (external_agent_session_imports.json) no se muestran: se
trabajan en Claude y ya aparecen como Claude.

Devuelve lo mismo que arma Claudito para Claude (estados y datos de la app), con claves 'codex:<id>'.
"""
import json
import os
import sqlite3
import time
from datetime import datetime

CODEX_DIR = os.environ.get('CLAUDITO_CODEX_DIR', os.path.join(os.path.expanduser('~'), '.codex'))
BASE = 'state_5.sqlite'
LINK = 'codex://threads/{}'
PREFIJO = 'codex:'
RECIENTE_S = 24 * 3600      # chats tocados en las últimas 24 h (los fijados entran siempre)
COLA = 512 * 1024           # se lee solo el final del historial
IMPORTADOS = 'external_agent_session_imports.json'   # chats que Codex importa de Claude Code
MARGEN_S = 60               # actividad hasta 1 min después de importar todavía es la importación

_cache = {}                 # ruta -> ((mtime, tamaño), (estado, desde))
_importados = {}            # ruta -> ((mtime, tamaño), {thread_id: momento de importación})


def importados(codex_dir=CODEX_DIR):
    """{thread_id: momento de importación} de los chats que Codex copió de Claude Code."""
    ruta = os.path.join(codex_dir, IMPORTADOS)
    try:
        st = os.stat(ruta)
    except OSError:
        return {}
    firma = (st.st_mtime, st.st_size)
    previo = _importados.get(ruta)
    if previo and previo[0] == firma:
        return previo[1]
    try:
        with open(ruta, encoding='utf-8') as f:
            registros = json.load(f).get('records') or []
        res = {r['imported_thread_id']: float(r.get('imported_at') or 0)
               for r in registros if r.get('imported_thread_id')}
    except Exception:
        res = {}
    _importados[ruta] = (firma, res)
    return res


def _epoch(iso):
    try:
        return datetime.fromisoformat(iso.replace('Z', '+00:00')).timestamp()
    except Exception:
        return 0.0


def estado_de_historial(ruta):
    """(estado, desde) según el último inicio/fin de tarea del historial, o (None, 0) si no hay."""
    try:
        st = os.stat(ruta)
    except OSError:
        return None, 0.0
    firma = (st.st_mtime, st.st_size)
    previo = _cache.get(ruta)
    if previo and previo[0] == firma:
        return previo[1]
    resultado = (None, 0.0)
    try:
        with open(ruta, 'rb') as f:
            desde_byte = max(0, st.st_size - COLA)
            f.seek(desde_byte)
            datos = f.read()
        lineas = datos.split(b'\n')
        if desde_byte:
            lineas = lineas[1:]          # la primera puede estar cortada
        for linea in reversed(lineas):
            if b'task_' not in linea:
                continue
            try:
                d = json.loads(linea)
            except Exception:
                continue
            tipo = (d.get('payload') or {}).get('type') if d.get('type') == 'event_msg' else None
            if tipo == 'task_complete':
                resultado = ('terminada', _epoch(d.get('timestamp', '')))
                break
            if tipo == 'task_started':
                resultado = ('trabajando', _epoch(d.get('timestamp', '')))
                break
    except OSError:
        pass
    _cache[ruta] = (firma, resultado)
    return resultado


def leer(codex_dir=CODEX_DIR, extra_ids=(), ahora=None):
    """(estados, app) de los chats de Codex recientes más los pedidos en extra_ids (ids sin prefijo)."""
    ahora = ahora if ahora is not None else time.time()
    ruta = os.path.join(codex_dir, BASE)
    if not os.path.exists(ruta):
        return {}, {}
    uri = 'file:' + ruta.replace('\\', '/') + '?mode=ro'
    try:
        con = sqlite3.connect(uri, uri=True, timeout=1)
    except sqlite3.Error:
        return {}, {}
    try:
        con.execute('PRAGMA query_only=ON')
        limite = int((ahora - RECIENTE_S) * 1000)
        extra = list(extra_ids)
        marcas = ','.join('?' * len(extra)) or "''"
        filas = con.execute(
            f"""SELECT t.id, t.rollout_path, COALESCE(NULLIF(t.name, ''), t.title), t.archived,
                       t.recency_at_ms, t.cwd,
                       EXISTS(SELECT 1 FROM thread_read_receipts r
                              WHERE r.thread_id = t.id AND r.first_unread_turn IS NOT NULL)
                FROM threads t
                WHERE (t.recency_at_ms >= ? OR t.id IN ({marcas}))
                  AND t.id NOT IN (SELECT child_thread_id FROM thread_spawn_edges)""",
            [limite, *extra]).fetchall()
    except sqlite3.Error:
        return {}, {}
    finally:
        con.close()
    estados, app = {}, {}
    copiados = importados(codex_dir)
    for tid, rollout, titulo, archivado, reciente_ms, cwd, sin_leer in filas:
        sid = PREFIJO + tid
        estado, desde = estado_de_historial(rollout)
        # Copia de un chat de Claude Code: se trabaja en Claude, no en Codex. Solo cuenta si la fijaste,
        # si pasó por el faro (extra_ids) o si Codex trabajó en ella después de importarla.
        if tid in copiados and tid not in extra and desde <= copiados[tid] + MARGEN_S:
            continue
        if estado:
            estados[sid] = {'session_id': sid, 'estado': estado, 'desde': desde, 'cwd': cwd, 'origen': 'codex'}
        app[sid] = {
            'app_id': None,
            'link': LINK.format(tid),
            'titulo': (titulo or '').strip().splitlines()[0][:120] if titulo else '',
            # visto: si Codex no lo marca como sin leer, cuenta como mirado después de terminar
            'foco': 0 if sin_leer or not desde else desde + 2,
            'reciente': (reciente_ms or 0) / 1000,
            'archivado': bool(archivado),
            'origen': 'codex',
        }
    return estados, app
