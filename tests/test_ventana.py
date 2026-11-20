"""Prueba la ventana de Claudito sin mouse: tamaños, arrastre, ocultar/mostrar y la marca del lanzador.
Abre una ventana unos segundos. Restaura config.json al terminar."""
import importlib.machinery
import os
import shutil
import subprocess
import sys
import time
import unittest
from types import SimpleNamespace

APP = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'app')
mod = importlib.machinery.SourceFileLoader('claudito', os.path.join(APP, 'claudito.pyw')).load_module()


class Ventana(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cfg = mod.CONFIG
        cls.respaldo = cls.cfg + '.prueba'
        if os.path.exists(cls.cfg):
            shutil.copy(cls.cfg, cls.respaldo)
        cls.c = mod.Claudito()
        cls.c.root.update()

    @classmethod
    def tearDownClass(cls):
        cls.c.root.destroy()
        if os.path.exists(cls.respaldo):
            shutil.move(cls.respaldo, cls.cfg)
        elif os.path.exists(cls.cfg):
            os.remove(cls.cfg)

    def test_tamanos_mantienen_la_esquina(self):
        c = self.c
        der, aba = c.x + c.ANCHO, c.y + c.ALTO
        c.cambiar_tamano('chico')
        self.assertEqual((c.esc, c.ANCHO, c.ALTO), (3, 102, 68))
        self.assertEqual((c.x + c.ANCHO, c.y + c.ALTO), (der, aba))
        c.cambiar_tamano('grande')
        self.assertEqual(c.esc, 7)
        self.assertEqual(c.config['tamano'], 'grande')
        c.cambiar_tamano('normal')

    def test_nada_se_corta_arriba_en_ningun_tamano_ni_estado(self):
        c = self.c
        try:
            for tam in ('chico', 'normal', 'grande'):
                c.cambiar_tamano(tam)
                E = c.esc
                for humor in ('festejo', 'terminada', 'esperando', 'tranquilo'):
                    for i in range(120):                       # 6 s de animación en pasos de 50 ms
                        c.cv.delete('all')
                        c._pose_parado(i * 0.05, humor, E, 6, 4 * E)
                        x0, y0, x1, y1 = c.cv.bbox('all')
                        self.assertGreaterEqual(y0, 0, f'{tam} {humor} t={i * 0.05:.2f}')
                        self.assertLessEqual(x1, c.ANCHO + 1, f'{tam} {humor}')
        finally:
            c.cambiar_tamano('normal')

    def test_arrastrar_mueve_y_guarda_y_clic_abre_lista(self):
        c = self.c
        x0, y0 = c.x, c.y
        c._ini_arrastre(SimpleNamespace(x_root=500, y_root=500))
        c._arrastrar(SimpleNamespace(x_root=400, y_root=420))
        c._fin_arrastre(None)
        self.assertEqual((c.x, c.y), c._dentro(x0 - 100, y0 - 80))
        self.assertEqual(c.config['pos'], [c.x, c.y])
        self.assertIsNone(c.panel)                       # arrastrar no abre la lista
        c._ini_arrastre(SimpleNamespace(x_root=10, y_root=10))
        c._fin_arrastre(None)                            # clic sin mover: abre la lista
        self.assertIsNotNone(c.panel)
        c.panel.destroy()
        c.panel = None
        c.a_la_esquina()
        self.assertEqual((c.x, c.y), c._esquina())
        self.assertNotIn('pos', c.config)

    def test_no_se_sale_de_la_pantalla(self):
        c = self.c
        l, t, r, b = mod.area_trabajo()
        self.assertEqual(c._dentro(-5000, 99999), (l, b - c.ALTO))

    def test_cambio_de_pantalla_lo_trae_adentro(self):
        c = self.c
        real = mod.area_trabajo
        try:
            mod.area_trabajo = lambda: (0, 0, 1920, 1040)        # oficina: monitor grande
            c._area = None
            c.config['pos'] = [1700, 940]
            c.x, c.y = 1700, 940
            c.revisar_pantalla()
            self.assertEqual((c.x, c.y), (1700, 940))
            mod.area_trabajo = lambda: (0, 0, 1366, 728)         # casa: pantalla de la notebook
            c.revisar_pantalla()
            self.assertEqual((c.x, c.y), (1366 - c.ANCHO, 728 - c.ALTO))
            del c.config['pos']                                  # sin posición propia: a la esquina
            mod.area_trabajo = lambda: (0, 0, 1920, 1040)
            c.revisar_pantalla()
            self.assertEqual((c.x, c.y), c._esquina())
        finally:
            mod.area_trabajo = real
            c._area = None
            c.config.pop('pos', None)

    def test_ocultar_y_volver(self):
        c = self.c
        c.ocultar('necesidad')
        c.root.update()
        self.assertEqual(c.root.state(), 'withdrawn')
        c.revisar_oculto('terminada')                    # algo terminó: sigue oculto
        self.assertEqual(c.root.state(), 'withdrawn')
        c.revisar_oculto('esperando')                    # un chat te espera: vuelve
        c.root.update()
        self.assertEqual(c.root.state(), 'normal')
        c.ocultar('siempre')
        c.revisar_oculto('esperando')
        self.assertEqual(c.root.state(), 'withdrawn')
        open(mod.MARCA_MOSTRAR, 'w').close()             # lo que deja el lanzador
        c.revisar_oculto(None)
        c.root.update()
        self.assertEqual(c.root.state(), 'normal')
        self.assertFalse(os.path.exists(mod.MARCA_MOSTRAR))

    def test_vuelve_encima_si_otra_ventana_siempre_al_frente_lo_tapa(self):
        # Otra app con su propia ventana "siempre al frente" encima de Claudito: Claudito conserva el atributo,
        # pero tiene que volver a quedar arriba.
        c = self.c
        c.mostrar()
        c.x, c.y = 150, 150                              # lejos de la esquina, donde está el Claudito de verdad
        c.root.geometry(f'+{c.x}+{c.y}')
        c.root.update()
        codigo = ('import tkinter as tk; r = tk.Tk(); r.overrideredirect(True); r.attributes("-topmost", True); '
                  f'r.geometry("{c.ANCHO + 40}x{c.ALTO + 40}+{c.x - 20}+{c.y - 20}"); '
                  'r.after(6000, r.destroy); r.mainloop()')
        otra = subprocess.Popen([sys.executable, '-c', codigo])
        try:
            fin = time.time() + 5
            while not c._tapado() and time.time() < fin:
                c.root.update()
                time.sleep(0.1)
            self.assertTrue(c._tapado(), 'la ventana de prueba no llegó a tapar a Claudito')
            self.assertTrue(c._es_topmost())
            c.reafirmar_frente()
            c.root.update()
            self.assertFalse(c._tapado())
        finally:
            otra.kill()
            otra.wait()

    def test_bandeja_trae_a_claudito_y_arma_el_menu(self):
        c = self.c
        c.ocultar('siempre')
        c.root.update()
        c.encolar(c.traer)                               # lo que hace el clic en el ícono (otro hilo)
        c.atender()
        c.root.update()
        self.assertEqual(c.root.state(), 'normal')
        self.assertIsNone(c.oculto)
        if mod.bandeja.pystray is None:
            self.skipTest('sin pystray')
        self.assertTrue(c.bandeja.iniciar())
        try:
            textos = [i.text for i in c.bandeja.icono.menu.items]
            for t in ('Mostrar a Claudito', 'Siempre al frente', 'Tamaño', 'Fijar un chat', 'Cerrar Claudito'):
                self.assertIn(t, textos)
            c.bandeja.actualizar()
            self.assertTrue(c.bandeja.icono.title.startswith('Claudito · '))
        finally:
            c.bandeja.detener()

    def test_texto_de_la_bandeja(self):
        t = mod.bandeja.texto_cuenta
        self.assertEqual(t({'trabajando': 0, 'esperando': 0, 'terminada': 0}), 'Claudito · sin chats activos')
        self.assertEqual(t({'trabajando': 2, 'esperando': 1, 'terminada': 3}),
                         'Claudito · 1 te espera · 2 trabajando · 3 terminadas')


if __name__ == '__main__':
    unittest.main(verbosity=2)
