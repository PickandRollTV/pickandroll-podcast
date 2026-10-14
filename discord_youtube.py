#!/usr/bin/env python3
"""Comparte en Discord los Shorts nuevos y el directo completo cuando termina.

Lee el RSS del canal de YouTube cada pocos minutos:
  - Shorts nuevos → 📱┃shorts (el canal se crea solo la primera vez, en 📌 INICIO y de solo lectura).
  - Directo terminado ("EN DIRECTO" en el título, ya emitido y con visitas) → 📢┃anuncios
    ("¿Te lo perdiste?") y, si hay un hilo de ese partido en 🏟️┃partidos, también dentro del hilo.
El estado se guarda en discord_youtube.json. La primera pasada solo apunta lo que ya hay.

Variables de entorno:
  DISCORD_BOT_TOKEN   token del bot (secreto del repositorio)
"""
import datetime
import json
import os
import pathlib
import sys
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET

from discord_web import with_utm

ROOT = pathlib.Path(__file__).resolve().parent
STATE_FILE = ROOT / "discord_youtube.json"
LIVE_FILE = ROOT / "discord_directo.json"
MATCHES_FILE = ROOT / "discord_partidos.json"
CONFIG = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
GUILD = CONFIG["discord"]["guild_id"]
FEED = f"https://www.youtube.com/feeds/videos.xml?channel_id={CONFIG['youtube_channel_id']}"
API = "https://discord.com/api/v10"
SHORTS_CHANNEL = ("📱┃shorts", "Los Shorts de PickandRollTV en cuanto salen en YouTube.")
NS = {"a": "http://www.w3.org/2005/Atom", "yt": "http://www.youtube.com/xml/schemas/2015",
      "media": "http://search.yahoo.com/mrss/"}
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/126 Safari/537.36"


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def discord(method, path, token, body=None):
    request = urllib.request.Request(
        API + path, method=method, data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization": f"Bot {token}", "Content-Type": "application/json",
                 "User-Agent": "DiscordBot (https://pickandroll.tv, 1.0) PickandRollTV"})
    with urllib.request.urlopen(request, timeout=30) as response:
        raw = response.read()
        return json.loads(raw) if raw else {}


def videos():
    request = urllib.request.Request(FEED, headers={"User-Agent": UA})
    root = ET.fromstring(urllib.request.urlopen(request, timeout=30).read())
    items = []
    for entry in root.findall("a:entry", NS):
        stats = entry.find("media:group/media:community/media:statistics", NS)
        items.append({
            "id": entry.findtext("yt:videoId", namespaces=NS),
            "title": entry.findtext("a:title", namespaces=NS) or "",
            "published": datetime.datetime.fromisoformat(entry.findtext("a:published", namespaces=NS)),
            "link": entry.find("a:link", NS).get("href", ""),
            "views": int(stats.get("views", "0")) if stats is not None else 0,
        })
    return items


def is_short(video):
    """YouTube responde 200 en /shorts/ID si es un Short, y redirige a /watch si no lo es."""
    if "/shorts/" in video["link"]:
        return True
    opener = urllib.request.build_opener(NoRedirect)
    try:
        opener.open(urllib.request.Request(f"https://www.youtube.com/shorts/{video['id']}", method="HEAD",
                                           headers={"User-Agent": UA}), timeout=20)
        return True
    except urllib.error.HTTPError as error:
        if error.code in (301, 302, 303, 307, 308, 404):
            return False
        raise


def share_video(video, state, ctx):
    """Publica un vídeo nuevo si toca. Devuelve True si queda resuelto (publicado o descartado)."""
    url = f"https://www.youtube.com/watch?v={video['id']}"
    token, channel, live, last_end, now, first_run = (ctx[k] for k in ("token", "channel", "live", "last_end", "now", "first_run"))
    if "en directo" in video["title"].lower():
        # Solo cuando ya no estamos en directo y el vídeo tiene visitas. Vale tanto para la emisión que
        # YouTube guarda sola como para la grabación que se sube después (publicada tras el fin del directo).
        if live.get("en_directo") or video["views"] <= 0:
            return False
        # Se marca antes de publicar: si algo falla a medias, no se repite en la siguiente pasada.
        state["directos"].append(video["id"])
        state["vistos"].append(video["id"])
        ctx["save"]()
        if not first_run and now - video["published"] < datetime.timedelta(days=2):
            message = {"content": f"📺 **¿Te lo perdiste?** El directo completo ya está en YouTube:\n### {video['title']}\n{url}\n📰 La crónica y el análisis, en <{with_utm(CONFIG['website_url'], 'directo-completo')}>"}
            targets = [channel(lambda c: "anuncios" in c["name"] and c["type"] in (0, 5)),
                       channel(lambda c: "general" in c["name"] and c["type"] == 0)]
            matches = json.loads(MATCHES_FILE.read_text(encoding="utf-8")) if MATCHES_FILE.exists() else {}
            targets += [{"id": e["thread"]} for k, e in matches.items() if not k.startswith("_")
                        and abs(datetime.datetime.fromisoformat(e["start"]) - video["published"]) < datetime.timedelta(hours=12)]
            for target in filter(None, targets):
                try:
                    discord("POST", f"/channels/{target['id']}/messages", token, message)
                except Exception as error:
                    print(f"No se pudo publicar el directo en {target['id']}: {error}")
            print(f"Directo compartido: {video['title']}")
        return True
    if not is_short(video):
        state["vistos"].append(video["id"])
        return True
    state["shorts"].append(video["id"])
    state["vistos"].append(video["id"])
    ctx["save"]()
    if not first_run:
        target = channel(lambda c: c["name"] == SHORTS_CHANNEL[0])
        if not target:
            news = channel(lambda c: "noticias-web" in c["name"])
            target = discord("POST", f"/guilds/{GUILD}/channels", token, {
                "name": SHORTS_CHANNEL[0], "type": 0, "topic": SHORTS_CHANNEL[1],
                "parent_id": news.get("parent_id") if news else None,
                "position": (news or {}).get("position", 0) + 1,
                "permission_overwrites": (news or {}).get("permission_overwrites", []),
            })
            ctx["channels"].append(target)
        short = f"https://www.youtube.com/shorts/{video['id']}"
        discord("POST", f"/channels/{target['id']}/messages", token,
                {"content": f"📱 **Nuevo Short:** {video['title']}\n{short}\n🌐 Toda la actualidad del Barça en <{with_utm(CONFIG['website_url'], 'shorts')}>"})
        print(f"Short compartido: {video['title']}")
    return True


def main():
    token = os.environ.get("DISCORD_BOT_TOKEN", "").strip()
    if not token:
        print("Falta el secreto DISCORD_BOT_TOKEN")
        return 1
    first_run = not STATE_FILE.exists()
    state = json.loads(STATE_FILE.read_text(encoding="utf-8")) if not first_run else {"shorts": [], "directos": [], "vistos": []}

    def save():
        for key in ("shorts", "directos", "vistos"):
            state[key] = state[key][-300:]
        STATE_FILE.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")

    def note_error(message):
        # Se guarda el último fallo para poder revisarlo; no se marca la ejecución como fallida.
        print(message)
        state["ultimo_error"] = f"{datetime.datetime.now(datetime.timezone.utc):%Y-%m-%d %H:%M} {message[:200]}"

    try:
        items = videos()
    except Exception as error:
        # YouTube falla a ratos desde los servidores de GitHub: se reintenta en la siguiente pasada.
        note_error(f"No se pudo leer el feed de YouTube: {error}")
        if not first_run:
            save()
        return 0
    live = json.loads(LIVE_FILE.read_text(encoding="utf-8")) if LIVE_FILE.exists() else {}
    ctx = {"token": token, "live": live, "first_run": first_run, "save": save, "channels": [],
           "last_end": datetime.datetime.fromisoformat(live["ultimo_fin"]) if live.get("ultimo_fin") else None,
           "now": datetime.datetime.now(datetime.timezone.utc)}

    def channel(match):
        if not ctx["channels"]:
            ctx["channels"] = discord("GET", f"/guilds/{GUILD}/channels", token)
        return next((c for c in ctx["channels"] if match(c)), None)
    ctx["channel"] = channel

    for video in sorted(items, key=lambda v: v["published"]):
        if video["id"] in state["vistos"]:
            continue
        try:
            share_video(video, state, ctx)
        except Exception as error:
            note_error(f"No se pudo compartir {video['id']}: {error}")
    save()
    return 0


if __name__ == "__main__":
    sys.exit(main())
