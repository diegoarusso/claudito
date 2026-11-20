"""Faro del monitor de Claude: anota en qué está cada chat, para que Claudito lo muestre.

Lo llaman los hooks clásicos de Claude Code (hooks.json de este plugin) con el evento por stdin.
Solo escribe un JSON chico por sesión en ESTADO_DIR; no aprueba, no bloquea, no toca permisos
ni abre puertos. Si algo falla, sale en silencio: el monitor nunca debe trabar a Claude.

Estados:
  trabajando  le mandaste algo y está corriendo
  esperando   te pide un permiso o te hizo una pregunta con opciones
  terminada   terminó el turno y espera que lo mires
"""
import json
import os
import sys
import tempfile
import time

ESTADO_DIR = os.environ.get('MONITOR_CLAUDE_ESTADO', os.path.join(os.path.expanduser('~'), '.claudito', 'estado'))


def corto(texto, n=90):
    texto = ' '.join(str(texto or '').split())
    return texto if len(texto) <= n else texto[:n - 1] + '…'


def leer(ruta):
    try:
        with open(ruta, encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


def escribir(ruta, datos):
    os.makedirs(os.path.dirname(ruta), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(ruta), suffix='.tmp')
    with os.fdopen(fd, 'w', encoding='utf-8') as f:
        json.dump(datos, f, ensure_ascii=False)
    os.replace(tmp, ruta)


def transicion(evento, previo):
    """(nuevo_estado, detalle) para un evento, o None si el evento no cambia nada."""
    nombre = evento.get('hook_event_name')
    estado_previo = previo.get('estado')
    if nombre == 'UserPromptSubmit':
        return 'trabajando', ''
    if nombre == 'PermissionRequest':
        return 'esperando', f"pide permiso: {evento.get('tool_name') or 'una herramienta'}"
    if nombre == 'Notification' and evento.get('notification_type') == 'permission_prompt':
        return 'esperando', corto(evento.get('message') or 'pide permiso')
    if nombre == 'PreToolUse' and evento.get('tool_name') == 'AskUserQuestion':
        return 'esperando', 'te hizo una pregunta'
    if nombre == 'PostToolUse' and estado_previo == 'esperando':
        return 'trabajando', ''            # ya respondiste: sigue
    if nombre == 'Stop' and not evento.get('agent_id'):
        return 'terminada', ''
    return None


def procesar(evento, ahora=None, estado_dir=ESTADO_DIR):
    sid = evento.get('session_id')
    if not sid:
        return None
    ruta = os.path.join(estado_dir, f'{sid}.json')
    if evento.get('hook_event_name') == 'SessionEnd':
        try:
            os.remove(ruta)
        except FileNotFoundError:
            pass
        return 'cerrada'
    previo = leer(ruta)
    nuevo = transicion(evento, previo)
    if nuevo is None:
        return previo.get('estado')
    estado, detalle = nuevo
    if estado == previo.get('estado') and detalle == previo.get('detalle', ''):
        return estado                      # sin cambios: no reescribe
    datos = {
        'session_id': sid,
        'estado': estado,
        'detalle': detalle,
        'desde': ahora if ahora is not None else time.time(),
        'cwd': evento.get('cwd') or previo.get('cwd', ''),
        'pedido': corto(evento.get('prompt')) if evento.get('prompt') else previo.get('pedido', ''),
        # la app de escritorio deja el id de su chat en el entorno: sirve para el link claude://
        'app_id': os.environ.get('CLAUDE_CODE_HOST_SESSION_ID') or previo.get('app_id'),
    }
    escribir(ruta, datos)
    return estado


def main():
    try:
        evento = json.loads(sys.stdin.buffer.read().decode('utf-8', 'replace') or '{}')
        resultado = procesar(evento)
        traza = os.environ.get('MONITOR_CLAUDE_TRAZA')     # diagnóstico opcional
        if traza:
            with open(traza, 'a', encoding='utf-8') as f:
                f.write(f"{time.strftime('%H:%M:%S')} {evento.get('hook_event_name')} "
                        f"{evento.get('tool_name') or evento.get('notification_type') or ''} -> {resultado}\n")
    except Exception:
        pass                               # nunca romper el turno de Claude
    return 0


if __name__ == '__main__':
    sys.exit(main())
