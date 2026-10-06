#!/usr/bin/env python3
"""Importa (una sola vez) los episodios que ya están en Spotify for Creators.

Lee el RSS actual del podcast, vuelve a alojar cada audio como release de GitHub
y conserva el guid original de cada episodio, para que al redirigir el feed
Spotify reconozca los episodios antiguos en lugar de duplicarlos.

Uso:  python import_spotify.py https://anchor.fm/s/XXXXXXXX/podcast/rss
"""
import email.utils
import pathlib
import sys
import tempfile
import urllib.request
import xml.etree.ElementTree as ET

from feed import ITUNES, write_feed
from podcast import CONFIG_FILE, EPISODES_FILE, FEED_FILE, ROOT, load_json, save_json, upload_audio

USER_AGENT = {"User-Agent": "pickandroll-podcast-import/1.0"}


def fetch(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=USER_AGENT), timeout=120) as response:
        return response.read()


def duration_to_seconds(value):
    """itunes:duration puede venir como '3600', '59:59' o '1:02:03'."""
    if not value:
        return 0
    seconds = 0
    for part in value.strip().split(":"):
        seconds = seconds * 60 + int(float(part))
    return seconds


def main(feed_url):
    config = load_json(CONFIG_FILE, {})
    episodes = load_json(EPISODES_FILE, [])
    known = {e["guid"] for e in episodes}
    channel = ET.fromstring(fetch(feed_url)).find("channel")

    # Portada del podcast: la copiamos a docs/ para no depender del CDN antiguo.
    image = channel.find(f"{{{ITUNES}}}image")
    if image is not None:
        (ROOT / "docs").mkdir(exist_ok=True)
        (ROOT / "docs" / "cover.jpg").write_bytes(fetch(image.get("href")))
        print("Portada copiada a docs/cover.jpg")

    items = channel.findall("item")
    for index, item in enumerate(reversed(items), start=1):
        guid = item.findtext("guid")
        title = item.findtext("title")
        if guid in known:
            continue
        enclosure = item.find("enclosure")
        print(f"[{index}/{len(items)}] {title}")
        with tempfile.TemporaryDirectory() as tmp:
            audio = pathlib.Path(tmp) / f"episodio-{index:03d}.mp3"
            audio.write_bytes(fetch(enclosure.get("url")))
            url = upload_audio(f"import-{index:03d}", title, audio)
            size = audio.stat().st_size
        episode_image = item.find(f"{{{ITUNES}}}image")
        episodes.append({
            "guid": guid,
            "source": "spotify-import",
            "title": title,
            "description": item.findtext("description") or "",
            "published": _iso(item.findtext("pubDate")),
            "duration": duration_to_seconds(item.findtext(f"{{{ITUNES}}}duration")),
            "image": episode_image.get("href") if episode_image is not None else None,
            "link": item.findtext("link"),
            "audio_url": url,
            "audio_bytes": size,
            "audio_type": enclosure.get("type") or "audio/mpeg",
        })
        save_json(EPISODES_FILE, episodes)

    write_feed(config, episodes, FEED_FILE)
    print(f"Listo: {len(episodes)} episodios en el feed")


def _iso(rfc2822):
    return email.utils.parsedate_to_datetime(rfc2822).isoformat()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(sys.argv[1])
