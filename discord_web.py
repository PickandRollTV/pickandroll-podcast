#!/usr/bin/env python3
"""Comparte en Discord cada noticia nueva de pickandroll.tv, para llevar tráfico a la web.

Flujo de cada ejecución:
  1. Lee el RSS de la web (config.json → discord.feed_url).
  2. Para cada noticia que aún no esté en discord_publicados.json, la publica en el
     canal de Discord con un webhook: titular, entradilla, foto y enlace a la web.
  3. Apunta la noticia en discord_publicados.json para no repetirla.

La primera vez solo apunta las noticias que ya hay, sin publicarlas, para no llenar
el canal de golpe con noticias antiguas.

Variables de entorno:
  DISCORD_WEBHOOK     URL del webhook del canal de noticias (secreto del repositorio).
                      Si no está, el script no hace nada.
  DISCORD_ROLE_ID     Opcional: id del rol a mencionar en cada noticia (por ejemplo,
                      un rol "Noticias" que los miembros eligen tener).
"""
import datetime
import email.utils
import html
import json
import os
import pathlib
import re
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

ROOT = pathlib.Path(__file__).resolve().parent
CONFIG_FILE = ROOT / "config.json"
STATE_FILE = ROOT / "discord_publicados.json"
USER_AGENT = "Mozilla/5.0 (compatible; PickandRollTV-Discord/1.0; +https://pickandroll.tv)"
CONTENT_NS = "{http://purl.org/rss/1.0/modules/content/}encoded"
MEDIA_NS = "{http://search.yahoo.com/mrss/}"
# Como mucho estas noticias por pasada, por si un día se publican muchas a la vez.
MAX_PER_RUN = 5
# Noticias recordadas: de sobra para no repetir ninguna que siga en el RSS.
MAX_REMEMBERED = 300


def fetch(url):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read()


def plain_text(fragment, limit):
    """Quita el HTML y recorta a `limit` caracteres sin partir palabras."""
    text = re.sub(r"<[^>]+>", " ", fragment or "")
    text = re.sub(r"\s+", " ", html.unescape(text)).strip()
    text = re.sub(r"\s*(The post|La entrada) .* (appeared first on|se publicó primero en) .*$", "", text)
    text = re.sub(r"(\s*(\[\s*(…|\.\.\.)\s*\]|…|\.\.\.))+$", "…", text)
    if len(text) > limit:
        text = text[:limit].rsplit(" ", 1)[0].rstrip(",;:.") + "…"
    return text


def find_image(item, link):
    """Foto de la noticia: la del RSS si la trae; si no, la de portada (og:image) de la página."""
    for tag in (MEDIA_NS + "content", MEDIA_NS + "thumbnail", "enclosure"):
        element = item.find(tag)
        if element is not None and element.get("url") and "image" in (element.get("type") or "image"):
            return element.get("url")
    try:
        page = fetch(link).decode("utf-8", "replace")
    except Exception as error:
        print(f"Sin foto para {link}: {error}", file=sys.stderr)
        page = ""
    meta = re.search(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)', page)
    if meta:
        return html.unescape(meta.group(1))
    content = item.findtext(CONTENT_NS) or ""
    img = re.search(r'<img[^>]+src=["\']([^"\']+)', content)
    return html.unescape(img.group(1)) if img else None


def with_utm(link, campaign):
    """Añade las etiquetas UTM para ver en las estadísticas de la web las visitas que llegan desde Discord."""
    parts = urllib.parse.urlsplit(link)
    query = urllib.parse.parse_qsl(parts.query)
    query += [("utm_source", "discord"), ("utm_medium", "social"), ("utm_campaign", campaign)]
    return urllib.parse.urlunsplit(parts._replace(query=urllib.parse.urlencode(query)))


def parse_items(feed_xml):
    channel = ET.fromstring(feed_xml).find("channel")
    items = []
    for item in channel.findall("item"):
        link = (item.findtext("link") or "").strip()
        published = item.findtext("pubDate")
        items.append({
            "item": item,
            "guid": (item.findtext("guid") or link).strip(),
            "title": html.unescape((item.findtext("title") or "").strip()),
            "link": link,
            "published": email.utils.parsedate_to_datetime(published) if published else None,
            "categories": [c.text.strip() for c in item.findall("category") if c.text],
        })
    return items


def build_message(news, settings, role_id):
    link = with_utm(news["link"], settings.get("utm_campaign", "noticias"))
    category = news["categories"][0] if news["categories"] else None
    embed = {
        "title": news["title"][:256],
        "url": link,
        "description": plain_text(news["item"].findtext("description"), 300)
        + f"\n\n**[👉 Lee la noticia completa en pickandroll.tv]({link})**",
        "color": int(settings.get("color", "#a50044").lstrip("#"), 16),
        "footer": {"text": "PickandRollTV · " + category if category else "PickandRollTV"},
    }
    if news["published"]:
        embed["timestamp"] = news["published"].astimezone(datetime.timezone.utc).isoformat()
    image = find_image(news["item"], news["link"])
    if image:
        embed["image"] = {"url": image}
    message = {
        "username": settings.get("username", "PickandRollTV"),
        "content": (f"<@&{role_id}> " if role_id else "") + settings.get("intro", "🏀 **Nueva noticia en la web**"),
        "embeds": [embed],
        "allowed_mentions": {"roles": [role_id] if role_id else []},
    }
    if settings.get("avatar_url"):
        message["avatar_url"] = settings["avatar_url"]
    return message


def post(webhook, message):
    data = json.dumps(message).encode("utf-8")
    for attempt in range(3):
        request = urllib.request.Request(
            webhook + ("&" if "?" in webhook else "?") + "wait=true",
            data=data,
            headers={"Content-Type": "application/json", "User-Agent": USER_AGENT},
        )
        try:
            with urllib.request.urlopen(request, timeout=30):
                return
        except urllib.error.HTTPError as error:
            if error.code != 429 or attempt == 2:
                raise RuntimeError(f"Discord respondió {error.code}: {error.read()[:300]!r}") from error
            time.sleep(float(error.headers.get("Retry-After", "5")))


def main():
    webhook = os.environ.get("DISCORD_WEBHOOK", "").strip()
    if not webhook:
        print("Falta el secreto DISCORD_WEBHOOK: no se publica nada")
        return 0
    role_id = os.environ.get("DISCORD_ROLE_ID", "").strip() or None
    settings = json.loads(CONFIG_FILE.read_text(encoding="utf-8")).get("discord", {})
    items = parse_items(fetch(settings.get("feed_url", "https://pickandroll.tv/feed/")))

    first_run = not STATE_FILE.exists()
    published = [] if first_run else json.loads(STATE_FILE.read_text(encoding="utf-8"))
    seen = set(published)
    new = [news for news in items if news["guid"] not in seen]
    if first_run:
        print(f"Primera pasada: se apuntan {len(new)} noticias sin publicarlas")
        published = [news["guid"] for news in new]
        new = []

    # Las más antiguas primero, para que en Discord queden en orden.
    new.sort(key=lambda news: news["published"] or datetime.datetime.min.replace(tzinfo=datetime.timezone.utc))
    status = 0
    for news in new[-MAX_PER_RUN:]:
        try:
            post(webhook, build_message(news, settings, role_id))
            print(f"Publicada: {news['title']}")
        except Exception as error:
            print(f"No se pudo publicar {news['link']}: {error}", file=sys.stderr)
            status = 1
            break
        published.append(news["guid"])
        time.sleep(2)
    # Las que se saltan por pasar del máximo se dan por vistas.
    published += [news["guid"] for news in new[:-MAX_PER_RUN]]

    STATE_FILE.write_text(json.dumps(published[-MAX_REMEMBERED:], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return status


if __name__ == "__main__":
    sys.exit(main())
