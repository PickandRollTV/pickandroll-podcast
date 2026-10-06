"""Miniatura cuadrada de cada episodio, con el estilo de los grandes podcasts deportivos.

Cada episodio lleva su propia imagen de 3000x3000, con el mismo diseño: el logo
arriba, el partido en grande (con el resultado si ya lo tenemos) y la competición y
la fecha abajo. Se lee bien incluso en pequeño en la lista de episodios de Spotify.
Se guardan en docs/episodios/ y las sirve GitHub Pages.
"""
import hashlib
import pathlib
import re

from PIL import Image, ImageDraw, ImageFont

ROOT = pathlib.Path(__file__).resolve().parent
LOGO = ROOT / "portada" / "logo-redondo-pickandroll.webp"
FONTS = ROOT / "fonts"
SIZE = 3000
BLUE = (44, 76, 148)        # El azul de los gajos del logo, igual que la portada.
NAVY = (16, 30, 66)
YELLOW = (232, 190, 74)     # El amarillo del aro del logo.
GARNET = (150, 22, 64)
WHITE = (255, 255, 255)
MONTHS = "ENE FEB MAR ABR MAY JUN JUL AGO SEP OCT NOV DIC".split()


def _font(weight, size):
    return ImageFont.truetype(str(FONTS / f"Inter-{weight}.otf"), size)


def _fit(draw, text, weight, size, width):
    """La fuente más grande (hasta size) con la que el texto cabe en width."""
    while size > 60:
        font = _font(weight, size)
        if draw.textlength(text, font=font) <= width:
            return font
        size -= 10
    return _font(weight, size)


def _center(draw, y, text, font, fill):
    left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
    draw.text(((SIZE - (right - left)) / 2 - left, y - top), text, font=font, fill=fill)
    return y + (bottom - top)


def split_match(title):
    """"Valencia Basket 86-87 Barça | Semifinal..." -> ("Valencia Basket", "86-87", "Barça", "Semifinal...")."""
    match, _, rest = title.partition(" | ")
    found = re.match(r"(.+?)\s+(\d{2,3}-\d{2,3}|vs)\s+(.+)$", match)
    if not found:
        return None, None, None, title
    home, score, away = found.groups()
    return home, (None if score == "vs" else score), away, rest


def render(title, published):
    home, score, away, rest = split_match(title)
    image = Image.new("RGB", (SIZE, SIZE), BLUE)
    draw = ImageDraw.Draw(image)
    # Franja inferior oscura con la competición y la fecha.
    draw.rectangle((0, 2380, SIZE, SIZE), fill=NAVY)
    draw.rectangle((0, 2360, SIZE, 2380), fill=YELLOW)

    logo = Image.open(LOGO).convert("RGBA").resize((900, 900), Image.LANCZOS)
    image.paste(logo, ((SIZE - 900) // 2, 130), logo)

    width = SIZE - 300
    if home:
        y = 1130
        y = _center(draw, y, home.upper(), _fit(draw, home.upper(), "ExtraBold", 260, width), WHITE) + 70
        middle = score.replace("-", " - ") if score else "VS"
        y = _center(draw, y, middle, _font("ExtraBold", 400 if score else 230), YELLOW) + 70
        _center(draw, y, away.upper(), _fit(draw, away.upper(), "ExtraBold", 260, width), WHITE)
    else:
        lines, line = [], ""
        for word in title.split():
            if line and draw.textlength(f"{line} {word}", font=_font("ExtraBold", 220)) > width:
                lines.append(line)
                line = word
            else:
                line = f"{line} {word}".strip()
        y = 1150
        for text in (lines + [line])[:4]:
            y = _center(draw, y, text, _font("ExtraBold", 220), WHITE) + 50

    date = f"{published.day} {MONTHS[published.month - 1]} {published.year}"
    bottom = " · ".join(p for p in rest.split(" | ") if p).upper() if home else ""
    if bottom:
        _center(draw, 2470, bottom, _fit(draw, bottom, "Bold", 150, width), WHITE)
    _center(draw, 2720, date, _font("SemiBold", 130), YELLOW)
    return image


def add_covers(episodes, docs_dir, base_url, title_of):
    """Crea o rehace la miniatura de los episodios cuyo título ha cambiado. Devuelve cuántas."""
    import datetime

    folder = docs_dir / "episodios"
    folder.mkdir(parents=True, exist_ok=True)
    made = 0
    for episode in episodes:
        title = title_of(episode)
        key = hashlib.sha1(f"v1|{title}".encode()).hexdigest()[:8]
        if episode.get("cover_key") == key:
            continue
        slug = re.sub(r"[^a-z0-9]+", "-", episode["guid"].lower()).strip("-")
        published = datetime.datetime.fromisoformat(episode["published"].replace("Z", "+00:00"))
        # El nombre cambia con el diseño: así Spotify no se queda con la imagen vieja.
        name = f"{slug}-{key}.jpg"
        render(title, published).save(folder / name, quality=88, optimize=True)
        for old in folder.glob(f"{slug}*.jpg"):
            if old.name != name:
                old.unlink()
        episode["cover"] = f"{base_url}/episodios/{name}"
        episode["cover_key"] = key
        made += 1
    return made
