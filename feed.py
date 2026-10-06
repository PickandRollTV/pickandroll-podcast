"""Genera el RSS del podcast en el formato que piden Spotify y Apple Podcasts."""
import datetime
import email.utils
import xml.etree.ElementTree as ET

ITUNES = "http://www.itunes.com/dtds/podcast-1.0.dtd"
ATOM = "http://www.w3.org/2005/Atom"
CONTENT = "http://purl.org/rss/1.0/modules/content/"
ET.register_namespace("itunes", ITUNES)
ET.register_namespace("atom", ATOM)
ET.register_namespace("content", CONTENT)


def _sub(parent, tag, text=None, **attrs):
    element = ET.SubElement(parent, tag, {k: str(v) for k, v in attrs.items()})
    if text is not None:
        element.text = str(text)
    return element


def _rfc2822(iso_time):
    moment = datetime.datetime.fromisoformat(iso_time.replace("Z", "+00:00"))
    return email.utils.format_datetime(moment.astimezone(datetime.timezone.utc))


def write_feed(config, episodes, path):
    show = config["show"]
    rss = ET.Element("rss", {"version": "2.0"})
    channel = _sub(rss, "channel")
    _sub(channel, "title", show["title"])
    _sub(channel, "link", show["link"])
    _sub(channel, "language", show.get("language", "es"))
    _sub(channel, "description", show["description"])
    _sub(channel, f"{{{ATOM}}}link", href=config["feed_url"], rel="self", type="application/rss+xml")
    _sub(channel, f"{{{ITUNES}}}author", show["author"])
    _sub(channel, f"{{{ITUNES}}}summary", show["description"])
    _sub(channel, f"{{{ITUNES}}}image", href=show["image"])
    _sub(channel, f"{{{ITUNES}}}explicit", "true" if show.get("explicit") else "false")
    _sub(channel, f"{{{ITUNES}}}type", "episodic")
    owner = _sub(channel, f"{{{ITUNES}}}owner")
    _sub(owner, f"{{{ITUNES}}}name", show["author"])
    _sub(owner, f"{{{ITUNES}}}email", show["owner_email"])
    # En iTunes la categoría va en el atributo "text", no como contenido.
    category = ET.SubElement(channel, f"{{{ITUNES}}}category", {"text": show.get("category", "Sports")})
    if show.get("subcategory"):
        ET.SubElement(category, f"{{{ITUNES}}}category", {"text": show["subcategory"]})

    for episode in sorted(episodes, key=lambda e: e["published"], reverse=True):
        item = _sub(channel, "item")
        _sub(item, "title", episode["title"])
        _sub(item, "description", episode["description"])
        _sub(item, f"{{{CONTENT}}}encoded", episode["description"].replace("\n", "<br/>"))
        if episode.get("link"):
            _sub(item, "link", episode["link"])
        # El guid no cambia nunca: así Spotify no duplica episodios al mover el feed.
        _sub(item, "guid", episode["guid"], isPermaLink="false")
        _sub(item, "pubDate", _rfc2822(episode["published"]))
        _sub(item, "enclosure", url=episode["audio_url"], length=episode["audio_bytes"],
             type=episode.get("audio_type", "audio/mpeg"))
        if episode.get("duration"):
            _sub(item, f"{{{ITUNES}}}duration", episode["duration"])
        if episode.get("image"):
            _sub(item, f"{{{ITUNES}}}image", href=episode["image"])
        _sub(item, f"{{{ITUNES}}}episodeType", "full")
        _sub(item, f"{{{ITUNES}}}explicit", "true" if show.get("explicit") else "false")

    path.parent.mkdir(parents=True, exist_ok=True)
    ET.indent(rss)
    ET.ElementTree(rss).write(path, encoding="utf-8", xml_declaration=True)
