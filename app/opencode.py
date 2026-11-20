"""Lector de sesiones de Opencode para Claudito. SOLO LECTURA: nunca escribe en la carpeta de Opencode.

De ~/.local/share/opencode/opencode.db (tabla session_v2, abierta en modo solo lectura) saca título,
archivado y estado: time_busy más nuevo que time_idle = trabajando; si no, terminada desde time_idle.
Opencode no guarda "esperando tu permiso" en la base, así que ese estado no se muestra.

Opencode no tiene link para abrir una sesión puntual: el clic trae la app al frente (opencode://).
Devuelve lo mismo que arma Claudito para Claude (estados y datos de la app), con claves 'opencode:<id>'.
"""
import os
import sqlite3
import time

OPENCODE_DIR = os.environ.get('CLAUDITO_OPENCODE_DIR',
                              os.path.join(os.path.expanduser('~'), '.local', 'share', 'opencode'))
BASE = 'opencode.db'
LINK = 'opencode://'
PREFIJO = 'opencode:'
RECIENTE_S = 24 * 3600      # sesiones tocadas en las últimas 24 h (las fijadas entran siempre)


def leer(opencode_dir=OPENCODE_DIR, extra_ids=(), ahora=None):
    """(estados, app) de las sesiones de Opencode recientes más las pedidas en extra_ids (ids sin prefijo)."""
    ahora = ahora if ahora is not None else time.time()
    ruta = os.path.join(opencode_dir, BASE)
    if not os.path.exists(ruta):
        return {}, {}
    uri = 'file:' + ruta.replace('\\', '/') + '?mode=ro'
    try:
        con = sqlite3.connect(uri, uri=True, timeout=1)
    except sqlite3.Error:
        return {}, {}
    try:
        con.execute('PRAGMA query_only=ON')
        extra = list(extra_ids)
        marcas = ','.join('?' * len(extra)) or "''"
        filas = con.execute(
            f"""SELECT id, title, directory, time_busy, time_idle, time_viewed, time_archived, time_updated
                FROM session_v2
                WHERE parent_id IS NULL
                  AND (time_updated >= ? OR id IN ({marcas}))""",
            [int((ahora - RECIENTE_S) * 1000), *extra]).fetchall()
    except sqlite3.Error:
        return {}, {}
    finally:
        con.close()
    estados, app = {}, {}
    for sid_oc, titulo, carpeta, busy, idle, visto, archivada, actualizada in filas:
        sid = PREFIJO + sid_oc
        busy, idle, visto = (busy or 0) / 1000, (idle or 0) / 1000, (visto or 0) / 1000
        if busy > idle:
            estado, desde = 'trabajando', busy
        elif idle:
            estado, desde = 'terminada', idle
        else:
            estado, desde = None, 0
        if estado:
            estados[sid] = {'session_id': sid, 'estado': estado, 'desde': desde, 'cwd': carpeta or '',
                            'origen': 'opencode'}
        app[sid] = {
            'app_id': None,
            'link': LINK,
            'titulo': (titulo or '').strip().splitlines()[0][:120] if titulo else '',
            # shortcut: Opencode marca time_viewed igual a time_idle al terminar, así que solo cuenta como
            # vista si la miraste después; revisar cuando Opencode distinga "sin leer".
            'foco': visto if visto > idle else 0,
            'reciente': (actualizada or 0) / 1000,
            'archivado': bool(archivada),
            'origen': 'opencode',
        }
    return estados, app
