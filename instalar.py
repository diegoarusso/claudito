"""Instala Claudito en esta máquina: ícono, accesos (Escritorio, menú Inicio, arranque con Windows) y lo abre.

Uso:  py -3 instalar.py
Los hooks (plugin monitor-chats de Claude Code) se instalan aparte: ver el README.
"""
import os
import subprocess
import sys

AQUI = os.path.dirname(os.path.abspath(__file__))
APP = os.path.join(AQUI, 'app')
PYW = os.path.join(os.path.dirname(sys.executable), 'pythonw.exe')


def main():
    # Pillow (ícono) y pystray (ícono en la bandeja de Windows); sin ellos Claudito anda igual.
    r = subprocess.run([sys.executable, '-m', 'pip', 'install', '--quiet', 'pillow', 'pystray'])
    if r.returncode:
        print('Aviso: no pude instalar pillow/pystray; Claudito anda sin ícono en la bandeja.')
    try:
        sys.path.insert(0, APP)
        import generar_icono
        generar_icono.generar()
    except ImportError:
        print('Aviso: falta Pillow para el ícono (py -3 -m pip install pillow); sigo sin ícono propio.')
    os.makedirs(os.path.join(os.path.expanduser('~'), '.claudito', 'estado'), exist_ok=True)
    ps = f"""
$sh = New-Object -ComObject WScript.Shell
# accesos del nombre anterior (Clawd), si quedaron de una instalación vieja
foreach ($v in @(
  (Join-Path ([Environment]::GetFolderPath('Desktop')) 'Clawd.lnk'),
  (Join-Path ([Environment]::GetFolderPath('Programs')) 'Clawd.lnk'),
  (Join-Path ([Environment]::GetFolderPath('Startup')) 'Clawd - monitor de chats.lnk'))) {{
  if (Test-Path $v) {{ Remove-Item $v; "borrado: $v" }}
}}
foreach ($d in @(
  (Join-Path ([Environment]::GetFolderPath('Desktop')) 'Claudito.lnk'),
  (Join-Path ([Environment]::GetFolderPath('Programs')) 'Claudito.lnk'),
  (Join-Path ([Environment]::GetFolderPath('Startup')) 'Claudito - monitor de chats.lnk'))) {{
  $l = $sh.CreateShortcut($d)
  $l.TargetPath = '{PYW}'
  $l.Arguments = '"{os.path.join(APP, 'claudito.pyw')}"'
  $l.WorkingDirectory = '{APP}'
  if (Test-Path '{os.path.join(APP, 'claudito.ico')}') {{ $l.IconLocation = '{os.path.join(APP, 'claudito.ico')},0' }}
  $l.Save(); "acceso: $d"
}}
"""
    subprocess.run(['powershell', '-NoProfile', '-Command', ps], check=True)
    subprocess.Popen([PYW, os.path.join(APP, 'claudito.pyw')], cwd=APP)
    print('Listo: Claudito abajo a la derecha. Reiniciá los chats abiertos para que reporten.')


if __name__ == '__main__':
    main()
