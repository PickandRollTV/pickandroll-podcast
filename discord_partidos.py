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
from resultados import find_score

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
# Con PARTIDOS_DIAS se abren de golpe los hilos de los próximos días (sin mencionar a nadie salvo en los inminentes).
OPEN_BEFORE = datetime.timedelta(days=float(os.environ.get("PARTIDOS_DIAS") or 0)) or datetime.timedelta(hours=30)
PING_BEFORE = datetime.timedelta(hours=30)
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


def euroleague_game(start):
    """Partido de Euroliga que empieza a esa hora (o None)."""
    try:
        games = json.loads(get(EUROLEAGUE.format(year=season_year(start)))).get("data", [])
    except Exception as error:
        print(f"No he podido leer la Euroliga: {error}")
        return None
    for game in games:
        when = datetime.datetime.fromisoformat(game["utcDate"].replace("Z", "+00:00"))
        if abs(when - start) < datetime.timedelta(hours=3):
            return game
    return None


def final_score(entry, start):
    """(puntos local, puntos visitante) del partido terminado, o None si aún no se sabe."""
    if entry.get("competition") == "Euroliga":
        game = euroleague_game(start)
        if game and game["played"]:
            return game["local"]["score"], game["road"]["score"]
    if entry.get("home") and entry.get("away"):
        try:
            found = find_score(f"{entry['home']} vs {entry['away']}", start)
        except Exception as error:
            print(f"No he podido buscar el resultado: {error}")
            found = None
        if found:
            local, road = found.split("-")
            return int(local), int(road)
    return None


def player_name(raw):
    """"KONE, ABDU" -> "Abdu Kone"."""
    last, _, first = raw.partition(",")
    return f"{first.strip()} {last.strip()}".strip().title()


def mvp_candidates(entry, start):
    """Hasta 10 jugadores del Barça para votar el MVP: los mejores por valoración del partido
    (Euroliga) o, si no hay estadísticas, la plantilla de la Euroliga."""
    names = []
    game = euroleague_game(start) if entry.get("competition") == "Euroliga" else None
    if game:
        try:
            stats = json.loads(get(f"https://api-live.euroleague.net/v3/competitions/E/seasons/E{season_year(start)}/games/{game['gameCode']}/stats"))
            side = stats["local"] if game["local"]["club"]["code"] == "BAR" else stats["road"]
            players = [(p.get("stats", {}).get("valuation") or 0, p.get("player", {}).get("person", {}).get("name", ""))
                       for p in side.get("players", []) if (p.get("stats", {}).get("timePlayed") or 0)]
            names = [player_name(n) for _, n in sorted(players, reverse=True) if n][:10]
        except Exception as error:
            print(f"Sin estadísticas del partido: {error}")
    if not names:
        try:
            people = json.loads(get(f"https://api-live.euroleague.net/v2/competitions/E/seasons/E{season_year(start)}/clubs/BAR/people"))
            names = [player_name(p["person"]["name"]) for p in sorted(people, key=lambda p: p.get("order") or 99)
                     if p.get("type") == "J" and p.get("active", True)][:10]
        except Exception as error:
            print(f"Sin plantilla: {error}")
    return names


def poll(question, answers, hours):
    return {"poll": {"question": {"text": question[:300]},
                     "answers": [{"poll_media": {"text": text[:55], **({"emoji": {"name": emoji}} if emoji else {})}}
                                 for text, emoji in answers],
                     "duration": max(1, min(int(hours), 768)), "allow_multiselect": False}}


def porra_answers(entry):
    rival = entry["away"] if plain(entry["home"]).startswith("barca") else entry["home"]
    return [("Gana el Barça por 10 o más", "🔥"), ("Gana el Barça por 1 a 9", "💙"),
            (f"Gana {rival} por 1 a 9", "😬"), (f"Gana {rival} por 10 o más", "😱")]


def porra_winner(entry, score):
    """Índice (1-4) de la respuesta acertada de la porra."""
    local, road = score
    barca, rival = (local, road) if plain(entry["home"]).startswith("barca") else (road, local)
    diff = barca - rival
    return 1 if diff >= 10 else 2 if diff > 0 else 4 if diff <= -10 else 3


def voters(token, channel, message, answer):
    users, after = [], None
    while True:
        page = discord("GET", f"/channels/{channel}/polls/{message}/answers/{answer}?limit=100" + (f"&after={after}" if after else ""), token)
        batch = page.get("users", [])
        users += [u["id"] for u in batch if not u.get("bot")]
        if len(batch) < 100:
            return users
        after = batch[-1]["id"]



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


def thread_message(game, ping, role_id):
    """Primer mensaje del hilo, en texto (se ve aunque alguien tenga desactivadas las tarjetas)."""
    ts = int(game["start"].timestamp())
    web = with_utm(CONFIG["website_url"], "partidos")
    lines = [
        (f"<@&{role_id}> " if role_id and ping else "") + ("🔥 **¡Día de partido!**" if ping else "🗓️ **Próximo partido.**")
        + " Aquí comentamos la previa, el directo y el postpartido.",
        f"## {game['home']} vs {game['away']}",
        f"🏆 **{game['competition']}**",
        f"🕒 <t:{ts}:F> (<t:{ts}:R>)",
    ]
    if game["venue"]:
        lines.append(f"🏟️ {game['venue']}")
    lines += ["", f"📰 **[Previa, crónica y toda la actualidad en pickandroll.tv](<{web}>)**",
              f"🔴 **[Lo vivimos en directo en Twitch](<{CONFIG['twitch_url']}>)**",
              "-# Comenta el partido en este hilo · PickandRollTV"]
    return {"content": "\n".join(lines), "embeds": [],
            "allowed_mentions": {"roles": [role_id] if role_id and ping else []}}


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
    fixtures = club_fixtures()
    if os.environ.get("PARTIDOS_REHACER"):
        # Reescribe el primer mensaje de los hilos ya abiertos con el formato actual.
        for game in fixtures:
            if game["key"] in state:
                thread = state[game["key"]]["thread"]
                discord("PATCH", f"/channels/{thread}/messages/{thread}", token, thread_message(game, False, None))
                print(f"Hilo actualizado: {game['home']} vs {game['away']}")
    for game in fixtures:
        start, key = game["start"], game["key"]
        home = plain(game["home"]).startswith("barca")
        rival = game["away"] if home else game["home"]
        entry = state.get(key)
        if entry:
            entry.update(home=game["home"], away=game["away"])

        # 1. Abrir el hilo.
        if not entry and now <= start <= now + OPEN_BEFORE:
            if forum is None:
                channels = discord("GET", f"/guilds/{GUILD}/channels", token)
                forum = next((c for c in channels if c["type"] == 15 and "partidos" in c["name"]), None)
                if not forum:
                    print("No encuentro el foro de partidos")
                    return 1
            tag = next((t["id"] for t in forum.get("available_tags", []) if t["name"] == game["competition"]), None)
            ping = start - now <= PING_BEFORE
            body = {
                "name": f"🏀 {game['home']} vs {game['away']} | {game['competition']}"[:100],
                "message": thread_message(game, ping, role_id),
            }
            if tag:
                body["applied_tags"] = [tag]
            thread = discord("POST", f"/channels/{forum['id']}/threads", token, body)
            entry = state[key] = {"thread": thread["id"], "start": start.isoformat(), "competition": game["competition"],
                                  "home": game["home"], "away": game["away"],
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

        # 3. Porra: encuesta del resultado hasta la hora del partido.
        if "porra" not in entry and entry.get("home") and now < start - datetime.timedelta(hours=1):
            message = discord("POST", f"/channels/{entry['thread']}/messages", token, {
                "content": "🔮 **Porra del partido.** ¿Cómo acaba? Se cierra al empezar el partido y los que aciertan suman para el ranking del mes 🏆",
                **poll(f"🔮 {entry['home']} vs {entry['away']}: ¿cómo acaba?", porra_answers(entry), (start - now).total_seconds() // 3600),
            })
            entry["porra"] = message["id"]
            print(f"Porra abierta: {key}")

        # 4. Final del partido: resultado, aciertos de la porra y votación del MVP.
        if not entry["final"] and now >= start + GAME_LENGTH:
            score = final_score(entry, start)
            if not score and now < start + datetime.timedelta(hours=12):
                continue  # aún no se sabe el resultado: se vuelve a mirar en la próxima pasada
            web = with_utm(CONFIG["website_url"], "partidos")
            lines = [f"🏁 **Final:** {entry.get('home', '')} **{score[0]}-{score[1]}** {entry.get('away', '')}" if score else "🏁 **¡Final del partido!**"]
            if score and entry.get("porra"):
                winner = porra_winner(entry, score)
                hits = voters(token, entry["thread"], entry["porra"], winner)
                # Solo se guarda la respuesta buena: el ranking del mes se recuenta en Discord (sin ids en el repositorio).
                entry["porra_buena"] = winner
                lines.append(f"🔮 **Porra:** {len(hits)} acertante{'s' if len(hits) != 1 else ''}"
                             + (": " + " ".join(f"<@{u}>" for u in hits[:20]) if hits else ". ¡La próxima!"))
            lines.append(f"📰 La crónica y el análisis, en <{web}>")
            discord("POST", f"/channels/{entry['thread']}/messages", token, {"content": "\n".join(lines), "allowed_mentions": {"parse": []}})
            names = mvp_candidates(entry, start)
            if len(names) >= 2:
                discord("POST", f"/channels/{entry['thread']}/messages", token, {
                    "content": f"⭐ **MVP del partido.** ¿Quién ha sido el mejor del Barça? Votación abierta 24 horas.\n📰 Las notas de los jugadores, en <{web}>",
                    **poll("⭐ ¿Quién ha sido el MVP del Barça?", [(n, None) for n in names], 24),
                })
            entry["final"] = True
            print(f"Final publicado: {key}")

    # 5. "DIA DE PARTIT" de la web: aviso destacado en #anuncios para los de 🏀 Partidos.
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
