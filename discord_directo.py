#!/usr/bin/env python3
"""Avisa en #anuncios de Discord cuando PickandRollTV empieza directo en Twitch.

Mira cada pocos minutos si el canal de Twitch está en directo (con decapi.me, que no
necesita claves) y, cuando pasa de apagado a encendido, publica un aviso con el bot
mencionando al rol 🔴 Directos. El estado se guarda en discord_directo.json para no
repetir el aviso durante el mismo directo.

Variables de entorno:
  DISCORD_BOT_TOKEN   token del bot (secreto del repositorio)
"""
import json
import os
import pathlib
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent
STATE = ROOT / "discord_directo.json"
ROLES_FILE = ROOT / "auditoria" / "roles-avisos.json"
API = "https://discord.com/api/v10"
CONFIG = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
CHANNEL = CONFIG["twitch_channel"]
GUILD = CONFIG["discord"]["guild_id"]
ANNOUNCE_NAME = "📢-anuncios"


def get_text(url):
    request = urllib.request.Request(url, headers={"User-Agent": "PickandRollTV/1.0"})
    with urllib.request.urlopen(request, timeout=20) as response:
        return response.read().decode("utf-8", "replace").strip()


def discord(method, path, token, body=None):
    request = urllib.request.Request(
        API + path, method=method, data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization": f"Bot {token}", "Content-Type": "application/json",
                 "User-Agent": "DiscordBot (https://pickandroll.tv, 1.0) PickandRollTV"})
    with urllib.request.urlopen(request, timeout=30) as response:
        raw = response.read()
        return json.loads(raw) if raw else {}


def live_info():
    """Devuelve (en_directo, título, juego). decapi responde 'X is offline' si no hay directo."""
    uptime = get_text(f"https://decapi.me/twitch/uptime/{CHANNEL}")
    if "offline" in uptime.lower() or "error" in uptime.lower() or not uptime:
        return False, "", ""
    title = get_text(f"https://decapi.me/twitch/title/{CHANNEL}")
    game = get_text(f"https://decapi.me/twitch/game/{CHANNEL}")
    return True, title, game


def main():
    token = os.environ.get("DISCORD_BOT_TOKEN", "").strip()
    if not token:
        print("Falta el secreto DISCORD_BOT_TOKEN")
        return 1
    state = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {"en_directo": False}
    try:
        live, title, game = live_info()
    except (urllib.error.URLError, TimeoutError) as error:
        print(f"No he podido mirar Twitch: {error}")
        return 0
    print("En directo" if live else "Sin directo")

    if live and not state.get("en_directo"):
        channels = discord("GET", f"/guilds/{GUILD}/channels", token)
        target = next((c for c in channels if c["name"] == ANNOUNCE_NAME), None)
        if not target:
            print(f"No encuentro el canal {ANNOUNCE_NAME}")
            return 1
        role_id = json.loads(ROLES_FILE.read_text(encoding="utf-8")).get("🔴 Directos") if ROLES_FILE.exists() else None
        url = f"https://www.twitch.tv/{CHANNEL}"
        discord("POST", f"/channels/{target['id']}/messages", token, {
            "content": (f"<@&{role_id}> " if role_id else "") + f"🔴 **¡Estamos en directo!**\n### {title or 'PickandRollTV'}\n👉 Entra ya: <{url}>",
            "allowed_mentions": {"roles": [role_id] if role_id else []},
            "embeds": [{
                "title": title or "PickandRollTV en directo", "url": url, "color": 0xE91916,
                "description": f"Jugando a **{game}**" if game else "Directo en Twitch",
                "image": {"url": f"https://static-cdn.jtvnw.net/previews-ttv/live_user_{CHANNEL}-1280x720.jpg?t={int(time.time())}"},
            }],
        })
        print("Aviso publicado en #anuncios")

    if live != bool(state.get("en_directo")):
        STATE.write_text(json.dumps({"en_directo": live}) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
