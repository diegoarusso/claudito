"""Claudito, el monitor de chats de Claude Code, en la esquina inferior derecha.

- Contador chico: 🟢 trabajando · 🟡 esperando tu OK · ✅ terminadas sin ver.
- Pasá el mouse por Claudito: se despliega la lista. Clic en un chat: lo abre en la app.
- Clic derecho en Claudito: sonido, marcar terminadas como vistas, fijar un chat, salir.
- Chats fijados: quedan arriba en la lista aunque ya los hayas visto (botón Fijar / Quitar en cada fila).
- Suena cuando un chat queda esperándote o termina.
- Ícono en la bandeja de Windows (bandeja.py): clic lo trae al frente, clic derecho tiene las mismas opciones.

Lee lo que anota el plugin monitor-chats (hooks/beacon.py) y los títulos de la app de Claude, y los
chats de Codex en solo lectura (codex.py). --prueba: segunda instancia de prueba, al lado de la diaria.
Claudito está dibujado acá en pixel art (no usa los sprites oficiales de Anthropic).
"""
import ctypes
import json
import math
import os
import queue
import struct
import sys
import time
import tkinter as tk
import wave
import winsound

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, AQUI)
import modelo  # noqa: E402
import codex  # noqa: E402
import opencode  # noqa: E402
import bandeja  # noqa: E402

PRUEBA = '--prueba' in sys.argv
CODEX_CADA = 3              # segundos entre lecturas de Codex

LOCAL = os.environ.get('CLAUDITO_LOCAL', AQUI)    # config, vistos y fijados (otra carpeta: capturas sin datos reales)
CONFIG = os.path.join(LOCAL, 'config.json')
MARCA_MOSTRAR = os.path.join(LOCAL, 'mostrar.flag')   # la deja el lanzador si Claudito ya corre
VISTOS = os.path.join(LOCAL, 'vistos.json')
FIJADOS = os.path.join(LOCAL, 'fijados.json')     # {session_id: momento en que lo fijaste}
SONIDOS = os.path.join(AQUI, 'sonidos')

LINEAS_CODIGO = [(4, '#58A6FF', 1), (7, '#3FB950', 0), (6, '#3FB950', 1), (6, '#3FB950', 2), (3, '#3FB950', 0), (5, '#8B949E', 0), (3, '#3FB950', 2), (5, '#3FB950', 2), (2, '#58A6FF', 2), (2, '#D2A8FF', 2), (5, '#3FB950', 0), (2, '#D2A8FF', 0), (4, '#8B949E', 0), (6, '#3FB950', 2), (4, '#D2A8FF', 0), (2, '#D2A8FF', 2), (7, '#58A6FF', 1), (2, '#D2A8FF', 0), (6, '#3FB950', 2), (3, '#8B949E', 2), (5, '#D97757', 1), (6, '#8B949E', 1), (4, '#58A6FF', 0), (7, '#58A6FF', 0)]   # (largo, color, sangría) del código que sube en el monitor
TRANSP = '#ff00fe'          # color que Windows vuelve transparente
NARANJA, NARANJA_OSC, OJO = '#D97757', '#B85F42', '#2B1B14'
COLOR = {'trabajando': '#3FB950', 'esperando': '#E3B341', 'terminada': '#58A6FF', 'quieta': '#6E7681'}
PIN = '#D97757'             # marca de las fijadas
FONDO, TEXTO, TENUE = '#1F2328', '#F0F3F6', '#9198A1'
TAMANOS = {'chico': 3, 'normal': 5, 'grande': 7}   # tamaño de cada pixel de Claudito
# Ventanas de Windows que pasan por encima un rato (menú Inicio, bandeja, vistas previas, menús, tooltips):
# Claudito no se les pone encima.
CLASES_SHELL = {'Shell_TrayWnd', 'Shell_SecondaryTrayWnd', 'Windows.UI.Core.CoreWindow', 'NotifyIconOverflowWindow',
                'TopLevelWindowForOverflowXamlIsland', 'Xaml_WindowedPopupClass', 'XamlExplorerHostIslandWindow',
                'TaskListThumbnailWnd', 'MultitaskingViewFrame', 'ForegroundStaging', 'tooltips_class32', '#32768'}

# Claudito: 16 x 9. X cuerpo, E ojo, A brazo, L pata.
CUERPO = [
    '..XXXXXXXXXXXX..',
    '..XXXXXXXXXXXX..',
    '..XXXEXXXXEXXX..',
    '..XXXEXXXXEXXX..',
    'AAXXXXXXXXXXXXAA',
    '..XXXXXXXXXXXX..',
    '..XXXXXXXXXXXX..',
    '...L.L....L.L...',
    '...L.L....L.L...',
]


def _leer_json(ruta, defecto):
    try:
        with open(ruta, encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return defecto


def _guardar_json(ruta, datos):
    try:
        with open(ruta, 'w', encoding='utf-8') as f:
            json.dump(datos, f)
    except Exception:
        pass


def _tono(ruta, notas, vol=0.35, rate=22050):
    """WAV corto y suave con las notas dadas [(frecuencia, segundos)]."""
    frames = bytearray()
    for frec, dur in notas:
        n = int(rate * dur)
        for i in range(n):
            env = min(1, i / (rate * 0.01)) * max(0.0, 1 - i / n) ** 1.5
            v = vol * env * math.sin(2 * math.pi * frec * i / rate)
            frames += struct.pack('<h', int(v * 32767))
    with wave.open(ruta, 'wb') as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(bytes(frames))


def preparar_sonidos():
    os.makedirs(SONIDOS, exist_ok=True)
    listo = os.path.join(SONIDOS, 'terminada.wav')
    espera = os.path.join(SONIDOS, 'esperando.wav')
    if not os.path.exists(listo):
        _tono(listo, [(784, 0.11), (988, 0.11), (1175, 0.22)])      # sol-si-re, subiendo
    if not os.path.exists(espera):
        _tono(espera, [(880, 0.12), (0.001, 0.06), (880, 0.12), (0.001, 0.06), (1047, 0.2)])
    return {'terminada': listo, 'esperando': espera}


def area_trabajo():
    """Rectángulo útil de la pantalla principal (sin la barra de tareas)."""
    class RECT(ctypes.Structure):
        _fields_ = [('l', ctypes.c_long), ('t', ctypes.c_long), ('r', ctypes.c_long), ('b', ctypes.c_long)]
    r = RECT()
    ctypes.windll.user32.SystemParametersInfoW(0x30, 0, ctypes.byref(r), 0)
    return r.l, r.t, r.r, r.b


class Claudito:
    def __init__(self):
        self.config = _leer_json(CONFIG, {'sonido': True})
        self.esc = TAMANOS.get(self.config.get('tamano', 'normal'), 5)
        self._medidas()
        self.root = tk.Tk()
        self.root.withdraw()
        self.root.overrideredirect(True)
        self.root.attributes('-topmost', True)
        self.root.attributes('-transparentcolor', TRANSP)
        self.root.configure(bg=TRANSP)
        self.cv = tk.Canvas(self.root, width=self.ANCHO, height=self.ALTO, bg=TRANSP,
                            highlightthickness=0, bd=0, cursor='hand2')
        self.cv.pack()
        pos = self.config.get('pos')
        if pos:
            self.x, self.y = self._dentro(*pos)
        else:
            self.x, self.y = self._esquina()
            if PRUEBA:                   # que no tape al Claudito diario
                self.x = max(0, self.x - self.ANCHO - 40)
        self.root.geometry(f'{self.ANCHO}x{self.ALTO}+{self.x}+{self.y}')
        self.root.deiconify()

        self.vistos = _leer_json(VISTOS, {})
        self.fijados = _leer_json(FIJADOS, {})
        self.sonidos = preparar_sonidos()
        self.app, self.app_t = {}, 0
        self.codex, self.codex_t = ({}, {}), 0
        self.opencode, self.opencode_t = ({}, {}), 0
        self.filas, self.cuenta = [], modelo.contar([])
        self.primera = True
        self.panel = None
        self.cierre = None
        self.t0 = time.time()
        self.festejo_hasta = 0
        self.oculto = None          # None | 'necesidad' (vuelve si algo te espera) | momento en que vuelve | 'siempre'
        self.pedidos = queue.Queue()   # acciones que llegan del ícono de la bandeja (otro hilo)
        self.bandeja = bandeja.Bandeja(self)

        self.cv.bind('<Enter>', lambda e: self.abrir_panel())
        self.cv.bind('<Leave>', lambda e: self.programar_cierre())
        self.cv.bind('<Button-3>', self.menu)
        self.cv.bind('<Button-1>', self._ini_arrastre)
        self.cv.bind('<B1-Motion>', self._arrastrar)
        self.cv.bind('<ButtonRelease-1>', self._fin_arrastre)
        self.arrastre = None

        self.refrescar()
        self.animar()
        self.atender()

    # ---------- bandeja ----------
    def encolar(self, fn):
        self.pedidos.put(fn)

    def atender(self):
        while not self.pedidos.empty():
            try:
                self.pedidos.get_nowait()()
            except Exception:
                pass
        self.root.after(100, self.atender)

    def traer(self):
        """Clic en el ícono de la bandeja: mostrarlo (si estaba oculto o fuera de pantalla) y al frente."""
        self.mostrar()
        try:
            ctypes.windll.user32.SetWindowPos(self._hwnd(), -1, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0010)
        except Exception:
            self.root.lift()
        self.festejo_hasta = max(self.festejo_hasta, time.time() + 1.5)   # un saltito para encontrarlo

    # ---------- datos ----------
    def refrescar(self):
        try:
            estados, app = self.datos()
            self.podar_fijados(app)
            filas = modelo.armar(estados, app, self.vistos, fijados=self.fijados)
            sonido = None if self.primera else modelo.novedades(self.filas, filas)
            self.filas, self.cuenta, self.primera = filas, modelo.contar(filas), False
            if sonido == 'terminada':
                self.festejo_hasta = time.time() + 4
            if sonido and self.config.get('sonido', True):
                winsound.PlaySound(self.sonidos[sonido], winsound.SND_FILENAME | winsound.SND_ASYNC)
            self.revisar_oculto(sonido)
            self.revisar_pantalla()
            self.reafirmar_frente()
            self.bandeja.actualizar()
            if self.panel:
                self.dibujar_panel()
        except Exception:
            pass
        self.root.after(1000, self.refrescar)

    def datos(self):
        """Estados y datos de app de Claude y de Codex juntos (claves de Codex: 'codex:<id>')."""
        if time.time() - self.app_t > 10:
            self.app, self.app_t = modelo.leer_app(), time.time()
        faro = modelo.leer_estados()
        if time.time() - self.opencode_t > CODEX_CADA:
            extra = [s[len(opencode.PREFIJO):] for s in self.fijados if s.startswith(opencode.PREFIJO)]
            try:
                self.opencode = opencode.leer(extra_ids=extra)
            except Exception:
                self.opencode = ({}, {})
            self.opencode_t = time.time()
        if time.time() - self.codex_t > CODEX_CADA:
            extra = [s[len(codex.PREFIJO):] for s in self.fijados if s.startswith(codex.PREFIJO)]
            extra += modelo.sin_app(faro, self.app)     # chats de Codex que pasaron por el faro
            try:
                self.codex = codex.leer(extra_ids=extra)
            except Exception:
                self.codex = ({}, {})
            self.codex_t = time.time()
        estados = modelo.unir_codex(faro, self.codex[0], self.codex[1], codex.PREFIJO)
        return {**estados, **self.opencode[0]}, {**self.app, **self.codex[1], **self.opencode[1]}

    # ---------- siempre al frente ----------
    def reafirmar_frente(self):
        # Windows le saca el "topmost" a una ventana sin bordes cuando otra se pone al frente
        # (o al volver de bloquear la sesión), y otra ventana "siempre al frente" puede quedar encima
        # aunque Claudito conserve el atributo: se revisan las dos cosas cada segundo.
        if self.oculto is not None:
            return
        arriba = self.config.get('siempre_arriba', True)
        if arriba == self._es_topmost() and not (arriba and self._tapado()):
            return                       # ya está como debe: no tocar la ventana (evita el parpadeo)
        self.root.attributes('-topmost', arriba)
        if arriba:
            try:                         # subir sin robar el foco
                ctypes.windll.user32.SetWindowPos(self._hwnd(), -1, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0010)
            except Exception:
                self.root.lift()

    def _hwnd(self):
        u = ctypes.windll.user32
        return u.GetParent(self.root.winfo_id()) or self.root.winfo_id()

    def _es_topmost(self):
        try:
            return bool(ctypes.windll.user32.GetWindowLongW(self._hwnd(), -20) & 0x8)   # WS_EX_TOPMOST
        except Exception:
            return None

    def _tapado(self):
        """True si una ventana visible de otro programa quedó encima de Claudito y lo pisa."""
        try:
            u = ctypes.windll.user32
            yo = os.getpid()

            class RECT(ctypes.Structure):
                _fields_ = [('l', ctypes.c_long), ('t', ctypes.c_long), ('r', ctypes.c_long), ('b', ctypes.c_long)]
            mio, otro = RECT(), RECT()
            hwnd = self._hwnd()
            u.GetWindowRect(hwnd, ctypes.byref(mio))
            pid, clase = ctypes.c_ulong(), ctypes.create_unicode_buffer(64)
            cloaked = ctypes.c_int()
            h = u.GetWindow(hwnd, 3)                         # GW_HWNDPREV: la que está justo encima
            while h:
                u.GetWindowThreadProcessId(h, ctypes.byref(pid))
                if pid.value != yo and u.IsWindowVisible(h) and not u.IsIconic(h):
                    u.GetClassNameW(h, clase, 64)
                    ctypes.windll.dwmapi.DwmGetWindowAttribute(h, 14, ctypes.byref(cloaked), 4)   # DWMWA_CLOAKED
                    if not cloaked.value and clase.value not in CLASES_SHELL:
                        u.GetWindowRect(h, ctypes.byref(otro))
                        if otro.l < mio.r and mio.l < otro.r and otro.t < mio.b and mio.t < otro.b:
                            return True
                h = u.GetWindow(h, 3)
            return False
        except Exception:
            return False

    def alternar_frente(self):
        self.config['siempre_arriba'] = not self.config.get('siempre_arriba', True)
        _guardar_json(CONFIG, self.config)
        self.reafirmar_frente()

    # ---------- tamaño y posición ----------
    def _medidas(self):
        self.ANCHO = 26 * self.esc + 24               # Claudito + monitor a su derecha
        self.ALTO = 14 * self.esc + 26                 # gorro/globos arriba, escritorio y contador abajo

    def _esquina(self):
        _, _, r, b = area_trabajo()
        return r - self.ANCHO - 14, b - self.ALTO - 8

    def _dentro(self, x, y):
        l, t, r, b = area_trabajo()
        return max(l, min(int(x), r - self.ANCHO)), max(t, min(int(y), b - self.ALTO))

    def _ini_arrastre(self, e):
        self.arrastre = (e.x_root, e.y_root, self.x, self.y, False)

    def _arrastrar(self, e):
        if not self.arrastre:
            return
        x0, y0, wx, wy, movido = self.arrastre
        dx, dy = e.x_root - x0, e.y_root - y0
        if not movido and abs(dx) + abs(dy) < 5:
            return                                   # todavía es un clic
        if self.panel:
            self.panel.destroy()
            self.panel = None
        self.x, self.y = self._dentro(wx + dx, wy + dy)
        self.root.geometry(f'+{self.x}+{self.y}')
        self.arrastre = (x0, y0, wx, wy, True)

    def _fin_arrastre(self, e):
        movido = self.arrastre and self.arrastre[4]
        self.arrastre = None
        if movido:
            self.config['pos'] = [self.x, self.y]
            _guardar_json(CONFIG, self.config)
        else:
            self.abrir_panel()

    def reubicar(self):
        """Vuelve a ubicar a Claudito dentro de la pantalla actual: la esquina si nunca lo moviste,
        o lo más cerca de donde lo dejaste."""
        if 'pos' in self.config:
            self.x, self.y = self._dentro(self.x, self.y)
        else:
            self.x, self.y = self._esquina()
        self.root.geometry(f'+{self.x}+{self.y}')

    def revisar_pantalla(self):
        # Al cambiar de monitor o de resolución (p. ej. volver de suspensión en otra pantalla)
        # la posición guardada puede quedar fuera de la vista: se reacomoda.
        area = area_trabajo()
        if area != getattr(self, '_area', None):
            self._area = area
            self.reubicar()

    def a_la_esquina(self):
        self.config.pop('pos', None)
        _guardar_json(CONFIG, self.config)
        self.x, self.y = self._esquina()
        self.root.geometry(f'+{self.x}+{self.y}')

    def cambiar_tamano(self, nombre):
        # mantiene fija la esquina inferior derecha de Claudito al cambiar de tamaño
        derecha, abajo = self.x + self.ANCHO, self.y + self.ALTO
        self.esc = TAMANOS[nombre]
        self._medidas()
        self.cv.configure(width=self.ANCHO, height=self.ALTO)
        self.x, self.y = self._dentro(derecha - self.ANCHO, abajo - self.ALTO)
        self.root.geometry(f'{self.ANCHO}x{self.ALTO}+{self.x}+{self.y}')
        self.config['tamano'] = nombre
        if 'pos' in self.config:
            self.config['pos'] = [self.x, self.y]
        _guardar_json(CONFIG, self.config)

    # ---------- ocultar / mostrar ----------
    def ocultar(self, modo):
        """modo: 'necesidad' (vuelve si un chat te espera), segundos (vuelve después) o 'siempre'."""
        self.oculto = time.time() + modo if isinstance(modo, (int, float)) else modo
        if self.panel:
            self.panel.destroy()
            self.panel = None
        self.root.withdraw()

    def mostrar(self):
        self.oculto = None
        self.reubicar()
        self.root.deiconify()
        self.reafirmar_frente()

    def revisar_oculto(self, sonido):
        # Abrir el lanzador con Claudito ya corriendo deja esta marca: es el pedido de "mostrate".
        if os.path.exists(MARCA_MOSTRAR):
            try:
                os.remove(MARCA_MOSTRAR)
            except OSError:
                pass
            self.mostrar()
            return
        if self.oculto is None or self.oculto == 'siempre':
            return
        if self.oculto == 'necesidad':
            if sonido == 'esperando':
                self.mostrar()
        elif time.time() >= self.oculto:
            self.mostrar()

    # ---------- Claudito ----------
    def humor(self):
        if self.cuenta['esperando']:
            return 'esperando'
        if time.time() < self.festejo_hasta:
            return 'festejo'
        if self.cuenta['trabajando']:
            return 'trabajando'
        if self.cuenta['terminada']:
            return 'terminada'
        return 'tranquilo'

    def animar(self):
        cv, t, humor = self.cv, time.time() - self.t0, self.humor()
        cv.delete('all')
        E = self.esc
        ox, oy = 6, 4 * E                              # Claudito a la izquierda; arriba, lugar para gorro y globos

        def px(gx, gy, color, w=1, h=1, dy=0):
            """Un 'pixel' de Claudito en la grilla (gx, gy), de w x h celdas; dy corre en pixeles reales."""
            x, y = ox + gx * E, oy + gy * E + dy
            cv.create_rectangle(x, y, x + w * E, y + h * E, fill=color, width=0)

        if humor == 'trabajando':
            self._pose_tecleando(px, t, E, ox, oy)
        elif humor == 'tranquilo':
            self._pose_durmiendo(px, t, E, ox, oy)
        else:
            self._pose_parado(t, humor, E, ox, oy)
        self.dibujar_contador()
        if PRUEBA:
            cv.create_text(4, 2, text='PRUEBA', anchor='nw', fill='#E3B341', font=('Segoe UI', 7, 'bold'))
        # durmiendo solo respira (ciclo de ~5 s): con 4 cuadros por segundo alcanza y gasta la mitad de CPU
        self.root.after(250 if humor == 'tranquilo' else 120, self.animar)

    # ---- de pie: terminada, festejo y esperando (sin cambios) ----
    def _pose_parado(self, t, humor, E, ox, oy):
        cv = self.cv
        dx = ox + 16 * E
        if humor == 'festejo':
            oy -= abs(round(math.sin(t * 9) * 7))
        # terminada: se balancea suave y cada 5 s da un saltito y saluda, para que se note que te espera
        ciclo = t % 5
        if humor == 'terminada':
            oy += round(math.sin(t * 3) * 2)
            if ciclo < 0.6:
                oy -= abs(round(math.sin(ciclo * math.pi / 0.3) * 6))
        parpadeo = (t % 4.2) < 0.15 and humor != 'festejo'
        saludo = ((humor == 'esperando' and int(t * 3) % 2 == 0)
                  or (humor == 'terminada' and 0.6 <= ciclo < 2.2 and int(t * 4) % 2 == 0))
        for fy, fila in enumerate(CUERPO):
            for fx, c in enumerate(fila):
                if c == '.':
                    continue
                if c == 'E':
                    if humor == 'festejo':             # ojos felices: ^ ^
                        color = OJO if fy == 2 else NARANJA
                    else:
                        color = NARANJA if parpadeo else OJO
                elif c == 'A' and fx < 2 and saludo:
                    continue                           # el brazo izquierdo sube (abajo)
                elif c == 'L':
                    color = NARANJA_OSC
                else:
                    color = NARANJA
                x, y = ox + fx * E, oy + fy * E
                cv.create_rectangle(x, y, x + E, y + E, fill=color, width=0)
        if saludo:                                     # brazo izquierdo en alto
            for fx, fy in ((0, 1), (0, 2), (1, 3)):
                x, y = ox + fx * E, oy + fy * E
                cv.create_rectangle(x, y, x + E, y + E, fill=NARANJA, width=0)
        if humor == 'esperando':                       # globo "!"
            bx, by = dx - 4, max(oy - 16, 1)           # en tamaño chico no se sale por arriba
            cv.create_oval(bx, by, bx + 20, by + 20, fill=COLOR['esperando'], width=0)
            cv.create_text(bx + 10, by + 10, text='!', fill=FONDO, font=('Segoe UI', 11, 'bold'))
        else:                                          # tilde
            bx, by = dx - 4, oy - 14
            r = 0
            if humor == 'terminada':                   # el tilde flota y late
                by += round(math.sin(t * 2.5) * 3)
                r = 2 if (t % 1.2) < 0.25 else 0
            by = max(by, r + 1)                        # con saltito o festejo no se sale por arriba del lienzo
            cv.create_oval(bx - r, by - r, bx + 18 + r, by + 18 + r, fill=COLOR['terminada'], width=0)
            cv.create_line(bx + 4, by + 9, bx + 8, by + 13, bx + 14, by + 5, fill='white', width=2)

    # ---- trabajando: tecleando en la compu ----
    def _pose_tecleando(self, px, t, E, ox, oy):
        golpe = int(t * 8) % 2                         # ritmo de tecleo: alterna las manos
        dy = 1 if golpe else 0                         # el cuerpo acompaña cada tecla
        # cuerpo, sin brazos ni patas (las patas quedan detrás del escritorio)
        for fy, fila in enumerate(CUERPO[:7]):
            for fx, c in enumerate(fila):
                if c in 'XE' or (c == 'A' and 2 <= fx <= 13):
                    px(fx, fy, NARANJA, dy=dy)
        # ojos: miran el monitor (corridos a la derecha); a veces bajan al teclado; pestañea
        if (t % 3.7) >= 0.14:
            fila_ojo = 3 if (t % 5.0) < 0.7 else 2
            for col in (6, 11):
                px(col, fila_ojo, OJO, h=2 if fila_ojo == 2 else 1, dy=dy)
        # escritorio y teclado
        px(-1, 8, '#57606A', w=27)
        px(0, 7, '#30363D', w=16)
        for i in range(7):                             # teclas; una o dos se encienden con cada golpe
            encendida = (i * 7 + int(t * 8) * 3) % 7 < 2
            x0 = 1 + i * 2
            xr, yr = ox + x0 * E + E // 4, oy + 7 * E + E // 4
            self.cv.create_rectangle(xr, yr, xr + max(2, E * 3 // 4), yr + max(1, E // 2),
                                     fill='#E6EDF3' if encendida else '#6E7681', width=0)
        # brazos (naranja oscuro, por delante del cuerpo) con las manos sobre el teclado, alternadas:
        # una golpea la tecla mientras la otra sube
        for lado, (brazo, mano) in enumerate((([(1, 4), (1, 5), (2, 6)], 3),
                                               ([(14, 4), (14, 5), (13, 6)], 12))):
            abajo = (golpe == lado)
            for gx, gy in brazo:
                px(gx, gy, NARANJA_OSC, dy=dy)
            px(mano, 7 if abajo else 6, NARANJA_OSC, dy=0 if abajo else dy)
        # monitor con código que sube
        px(17, 0, '#3A3F47', w=9, h=7)                 # marco
        px(18, 1, '#0D1117', w=7, h=5)                 # pantalla
        px(21, 7, '#3A3F47')                           # pie
        avance = int(t * 2.5)
        for r in range(5):
            largo, color, sangria = LINEAS_CODIGO[(avance + r) % len(LINEAS_CODIGO)]
            largo = min(largo, 7 - sangria)
            xr, yr = ox + (18 + sangria) * E, oy + (1 + r) * E + E // 4
            self.cv.create_rectangle(xr, yr, xr + largo * E - 1, yr + max(1, E // 2), fill=color, width=0)
        if int(t * 3) % 2:                             # cursor que titila al final
            largo, _, sangria = LINEAS_CODIGO[(avance + 4) % len(LINEAS_CODIGO)]
            cx = min(18 + sangria + min(largo, 7 - sangria), 24)
            xr, yr = ox + cx * E, oy + 5 * E + E // 4
            self.cv.create_rectangle(xr, yr, xr + max(1, E // 2), yr + max(2, E * 3 // 4), fill='#E6EDF3', width=0)

    # ---- inactivo: durmiendo con gorro, burbuja y zzz; a veces bosteza ----
    def _pose_durmiendo(self, px, t, E, ox, oy):
        cv = self.cv
        respira = round(math.sin(t * 1.3) * E * 0.35)  # el pecho sube y baja
        bostezo = (t % 14.0) < 1.6
        for fy, fila in enumerate(CUERPO):
            for fx, c in enumerate(fila):
                if c == 'L':
                    px(fx, fy, NARANJA_OSC)
                elif c in 'XE' or (c == 'A' and 2 <= fx <= 13):
                    px(fx, fy, NARANJA, dy=respira if fy < 7 else 0)
        if bostezo:                                    # se estira: brazos arriba, ojos entrecerrados, boca abierta
            for col in (0, 15):
                px(col, 1, NARANJA, dy=respira)
                px(col, 2, NARANJA, dy=respira)
                px(col, 3, NARANJA, dy=respira)
            for col in (5, 10):
                px(col, 3, OJO, h=0.5, dy=respira + E // 2)
            px(7, 4, OJO, w=2, h=2, dy=respira)
        else:                                          # brazos caídos y ojos cerrados
            for col in (1, 14):
                px(col, 5, NARANJA, dy=respira)
            for col in (4, 9):
                px(col, 3, OJO, w=2, h=0.5, dy=respira + E // 3)
        # gorro de dormir caído hacia la derecha, con pompón
        gorro, pompon = '#5B6CC7', '#E6EDF3'
        px(2, -1, gorro, w=11, dy=respira)
        px(4, -2, gorro, w=8, dy=respira)
        px(8, -3, gorro, w=5, dy=respira)
        px(12, -2, gorro, w=2, dy=respira)
        px(13, -1, gorro, w=2, dy=respira)
        px(15, -1, pompon, dy=respira)
        # burbuja de la nariz: se infla y explota (no mientras bosteza)
        if not bostezo:
            fase = (t % 4.0) / 4.0
            bx, by = ox + 12 * E, oy + 4 * E + respira
            if fase < 0.88:
                r = 1 + fase * E * 1.3
                cv.create_oval(bx - r, by - r, bx + r, by + r, fill='#BFE3FF', outline='#E6F4FF', width=1)
            elif fase < 0.95:                          # ¡pop!
                for ddx, ddy in ((-1, -1), (1, -1), (-1, 1), (1, 1)):
                    cv.create_line(bx + ddx * 2, by + ddy * 2, bx + ddx * (E + 2), by + ddy * (E + 2),
                                   fill='#E6F4FF', width=1)
        # zzz que suben flotando y se apagan
        tonos = ('#C9D1D9', '#8B949E', '#57606A')
        for i in range(3):
            fase = ((t / 3.0) + i / 3.0) % 1.0
            s = max(2, round(E * 0.35 * (1 + fase)))
            zx = ox + 16 * E + round(fase * 3 * E) + i * 2
            zy = oy - round(fase * 3 * E)
            color = tonos[min(2, int(fase * 3))]
            for ppx, ppy in ((0, 0), (1, 0), (2, 0), (1, 1), (0, 2), (1, 2), (2, 2)):
                cv.create_rectangle(zx + ppx * s, zy + ppy * s, zx + ppx * s + s, zy + ppy * s + s,
                                    fill=color, width=0)

    def dibujar_contador(self):
        c = self.cuenta
        partes = [(k, c[k]) for k in ('trabajando', 'esperando', 'terminada') if c[k]]
        if not partes:
            return
        paso = 24 if self.esc <= 3 else 30
        ancho = 14 + paso * len(partes)
        x0, y0 = (self.ANCHO - ancho) // 2, self.ALTO - 20
        self.cv.create_rectangle(x0 + 8, y0, x0 + ancho - 8, y0 + 18, fill=FONDO, width=0)
        self.cv.create_oval(x0, y0, x0 + 18, y0 + 18, fill=FONDO, width=0)
        self.cv.create_oval(x0 + ancho - 18, y0, x0 + ancho, y0 + 18, fill=FONDO, width=0)
        x = x0 + 9
        for k, n in partes:
            self.cv.create_oval(x, y0 + 5, x + 8, y0 + 13, fill=COLOR[k], width=0)
            self.cv.create_text(x + 12, y0 + 9, text=str(n), anchor='w', fill=TEXTO,
                                font=('Segoe UI', 8 if self.esc <= 3 else 9, 'bold'))
            x += paso

    # ---------- panel ----------
    def abrir_panel(self):
        if self.cierre:
            self.root.after_cancel(self.cierre)
            self.cierre = None
        if self.panel:
            return
        self.panel = tk.Toplevel(self.root)
        self.panel.overrideredirect(True)
        self.panel.attributes('-topmost', True)
        self.panel.configure(bg=FONDO)
        self.panel.bind('<Enter>', lambda e: self.abrir_panel())
        self.panel.bind('<Leave>', lambda e: self.programar_cierre())
        self._firma_panel = None
        self.dibujar_panel()

    def programar_cierre(self):
        if self.cierre:
            self.root.after_cancel(self.cierre)
        self.cierre = self.root.after(700, self.cerrar_panel)

    def cerrar_panel(self):
        self.cierre = None
        px, py = self.root.winfo_pointerxy()
        for w in (self.panel, self.root):
            if w and w.winfo_rootx() <= px <= w.winfo_rootx() + w.winfo_width() \
                    and w.winfo_rooty() <= py <= w.winfo_rooty() + w.winfo_height():
                self.programar_cierre()
                return
        if self.panel:
            self.panel.destroy()
            self.panel = None

    def dibujar_panel(self):
        p = self.panel
        # Solo se rearma si cambió algo visible (estado, título, "hace X min"...): rearmarla cada
        # segundo sin cambios hacía parpadear la lista.
        firma = tuple((f['sid'], f['estado'], f['colgada'], f['fijada'], f['titulo'], f['detalle'],
                       f.get('origen'), modelo.hace(f['desde'])) for f in self.filas[:15])
        if firma == getattr(self, '_firma_panel', None):
            return
        self._firma_panel = firma
        for w in p.winfo_children():
            w.destroy()
        ancho = 380
        tk.Label(p, text='Chats de Claude, Codex y Opencode' + (' · PRUEBA' if PRUEBA else ''), bg=FONDO, fg=TEXTO, anchor='w',
                 font=('Segoe UI', 10, 'bold')).pack(fill='x', padx=12, pady=(10, 4))
        if not self.filas:
            tk.Label(p, text='Nada corriendo ni esperando. Claudito descansa.', bg=FONDO, fg=TENUE,
                     anchor='w', font=('Segoe UI', 9)).pack(fill='x', padx=12, pady=(0, 10))
        etiqueta = {'esperando': 'te espera', 'terminada': 'terminó', 'trabajando': 'trabajando',
                    'quieta': 'sin novedades'}
        hay_fijadas = any(f['fijada'] for f in self.filas)
        seccion = None
        for f in self.filas[:14]:
            if hay_fijadas and f['fijada'] != seccion:
                seccion = f['fijada']
                tk.Label(p, text='FIJADAS' if seccion else 'OTROS CHATS', bg=FONDO,
                         fg=PIN if seccion else TENUE, anchor='w',
                         font=('Segoe UI', 7, 'bold')).pack(fill='x', padx=12, pady=(4, 0))
            fila = tk.Frame(p, bg=FONDO, cursor='hand2')
            fila.pack(fill='x', padx=6, pady=1)
            color = TENUE if f['colgada'] else COLOR[f['estado']]
            punto = tk.Canvas(fila, width=12, height=12, bg=FONDO, highlightthickness=0)
            punto.create_oval(2, 2, 10, 10, fill=color, width=0)
            punto.pack(side='left', padx=(6, 6))
            titulo = f['titulo'] if len(f['titulo']) <= 44 else f['titulo'][:43] + '…'
            origen = modelo.ORIGENES.get(f.get('origen'), 'Claude')
            sub = f"{origen} · {'¿se cortó? ' if f['colgada'] else ''}{etiqueta[f['estado']]} · {modelo.hace(f['desde'])}"
            if f['detalle']:
                sub += f" · {f['detalle'][:40]}"
            if f['fijada']:
                botones = [('Quitar', PIN, lambda e, f=f: self.alternar_fijado(f['sid']))]
            else:                        # Quitar: se va de la lista hasta que el chat cambie de estado
                botones = [('Quitar', TENUE, lambda e, f=f: self.quitar_fila(f)),
                           ('Fijar', TENUE, lambda e, f=f: self.alternar_fijado(f['sid']))]
            for i, (texto, fg, accion) in enumerate(botones):
                boton = tk.Label(fila, text=texto, bg=FONDO, fg=fg, font=('Segoe UI', 8, 'underline'), cursor='hand2')
                boton.pack(side='right', padx=(4, 8 if i == 0 else 0))
                boton.bind('<Button-1>', accion)
                boton.bind('<Enter>', lambda e, fila=fila: self._resaltar(fila, True))
                boton.bind('<Leave>', lambda e, fila=fila: self._resaltar(fila, False))
            textos = tk.Frame(fila, bg=FONDO)
            textos.pack(side='left', fill='x', expand=True)
            a = tk.Label(textos, text=titulo, bg=FONDO, fg=TEXTO, anchor='w', font=('Segoe UI', 9, 'bold'))
            b = tk.Label(textos, text=sub, bg=FONDO, fg=color, anchor='w', font=('Segoe UI', 8))
            a.pack(fill='x')
            b.pack(fill='x')
            for w in (fila, punto, textos, a, b):
                w.bind('<Button-1>', lambda e, f=f: self.abrir_chat(f))
                w.bind('<Enter>', lambda e, fila=fila: self._resaltar(fila, True))
                w.bind('<Leave>', lambda e, fila=fila: self._resaltar(fila, False))
        if len(self.filas) > 14:
            tk.Label(p, text=f'… y {len(self.filas) - 14} más', bg=FONDO, fg=TENUE, anchor='w',
                     font=('Segoe UI', 8)).pack(fill='x', padx=12)
        tk.Label(p, text='clic: abrir · Fijar: que no se vaya · Quitar: sacarlo · clic derecho en Claudito: opciones', bg=FONDO, fg=TENUE,
                 anchor='w', font=('Segoe UI', 7)).pack(fill='x', padx=12, pady=(4, 8))
        p.update_idletasks()
        alto = p.winfo_reqheight()
        l, t, r, b = area_trabajo()
        x = max(l + 4, min(self.x + self.ANCHO - ancho, r - ancho - 4))
        y = self.y - alto - 4 if self.y - alto - 4 >= t else min(self.y + self.ALTO + 4, b - alto)
        p.geometry(f'{ancho}x{alto}+{x}+{y}')

    def _resaltar(self, fila, si):
        bg = '#2D333B' if si else FONDO
        def pintar(w):
            if isinstance(w, (tk.Frame, tk.Label, tk.Canvas)):
                w.configure(bg=bg)
            for h in w.winfo_children():
                pintar(h)
        pintar(fila)

    def abrir_chat(self, f):
        if f['estado'] == 'terminada':
            self.vistos[f['sid']] = f['desde']
            _guardar_json(VISTOS, self.vistos)
        if f.get('link'):
            try:
                os.startfile(f['link'])
            except Exception:
                pass

    # ---------- menú ----------
    def menu(self, e):
        m = tk.Menu(self.root, tearoff=0)
        sonido = self.config.get('sonido', True)
        m.add_command(label='Silenciar' if sonido else 'Activar sonido', command=self.alternar_sonido)
        m.add_command(label='Marcar terminadas como vistas', command=self.marcar_vistas)
        fijar = tk.Menu(m, tearoff=0)
        recientes = modelo.recientes(self.datos()[1], self.fijados)
        for sid, titulo, origen in recientes:
            corto = titulo if len(titulo) <= 44 else titulo[:43] + '…'
            corto = modelo.ORIGENES.get(origen, 'Claude') + ' · ' + corto
            fijar.add_command(label=corto, command=lambda s=sid: self.alternar_fijado(s))
        if not recientes:
            fijar.add_command(label='(no hay chats para fijar)', state='disabled')
        m.add_cascade(label='Fijar un chat', menu=fijar)
        if self.fijados:
            m.add_command(label='Quitar todas las fijadas', command=self.quitar_fijados)
        m.add_command(label='Abrir carpeta del monitor', command=lambda: os.startfile(AQUI))
        tam = tk.Menu(m, tearoff=0)
        actual = self.config.get('tamano', 'normal')
        for nombre in ('chico', 'normal', 'grande'):
            tam.add_command(label=('● ' if nombre == actual else '   ') + nombre.capitalize(),
                            command=lambda n=nombre: self.cambiar_tamano(n))
        m.add_cascade(label='Tamaño', menu=tam)
        m.add_command(label=('● ' if self.config.get('siempre_arriba', True) else '   ') + 'Siempre al frente',
                      command=self.alternar_frente)
        m.add_command(label='Volver a la esquina', command=self.a_la_esquina)
        m.add_separator()
        m.add_command(label='Ocultar (vuelve si un chat te espera)', command=lambda: self.ocultar('necesidad'))
        m.add_command(label='Ocultar 1 hora', command=lambda: self.ocultar(3600))
        m.add_command(label='Ocultar hasta volver a mostrarlo', command=lambda: self.ocultar('siempre'))
        m.add_separator()
        m.add_command(label='Cerrar Claudito' + (' de prueba' if PRUEBA else ''), command=self.root.destroy)
        m.tk_popup(e.x_root, e.y_root)

    def alternar_sonido(self):
        self.config['sonido'] = not self.config.get('sonido', True)
        _guardar_json(CONFIG, self.config)

    # ---------- fijadas ----------
    def alternar_fijado(self, sid):
        if sid in self.fijados:
            del self.fijados[sid]
        else:
            self.fijados[sid] = time.time()
        _guardar_json(FIJADOS, self.fijados)
        self.app_t = self.codex_t = self.opencode_t = 0    # que el próximo refresco traiga títulos al día
        self.refrescar_ya()

    def quitar_fijados(self):
        self.fijados = {}
        _guardar_json(FIJADOS, self.fijados)
        self.refrescar_ya()

    def podar_fijados(self, app):
        """Si archivaste en la app (Claude o Codex) un chat fijado, se suelta solo."""
        archivados = [s for s in self.fijados if app.get(s, {}).get('archivado')]
        for s in archivados:
            del self.fijados[s]
        if archivados:
            _guardar_json(FIJADOS, self.fijados)

    def refrescar_ya(self):
        try:
            estados, app = self.datos()
            self.filas = modelo.armar(estados, app, self.vistos, fijados=self.fijados)
            self.cuenta = modelo.contar(self.filas)
            if self.panel:
                self.dibujar_panel()
        except Exception:
            pass

    def quitar_fila(self, f):
        """Saca un chat no fijado de la lista hasta que cambie de estado."""
        self.vistos[f['sid']] = f['desde']
        _guardar_json(VISTOS, self.vistos)
        self.refrescar_ya()

    def marcar_vistas(self):
        for f in self.filas:
            if f['estado'] == 'terminada':
                self.vistos[f['sid']] = f['desde']
        _guardar_json(VISTOS, self.vistos)


def una_sola_instancia():
    nombre = 'Global\\Claudito' + ('Prueba' if PRUEBA else '')
    ctypes.windll.kernel32.CreateMutexW(None, False, nombre)
    return ctypes.windll.kernel32.GetLastError() != 183      # ERROR_ALREADY_EXISTS


if __name__ == '__main__':
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    if not una_sola_instancia():
        # Ya hay un Claudito corriendo (quizás oculto): pedirle que se muestre y salir.
        open(MARCA_MOSTRAR, 'w').close()
    else:
        claudito = Claudito()
        if '--panel' in sys.argv:          # para capturas: abre la lista sin pasar el mouse
            claudito.root.after(1500, claudito.abrir_panel)
            claudito.programar_cierre = lambda: None
        claudito.bandeja.iniciar()
        try:
            claudito.root.mainloop()
        finally:
            claudito.bandeja.detener()
