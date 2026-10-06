"""Diseño de la miniatura de cada episodio, al estilo de las grandes marcas deportivas.

Fondo azul marino con un panel diagonal granate (los colores del logo), textura de
rayas y grano, el logo gigante como marca de agua, y el partido con tipografía
condensada en cursiva: competición arriba, equipos y marcador en grande, y abajo
la marca y si fue victoria o derrota del Barça.
"""
import pathlib
import random
import re

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

ROOT = pathlib.Path(__file__).resolve().parent
LOGO = ROOT / "portada" / "logo-redondo-pickandroll.webp"
FONTS = ROOT / "fonts"
SIZE = 3000

NAVY = (8, 18, 46)
BLUE = (30, 58, 130)
GARNET = (128, 14, 52)
YELLOW = (240, 196, 64)
WHITE = (255, 255, 255)


def font(style, size):
    return ImageFont.truetype(str(FONTS / f"BarlowCondensed-{style}.ttf"), size)


def fit(text, style, size, width):
    probe = ImageDraw.Draw(Image.new("L", (1, 1)))
    while size > 80 and probe.textlength(text, font=font(style, size)) > width:
        size -= 10
    return font(style, size)


def _gradient(top, bottom):
    column = Image.linear_gradient("L").resize((SIZE, SIZE))
    return Image.composite(Image.new("RGB", (SIZE, SIZE), bottom), Image.new("RGB", (SIZE, SIZE), top), column)


def background():
    image = _gradient(BLUE, NAVY)
    # Panel granate en diagonal, con un filo amarillo.
    panel = Image.new("L", (SIZE, SIZE), 0)
    ImageDraw.Draw(panel).polygon([(0, 2050), (SIZE, 1500), (SIZE, SIZE), (0, SIZE)], fill=255)
    garnet = _gradient(GARNET, (70, 6, 30))
    image = Image.composite(garnet, image, panel)
    edge = Image.new("L", (SIZE, SIZE), 0)
    ImageDraw.Draw(edge).polygon([(0, 2050), (SIZE, 1500), (SIZE, 1530), (0, 2080)], fill=255)
    image = Image.composite(Image.new("RGB", (SIZE, SIZE), YELLOW), image, edge)

    # Rayas diagonales finas, muy suaves.
    stripes = Image.new("L", (SIZE, SIZE), 0)
    draw = ImageDraw.Draw(stripes)
    for x in range(-SIZE, SIZE * 2, 60):
        draw.line([(x, 0), (x + SIZE, SIZE)], fill=18, width=14)
    image = Image.composite(Image.new("RGB", (SIZE, SIZE), WHITE), image, stripes)

    # Logo gigante como marca de agua, cortado por la derecha.
    logo = Image.open(LOGO).convert("RGBA").resize((2600, 2600), Image.LANCZOS)
    alpha = logo.getchannel("A").point(lambda a: a * 0.05)
    logo.putalpha(alpha)
    image.paste(logo, (1250, -350), logo)

    # Luz desde arriba y viñeta, y un poco de grano.
    glow = Image.new("L", (SIZE, SIZE), 0)
    ImageDraw.Draw(glow).ellipse((-600, -1400, 2600, 1400), fill=70)
    glow = glow.filter(ImageFilter.GaussianBlur(400))
    image = Image.composite(Image.new("RGB", (SIZE, SIZE), (120, 160, 255)), image, glow)
    random.seed(7)
    noise = Image.effect_noise((SIZE, SIZE), 22).convert("RGB")
    image = Image.blend(image, ImageChops.overlay(image, noise), 0.25)
    return image


def shadowed_text(image, xy, text, fnt, fill, anchor="la", shadow=40):
    """Texto con sombra difuminada, para que tenga volumen sobre el fondo."""
    layer = Image.new("L", image.size, 0)
    ImageDraw.Draw(layer).text((xy[0] + shadow * 0.4, xy[1] + shadow * 0.6), text, font=fnt, fill=200, anchor=anchor)
    layer = layer.filter(ImageFilter.GaussianBlur(shadow))
    image.paste(Image.new("RGB", image.size, (0, 0, 0)), (0, 0), layer)
    ImageDraw.Draw(image).text(xy, text, font=fnt, fill=fill, anchor=anchor)


def tag(image, x, y, text, fnt, fill, color, pad=(60, 26), slant=40):
    """Etiqueta en paralelogramo, como los rótulos de televisión."""
    draw = ImageDraw.Draw(image)
    left, top, right, bottom = draw.textbbox((0, 0), text, font=fnt)
    w, h = right - left + pad[0] * 2, bottom - top + pad[1] * 2
    draw.polygon([(x + slant, y), (x + w + slant, y), (x + w, y + h), (x, y + h)], fill=fill)
    draw.text((x + pad[0] + slant / 2 - left, y + pad[1] - top), text, font=fnt, fill=color)
    return w + slant, h


def short_name(team):
    name = re.sub(r"\s+(basket|basketball|badalona)$", "", team.strip(), flags=re.I)
    name = re.sub(r"^emporio armani\s+", "", name, flags=re.I)
    return name.upper()


def barca_result(home, score, away):
    if not score:
        return None
    a, b = (int(n) for n in score.split("-"))
    barca_home = "barç" in home.lower() or "barc" in home.lower()
    won = a > b if barca_home else b > a
    return "VICTORIA" if won else "DERROTA"


def render(home, score, away, competition, kicker_date):
    image = background()
    margin = 190
    width = SIZE - margin * 2

    # Arriba: la competición en una etiqueta amarilla y el logo a la derecha.
    tag(image, margin, 210, competition.upper(), fit(competition.upper(), "Bold", 150, 1900), YELLOW, NAVY)
    logo = Image.open(LOGO).convert("RGBA").resize((470, 470), Image.LANCZOS)
    image.paste(logo, (SIZE - margin - 470, 120), logo)

    if home:
        shadowed_text(image, (margin, 640), short_name(home), fit(short_name(home), "BlackItalic", 560, width), WHITE)
        big = score.replace("-", "–") if score else "VS"
        shadowed_text(image, (SIZE / 2, 1660), big, fit(big, "BlackItalic", 1080, width), YELLOW, anchor="mm", shadow=60)
        shadowed_text(image, (SIZE - margin, 2560), short_name(away), fit(short_name(away), "BlackItalic", 560, width), WHITE, anchor="rd")
    # Abajo: la marca y el resultado para el Barça.
    draw = ImageDraw.Draw(image)
    draw.text((margin, SIZE - 170), "PICKANDROLLTV  ·  PODCAST", font=font("SemiBold", 120), fill=WHITE, anchor="ld")
    result = barca_result(home or "", score, away or "")
    if result:
        fnt = font("Bold", 120)
        w = draw.textlength(result, font=fnt) + 160
        tag(image, SIZE - margin - w - 40, SIZE - 330, result, fnt, YELLOW if result == "VICTORIA" else WHITE, NAVY)
    return image
