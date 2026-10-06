"""Busca el resultado final de un partido en los titulares de la agencia EFE.

EFE publica la crónica de cada partido de Liga Endesa y Euroliga con el marcador
delante ("100-94. Un Barça cae en Murcia..."), con el equipo local primero. Los
buscamos en Google News, solo entre las noticias de las 36 horas siguientes al inicio
del directo, y nos quedamos con el marcador que más se repite.
"""
import collections
import datetime
import email.utils
import re
import unicodedata
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

SCORE = re.compile(r"^\s*(\d{2,3})\s*-\s*(\d{2,3})\s*[.:]")
# Palabras del título que no sirven para buscar el partido.
STOP = {"vs", "v", "basket", "basketball", "bc", "fc", "club", "baloncesto", "barca"}


def _plain(text):
    text = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in text if not unicodedata.combining(c))


def rival_words(match):
    """Palabras del equipo rival ("UCAM Murcia vs Barça Basket" -> ["ucam", "murcia"])."""
    teams = re.split(r"\s+vs\s+", match)
    rival = next((t for t in teams if "barça" not in t.lower() and "barca" not in _plain(t)), "")
    return [w for w in re.findall(r"[a-z]+", _plain(rival)) if w not in STOP and len(w) > 2]


def _search(query, start, words):
    url = "https://news.google.com/rss/search?" + urllib.parse.urlencode(
        {"q": query, "hl": "es", "gl": "ES", "ceid": "ES:es"})
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request, timeout=30) as response:
        items = ET.fromstring(response.read()).iter("item")
    votes = collections.Counter()
    for item in items:
        title = item.findtext("title") or ""
        published = email.utils.parsedate_to_datetime(item.findtext("pubDate"))
        if not datetime.timedelta(0) <= published - start <= datetime.timedelta(hours=36):
            continue
        found = SCORE.match(title)
        if found and any(w in _plain(title) for w in words + ["barca", "barcelona"]):
            votes[f"{int(found.group(1))}-{int(found.group(2))}"] += 1
    return votes


def find_score(match, start):
    """Devuelve "100-94" (local-visitante) o None si aún no hay crónica."""
    words = rival_words(match)
    if not words:
        return None
    after = (start - datetime.timedelta(days=1)).strftime("%Y-%m-%d")
    before = (start + datetime.timedelta(days=2)).strftime("%Y-%m-%d")
    votes = collections.Counter()
    # Varias búsquedas, de la más precisa a la más amplia, limitadas a los días del partido.
    for terms in (" ".join(words), words[-1], words[0]):
        votes += _search(f"{terms} Barça after:{after} before:{before}", start, words)
        if votes:
            break
    return votes.most_common(1)[0][0] if votes else None
