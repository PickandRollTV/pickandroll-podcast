#!/usr/bin/env python3
"""Abre en el foro 🏟️┃partidos un hilo para cada partido del Barça (Euroliga, Liga Endesa, Copa...).

Cada hora:
  1. Lee el calendario oficial del club (fcbarcelona.es). Si un partido empieza en
     las próximas 30 horas y aún no tiene hilo, lo abre con la hora, el pabellón y los
     enlaces a pickandroll.tv y a Twitch, mencionando al rol 🏀 Partidos.
  2. Si la web publica una noticia sobre ese rival (de 2 días antes a 1 día después
     del partido), la enlaza en el hilo: previas, crónicas y ruedas de prensa llevan a
     la web.
  3. Cuando el partido termina, lo cierra en el hilo con el resultado (en la Euroliga
     lo coge de su web oficial) e invita a leer la crónica en pickandroll.tv.

El estado (qué hilos existen y qué se ha publicado en cada uno) se guarda en
discord_partidos.json para no repetir nada.

Variables de entorno:
  DISCORD_BOT_TOKEN   token del bot (secreto del repositorio)
"""
import datetime
import html as htmllib
import json
import os
import pathlib
import sys
import re
import unicodedata
import urllib.request
import zoneinfo

from discord_web import with_utm

ROOT = pathlib.Path(__file__).resolve().parent
STATE_FILE = ROOT / "discord_partidos.json"
HISTORY_FILE = ROOT / "discord_historial.json"
ROLES_FILE = ROOT / "auditoria" / "roles-avisos.json"
CONFIG = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
GUILD = CONFIG["discord"]["guild_id"]
API = "https://discord.com/api/v10"
CALENDAR = "https://www.fcbarcelona.es/es/baloncesto/primer-equipo/calendario"
EUROLEAGUE = "https://api-live.euroleague.net/v2/competitions/E/seasons/E{year}/games?teamCode=BAR"
BADGE = "https://resources.fcbarcelona.pulselive.com/badges/bas/40/t{team}@x2.png"
# Códigos de competición del calendario del club (los demás salen como "Partido").
COMPETITIONS = {"6201": "Euroliga", "6200": "Liga Endesa"}
MADRID = zoneinfo.ZoneInfo("Europe/Madrid")
OPEN_BEFORE = datetime.timedelta(hours=30)
GAME_LENGTH = datetime.timedelta(hours=2, minutes=15)
NEWS_BEFORE, NEWS_AFTER = datetime.timedelta(days=2), datetime.timedelta(days=1)
# Palabras que no sirven para reconocer al rival en un titular.
STOPWORDS = {"club", "basket", "basketball", "baloncesto", "armani", "olimpia", "real", "tel", "aviv", "kaunas",
             "piraeus", "athens", "belgrade", "istanbul", "munich", "paris", "monaco", "virtus", "segafredo", "bologna"}


def get(url):
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/126 Safari/537.36",
                                                   "Accept-Language": "es-ES,es;q=0.9"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read().decode("utf-8", "replace")


def club_fixtures():
    """Partidos del calendario de fcbarcelona.es: id, competición, inicio (UTC), equipos y pabellón."""
    page = get(CALENDAR)
    fixtures = []
    for block in re.findall(r'<li class="fixture-result-list__fixture[^"]*"(.*?)</li>', page, re.S):
        attr = lambda name: (re.search(name + r'="([^"]*)"', block) or [None, ""])[1]
        text = lambda cls: htmllib.unescape(re.sub(r"\s+", " ", (re.search(r'class="' + cls + r'"[^>]*>(.*?)</div>', block, re.S) or [None, ""])[1]).strip())
        date, time_ = attr("data-date"), attr("data-time")
        if not date or not re.match(r"\d\d:\d\d", time_ or ""):
            continue
        start = datetime.datetime.fromisoformat(f"{date}T{time_}").replace(tzinfo=MADRID).astimezone(datetime.timezone.utc)
        competition = (re.search(r'visually-hidden">([\d.]+)<', block) or [None, ""])[1].replace(".", "")
        fixtures.append({
            "key": f"{attr('data-comp-season-id')}-{attr('data-fixture-id')}",
            "competition": COMPETITIONS.get(competition, "Partido"),
            "start": start,
            "home": text("fixture-info__name fixture-info__name--home"),
            "away": text("fixture-info__name fixture-info__name--away"),
            "home_id": attr("data-home-team"), "away_id": attr("data-away-team"),
            "venue": text("fixture-result-list__stage-location"),
        })
    return fixtures


def euroleague_score(start):
    """Resultado del partido de Euroliga que empezó a esa hora, si ya ha terminado."""
    try:
        games = json.loads(get(EUROLEAGUE.format(year=season_year(start)))).get("data", [])
    except Exception as error:
        print(f"No he podido leer la Euroliga: {error}")
        return None
    for game in games:
        when = datetime.datetime.fromisoformat(game["utcDate"].replace("Z", "+00:00"))
        if abs(when - start) < datetime.timedelta(hours=3) and game["played"]:
            return f"{game['local']['club']['abbreviatedName']} **{game['local']['score']}-{game['road']['score']}** {game['road']['club']['abbreviatedName']}"
    return None


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


def rival_keywords(name):
    words = {w for w in plain(name).replace("-", " ").split() if len(w) >= 4}
    return sorted(words - STOPWORDS) or [plain(name)]


def is_matchday(news):
    """Las entradas "DIA DE PARTIT" / "MATCHDAY" de la web (por el enlace o el titular)."""
    title = plain(news["title"])
    return "dia-de-partit" in news["link"] or "dia de partit" in title or "matchday" in title


def season_year(now):
    return now.year if now.month >= 7 else now.year - 1


def main():
    token = os.environ.get("DISCORD_BOT_TOKEN", "").strip()
    if not token:
        print("Falta el secreto DISCORD_BOT_TOKEN")
        return 1
    now = datetime.datetime.now(datetime.timezone.utc)
    state = json.loads(STATE_FILE.read_text(encoding="utf-8")) if STATE_FILE.exists() else {}
    history = json.loads(HISTORY_FILE.read_text(encoding="utf-8")) if HISTORY_FILE.exists() else []
    role_id = json.loads(ROLES_FILE.read_text(encoding="utf-8")).get("🏀 Partidos") if ROLES_FILE.exists() else None

    forum = None
    for game in club_fixtures():
        start, key = game["start"], game["key"]
        home = plain(game["home"]).startswith("barca")
        rival = game["away"] if home else game["home"]
        entry = state.get(key)

        # 1. Abrir el hilo.
        if not entry and now <= start <= now + OPEN_BEFORE:
            if forum is None:
                channels = discord("GET", f"/guilds/{GUILD}/channels", token)
                forum = next((c for c in channels if c["type"] == 15 and "partidos" in c["name"]), None)
                if not forum:
                    print("No encuentro el foro de partidos")
                    return 1
            tag = next((t["id"] for t in forum.get("available_tags", []) if t["name"] == game["competition"]), None)
            ts = int(start.timestamp())
            web = with_utm(CONFIG["website_url"], "partidos")
            embed = {
                "title": f"{game['home']} vs {game['away']}",
                "description": (f"🏆 **{game['competition']}**\n"
                                f"🕒 <t:{ts}:F> (<t:{ts}:R>)\n"
                                + (f"🏟️ {game['venue']}\n" if game["venue"] else "")
                                + f"\n📰 **[Previa, crónica y toda la actualidad en pickandroll.tv]({web})**\n"
                                f"🔴 **[Lo vivimos en directo en Twitch]({CONFIG['twitch_url']})**"),
                "color": 0xA50044,
                "thumbnail": {"url": BADGE.format(team=game["away_id"] if home else game["home_id"])},
                "footer": {"text": "Comenta el partido en este hilo · PickandRollTV"},
            }
            body = {
                "name": f"🏀 {game['home']} vs {game['away']} | {game['competition']}"[:100],
                "message": {
                    "content": (f"<@&{role_id}> " if role_id else "") + "🔥 **¡Día de partido!** Aquí comentamos la previa, el directo y el postpartido.",
                    "embeds": [embed],
                    "allowed_mentions": {"roles": [role_id] if role_id else []},
                },
            }
            if tag:
                body["applied_tags"] = [tag]
            thread = discord("POST", f"/channels/{forum['id']}/threads", token, body)
            entry = state[key] = {"thread": thread["id"], "start": start.isoformat(), "competition": game["competition"],
                                  "rival": rival_keywords(rival), "news": [], "final": False}
            print(f"Hilo abierto: {body['name']}")
    # Los partidos ya abiertos pueden haber desaparecido del calendario al jugarse: se siguen desde el estado.
    for key, entry in state.items():
        if key.startswith("_"):
            continue
        start = datetime.datetime.fromisoformat(entry["start"])

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

        # 3. Final del partido.
        if not entry["final"] and now >= start + GAME_LENGTH:
            score = euroleague_score(start) if entry.get("competition") == "Euroliga" else None
            if entry.get("competition") == "Euroliga" and not score and now < start + datetime.timedelta(hours=6):
                continue  # la Euroliga aún no ha dado el resultado: se vuelve a mirar en la próxima pasada
            web = with_utm(CONFIG["website_url"], "partidos")
            discord("POST", f"/channels/{entry['thread']}/messages", token, {
                "content": ((f"🏁 **Final:** {score}\n" if score else "🏁 **¡Final del partido!**\n")
                            + f"¿Cómo lo habéis visto? 👇\n📰 La crónica y el análisis, en <{web}>"),
            })
            entry["final"] = True
            print(f"Final publicado: {key}")

    # 4. "DIA DE PARTIT" de la web: aviso destacado en #anuncios para los de 🏀 Partidos.
    announced = state.setdefault("_dia_de_partit", [])
    first_time = not announced and not any(not k.startswith("_") for k in state)
    for news in history:
        if news["link"] in announced or not is_matchday(news):
            continue
        published = datetime.datetime.fromisoformat(news["date"])
        if not first_time and now - published < datetime.timedelta(hours=18):
            channels = discord("GET", f"/guilds/{GUILD}/channels", token)
            target = next((c for c in channels if "anuncios" in c["name"] and c["type"] in (0, 5)), None)
            thread = next((e["thread"] for k, e in state.items() if not k.startswith("_")
                           and abs(datetime.datetime.fromisoformat(e["start"]) - published) < datetime.timedelta(hours=18)), None)
            link = with_utm(news["link"], "dia-de-partit")
            if target:
                discord("POST", f"/channels/{target['id']}/messages", token, {
                    "content": (f"<@&{role_id}> " if role_id else "") + f"🚨🏀 **{news['title']}**\n👉 Toda la previa en la web: <{link}>"
                               + (f"\n💬 Coméntalo en <#{thread}>" if thread else ""),
                    "embeds": [{"title": news["title"][:256], "url": link, "color": 0xA50044,
                                **({"image": {"url": news["image"]}} if news.get("image") else {})}],
                    "allowed_mentions": {"roles": [role_id] if role_id else []},
                })
                print(f"Dia de Partit anunciado: {news['title']}")
        announced.append(news["link"])
    state["_dia_de_partit"] = announced[-100:]

    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
