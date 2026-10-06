"""Limpia títulos y descripciones para que el podcast se vea ordenado en Spotify.

Los títulos de los directos están pensados para YouTube y Twitch ("🔴 EN DIRECTO |
🏀 UCAM MURCIA v BARÇA BASKET | ..."). En un podcast sobran los emojis, el "EN DIRECTO"
y las mayúsculas, así que se dejan con un formato fijo: "Equipo vs Equipo | Competición".
"""
import html
import re

# Siglas y nombres que se escriben siempre igual, aunque el título venga en mayúsculas.
FIXED_WORDS = {
    "ucam": "UCAM", "acb": "ACB", "nba": "NBA", "fiba": "FIBA", "mvp": "MVP", "bc": "BC",
    "barça": "Barça", "barca": "Barça", "euroleague": "EuroLeague", "euroliga": "Euroliga",
    "eurocup": "EuroCup", "efes": "Efes", "breogán": "Breogán", "v": "vs", "vs": "vs",
    "de": "de", "del": "del", "la": "la", "el": "el", "y": "y", "en": "en", "a": "a",
}
NOISE = [
    r"\bnarraci[oó]n en (espa[ñn]ol|directo)\b", r"\ben directo\b",
    r"\bdirecto\b(?=\s*(\||$))", r"\blive\b",
]
EMOJI = re.compile("[\U0001F000-\U0001FAFF☀-➿️‍]")


def _fix_case(text):
    words = text.split(" ")
    # Solo se reescriben las palabras si el título viene gritado (casi todo en mayúsculas).
    letters = [c for c in text if c.isalpha()]
    shouting = letters and sum(c.isupper() for c in letters) / len(letters) > 0.6
    out = []
    for i, word in enumerate(words):
        key = word.lower()
        if key in FIXED_WORDS and (shouting or key in ("v", "barca")):
            fixed = FIXED_WORDS[key]
            out.append(fixed[0].upper() + fixed[1:] if i == 0 and fixed.islower() else fixed)
        elif shouting and word.isupper() and len(word) > 1:
            out.append(word.capitalize())
        else:
            out.append(word)
    return " ".join(out)


def _fix_part(part):
    part = re.sub(r"\bligaendesa\b", "Liga Endesa", part, flags=re.I)
    part = re.sub(r"\bliga endesa\b", "Liga Endesa", part, flags=re.I)
    part = re.sub(r"\b(round|jornada)\s*(\d+)\s*(euroleague|euroliga)\b", r"EuroLeague Jornada \2", part, flags=re.I)
    part = re.sub(r"\bround\s*(\d+)\b", r"Jornada \1", part, flags=re.I)
    part = re.sub(r"\bJ(\d+)\b", r"Jornada \1", part)
    part = re.sub(r"\b(jornada \d+) (liga endesa|euroleague)\b", r"\2 \1", part, flags=re.I)
    part = re.sub(r"(\d)\s*-\s*(?=\d)", r"\1-", part)  # "76 - 95" -> "76-95"
    part = re.sub(r"(?<=[^\d\s])\s+-\s+(?=[^\d\s])", " vs ", part)  # "Barça - Baskonia"
    return part


def clean_title(title):
    text = EMOJI.sub(" ", title)
    for pattern in NOISE:
        text = re.sub(pattern, " ", text, flags=re.I)
    parts = []
    for part in text.split("|"):
        part = re.sub(r"\s+", " ", part).strip(" -·")
        if part:
            parts.append(_fix_part(_fix_case(part)))
    # La competición repetida dos veces no aporta nada.
    unique = [p for i, p in enumerate(parts) if p.lower() not in (q.lower() for q in parts[:i])]
    return " | ".join(unique) or title.strip()


def twitch_description(episode, config):
    """Descripción de un directo publicado desde Twitch (allí no hay texto que copiar)."""
    show = config["show"]
    lines = [
        f"<p><strong>{html.escape(clean_title(episode['title']))}</strong></p>",
        f"<p>{html.escape(show['episode_blurb'])}</p>" if show.get("episode_blurb") else "",
    ]
    # Twitch borra los directos guardados a los pocos días, así que enlazamos a los canales.
    links = ["Síguenos en directo:"]
    for label, key in (("YouTube", "youtube_channel_url"), ("Twitch", "twitch_url")):
        if config.get(key):
            links.append(f'{label}: <a href="{config[key]}">{config[key]}</a>')
    lines.append("<p>" + "<br/>".join(links) + "</p>")
    return "".join(line for line in lines if line)


def episode_description(episode, config):
    if episode.get("source") == "twitch":
        return twitch_description(episode, config)
    return episode["description"]
