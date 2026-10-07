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
SPOTIFY = ROOT / "portada" / "spotify-icono.png"
FONTS = ROOT / "fonts"
SIZE = 3000

# Colores oficiales del FC Barcelona: azul #004D98, grana #A50044 y amarillo #EDBB00.
BLUE = (0, 77, 152)
NAVY = (0, 34, 82)        # El mismo azul, oscurecido para el degradado.
GARNET = (165, 0, 68)
GARNET_DARK = (92, 0, 38)
YELLOW = (237, 187, 0)
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
    garnet = _gradient(GARNET, GARNET_DARK)
    image = Image.composite(garnet, image, panel)
    edge = Image.new("L", (SIZE, SIZE), 0)
    ImageDraw.Draw(edge).polygon([(0, 2050), (SIZE, 1500), (SIZE, 1530), (0, 2080)], fill=255)
    image = Image.composite(Image.new("RGB", (SIZE, SIZE), YELLOW), image, edge)

    # Rayas diagonales finas, muy suaves.
    stripes = Image.new("L", (SIZE, SIZE), 0)
    draw = ImageDraw.Draw(stripes)
    for x in range(-SIZE, SIZE * 2, 34):
        draw.line([(x, 0), (x + SIZE, SIZE)], fill=9, width=6)
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
    noise = Image.effect_noise((SIZE, SIZE), 14).convert("RGB")
    image = Image.blend(image, ImageChops.overlay(image, noise), 0.12)
    # Barrido de luz en diagonal y viñeta suave en los bordes: acabado de cartel de televisión.
    sweep = Image.new("L", (SIZE, SIZE), 0)
    ImageDraw.Draw(sweep).polygon([(700, 0), (1500, 0), (300, SIZE), (-500, SIZE)], fill=34)
    sweep = sweep.filter(ImageFilter.GaussianBlur(120))
    image = Image.composite(Image.new("RGB", (SIZE, SIZE), WHITE), image, sweep)
    vignette = Image.new("L", (SIZE, SIZE), 255)
    ImageDraw.Draw(vignette).ellipse((-500, -500, SIZE + 500, SIZE + 500), fill=0)
    vignette = vignette.filter(ImageFilter.GaussianBlur(300)).point(lambda v: v * 0.55)
    image = Image.composite(Image.new("RGB", (SIZE, SIZE), (0, 0, 0)), image, vignette)
    return image


def gold_text(image, xy, text, fnt, anchor="mm"):
    """Texto dorado con degradado metálico, filo claro y sombra profunda."""
    mask = Image.new("L", image.size, 0)
    ImageDraw.Draw(mask).text(xy, text, font=fnt, fill=255, anchor=anchor)
    box = mask.getbbox()
    shadow = mask.filter(ImageFilter.GaussianBlur(45)).point(lambda v: v * 0.75)
    image.paste(Image.new("RGB", image.size, (0, 0, 0)), (28, 46), shadow)
    top, bottom = box[1], box[3]
    ramp = Image.linear_gradient("L").resize((1, bottom - top)).resize((image.width, bottom - top))
    stops = [(0.0, (255, 232, 140)), (0.45, (237, 187, 0)), (0.55, (204, 152, 0)), (1.0, (246, 204, 60))]
    def color(t):
        for (a, ca), (b, cb) in zip(stops, stops[1:]):
            if t <= b:
                k = (t - a) / (b - a)
                return tuple(int(ca[i] + (cb[i] - ca[i]) * k) for i in range(3))
        return stops[-1][1]
    lut = [color(v / 255) for v in range(256)]
    gradient = Image.merge("RGB", [ramp.point([c[i] for c in lut]) for i in range(3)])
    fill = Image.new("RGB", image.size, (0, 0, 0))
    fill.paste(gradient, (0, top))
    # Filo fino más oscuro alrededor de las cifras para que recorten sobre el fondo.
    edge = mask.filter(ImageFilter.MaxFilter(9))
    image.paste(Image.new("RGB", image.size, (120, 80, 10)), (0, 0), edge)
    image.paste(fill, (0, 0), mask)
    # Brillo en la mitad superior de las cifras.
    gloss = Image.new("L", image.size, 0)
    ImageDraw.Draw(gloss).rectangle((0, top, image.width, top + (bottom - top) * 0.42), fill=60)
    image.paste(Image.new("RGB", image.size, WHITE), (0, 0), ImageChops.multiply(gloss, mask))


def frame(image):
    """Marco fino dorado, como las tarjetas de las retransmisiones."""
    draw = ImageDraw.Draw(image)
    draw.rectangle((60, 60, SIZE - 60, SIZE - 60), outline=(200, 160, 60), width=8)


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


def render(home, score, away, competition, kicker_date):
    image = background()
    margin = 190
    width = SIZE - margin * 2

    # Arriba: la competición en una etiqueta amarilla y el logo a la derecha.
    tag(image, margin, 210, competition.upper(), fit(competition.upper(), "Bold", 150, 1900), YELLOW, NAVY)
    logo = Image.open(LOGO).convert("RGBA").resize((470, 470), Image.LANCZOS)
    image.paste(logo, (SIZE - margin - 470, 120), logo)

    if home:
        big = score.replace("-", "–") if score else "VS"
        home_font = fit(short_name(home), "BlackItalic", 560, width)
        score_font = fit(big, "BlackItalic", 1080, width)
        away_font = fit(short_name(away), "BlackItalic", 560, width)
        # Se colocan por la altura de las mayúsculas (sin contar la cedilla de BARÇA), con
        # el mismo hueco entre el equipo de arriba y el marcador que entre el marcador y el de abajo.
        gap = 150
        home_base = 560 + cap_height(home_font)
        score_base = home_base + gap + cap_height(score_font)
        away_base = score_base + gap + cap_height(away_font)
        shadowed_text(image, (margin, home_base), short_name(home), home_font, WHITE, anchor="ls")
        gold_text(image, (SIZE / 2, score_base), big, score_font, anchor="ms")
        shadowed_text(image, (SIZE - margin, away_base), short_name(away), away_font, WHITE, anchor="rs")
    # Abajo: la marca y el resultado para el Barça.
    spotify = Image.open(SPOTIFY).convert("RGBA").resize((190, 190), Image.LANCZOS)
    image.paste(spotify, (margin, SIZE - 170 - 120 - 60 - 190), spotify)
    draw = ImageDraw.Draw(image)
    draw.text((margin, SIZE - 170), "PICKANDROLLTV  ·  PODCAST", font=font("SemiBold", 120), fill=WHITE, anchor="ld")
    result = barca_result(home or "", score, away or "")
    if result:
        fnt = font("Bold", 120)
        w = draw.textlength(result, font=fnt) + 160
        tag(image, SIZE - margin - w - 40, SIZE - 330, result, fnt, YELLOW if result == "VICTORIA" else WHITE, NAVY)
    frame(image)
    # Nitidez final, para que se vea limpia también en pantallas grandes.
    return image.filter(ImageFilter.UnsharpMask(radius=2, percent=80, threshold=2))
