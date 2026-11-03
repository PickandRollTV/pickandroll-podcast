#!/usr/bin/env python3
"""Reacciona a lo que escriben los miembros en Discord y avisa al dueño cuando le preguntan algo.

Cada pocos minutos repasa los mensajes recientes de los canales de texto y de los hilos abiertos:
  - Pone una reacción según el contenido: 👀 a preguntas y críticas (para pensarlo), 😂 a las risas,
    🔥 a las celebraciones, ❤️ a los agradecimientos y 👍 al resto.
  - Si el mensaje va dirigido al dueño del servidor (lo menciona, le responde, menciona al bot o
    pregunta por PickandRollTV), se lo manda por mensaje privado con el enlace.
La propia reacción del bot marca el mensaje como visto, así que no hace falta guardar estado y
nunca se reacciona ni se avisa dos veces. Los canales de voz (Parquet incluido) no se tocan.

Variables de entorno:
  DISCORD_BOT_TOKEN   token del bot (secreto del repositorio)
"""
import datetime
import json
import os
import pathlib
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent
API = "https://discord.com/api/v10"
CONFIG = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
GUILD = CONFIG["discord"]["guild_id"]
LOOKBACK = datetime.timedelta(hours=3)
SKIP_CATEGORIES = ("archivo",)

RULES = [  # (emoji, palabras); gana la primera que encaje
    ("😂", r"\b(ja(ja)+|je(je)+|xd+|lol|jaj)\b|😂|🤣"),
    ("🔥", r"\b(ganamos|ganado|victoria|vamos|visca|golazo|triple|canastas?|tapon|mate|brutal|bestia|crack|"
           r"partidazo|remontada|campeon|campeones|increible|espectacular)\b|🔥|💪|🏆"),
    ("❤️", r"\b(gracias|grax|merci|thanks|os quiero|te quiero|grande|enhorabuena)\b|❤️|♥️|🙏"),
    ("👀", r"\b(mal|fatal|horrible|desastre|verguenza|perdemos|perdido|derrota|arbitro|arbitraje|"
           r"injusto|problema|preocupa|deberia|habria que|no entiendo|por que)\b"),
]
OWNER_HINTS = r"\b(pickandroll\w*|pick and roll|jaume|directos?|stream|twitch|youtube|podcast|la web|canal)\b"


def normalize(text):
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()


def pick_emoji(text):
    plain = normalize(text)
    if "?" in text:
        return "👀"
    for emoji, pattern in RULES:
        if re.search(pattern, plain) or re.search(pattern, text):
            return emoji
    return "👍"


def discord(method, path, token, body=None):
    for _ in range(5):
        request = urllib.request.Request(
            API + path, method=method, data=json.dumps(body).encode() if body is not None else None,
            headers={"Authorization": f"Bot {token}", "Content-Type": "application/json",
                     "User-Agent": "DiscordBot (https://pickandroll.tv, 1.0) PickandRollTV"})
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                raw = response.read()
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as error:
            if error.code == 429:
                time.sleep(float(json.loads(error.read() or b"{}").get("retry_after", 2)) + 0.5)
                continue
            raise
    raise RuntimeError(f"{method} {path}: demasiados reintentos")


def is_for_owner(message, owner_id, bot_id):
    mentioned = {u["id"] for u in message.get("mentions", [])}
    replied = (message.get("referenced_message") or {}).get("author", {}).get("id")
    if owner_id in mentioned or bot_id in mentioned or replied in (owner_id, bot_id):
        return True
    return "?" in message["content"] and bool(re.search(OWNER_HINTS, normalize(message["content"])))


def main():
    token = os.environ.get("DISCORD_BOT_TOKEN", "").strip()
    if not token:
        print("Falta el secreto DISCORD_BOT_TOKEN")
        return 1
    owner_id = discord("GET", f"/guilds/{GUILD}", token)["owner_id"]
    bot_id = discord("GET", "/users/@me", token)["id"]
    channels = discord("GET", f"/guilds/{GUILD}/channels", token)
    names = {c["id"]: c["name"] for c in channels}
    skipped = {c["id"] for c in channels if c["type"] == 4 and any(s in normalize(c["name"]) for s in SKIP_CATEGORIES)}
    # Solo canales de texto y anuncios: los de voz (Parquet incluido) quedan fuera.
    targets = [c for c in channels if c["type"] in (0, 5) and c.get("parent_id") not in skipped]
    targets += [t for t in discord("GET", f"/guilds/{GUILD}/threads/active", token).get("threads", [])
                if t.get("parent_id") in {c["id"] for c in channels if c.get("parent_id") not in skipped}]
    since = datetime.datetime.now(datetime.timezone.utc) - LOOKBACK
    dm_channel = None
    reacted = notified = 0
    for channel in targets:
        try:
            messages = discord("GET", f"/channels/{channel['id']}/messages?limit=50", token)
        except urllib.error.HTTPError as error:
            print(f"No puedo leer {channel.get('name')}: {error.code}")
            continue
        for message in reversed(messages):
            if message["author"].get("bot") or message.get("type") not in (0, 19) or message["author"]["id"] == owner_id:
                continue
            if datetime.datetime.fromisoformat(message["timestamp"]) < since:
                continue
            if any(r.get("me") for r in message.get("reactions", [])):
                continue  # ya lo vimos en una pasada anterior
            link = f"https://discord.com/channels/{GUILD}/{channel['id']}/{message['id']}"
            # Primero la reacción: es la marca de "visto", así un fallo nunca repite el aviso.
            try:
                discord("PUT", f"/channels/{channel['id']}/messages/{message['id']}/reactions/"
                               f"{urllib.parse.quote(pick_emoji(message['content']))}/@me", token)
            except urllib.error.HTTPError as error:
                print(f"No puedo reaccionar en {channel.get('name')}: {error.code}")
                continue
            reacted += 1
            if is_for_owner(message, owner_id, bot_id):
                dm_channel = dm_channel or discord("POST", "/users/@me/channels", token, {"recipient_id": owner_id})
                where = names.get(channel["id"]) or channel.get("name", "")
                discord("POST", f"/channels/{dm_channel['id']}/messages", token, {
                    "content": f"❓ **Te han preguntado algo en {where}**\n> {message['content'][:1500]}\n👉 Responder: <{link}>",
                    "allowed_mentions": {"parse": []}})
                notified += 1
            time.sleep(0.3)
    print(f"Reacciones: {reacted} · Avisos al dueño: {notified}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
