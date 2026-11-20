"""Genera las capturas del README con datos inventados (nunca lee chats reales).

Arma en una carpeta temporal estados, chats de la app de Claude, una base de Codex y una de Opencode
ficticias, abre Claudito con esas rutas y fotografía la ventana sobre un fondo liso.

Uso (Windows):  py -3 docs/generar_capturas.py
Deja docs/lista.png y docs/estados.png.
"""
import ctypes
import importlib.machinery
import json
import os
import sqlite3
import sys
import tempfile
import time

AQUI = os.path.dirname(os.path.abspath(__file__))
APP = os.path.join(AQUI, '..', 'app')
FONDO = '#2B3038'


def preparar(base, ahora):
    """Crea los datos de mentira y devuelve las variables de entorno que los apuntan."""
    estado = os.path.join(base, 'estado')
    sesiones = os.path.join(base, 'appdata', 'Claude', 'claude-code-sessions', 'a', 'b')
    codex_dir, oc_dir, local = (os.path.join(base, n) for n in ('codex', 'opencode', 'local'))
    for d in (estado, sesiones, codex_dir, oc_dir, local):
        os.makedirs(d, exist_ok=True)

    # Claude Code: (id, título, estado, hace cuántos segundos, detalle)
    claude = [
        ('c1', 'Refactor del checkout', 'esperando', 40, 'pide permiso: Bash'),
        ('c2', 'Migrar los tests a pytest', 'terminada', 180, ''),
        ('c3', 'Landing page nueva', 'trabajando', 25, ''),
        ('c4', 'Notas de la versión 2.0', 'terminada', 7200, ''),
    ]
    for sid, titulo, est, hace, detalle in claude:
        with open(os.path.join(estado, f'{sid}.json'), 'w', encoding='utf-8') as f:
            json.dump({'session_id': sid, 'estado': est, 'detalle': detalle, 'desde': ahora - hace,
                       'cwd': r'C:\proyectos\demo', 'pedido': titulo, 'app_id': f'local_{sid}'}, f)
        with open(os.path.join(sesiones, f'local_{sid}.json'), 'w', encoding='utf-8') as f:
            json.dump({'cliSessionId': sid, 'sessionId': f'local_{sid}', 'title': titulo,
                       'lastFocusedAt': (ahora - 9000) * 1000, 'isArchived': False}, f)

    # Codex: un chat trabajando y uno terminado
    con = sqlite3.connect(os.path.join(codex_dir, 'state_5.sqlite'))
    con.executescript('''CREATE TABLE threads (id TEXT PRIMARY KEY, rollout_path TEXT, title TEXT, name TEXT,
                             archived INTEGER, recency_at_ms INTEGER, cwd TEXT);
                         CREATE TABLE thread_read_receipts (thread_id TEXT PRIMARY KEY, first_unread_turn TEXT);
                         CREATE TABLE thread_spawn_edges (parent_thread_id TEXT, child_thread_id TEXT PRIMARY KEY);''')
    for tid, nombre, eventos in (('x1', 'Auditar dependencias', [('task_started', 90)]),
                                 ('x2', 'Documentar la API', [('task_started', 900), ('task_complete', 600)])):
        ruta = os.path.join(codex_dir, f'{tid}.jsonl')
        with open(ruta, 'w', encoding='utf-8') as f:
            for tipo, hace in eventos:
                iso = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(ahora - hace))
                f.write(json.dumps({'timestamp': iso, 'type': 'event_msg', 'payload': {'type': tipo}}) + '\n')
        con.execute('INSERT INTO threads VALUES (?,?,?,?,?,?,?)', (tid, ruta, nombre, nombre, 0, (ahora - 60) * 1000, ''))
        con.execute('INSERT INTO thread_read_receipts VALUES (?, ?)', (tid, 'turno'))
    con.commit()
    con.close()

    # Opencode: una sesión que terminó
    con = sqlite3.connect(os.path.join(oc_dir, 'opencode.db'))
    con.execute('''CREATE TABLE session_v2 (id TEXT, parent_id TEXT, directory TEXT, title TEXT, time_busy INTEGER,
                   time_idle INTEGER, time_viewed INTEGER, time_archived INTEGER, time_updated INTEGER)''')
    con.execute('INSERT INTO session_v2 VALUES (?,?,?,?,?,?,?,?,?)',
                ('o1', None, '', 'Script de backup', (ahora - 1500) * 1000, (ahora - 1200) * 1000,
                 (ahora - 1200) * 1000, None, (ahora - 1200) * 1000))
    con.commit()
    con.close()

    with open(os.path.join(local, 'fijados.json'), 'w', encoding='utf-8') as f:
        json.dump({'c4': ahora - 8000}, f)
    with open(os.path.join(local, 'config.json'), 'w', encoding='utf-8') as f:
        json.dump({'sonido': False, 'tamano': 'grande', 'pos': [380, 640]}, f)
    return {'MONITOR_CLAUDE_ESTADO': estado, 'APPDATA': os.path.join(base, 'appdata'),
            'CLAUDITO_CODEX_DIR': codex_dir, 'CLAUDITO_OPENCODE_DIR': oc_dir, 'CLAUDITO_LOCAL': local}


def esperar(root, segundos):
    fin = time.time() + segundos
    while time.time() < fin:
        root.update()
        time.sleep(0.02)


def foto(rect, destino):
    from PIL import ImageGrab
    ImageGrab.grab(bbox=rect, all_screens=True).save(destino)


def main():
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
    os.environ.update(preparar(tempfile.mkdtemp(prefix='claudito-capturas-'), time.time()))
    sys.path.insert(0, APP)
    mod = importlib.machinery.SourceFileLoader('claudito', os.path.join(APP, 'claudito.pyw')).load_module()
    import tkinter as tk

    c = mod.Claudito()
    fondo = tk.Toplevel(c.root)                     # fondo liso detrás, para que no se vea el escritorio
    fondo.overrideredirect(True)
    fondo.configure(bg=FONDO)
    fondo.geometry(f'760x820+{c.x - 460}+{c.y - 620}')
    c.root.lift()
    c.programar_cierre = lambda: None
    esperar(c.root, 2)

    # 1) la lista abierta
    c.abrir_panel()
    esperar(c.root, 3)
    p = c.panel
    x0 = min(p.winfo_rootx(), c.root.winfo_rootx()) - 20
    y0 = p.winfo_rooty() - 20
    x1 = max(p.winfo_rootx() + p.winfo_width(), c.root.winfo_rootx() + c.ANCHO) + 20
    y1 = c.root.winfo_rooty() + c.ALTO + 20
    foto((x0, y0, x1, y1), os.path.join(AQUI, 'lista.png'))
    c.panel.destroy()
    c.panel = None

    # 2) los estados de Claudito, uno al lado del otro
    from PIL import Image
    cuadros = []
    for humor, t in (('trabajando', 1.0), ('esperando', 0.1), ('terminada', 1.0), ('tranquilo', 3.0)):
        c.humor = lambda h=humor: h
        c.t0 = time.time() - t
        esperar(c.root, 1.2)
        r = (c.root.winfo_rootx(), c.root.winfo_rooty(), c.root.winfo_rootx() + c.ANCHO, c.root.winfo_rooty() + c.ALTO)
        ruta = os.path.join(tempfile.gettempdir(), f'claudito-{humor}.png')
        foto(r, ruta)
        cuadros.append(Image.open(ruta))
    margen = 24
    tira = Image.new('RGB', (sum(i.width for i in cuadros) + margen * (len(cuadros) + 1),
                            max(i.height for i in cuadros) + 2 * margen), FONDO)
    x = margen
    for i in cuadros:
        tira.paste(i, (x, margen))
        x += i.width + margen
    tira.save(os.path.join(AQUI, 'estados.png'))
    c.root.destroy()
    print('listo:', os.path.join(AQUI, 'lista.png'), os.path.join(AQUI, 'estados.png'))


if __name__ == '__main__':
    main()
