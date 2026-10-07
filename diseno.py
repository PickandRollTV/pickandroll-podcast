"""Diseño de la miniatura de cada episodio, con el estilo de la web pickandroll.tv.

Como las tarjetas de la web: fondo azul noche, una tarjeta redondeada con borde
amarillo y degradado del azul Barça al morado, una etiqueta roja inclinada con la
competición, los equipos en blanco y el marcador en amarillo con tipografía
Poppins, y abajo la franja de la web (azul a grana) con Spotify, la marca y si fue
victoria o derrota del Barça.
"""
import pathlib
import random
import re

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

ROOT = pathlib.Path(__file__).resolve().parent
LOGO = ROOT / "portada" / "logo-redondo-pickandroll.webp"
SPOTIFY = ROOT / "portada" / "spotify-icono.png"
PERSONAJE = ROOT / "portada" / "personaje.png"
FONTS = ROOT / "fonts"
SIZE = 3000

# Colores tomados de la web.
NIGHT = (3, 19, 83)          # Fondo de la página.
CARD_BLUE = (0, 73, 147)     # Esquina de la tarjeta: azul Barça.
CARD_NAVY = (2, 33, 99)
CARD_PURPLE = (56, 30, 100)
GARNET = (145, 2, 69)        # Final de la franja de abajo.
RED = (211, 18, 31)          # Etiqueta "NEWSLETTER DIARIA".
YELLOW = (237, 189, 0)       # Borde, palabras destacadas y botón.
WHITE = (255, 255, 255)

CARD = (110, 110, SIZE - 110, SIZE - 110)
RADIUS = 150
BORDER = 22


def font(style, size):
    return ImageFont.truetype(str(FONTS / f"Poppins-{style}.ttf"), size)


def fit(text, style, size, width):
    probe = ImageDraw.Draw(Image.new("L", (1, 1)))
    while size > 80 and probe.textlength(text, font=font(style, size)) > width:
        size -= 10
    return font(style, size)


def _ramp(stops, size, tilt):
    """Degradado de varios colores de izquierda a derecha; con tilt > 0 baja también en diagonal."""
    w, h = size
    across = Image.linear_gradient("L").rotate(90).resize((w, h))
    down = Image.linear_gradient("L").resize((w, h))
    ramp = Image.blend(across, down, tilt)
    def color(t):
        for (a, ca), (b, cb) in zip(stops, stops[1:]):
            if t <= b:
                k = (t - a) / (b - a) if b > a else 0
                return tuple(int(ca[i] + (cb[i] - ca[i]) * k) for i in range(3))
        return stops[-1][1]
    lut = [color(v / 255) for v in range(256)]
    return Image.merge("RGB", [ramp.point([c[i] for c in lut]) for i in range(3)])


def card_mask(inset=0):
    mask = Image.new("L", (SIZE, SIZE), 0)
    x0, y0, x1, y1 = CARD
    ImageDraw.Draw(mask).rounded_rectangle(
        (x0 + inset, y0 + inset, x1 - inset, y1 - inset), RADIUS - inset, fill=255)
    return mask


def background():
    image = Image.new("RGB", (SIZE, SIZE), NIGHT)
    # Sombra de la tarjeta sobre el fondo.
    shadow = card_mask().filter(ImageFilter.GaussianBlur(60)).point(lambda v: v * 0.6)
    image.paste(Image.new("RGB", image.size, (0, 4, 30)), (0, 40), shadow)
    # Borde amarillo y, dentro, el degradado diagonal de la web.
    image.paste(Image.new("RGB", image.size, YELLOW), (0, 0), card_mask())
    fill = _ramp([(0.0, CARD_BLUE), (0.45, CARD_NAVY), (1.0, CARD_PURPLE)], (SIZE, SIZE), 0.4)
    # Resplandor morado a la derecha, como en la tarjeta de la web.
    glow = Image.new("L", (SIZE, SIZE), 0)
    ImageDraw.Draw(glow).ellipse((1900, 900, 3600, 2600), fill=90)
    glow = glow.filter(ImageFilter.GaussianBlur(350))
    fill = Image.composite(Image.new("RGB", image.size, (88, 40, 130)), fill, glow)
    # Logo gigante muy suave como marca de agua.
    logo = Image.open(LOGO).convert("RGBA").resize((2400, 2400), Image.LANCZOS)
    logo.putalpha(logo.getchannel("A").point(lambda a: a * 0.045))
    fill.paste(logo, (1350, -250), logo)
    # Grano finísimo para que el degradado no haga bandas en pantallas grandes.
    random.seed(7)
    noise = Image.effect_noise((SIZE, SIZE), 10).convert("RGB")
    fill = Image.blend(fill, ImageChops.overlay(fill, noise), 0.08)
    image.paste(fill, (0, 0), card_mask(BORDER))
    return image


def band(image, top):
    """Franja de abajo, como el aviso de la web: filo amarillo y degradado azul, noche y grana."""
    x0, _, x1, y1 = CARD
    stripe = _ramp([(0.0, CARD_BLUE), (0.5, CARD_NAVY), (1.0, GARNET)], (SIZE, SIZE), 0)
    area = Image.new("L", (SIZE, SIZE), 0)
    ImageDraw.Draw(area).rectangle((0, top, SIZE, SIZE), fill=255)
    inner = ImageChops.multiply(area, card_mask(BORDER))
    image.paste(stripe, (0, 0), inner)
    line = Image.new("L", (SIZE, SIZE), 0)
    ImageDraw.Draw(line).rectangle((0, top, SIZE, top + BORDER), fill=255)
    image.paste(Image.new("RGB", image.size, YELLOW), (0, 0), ImageChops.multiply(line, card_mask()))


def red_tag(image, x, y, text, fnt, pad=(70, 34), slant=36):
    """Etiqueta roja inclinada, como "NEWSLETTER DIARIA"."""
    draw = ImageDraw.Draw(image)
    left, top, right, bottom = draw.textbbox((0, 0), text, font=fnt)
    w, h = right - left + pad[0] * 2, bottom - top + pad[1] * 2
    draw.polygon([(x + slant, y), (x + w + slant, y), (x + w, y + h), (x, y + h)], fill=RED)
    draw.text((x + pad[0] + slant / 2 - left, y + pad[1] - top), text, font=fnt, fill=WHITE)
    return w + slant, h


def pill(image, right, cy, text, fnt, fill, color):
    """Botón redondeado, como "APÓYANOS"."""
    draw = ImageDraw.Draw(image)
    left, top, r, bottom = draw.textbbox((0, 0), text, font=fnt)
    w, h = r - left + 150, bottom - top + 80
    x, y = right - w, cy - h / 2
    draw.rounded_rectangle((x, y, x + w, y + h), h / 2, fill=fill)
    draw.text((x + 75 - left, y + 40 - top), text, font=fnt, fill=color)


def cap_height(fnt):
    probe = ImageDraw.Draw(Image.new("L", (1, 1)))
    return -probe.textbbox((0, 0), "H0", font=fnt, anchor="ls")[1]


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


def character(image, bottom, height=2000, right=SIZE + 470):
    person = Image.open(PERSONAJE).convert("RGBA")
    person = person.resize((round(person.width * height / person.height), height), Image.LANCZOS)
    layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
    x, y = right - person.width, bottom - height
    # Sombra suave detrás, para que se despegue del fondo.
    shadow = Image.new("L", image.size, 0)
    shadow.paste(person.getchannel("A"), (x + 30, y + 40))
    shadow = shadow.filter(ImageFilter.GaussianBlur(40)).point(lambda v: v * 0.55)
    layer.paste(person, (x, y), person)
    clip = ImageChops.multiply(card_mask(BORDER), Image.new("L", image.size, 255))
    ImageDraw.Draw(clip).rectangle((0, bottom, SIZE, SIZE), fill=0)
    image.paste(Image.new("RGB", image.size, (0, 6, 40)), (0, 0), ImageChops.multiply(shadow, clip))
    image.paste(layer, (0, 0), ImageChops.multiply(layer.getchannel("A"), clip))


def render(home, score, away, competition, kicker_date):
    image = background()
    margin = 300
    width = SIZE - margin * 2
    band_top = 2430

    # Arriba: la competición en la etiqueta roja (el logo ya va en la camiseta del personaje).
    label = competition.upper()
    red_tag(image, margin, 300, label, fit(label, "ExtraBoldItalic", 120, 1650))

    # A la derecha, el personaje de PickandRollTV girando el balón, saliendo de la franja de abajo.
    character(image, band_top)

    if home:
        big = score.replace("-", "–") if score else "VS"
        column = 1180
        home_font = fit(short_name(home), "Black", 340, column)
        score_font = fit(big, "Black", 620, column)
        away_font = fit(short_name(away), "Black", 340, column)
        # Se colocan por la altura de las mayúsculas (sin contar la cedilla de BARÇA), con
        # el mismo hueco entre el equipo de arriba y el marcador que entre el marcador y el de abajo,
        # y el bloque centrado entre la etiqueta y la franja.
        gap = 130
        block = cap_height(home_font) + cap_height(score_font) + cap_height(away_font) + gap * 2
        home_base = (560 + band_top - 110) / 2 - block / 2 + cap_height(home_font)
        score_base = home_base + gap + cap_height(score_font)
        away_base = score_base + gap + cap_height(away_font)
        shadowed_text(image, (margin, home_base), short_name(home), home_font, WHITE, anchor="ls", shadow=30)
        shadowed_text(image, (margin - 10, score_base), big, score_font, YELLOW, anchor="ls", shadow=30)
        shadowed_text(image, (margin, away_base), short_name(away), away_font, WHITE, anchor="ls", shadow=30)

    # Abajo: la franja de la web con Spotify y la marca, y el resultado como el botón amarillo.
    band(image, band_top)
    spotify = Image.open(SPOTIFY).convert("RGBA").resize((150, 150), Image.LANCZOS)
    image.paste(spotify, (margin - 40, band_top + 95), spotify)
    draw = ImageDraw.Draw(image)
    draw.text((margin - 40, band_top + 380), "PICKANDROLLTV  ·  PODCAST", font=font("Bold", 100), fill=WHITE, anchor="ls")
    result = barca_result(home or "", score, away or "")
    if result:
        won = result == "VICTORIA"
        pill(image, SIZE - margin + 40, band_top + 228, result, font("ExtraBold", 110),
             YELLOW if won else WHITE, CARD_NAVY)
    return image.filter(ImageFilter.UnsharpMask(radius=2, percent=60, threshold=2))
