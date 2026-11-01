#!/usr/bin/env python3
"""Pone el marcador final en la miniatura de resumen del pack del partido (donde pone 00-00).

Uso: python miniatura_resumen.py <plantilla.jpg> <marcador, p. ej. 78-91> <salida.jpg>

Busca el texto blanco del marcador en la franja de abajo a la izquierda (entre los dos
escudos), lo borra rellenando con el fondo de alrededor y escribe el resultado con la misma
letra (Bebas Neue), el mismo alto y el mismo centro. Sale a 1280x720 y < 2 MB para YouTube.
"""
import pathlib
import sys

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

FONT = pathlib.Path(__file__).resolve().parent / "fonts" / "BebasNeue-Regular.ttf"


def score_box(img):
    """Caja del 00-00: píxeles casi blancos en la zona del marcador de la plantilla 16:9."""
    h, w = img.shape[:2]
    x0, x1, y0, y1 = int(w * 0.13), int(w * 0.34), int(h * 0.72), int(h * 0.93)
    zone = img[y0:y1, x0:x1]
    white = (zone.min(axis=2) > 200).astype(np.uint8)
    rows = np.where(white.sum(axis=1) > 3)[0]
    if len(rows) == 0:
        raise SystemExit("No encuentro el marcador 00-00 en la plantilla")
    # Se queda con el bloque de filas más alto (el marcador), no con el pie de RESUMEN de encima.
    runs, start = [], rows[0]
    for prev, cur in zip(rows, rows[1:]):
        if cur != prev + 1:
            runs.append((start, prev)); start = cur
    runs.append((start, rows[-1]))
    r0, r1 = max(runs, key=lambda r: r[1] - r[0])
    cols = np.where(white[r0:r1 + 1].sum(axis=0) > 3)[0]
    return x0 + cols[0], y0 + r0, x0 + cols[-1], y0 + r1


def main(template, score, out):
    img = cv2.imread(template)
    a, b, c, d = score_box(img)
    pad = max(6, int((d - b) * 0.06))
    a, b, c, d = a - pad, b - pad, c + pad, d + pad
    # Fondo: degradado horizontal entre la columna justo a la izquierda y la de la derecha del
    # marcador (los huecos oscuros junto a los escudos), con un poco de grano para que no se note.
    clean = img.copy()
    left = img[b:d, a - 3:a].mean(axis=1)
    right = img[b:d, c:c + 3].mean(axis=1)
    t = np.linspace(0, 1, c - a)[None, :, None]
    fill = left[:, None, :] * (1 - t) + right[:, None, :] * t
    fill += np.random.default_rng(1).normal(0, 2.5, fill.shape)
    clean[b:d, a:c] = np.clip(fill, 0, 255).astype(np.uint8)
    pil = Image.fromarray(cv2.cvtColor(clean, cv2.COLOR_BGR2RGB))

    height = d - b - 2 * pad
    size = int(height * 1.42)  # alto de las cifras de Bebas Neue ≈ 0,7 del tamaño
    font = ImageFont.truetype(str(FONT), size)
    draw = ImageDraw.Draw(pil)
    l, t, r, btm = draw.textbbox((0, 0), score, font=font)
    while r - l > (c - a) * 1.12 and size > 20:  # 100-99 es más ancho que 00-00
        size -= 4
        font = ImageFont.truetype(str(FONT), size)
        l, t, r, btm = draw.textbbox((0, 0), score, font=font)
    cx, cy = (a + c) / 2, (b + d) / 2
    x, y = cx - (r - l) / 2 - l, cy - (btm - t) / 2 - t
    shadow = Image.new("L", pil.size, 0)
    ImageDraw.Draw(shadow).text((x + 8, y + 10), score, font=font, fill=180)
    pil.paste((0, 0, 0), (0, 0), shadow.filter(ImageFilter.GaussianBlur(14)))
    draw = ImageDraw.Draw(pil)
    draw.text((x, y), score, font=font, fill=(245, 243, 240))
    pil.resize((1280, 720), Image.LANCZOS).save(out, quality=92, optimize=True)


if __name__ == "__main__":
    main(*sys.argv[1:4])
