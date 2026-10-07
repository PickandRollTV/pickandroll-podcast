#!/usr/bin/env python3
"""Abre en el foro 🏟️┃partidos un hilo para cada partido de Euroliga del Barça.

Cada hora:
  1. Mira el calendario oficial de la Euroliga. Si un partido del Barça empieza en
     las próximas 30 horas y aún no tiene hilo, lo abre con la hora, el pabellón y los
     enlaces a pickandroll.tv y a Twitch, mencionando al rol 🏀 Partidos.
  2. Si la web publica una noticia sobre ese rival (de 2 días antes a 1 día después
     del partido), la enlaza en el hilo: previas, crónicas y ruedas de prensa llevan a
     la web.
  3. Cuando el partido termina, publica el resultado final en el hilo.

El estado (qué hilos existen y qué se ha publicado en cada uno) se guarda en
discord_partidos.json para no repetir nada.

Variables de entorno:
  DISCORD_BOT_TOKEN   token del bot (secreto del repositorio)
"""
import datetime
import json
import os
import pathlib
import sys
import unicodedata
import urllib.request

from discord_web import with_utm

ROOT = pathlib.Path(__file__).resolve().parent
STATE_FILE = ROOT / "discord_partidos.json"
HISTORY_FILE = ROOT / "discord_historial.json"
ROLES_FILE = ROOT / "auditoria" / "roles-avisos.json"
CONFIG = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
GUILD = CONFIG["discord"]["guild_id"]
API = "https://discord.com/api/v10"
EUROLEAGUE = "https://api-live.euroleague.net/v2/competitions/E/seasons/E{year}/games?teamCode=BAR"
OPEN_BEFORE = datetime.timedelta(hours=30)
NEWS_BEFORE, NEWS_AFTER = datetime.timedelta(days=2), datetime.timedelta(days=1)
# Palabras que no sirven para reconocer al rival en un titular.
STOPWORDS = {"club", "basket", "basketball", "baloncesto", "armani", "olimpia", "real", "tel", "aviv", "kaunas",
             "piraeus", "athens", "belgrade", "istanbul", "munich", "paris", "monaco", "virtus", "segafredo", "bologna"}


def get_json(url, headers=None):
    request = urllib.request.Request(url, headers={"User-Agent": "PickandRollTV/1.0", **(headers or {})})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read())


def discord(method, path, token, body=None):
    request = urllib.request.Request(
        API + path, method=method, data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization": f"Bot {token}", "Content-Type": "application/json",
                 "User-Agent": "DiscordBot (https://pickandroll.tv, 1.0) PickandRollTV"})
    with urllib.request.urlopen(request, timeout=30) as response:
        raw = response.read()
        return json.loads(raw) if raw else {}


def plain(text):
    text = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in text if not unicodedata.combining(c))


def rival_keywords(rival):
    names = {rival.get("editorialName", ""), rival.get("abbreviatedName", ""), rival.get("name", "")}
    words = {w for name in names for w in plain(name).replace("-", " ").split() if len(w) >= 4}
    return sorted(words - STOPWORDS) or [plain(rival.get("abbreviatedName", ""))]


def season_year(now):
    return now.year if now.month >= 7 else now.year - 1


def main():
    token = os.environ.get("DISCORD_BOT_TOKEN", "").strip()
    if not token:
        print("Falta el secreto DISCORD_BOT_TOKEN")
        return 1
    now = datetime.datetime.now(datetime.timezone.utc)
    state = json.loads(STATE_FILE.read_text(encoding="utf-8")) if STATE_FILE.exists() else {}
    games = get_json(EUROLEAGUE.format(year=season_year(now))).get("data", [])
    history = json.loads(HISTORY_FILE.read_text(encoding="utf-8")) if HISTORY_FILE.exists() else []
    role_id = json.loads(ROLES_FILE.read_text(encoding="utf-8")).get("🏀 Partidos") if ROLES_FILE.exists() else None

    forum = None
    for game in games:
        start = datetime.datetime.fromisoformat(game["utcDate"].replace("Z", "+00:00"))
        key = game["identifier"]
        home = game["local"]["club"]["code"] == "BAR"
        rival = game["road" if home else "local"]["club"]
        entry = state.get(key)

        # 1. Abrir el hilo.
        if not entry and not game["played"] and now <= start <= now + OPEN_BEFORE:
            if forum is None:
                channels = discord("GET", f"/guilds/{GUILD}/channels", token)
                forum = next((c for c in channels if c["type"] == 15 and "partidos" in c["name"]), None)
                if not forum:
                    print("No encuentro el foro de partidos")
                    return 1
            tag = next((t["id"] for t in forum.get("available_tags", []) if t["name"] == "Euroliga"), None)
            local, road = game["local"]["club"]["abbreviatedName"], game["road"]["club"]["abbreviatedName"]
            ts = int(start.timestamp())
            web = with_utm(CONFIG["website_url"], "partidos")
            embed = {
                "title": f"{local} vs {road}",
                "description": (f"🏆 **Euroliga** · Jornada {game['round']}\n"
                                f"🕒 <t:{ts}:F> (<t:{ts}:R>)\n"
                                f"🏟️ {game['venue']['name'].title()}\n\n"
                                f"📰 **[Previa, crónica y toda la actualidad en pickandroll.tv]({web})**\n"
                                f"🔴 **[Lo vivimos en directo en Twitch]({CONFIG['twitch_url']})**"),
                "color": 0xA50044,
                "thumbnail": {"url": rival.get("images", {}).get("crest") or CONFIG["show"]["image"]},
                "footer": {"text": "Comenta el partido en este hilo · PickandRollTV"},
            }
            body = {
                "name": f"🏀 {local} vs {road} | Euroliga J{game['round']}"[:100],
                "message": {
                    "content": (f"<@&{role_id}> " if role_id else "") + "🔥 **¡Día de partido!** Aquí comentamos la previa, el directo y el postpartido.",
                    "embeds": [embed],
                    "allowed_mentions": {"roles": [role_id] if role_id else []},
                },
            }
            if tag:
                body["applied_tags"] = [tag]
            thread = discord("POST", f"/channels/{forum['id']}/threads", token, body)
            entry = state[key] = {"thread": thread["id"], "start": game["utcDate"], "rival": rival_keywords(rival),
                                  "news": [], "final": False}
            print(f"Hilo abierto: {body['name']}")
        if not entry:
            continue

        # 2. Noticias de la web sobre el rival.
        for news in history:
            published = datetime.datetime.fromisoformat(news["date"])
            title = plain(news["title"])
            if (news["link"] not in entry["news"] and start - NEWS_BEFORE <= published <= start + NEWS_AFTER
                    and any(word in title for word in entry["rival"])):
                link = with_utm(news["link"], "partidos")
                discord("POST", f"/channels/{entry['thread']}/messages", token, {
                    "content": f"📰 **En la web:** {news['title']}\n👉 <{link}>",
                    "embeds": [{"title": news["title"][:256], "url": link, "color": 0xA50044,
                                **({"image": {"url": news["image"]}} if news.get("image") else {})}],
                })
                entry["news"].append(news["link"])
                print(f"Noticia enlazada: {news['title']}")

        # 3. Resultado final.
        if game["played"] and not entry["final"]:
            local, road = game["local"], game["road"]
            won = (local if home else road)["score"] > (road if home else local)["score"]
            discord("POST", f"/channels/{entry['thread']}/messages", token, {
                "content": (f"🏁 **Final:** {local['club']['abbreviatedName']} **{local['score']}-{road['score']}** "
                            f"{road['club']['abbreviatedName']} {'💙❤️ ¡Victoria!' if won else '😔'}\n"
                            f"📰 La crónica y el análisis, en breve en <{with_utm(CONFIG['website_url'], 'partidos')}>"),
            })
            entry["final"] = True
            print(f"Resultado publicado: {key}")

    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
