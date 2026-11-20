"""Lector de Codex con una base y historiales de ejemplo (nunca toca ~/.codex)."""
import json
import os
import sqlite3
import sys
import tempfile
import unittest

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(AQUI, '..', 'app'))
import codex  # noqa: E402
import modelo  # noqa: E402

AHORA = 2_000_000_000


def iso(t):
    from datetime import datetime, timezone
    return datetime.fromtimestamp(t, timezone.utc).isoformat().replace('+00:00', 'Z')


def evento(tipo, t):
    return json.dumps({'timestamp': iso(t), 'type': 'event_msg', 'payload': {'type': tipo}})


class LectorCodex(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        con = sqlite3.connect(os.path.join(self.dir, codex.BASE))
        con.executescript('''
            CREATE TABLE threads (id TEXT PRIMARY KEY, rollout_path TEXT, title TEXT, name TEXT,
                archived INTEGER, recency_at_ms INTEGER, cwd TEXT);
            CREATE TABLE thread_read_receipts (thread_id TEXT PRIMARY KEY, first_unread_turn TEXT);
            CREATE TABLE thread_spawn_edges (parent_thread_id TEXT, child_thread_id TEXT PRIMARY KEY, status TEXT);
        ''')
        hist = {
            't1': [evento('task_started', AHORA - 100), evento('task_complete', AHORA - 50)],   # terminó, sin leer
            't2': [evento('task_started', AHORA - 30), '{"type":"response_item"}'],              # trabajando
            't3': [evento('task_started', AHORA - 900), evento('task_complete', AHORA - 800)],   # terminó, leída
            't4': [evento('task_complete', AHORA - 60)],                                         # subagente
            't5': [evento('task_complete', AHORA - 9 * 86400)],                                  # vieja, fijada
            't6': [evento('task_complete', AHORA - 9 * 86400)],                                  # vieja, no fijada
        }
        for tid, lineas in hist.items():
            ruta = os.path.join(self.dir, f'{tid}.jsonl')
            with open(ruta, 'w', encoding='utf-8') as f:
                f.write('\n'.join(lineas) + '\n')
            viejo = tid in ('t5', 't6')
            con.execute('INSERT INTO threads VALUES (?,?,?,?,?,?,?)',
                        (tid, ruta, f'Primer mensaje {tid}\nsegunda línea', 'Nombre t1' if tid == 't1' else '',
                         0, (AHORA - (9 * 86400 if viejo else 10)) * 1000, r'C:\proyectos'))
        con.execute("INSERT INTO thread_read_receipts VALUES ('t1', 'turno')")
        con.execute("INSERT INTO thread_spawn_edges VALUES ('t1', 't4', 'done')")
        con.commit()
        con.close()

    def test_estados_titulos_y_links(self):
        estados, app = codex.leer(self.dir, extra_ids=['t5'], ahora=AHORA)
        self.assertEqual(sorted(app), ['codex:t1', 'codex:t2', 'codex:t3', 'codex:t5'])   # sin subagente ni vieja
        self.assertEqual(estados['codex:t1']['estado'], 'terminada')
        self.assertEqual(estados['codex:t2']['estado'], 'trabajando')
        self.assertAlmostEqual(estados['codex:t2']['desde'], AHORA - 30)
        self.assertEqual(app['codex:t1']['titulo'], 'Nombre t1')
        self.assertEqual(app['codex:t2']['titulo'], 'Primer mensaje t2')
        self.assertEqual(app['codex:t1']['link'], 'codex://threads/t1')

    def test_en_la_lista_de_claudito(self):
        estados, app = codex.leer(self.dir, extra_ids=['t5'], ahora=AHORA)
        filas = modelo.armar(estados, app, {}, ahora=AHORA)
        # t1 sin leer aparece; t3 ya leída se va; t2 trabajando aparece
        self.assertEqual([f['sid'] for f in filas], ['codex:t1', 'codex:t2'])
        self.assertTrue(all(f['origen'] == 'codex' for f in filas))
        self.assertEqual(filas[0]['link'], 'codex://threads/t1')
        # fijadas: la leída y la vieja se quedan
        filas = modelo.armar(estados, app, {}, ahora=AHORA, fijados={'codex:t3': 1, 'codex:t5': 1})
        self.assertEqual([(f['sid'], f['estado']) for f in filas][:2], [('codex:t3', 'quieta'), ('codex:t5', 'quieta')])
        self.assertEqual(modelo.contar(filas), {'trabajando': 1, 'esperando': 0, 'terminada': 1})

    def test_recientes_mezcla_claude_y_codex(self):
        _, app = codex.leer(self.dir, ahora=AHORA)
        app['claude1'] = {'app_id': 'local_1', 'titulo': 'De Claude', 'foco': AHORA, 'archivado': False}
        r = modelo.recientes(app, {'codex:t3': 1})
        self.assertEqual(r[0], ('claude1', 'De Claude', 'claude'))
        self.assertNotIn('codex:t3', [x[0] for x in r])
        self.assertIn(('codex:t1', 'Nombre t1', 'codex'), r)

    def test_chat_de_codex_anotado_por_el_faro(self):
        # Codex corre los hooks de este plugin: el faro anota el chat t6 (viejo, fuera de las 24 h) con su
        # id pelado y sin app_id, y el t2 esperando un permiso. Tienen que salir como Codex, con su nombre.
        faro = {
            't6': {'session_id': 't6', 'estado': 'terminada', 'desde': AHORA - 20, 'pedido': 'Dale, aplicá', 'app_id': None},
            't2': {'session_id': 't2', 'estado': 'esperando', 'desde': AHORA - 5, 'pedido': 'x', 'app_id': None},
            'claude1': {'session_id': 'claude1', 'estado': 'terminada', 'desde': AHORA - 40, 'app_id': 'local_1'},
        }
        app_claude = {'claude1': {'app_id': 'local_1', 'titulo': 'De Claude', 'foco': 0, 'archivado': False}}
        extra = modelo.sin_app(faro, app_claude)
        self.assertEqual(sorted(extra), ['t2', 't6'])
        c_estados, c_app = codex.leer(self.dir, extra_ids=extra, ahora=AHORA)
        estados = modelo.unir_codex(faro, c_estados, c_app)
        self.assertNotIn('t6', estados)
        self.assertEqual(estados['codex:t2']['estado'], 'esperando')      # el faro es más nuevo
        filas = {f['sid']: f for f in modelo.armar(estados, {**app_claude, **c_app}, {}, ahora=AHORA)}
        self.assertEqual((filas['codex:t6']['origen'], filas['codex:t6']['titulo']), ('codex', 'Primer mensaje t6'))
        self.assertEqual(filas['codex:t6']['link'], 'codex://threads/t6')
        self.assertEqual(filas['claude1']['origen'], 'claude')

    def test_tarea_interna_de_codex_no_aparece(self):
        # Codex corre sola una tarea de sugerencias que pasa por el faro pero no es un chat de su lista.
        interna = '01a1f9fd-7364-7192-954a-75f71de29bb2'
        terminal = '7aeb534e-ca49-4222-9919-5010337b9af7'     # Claude Code en terminal: sin app_id, se queda
        faro = {interna: {'session_id': interna, 'estado': 'trabajando', 'desde': AHORA - 5, 'app_id': None},
                terminal: {'session_id': terminal, 'estado': 'trabajando', 'desde': AHORA - 5, 'app_id': None}}
        c_estados, c_app = codex.leer(self.dir, extra_ids=modelo.sin_app(faro, {}), ahora=AHORA)
        estados = modelo.unir_codex(faro, c_estados, c_app)
        self.assertNotIn(interna, estados)
        self.assertIn(terminal, estados)

    def test_copias_de_claude_no_aparecen(self):
        # t1 y t2 son copias que Codex importó de Claude Code. t1 no se tocó después de importar: se va.
        # t2 tuvo trabajo en Codex después de importarla: se queda. Fijada o anotada por el faro, también.
        with open(os.path.join(self.dir, codex.IMPORTADOS), 'w', encoding='utf-8') as f:
            json.dump({'records': [{'imported_thread_id': 't1', 'imported_at': AHORA - 50},
                                   {'imported_thread_id': 't2', 'imported_at': AHORA - 600}]}, f)
        _, app = codex.leer(self.dir, ahora=AHORA)
        self.assertNotIn('codex:t1', app)
        self.assertIn('codex:t2', app)
        _, app = codex.leer(self.dir, extra_ids=['t1'], ahora=AHORA)
        self.assertIn('codex:t1', app)

    def test_quitar_de_la_lista(self):
        estados, app = codex.leer(self.dir, ahora=AHORA)
        vistos = {'codex:t2': AHORA - 30}                  # quitada mientras trabajaba
        self.assertNotIn('codex:t2', [f['sid'] for f in modelo.armar(estados, app, vistos, ahora=AHORA)])
        estados['codex:t2'] = {**estados['codex:t2'], 'estado': 'terminada', 'desde': AHORA - 1}
        self.assertIn('codex:t2', [f['sid'] for f in modelo.armar(estados, app, vistos, ahora=AHORA)])

    def test_sin_codex_no_explota(self):
        self.assertEqual(codex.leer(os.path.join(self.dir, 'no-existe')), ({}, {}))

    def test_no_escribe_la_base(self):
        ruta = os.path.join(self.dir, codex.BASE)
        antes = os.path.getmtime(ruta), os.path.getsize(ruta)
        codex.leer(self.dir, ahora=AHORA)
        self.assertEqual((os.path.getmtime(ruta), os.path.getsize(ruta)), antes)


if __name__ == '__main__':
    unittest.main(verbosity=2)
