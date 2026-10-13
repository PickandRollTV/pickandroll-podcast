#!/usr/bin/env python3
"""Publica en #anuncios el resumen semanal de noticias de pickandroll.tv.

Lee las noticias publicadas en Discord durante los últimos 7 días (discord_historial.json,
que rellena discord_web.py) y publica con el bot una tarjeta con todas ellas enlazadas
a la web, con etiquetas UTM para medir las visitas en las estadísticas de la web.

Variables de entorno:
  DISCORD_BOT_TOKEN   token del bot (secreto del repositorio)
"""
import datetime
import json
import os
import pathlib
import re
import sys
import urllib.request

from discord_web import with_utm

ROOT = pathlib.Path(__file__).resolve().parent
HISTORY_FILE = ROOT / "discord_historial.json"
ROLES_FILE = ROOT / "auditoria" / "roles-avisos.json"
CONFIG = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
GUILD = CONFIG["discord"]["guild_id"]
API = "https://discord.com/api/v10"
MAX_ITEMS = 12


def discord(method, path, token, body=None):
    request = urllib.request.Request(
        API + path, method=method, data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization": f"Bot {token}", "Content-Type": "application/json",
                 "User-Agent": "DiscordBot (https://pickandroll.tv, 1.0) PickandRollTV"})
    with urllib.request.urlopen(request, timeout=30) as response:
        raw = response.read()
        return json.loads(raw) if raw else {}


def main():
    token = os.environ.get("DISCORD_BOT_TOKEN", "").strip()
    if not token:
        print("Falta el secreto DISCORD_BOT_TOKEN")
        return 1
    history = json.loads(HISTORY_FILE.read_text(encoding="utf-8")) if HISTORY_FILE.exists() else []
    since = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=7)
    week = [n for n in history if datetime.datetime.fromisoformat(n["date"]) >= since]
    if not week:
        print("No hay noticias esta semana: no se publica resumen")
        return 0
    week.sort(key=lambda n: n["date"], reverse=True)

    lines = [f"**{i}.** [{n['title']}]({with_utm(n['link'], 'resumen-semanal')})" for i, n in enumerate(week[:MAX_ITEMS], 1)]
    if len(week) > MAX_ITEMS:
        lines.append(f"…y {len(week) - MAX_ITEMS} más en la web")
    description = "\n".join(lines)
    while len(description) > 3900:
        lines.pop(-1)
        description = "\n".join(lines)
    site = with_utm(CONFIG["website_url"], "resumen-semanal")
    embed = {
        "title": "📰 Lo mejor de la semana en pickandroll.tv",
        "url": site,
        "description": description + f"\n\n**[👉 Todas las noticias en pickandroll.tv]({site})**",
        "color": 0xA50044,
        "footer": {"text": f"PickandRollTV · {len(week)} noticias esta semana"},
    }
    if week[0].get("image"):
        embed["image"] = {"url": week[0]["image"]}

    channels = discord("GET", f"/guilds/{GUILD}/channels", token)
    target = next((c for c in channels if "anuncios" in c["name"] and c["type"] in (0, 5)), None)
    if not target:
        print("No encuentro el canal de anuncios")
        return 1
    role_id = json.loads(ROLES_FILE.read_text(encoding="utf-8")).get("📰 Noticias web") if ROLES_FILE.exists() else None
    # Todo en texto (con <> para no generar una vista previa por enlace), y la imagen aparte.
    text = re.sub(r"\]\((https?://[^)\s>]+)\)", r"](<\1>)", f"## {embed['title']}\n{embed['description']}")
    content = (f"<@&{role_id}> " if role_id else "") + "🗞️ **El resumen de la semana ya está aquí.** ¿Te perdiste alguna?\n" + text
    while len(content) > 2000 and len(lines) > 1:
        lines.pop(-1)
        text = re.sub(r"\]\((https?://[^)\s>]+)\)", r"](<\1>)", f"## {embed['title']}\n" + "\n".join(lines)
                      + f"\n\n**[👉 Todas las noticias en pickandroll.tv]({site})**")
        content = (f"<@&{role_id}> " if role_id else "") + "🗞️ **El resumen de la semana ya está aquí.** ¿Te perdiste alguna?\n" + text
    discord("POST", f"/channels/{target['id']}/messages", token, {
        "content": content,
        "embeds": [{"image": embed["image"], "color": 0xA50044}] if embed.get("image") else [],
        "allowed_mentions": {"roles": [role_id] if role_id else []},
    })
    print(f"Resumen publicado con {len(week)} noticias")
    return 0


if __name__ == "__main__":
    sys.exit(main())
