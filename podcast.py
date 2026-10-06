#!/usr/bin/env python3
"""Publica como episodio de podcast cada directo terminado en el canal de YouTube.

Flujo de cada ejecución:
  1. Pregunta a la API de YouTube por los últimos vídeos del canal y se queda con
     los directos que ya han terminado y son públicos.
  2. Para cada uno que aún no esté en episodes.json: descarga solo el audio (MP3),
     lo sube como "release" de GitHub y lo apunta en episodes.json.
  3. Regenera docs/feed.xml, el RSS que lee Spotify (servido con GitHub Pages).

Variables de entorno:
  YT_API_KEY          clave de la API de YouTube Data v3 (obligatoria)
  GITHUB_REPOSITORY   owner/repo donde se suben los audios (lo pone GitHub Actions)
  GH_TOKEN            token con permiso para crear releases (lo pone GitHub Actions)
  YT_COOKIES_FILE     opcional, cookies.txt para cuando YouTube pide "no soy un robot"
"""
import datetime
import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request

from feed import write_feed
from intro import intro_offset

ROOT = pathlib.Path(__file__).resolve().parent
CONFIG_FILE = ROOT / "config.json"
EPISODES_FILE = ROOT / "episodes.json"
FEED_FILE = ROOT / "docs" / "feed.xml"
STATUS_FILE = ROOT / "ultimos_videos.json"
YT_API = "https://www.googleapis.com/youtube/v3/"

# Espera tras el final del directo antes de descargarlo, para que YouTube termine de procesarlo.
MIN_MINUTES_AFTER_END = 15


def load_json(path, default):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def save_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def parse_time(value):
    return datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))


def iso_duration_to_seconds(value):
    """'PT2H3M4S' -> 7384."""
    match = re.fullmatch(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", value or "")
    if not match:
        return 0
    days, hours, minutes, seconds = (int(g or 0) for g in match.groups())
    return ((days * 24 + hours) * 60 + minutes) * 60 + seconds


def youtube(endpoint, **params):
    params["key"] = os.environ["YT_API_KEY"]
    url = YT_API + endpoint + "?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=30) as response:
        return json.load(response)


def recent_videos(channel_id):
    """Últimos 15 vídeos del canal con sus datos de directo (cuesta 2 unidades de cuota)."""
    uploads_playlist = "UU" + channel_id[2:]
    items = youtube("playlistItems", part="contentDetails", playlistId=uploads_playlist, maxResults=15)["items"]
    ids = [item["contentDetails"]["videoId"] for item in items]
    if not ids:
        return []
    return youtube("videos", part="snippet,contentDetails,liveStreamingDetails,status", id=",".join(ids))["items"]


def is_finished_stream(video):
    return bool(video.get("liveStreamingDetails", {}).get("actualEndTime")) and video["status"]["privacyStatus"] == "public"


def write_status(videos):
    """Deja en ultimos_videos.json lo que vio la última pasada, para revisar por qué se publicó o no algo."""
    save_json(STATUS_FILE, [
        {
            "id": v["id"],
            "titulo": v["snippet"]["title"],
            "privacidad": v["status"]["privacyStatus"],
            "fin_del_directo": v.get("liveStreamingDetails", {}).get("actualEndTime"),
        }
        for v in videos
    ])


def best_thumbnail(snippet):
    thumbs = snippet.get("thumbnails", {})
    for size in ("maxres", "standard", "high", "medium", "default"):
        if size in thumbs:
            return thumbs[size]["url"]
    return None


def download_audio(video_id, workdir):
    cmd = [
        "yt-dlp", "--no-playlist", "--quiet", "--no-warnings",
        "-f", "bestaudio/best", "-x", "--audio-format", "mp3", "--audio-quality", "96K",
        # Mono: es una retransmisión hablada y el archivo pesa la mitad.
        "--postprocessor-args", "ExtractAudio:-ac 1",
        "-o", str(workdir / "%(id)s.%(ext)s"),
        f"https://www.youtube.com/watch?v={video_id}",
    ]
    cookies = os.environ.get("YT_COOKIES_FILE")
    if cookies and pathlib.Path(cookies).exists():
        cmd[1:1] = ["--cookies", cookies]
    subprocess.run(cmd, check=True)
    return workdir / f"{video_id}.mp3"


def trim_start(audio_path, seconds):
    """Quita los primeros segundos (la cuenta atrás) sin recodificar el audio."""
    if seconds <= 0:
        return audio_path
    trimmed = audio_path.with_name(audio_path.stem + "-podcast.mp3")
    subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-y", "-ss", str(seconds), "-i", str(audio_path),
         "-c", "copy", str(trimmed)],
        check=True,
    )
    audio_path.unlink()
    return trimmed.rename(audio_path)


def upload_audio(tag, title, audio_path):
    """Sube el MP3 como release de GitHub y devuelve su URL pública de descarga."""
    repo = os.environ["GITHUB_REPOSITORY"]
    subprocess.run(
        ["gh", "release", "create", tag, str(audio_path), "--repo", repo,
         "--title", title, "--notes", "Audio del episodio del podcast."],
        check=True,
    )
    return f"https://github.com/{repo}/releases/download/{tag}/{audio_path.name}"


def episode_from_video(video, audio_url, audio_bytes, trimmed_seconds=0):
    snippet = video["snippet"]
    video_url = f"https://www.youtube.com/watch?v={video['id']}"
    return {
        "guid": f"youtube:{video['id']}",
        "source": "youtube",
        "video_id": video["id"],
        "title": snippet["title"],
        "description": f"{snippet.get('description', '').strip()}\n\nDirecto completo en vídeo: {video_url}".strip(),
        "published": video["liveStreamingDetails"].get("actualStartTime") or snippet["publishedAt"],
        "duration": max(iso_duration_to_seconds(video["contentDetails"].get("duration")) - trimmed_seconds, 0),
        "image": best_thumbnail(snippet),
        "link": video_url,
        "audio_url": audio_url,
        "audio_bytes": audio_bytes,
        "audio_type": "audio/mpeg",
    }


def main():
    config = load_json(CONFIG_FILE, {})
    if not os.environ.get("YT_API_KEY") or "x" * 10 in config["youtube_channel_id"]:
        print("Falta la clave YT_API_KEY o el ID del canal en config.json; no hago nada todavía.")
        return 0
    episodes = load_json(EPISODES_FILE, [])
    known = {e.get("video_id") for e in episodes}
    publish_after = parse_time(config["publish_streams_after"])
    now = datetime.datetime.now(datetime.timezone.utc)

    pending = []
    videos = recent_videos(config["youtube_channel_id"])
    write_status(videos)
    for video in filter(is_finished_stream, videos):
        ended = parse_time(video["liveStreamingDetails"]["actualEndTime"])
        if video["id"] in known or ended < publish_after:
            continue
        if now - ended < datetime.timedelta(minutes=MIN_MINUTES_AFTER_END):
            print(f"{video['id']}: terminó hace muy poco, se publicará en la próxima pasada")
            continue
        pending.append(video)

    # Si no se encuentra el saludo de bienvenida, se recortan estos segundos.
    fallback_seconds = int(config.get("countdown_seconds", 0))
    failures = 0
    for video in sorted(pending, key=lambda v: v["liveStreamingDetails"]["actualEndTime"]):
        title = video["snippet"]["title"]
        print(f"Publicando: {title} ({video['id']})")
        try:
            with tempfile.TemporaryDirectory() as tmp:
                audio = download_audio(video["id"], pathlib.Path(tmp))
                skip = intro_offset(audio, fallback_seconds)
                audio = trim_start(audio, skip)
                size = audio.stat().st_size
                url = upload_audio(f"ep-{video['id']}", title, audio)
        except subprocess.CalledProcessError as error:
            # Se reintenta solo en la siguiente ejecución, porque no queda apuntado en episodes.json.
            print(f"  Falló ({error}); se reintentará en la próxima pasada", file=sys.stderr)
            failures += 1
            continue
        episodes.append(episode_from_video(video, url, size, skip))
        # Guardamos tras cada episodio para no volver a subir uno ya publicado si algo falla después.
        save_json(EPISODES_FILE, episodes)
        write_feed(config, episodes, FEED_FILE)

    write_feed(config, episodes, FEED_FILE)
    print(f"{len(pending) - failures} episodio(s) nuevo(s); {len(episodes)} en total")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
