"""Ícono de Claudito en la bandeja de Windows (junto al reloj).

Clic: muestra a Claudito y lo trae al frente (aunque esté oculto o se haya perdido).
Clic derecho: las mismas opciones que el clic derecho sobre Claudito.
Pasar el mouse: cuántos chats trabajan, te esperan o terminaron.

Usa pystray (py -3 -m pip install pystray). Si no está, Claudito anda igual, sin ícono en la bandeja.
pystray corre en su propio hilo: cada acción se encola y la ejecuta la ventana de Claudito (tkinter no es
seguro entre hilos).
"""
import os

import modelo

try:
    import pystray
    from PIL import Image
except ImportError:          # sin pystray/Pillow: Claudito sin bandeja
    pystray = None

ICONO = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'claudito.ico')


def texto_cuenta(cuenta):
    """Lo que se ve al pasar el mouse por el ícono (Windows lo corta en 127 caracteres)."""
    partes = []
    if cuenta.get('esperando'):
        partes.append(f"{cuenta['esperando']} te espera" + ('n' if cuenta['esperando'] > 1 else ''))
    if cuenta.get('trabajando'):
        partes.append(f"{cuenta['trabajando']} trabajando")
    if cuenta.get('terminada'):
        partes.append(f"{cuenta['terminada']} terminada" + ('s' if cuenta['terminada'] > 1 else ''))
    return 'Claudito · ' + (' · '.join(partes) if partes else 'sin chats activos')


class Bandeja:
    def __init__(self, claudito):
        self.c = claudito
        self.icono = None
        self.firma = None

    def iniciar(self):
        if pystray is None:
            return False
        try:
            if os.path.exists(ICONO):
                with Image.open(ICONO) as i:
                    imagen = i.copy()
            else:
                imagen = Image.new('RGB', (32, 32), '#D97757')
            self.icono = pystray.Icon('claudito', imagen, texto_cuenta(self.c.cuenta), self._menu())
            self.icono.run_detached()
            return True
        except Exception:
            self.icono = None
            return False

    def detener(self):
        if self.icono:
            try:
                self.icono.stop()
            except Exception:
                pass

    def actualizar(self):
        """Lo llama la ventana cada segundo: rearma texto y menú solo si algo cambió."""
        if not self.icono:
            return
        c = self.c
        titulo = texto_cuenta(c.cuenta)
        if self.icono.title != titulo:
            self.icono.title = titulo
        firma = (repr(sorted(c.config.items())), tuple(sorted(c.fijados)), c.oculto is None,
                 tuple(s for s, _, _ in self._recientes()))
        if firma != self.firma:
            self.firma = firma
            self.icono.update_menu()

    # ---------- menú ----------
    def _hacer(self, fn):
        """Acción de menú → la ejecuta el hilo de la ventana."""
        return lambda icon, item: self.c.encolar(fn)

    def _recientes(self):
        try:
            return modelo.recientes({**self.c.app, **self.c.codex[1], **self.c.opencode[1]}, self.c.fijados)
        except Exception:
            return []

    def _fijar(self):
        recientes = self._recientes()
        if not recientes:
            yield pystray.MenuItem('(no hay chats para fijar)', None, enabled=False)
        for sid, titulo, origen in recientes:
            corto = titulo if len(titulo) <= 44 else titulo[:43] + '…'
            corto = modelo.ORIGENES.get(origen, 'Claude') + ' · ' + corto
            yield pystray.MenuItem(corto, self._hacer(lambda s=sid: self.c.alternar_fijado(s)))

    def _menu(self):
        c, M, I = self.c, pystray.Menu, pystray.MenuItem
        cfg = lambda clave, defecto=True: c.config.get(clave, defecto)   # noqa: E731
        tamanos = [I(n.capitalize(), self._hacer(lambda n=n: c.cambiar_tamano(n)), radio=True,
                     checked=lambda item, n=n: cfg('tamano', 'normal') == n)
                   for n in ('chico', 'normal', 'grande')]
        return M(
            I('Mostrar a Claudito', self._hacer(c.traer), default=True),
            M.SEPARATOR,
            I('Sonido', self._hacer(c.alternar_sonido), checked=lambda item: cfg('sonido')),
            I('Marcar terminadas como vistas', self._hacer(c.marcar_vistas)),
            I('Fijar un chat', M(self._fijar)),
            I('Quitar todas las fijadas', self._hacer(c.quitar_fijados), visible=lambda item: bool(c.fijados)),
            I('Tamaño', M(*tamanos)),
            I('Siempre al frente', self._hacer(c.alternar_frente), checked=lambda item: cfg('siempre_arriba')),
            I('Volver a la esquina', self._hacer(c.a_la_esquina)),
            M.SEPARATOR,
            I('Ocultar (vuelve si un chat te espera)', self._hacer(lambda: c.ocultar('necesidad'))),
            I('Ocultar 1 hora', self._hacer(lambda: c.ocultar(3600))),
            I('Ocultar hasta volver a mostrarlo', self._hacer(lambda: c.ocultar('siempre'))),
            M.SEPARATOR,
            I('Abrir carpeta del monitor', self._hacer(lambda: os.startfile(os.path.dirname(ICONO)))),
            I('Cerrar Claudito', self._hacer(c.root.destroy)),
        )
