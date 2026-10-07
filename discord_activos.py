#!/usr/bin/env python3
"""Da el rol 🔥 Top del mes a los miembros que más han participado en los últimos 30 días.

Cuenta los mensajes de cada miembro en los canales de texto de la categoría PickandRoll
(sin bots), da el rol a los TOP_N primeros, se lo quita a quien ya no está y lo anuncia
en 💬┃general sin notificar a nadie. No guarda nombres en el repositorio.

Variables de entorno:
  DISCORD_BOT_TOKEN   token del bot (secreto del repositorio)
"""
import collections
import datetime
import json
import os
import pathlib
import sys
import time
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent
GUILD = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))["discord"]["guild_id"]
API = "https://discord.com/api/v10"
ROLE_NAME = "🔥 Top del mes"
TOP_N = 5
DAYS = 30
DISCORD_EPOCH = 1420070400000


def discord(method, path, token, body=None):
    for _ in range(6):
        request = urllib.request.Request(
            API + path, method=method, data=json.dumps(body).encode() if body is not None else None,
            headers={"Authorization": f"Bot {token}", "Content-Type": "application/json",
                     "User-Agent": "DiscordBot (https://pickandroll.tv, 1.0) PickandRollTV",
                     "X-Audit-Log-Reason": "Top del mes PickandRollTV"})
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                raw = response.read()
                time.sleep(0.4)
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as error:
            if error.code == 429:
                time.sleep(float(json.loads(error.read() or b"{}").get("retry_after", 2)) + 0.5)
                continue
            raise
    raise RuntimeError(f"{method} {path}: demasiados reintentos")


def snowflake(when):
    return str(int(when.timestamp() * 1000 - DISCORD_EPOCH) << 22)


def count_messages(token, channel_id, since):
    counts = collections.Counter()
    after = snowflake(since)
    while True:
        batch = discord("GET", f"/channels/{channel_id}/messages?limit=100&after={after}", token)
        if not batch:
            return counts
        for message in batch:
            if not message["author"].get("bot") and message.get("type") in (0, 19):
                counts[message["author"]["id"]] += 1
        after = max(batch, key=lambda m: int(m["id"]))["id"]


def main():
    token = os.environ.get("DISCORD_BOT_TOKEN", "").strip()
    if not token:
        print("Falta el secreto DISCORD_BOT_TOKEN")
        return 1
    since = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=DAYS)
    channels = discord("GET", f"/guilds/{GUILD}/channels", token)
    category = next((c for c in channels if c["type"] == 4 and ("PICKANDROLL" in c["name"].upper() or "𝗣𝗜𝗖𝗞𝗔𝗡𝗗𝗥𝗢𝗟𝗟" in c["name"])), None)
    text = [c for c in channels if c["type"] in (0, 5) and category and c.get("parent_id") == category["id"]]
    counts = collections.Counter()
    for channel in text:
        try:
            counts += count_messages(token, channel["id"], since)
        except urllib.error.HTTPError as error:
            print(f"No puedo leer {channel['name']}: {error.code}")
    top = [user for user, _ in counts.most_common(TOP_N)]
    print(f"{len(counts)} miembros han escrito en {len(text)} canales; top {len(top)}")

    roles = discord("GET", f"/guilds/{GUILD}/roles", token)
    role = next((r for r in roles if r["name"] == ROLE_NAME), None)
    if not role:
        role = discord("POST", f"/guilds/{GUILD}/roles", token,
                       {"name": ROLE_NAME, "color": 0xFF7A00, "hoist": True, "permissions": "0"})
    holders, after = [], "0"
    while True:
        members = discord("GET", f"/guilds/{GUILD}/members?limit=1000&after={after}", token)
        if not members:
            break
        holders += [m["user"]["id"] for m in members if role["id"] in m["roles"]]
        after = members[-1]["user"]["id"]
        if len(members) < 1000:
            break
    for user in holders:
        if user not in top:
            discord("DELETE", f"/guilds/{GUILD}/members/{user}/roles/{role['id']}", token)
    for user in top:
        if user not in holders:
            discord("PUT", f"/guilds/{GUILD}/members/{user}/roles/{role['id']}", token)

    general = next((c for c in text if "general" in c["name"]), None)
    if general and top:
        medals = ["🥇", "🥈", "🥉", "🏅", "🏅"]
        lines = "\n".join(f"{medals[i]} <@{user}> · {counts[user]} mensajes" for i, user in enumerate(top))
        discord("POST", f"/channels/{general['id']}/messages", token, {
            "embeds": [{"title": f"{ROLE_NAME}: los que más han dado vida al servidor",
                        "description": lines + "\n\n¡Gracias! Lleváis el rol durante todo el mes. El mes que viene, ¿quién se lo lleva?",
                        "color": 0xFF7A00}],
            "allowed_mentions": {"parse": []},
        })
    return 0


if __name__ == "__main__":
    sys.exit(main())
