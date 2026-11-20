"""Genera claudito.ico (el ícono de los accesos directos) desde el mismo pixel art de la ventana."""
import os
import sys

from PIL import Image

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, AQUI)

# Mismo dibujo que claudito.pyw (sin importarlo: abriría la ventana).
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
COLORES = {'X': (217, 119, 87, 255), 'A': (217, 119, 87, 255), 'E': (43, 27, 20, 255), 'L': (184, 95, 66, 255)}


def generar(destino=os.path.join(AQUI, 'claudito.ico')):
    lado = 16                                   # lienzo cuadrado de 16 x 16, Claudito centrado
    img = Image.new('RGBA', (lado, lado), (0, 0, 0, 0))
    oy = (lado - len(CUERPO)) // 2
    for y, fila in enumerate(CUERPO):
        for x, c in enumerate(fila):
            if c in COLORES:
                img.putpixel((x, y + oy), COLORES[c])
    grande = img.resize((256, 256), Image.NEAREST)  # NEAREST: mantiene los pixeles nítidos
    grande.save(destino, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    return destino


if __name__ == '__main__':
    print(generar())
