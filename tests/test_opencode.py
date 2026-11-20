"""Prueba el lector de Opencode con una base falsa (misma forma que session_v2)."""
import os
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'app'))
import modelo  # noqa: E402
import opencode  # noqa: E402

AHORA = 2_000_000_000
MS = 1000


class LectorOpencode(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        con = sqlite3.connect(os.path.join(self.dir, opencode.BASE))
        con.execute('''CREATE TABLE session_v2 (id TEXT PRIMARY KEY, parent_id TEXT, directory TEXT, title TEXT,
                       time_busy INTEGER, time_idle INTEGER, time_viewed INTEGER, time_archived INTEGER,
                       time_updated INTEGER)''')
        filas = [
            # id, padre, título, busy, idle, viewed, archivada, actualizada
            ('s1', None, 'Tarea nocturna', AHORA - 30, AHORA - 100, AHORA - 100, None, AHORA - 30),   # trabajando
            ('s2', None, 'Revisar PR', AHORA - 200, AHORA - 60, AHORA - 60, None, AHORA - 60),      # terminó
            ('s3', None, 'Ya mirada', AHORA - 500, AHORA - 400, AHORA - 10, None, AHORA - 10),           # mirada después
            ('s4', 's1', 'Subagente', AHORA - 20, None, None, None, AHORA - 20),                         # hija: no
            ('s5', None, 'Archivada', AHORA - 90, AHORA - 80, AHORA - 80, AHORA - 70, AHORA - 70),       # archivada
            ('s6', None, 'Vieja fijada', AHORA - 9 * 86400, AHORA - 9 * 86400 + 5, None, None, AHORA - 9 * 86400),
        ]
        for sid, padre, titulo, busy, idle, visto, arch, act in filas:
            con.execute('INSERT INTO session_v2 VALUES (?,?,?,?,?,?,?,?,?)',
                        (sid, padre, 'C:/proyectos', titulo, busy * MS if busy else None, idle * MS if idle else None,
                         visto * MS if visto else None, arch * MS if arch else None, act * MS))
        con.commit()
        con.close()

    def test_estados_y_lista(self):
        estados, app = opencode.leer(self.dir, extra_ids=['s6'], ahora=AHORA)
        self.assertNotIn('opencode:s4', app)                                    # subagente afuera
        self.assertEqual(estados['opencode:s1']['estado'], 'trabajando')
        self.assertEqual(estados['opencode:s2']['estado'], 'terminada')
        self.assertEqual(app['opencode:s2']['link'], 'opencode://')
        filas = modelo.armar(estados, app, {}, ahora=AHORA, fijados={'opencode:s6': 1})
        sids = [f['sid'] for f in filas]
        self.assertEqual(sids, ['opencode:s6', 'opencode:s2', 'opencode:s1'])   # s3 vista, s5 archivada
        self.assertTrue(all(f['origen'] == 'opencode' for f in filas))
        self.assertEqual(modelo.ORIGENES[filas[1]['origen']], 'Opencode')

    def test_sin_opencode_no_explota(self):
        self.assertEqual(opencode.leer(os.path.join(self.dir, 'no-existe')), ({}, {}))

    def test_no_escribe_la_base(self):
        ruta = os.path.join(self.dir, opencode.BASE)
        antes = os.path.getmtime(ruta), os.path.getsize(ruta)
        opencode.leer(self.dir, ahora=AHORA)
        self.assertEqual((os.path.getmtime(ruta), os.path.getsize(ruta)), antes)


if __name__ == '__main__':
    unittest.main(verbosity=2)
