"""Miniatura cuadrada para cada episodio, guardada en docs/episodios/ y servida con GitHub Pages.

Spotify muestra la imagen de cada episodio en cuadrado. Las miniaturas de Twitch son
apaisadas, así que se monta una imagen de 3000x3000: la miniatura entera en el centro
sobre una versión ampliada y desenfocada de sí misma. Las imágenes de los episodios
importados de Spotify for Creators se copian aquí porque allí dejarán de existir.
"""
import io
import re
import urllib.request

from PIL import Image, ImageEnhance, ImageFilter

SIZE = 3000


def _download(url):
    # Las miniaturas de Twitch admiten cualquier tamaño en la URL: pedimos la grande.
    big = re.sub(r"-\d+x\d+\.(jpg|png)$", r"-1920x1080.\1", url)
    for candidate in dict.fromkeys([big, url]):
        try:
            request = urllib.request.Request(candidate, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(request, timeout=30) as response:
                return Image.open(io.BytesIO(response.read())).convert("RGB")
        except Exception as error:
            last = error
    raise last


def square(image):
    width, height = image.size
    if abs(width - height) <= 2:
        return image.resize((SIZE, SIZE), Image.LANCZOS)
    fill = max(SIZE / width, SIZE / height)
    background = image.resize((round(width * fill), round(height * fill)), Image.LANCZOS)
    left, top = (background.width - SIZE) // 2, (background.height - SIZE) // 2
    background = background.crop((left, top, left + SIZE, top + SIZE)).filter(ImageFilter.GaussianBlur(60))
    background = ImageEnhance.Brightness(background).enhance(0.45)
    fit = min(SIZE / width, SIZE / height)
    front = image.resize((round(width * fit), round(height * fit)), Image.LANCZOS)
    background.paste(front, ((SIZE - front.width) // 2, (SIZE - front.height) // 2))
    return background


def add_covers(episodes, docs_dir, base_url):
    """Crea la miniatura de los episodios que aún no la tienen. Devuelve cuántas ha creado."""
    folder = docs_dir / "episodios"
    folder.mkdir(parents=True, exist_ok=True)
    made = 0
    for episode in episodes:
        if episode.get("cover") or not episode.get("image"):
            continue
        name = re.sub(r"[^a-z0-9]+", "-", episode["guid"].lower()).strip("-") + ".jpg"
        try:
            square(_download(episode["image"])).save(folder / name, quality=88, optimize=True)
        except Exception as error:  # Sin miniatura se usa la portada del programa.
            print(f"Sin miniatura para {episode['title']}: {error}")
            continue
        episode["cover"] = f"{base_url}/episodios/{name}"
        made += 1
    return made
