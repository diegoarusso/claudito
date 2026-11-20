import json
import os
import sys
import tempfile
import unittest

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(AQUI, '..', 'hooks'))
sys.path.insert(0, os.path.join(AQUI, '..', 'app'))
import beacon  # noqa: E402
import modelo  # noqa: E402

SID = '2313cdfb-1ca7-448d-8324-2a1121c09d70'


class Faro(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def ev(self, nombre, t, **extra):
        return beacon.procesar({'hook_event_name': nombre, 'session_id': SID, 'cwd': r'C:\proyectos', **extra},
                               ahora=t, estado_dir=self.dir)

    def estado(self):
        return json.load(open(os.path.join(self.dir, f'{SID}.json'), encoding='utf-8'))

    def test_ciclo_completo(self):
        self.assertEqual(self.ev('UserPromptSubmit', 100, prompt='Arreglá el test del login'), 'trabajando')
        self.assertEqual(self.estado()['pedido'], 'Arreglá el test del login')
        self.assertEqual(self.ev('PostToolUse', 101, tool_name='Bash'), 'trabajando')
        self.assertEqual(self.estado()['desde'], 100)          # sin cambios no reescribe
        self.assertEqual(self.ev('PermissionRequest', 102, tool_name='Bash'), 'esperando')
        self.assertEqual(self.estado()['detalle'], 'pide permiso: Bash')
        self.assertEqual(self.ev('PostToolUse', 103, tool_name='Bash'), 'trabajando')
        self.assertEqual(self.ev('PreToolUse', 104, tool_name='AskUserQuestion'), 'esperando')
        self.assertEqual(self.estado()['detalle'], 'te hizo una pregunta')
        self.assertEqual(self.ev('PostToolUse', 105, tool_name='AskUserQuestion'), 'trabajando')
        self.assertEqual(self.ev('Stop', 106), 'terminada')
        self.assertEqual(self.estado()['pedido'], 'Arreglá el test del login')
        self.assertEqual(self.ev('SessionEnd', 107, reason='exit'), 'cerrada')
        self.assertFalse(os.path.exists(os.path.join(self.dir, f'{SID}.json')))

    def test_notificacion_de_permiso_y_de_inactividad(self):
        self.ev('UserPromptSubmit', 1)
        self.assertEqual(self.ev('Notification', 2, notification_type='idle_prompt', message='x'), 'trabajando')
        self.assertEqual(self.ev('Notification', 3, notification_type='permission_prompt',
                                 message='Claude needs your permission to use Bash'), 'esperando')

    def test_el_stop_de_un_subagente_no_termina_el_chat(self):
        self.ev('UserPromptSubmit', 1)
        self.assertEqual(self.ev('Stop', 2, agent_id='a1'), 'trabajando')

    def test_guarda_el_id_del_chat_de_la_app(self):
        os.environ['CLAUDE_CODE_HOST_SESSION_ID'] = 'local_abc'
        try:
            self.ev('UserPromptSubmit', 1)
        finally:
            del os.environ['CLAUDE_CODE_HOST_SESSION_ID']
        self.ev('Stop', 2)                                   # sin la variable: conserva el que tenía
        self.assertEqual(self.estado()['app_id'], 'local_abc')
        filas = modelo.armar({SID: self.estado()}, {}, {}, ahora=3)
        self.assertEqual(filas[0]['link'], 'claude://claude.ai/epitaxy/local_abc')

    def test_entrada_rota_no_explota(self):
        self.assertIsNone(beacon.procesar({}, estado_dir=self.dir))


class Modelo(unittest.TestCase):
    def test_lista_orden_visto_y_links(self):
        ahora = 10_000
        estados = {
            'a': {'session_id': 'a', 'estado': 'trabajando', 'desde': ahora - 60, 'cwd': r'C:\proyectos'},
            'b': {'session_id': 'b', 'estado': 'esperando', 'desde': ahora - 30, 'detalle': 'pide permiso: Bash'},
            'c': {'session_id': 'c', 'estado': 'terminada', 'desde': ahora - 20},     # sin ver
            'd': {'session_id': 'd', 'estado': 'terminada', 'desde': ahora - 500},    # la abriste después
            'e': {'session_id': 'e', 'estado': 'terminada', 'desde': ahora - 40},     # marcada en el monitor
            'f': {'session_id': 'f', 'estado': 'trabajando', 'desde': ahora - 4 * 3600, 'cwd': r'C:\proyectos'},  # colgada
            'g': {'session_id': 'g', 'estado': 'terminada', 'desde': ahora - 30 * 3600},  # vieja
            'h': {'session_id': 'h', 'estado': 'esperando', 'desde': ahora - 10},     # chat archivado
        }
        app = {
            'a': {'app_id': 'local_a', 'titulo': 'Rediseño de la home', 'foco': 0, 'archivado': False},
            'b': {'app_id': 'local_b', 'titulo': 'Migrar la base', 'foco': 0, 'archivado': False},
            'd': {'app_id': 'local_d', 'titulo': 'Docs', 'foco': ahora - 100, 'archivado': False},
            'h': {'app_id': 'local_h', 'titulo': 'Viejo', 'foco': 0, 'archivado': True},
        }
        filas = modelo.armar(estados, app, {'e': ahora - 40}, ahora=ahora)
        self.assertEqual([f['sid'] for f in filas], ['b', 'c', 'a', 'f'])
        self.assertEqual(filas[0]['link'], 'claude://claude.ai/epitaxy/local_b')
        self.assertIsNone(filas[1]['link'])                     # chat de terminal: sin link
        self.assertEqual(filas[2]['titulo'], 'Rediseño de la home')
        self.assertEqual(filas[3]['titulo'], 'proyectos')          # sin título: carpeta
        self.assertTrue(filas[3]['colgada'])
        self.assertEqual(modelo.contar(filas), {'trabajando': 1, 'esperando': 1, 'terminada': 1})

    def test_fijadas_quedan_arriba_aunque_esten_vistas_o_viejas(self):
        ahora = 500_000
        estados = {
            'a': {'session_id': 'a', 'estado': 'terminada', 'desde': ahora - 500},    # vista, fijada
            'b': {'session_id': 'b', 'estado': 'esperando', 'desde': ahora - 10},     # no fijada
            'c': {'session_id': 'c', 'estado': 'trabajando', 'desde': ahora - 60},    # fijada trabajando
            'd': {'session_id': 'd', 'estado': 'terminada', 'desde': ahora - 30 * 3600},  # vieja, fijada
            'v': {'session_id': 'v', 'estado': 'terminada', 'desde': ahora - 500},    # vista, no fijada
        }
        app = {
            'a': {'app_id': 'local_a', 'titulo': 'Pagos', 'foco': ahora - 100, 'archivado': False},
            'e': {'app_id': 'local_e', 'titulo': 'Sin estado', 'foco': ahora - 9000, 'archivado': False},
            'x': {'app_id': 'local_x', 'titulo': 'Archivada', 'foco': ahora, 'archivado': True},
            'v': {'app_id': 'local_v', 'titulo': 'Vista', 'foco': ahora - 100, 'archivado': False},
        }
        fijados = {'a': 1, 'c': 1, 'd': 1, 'e': 1, 'x': 1, 'z': 1}   # z: ya no existe
        filas = modelo.armar(estados, app, {}, ahora=ahora, fijados=fijados)
        self.assertEqual([f['sid'] for f in filas], ['d', 'c', 'a', 'e', 'b'])
        self.assertEqual([f['estado'] for f in filas], ['terminada', 'trabajando', 'quieta', 'quieta', 'esperando'])
        self.assertTrue(all(f['fijada'] for f in filas[:4]))
        self.assertFalse(filas[4]['fijada'])
        self.assertEqual(filas[3]['link'], 'claude://claude.ai/epitaxy/local_e')
        self.assertEqual(modelo.contar(filas), {'trabajando': 1, 'esperando': 1, 'terminada': 1})
        # sin fijar, todo vuelve a ser como antes
        self.assertEqual([f['sid'] for f in modelo.armar(estados, app, {}, ahora=ahora)], ['b', 'c'])

    def test_recientes_para_fijar(self):
        app = {
            'a': {'app_id': 'local_a', 'titulo': 'Viejo', 'foco': 1, 'archivado': False},
            'b': {'app_id': 'local_b', 'titulo': 'Nuevo', 'foco': 9, 'archivado': False},
            'c': {'app_id': 'local_c', 'titulo': 'Fijado', 'foco': 5, 'archivado': False},
            'd': {'app_id': 'local_d', 'titulo': 'Archivado', 'foco': 7, 'archivado': True},
        }
        self.assertEqual(modelo.recientes(app, {'c': 1}), [('b', 'Nuevo', 'claude'), ('a', 'Viejo', 'claude')])

    def test_sonidos(self):
        antes = [{'sid': 'a', 'estado': 'trabajando', 'desde': 1}]
        self.assertEqual(modelo.novedades(antes, [{'sid': 'a', 'estado': 'terminada', 'desde': 2}]), 'terminada')
        self.assertEqual(modelo.novedades(antes, [{'sid': 'a', 'estado': 'terminada', 'desde': 2},
                                                  {'sid': 'b', 'estado': 'esperando', 'desde': 2}]), 'esperando')
        self.assertIsNone(modelo.novedades(antes, antes))
        self.assertIsNone(modelo.novedades(antes, [{'sid': 'z', 'estado': 'trabajando', 'desde': 5}]))

    def test_lee_la_app_real_si_esta(self):
        app = modelo.leer_app()
        if not app:
            self.skipTest('sin archivos de la app')
        uno = next(iter(app.values()))
        self.assertTrue(uno['app_id'].startswith('local_'))


class CarpetaVieja(unittest.TestCase):
    def test_lee_las_dos_carpetas_y_gana_el_mas_nuevo(self):
        # Hooks instalados antes del cambio de nombre siguen escribiendo en la carpeta vieja.
        nueva, vieja = tempfile.mkdtemp(), tempfile.mkdtemp()
        for carpeta, sid, desde in ((nueva, 'x', 200), (vieja, 'x', 100), (vieja, 'y', 50)):
            with open(os.path.join(carpeta, f'{sid}.json'), 'w', encoding='utf-8') as f:
                json.dump({'session_id': sid, 'estado': 'terminada', 'desde': desde}, f)
        antes = modelo.ESTADO_DIRS
        try:
            modelo.ESTADO_DIRS = [nueva, vieja]
            estados = modelo.leer_estados()
        finally:
            modelo.ESTADO_DIRS = antes
        self.assertEqual({s: e['desde'] for s, e in estados.items()}, {'x': 200, 'y': 50})


if __name__ == '__main__':
    unittest.main(verbosity=2)
