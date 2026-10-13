#!/usr/bin/env python3
"""Publica como episodio de podcast cada directo terminado en el canal de Twitch.

Usamos Twitch como fuente porque el directo sale a la vez en YouTube, Twitch y Kick,
y YouTube bloquea las descargas desde los servidores de GitHub.

Flujo de cada ejecución:
  1. Lista los últimos directos guardados (VODs) del canal de Twitch y se queda con
     los que ya han terminado.
  2. Para cada uno que aún no esté en episodes.json: descarga solo el audio (MP3),
     recorta la cuenta atrás, lo sube como "release" de GitHub y lo apunta en episodes.json.
  3. Regenera docs/feed.xml, el RSS que lee Spotify (servido con GitHub Pages).

Variables de entorno:
  GITHUB_REPOSITORY   owner/repo donde se suben los audios (lo pone GitHub Actions)
  GH_TOKEN            token con permiso para crear releases (lo pone GitHub Actions)
"""
import datetime
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import time

from feed import write_feed
from intro import intro_offset
from miniaturas import add_covers
from presentacion import clean_title, episode_title
from resultados import find_score

ROOT = pathlib.Path(__file__).resolve().parent
CONFIG_FILE = ROOT / "config.json"
EPISODES_FILE = ROOT / "episodes.json"
FEED_FILE = ROOT / "docs" / "feed.xml"
STATUS_FILE = ROOT / "ultimos_videos.json"
# Último error de descarga o subida, para poder revisarlo sin abrir los registros de GitHub.
ERROR_FILE = ROOT / "ultimo_error.txt"
# Qué hizo la última pasada con resultados y recortes, para revisarlo sin abrir los registros.
LOG_FILE = ROOT / "ultima_pasada.txt"
# Pasadas seguidas en las que no se pudo leer Twitch.
TWITCH_FAILS_FILE = ROOT / "twitch_fallos.txt"
LOG = []

# Mientras dura el directo el VOD va creciendo; damos por terminado el que lleva
# este tiempo sin crecer.
MIN_MINUTES_AFTER_END = 15
# Cuántos VODs recientes se revisan en cada pasada.
RECENT_VODS = 8
# Twitch a veces falla un momento: se reintenta dentro de la pasada, y solo se marca la
# ejecución como fallida (lo que manda un correo) si lleva este número de pasadas sin
# poder leerse (8 pasadas = 2 horas).
TWITCH_TRIES = 3
TWITCH_FAILS_BEFORE_ALERT = 8


def load_json(path, default):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def save_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def parse_time(value):
    return datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))


def yt_dlp_json(*args):
    out = subprocess.run(["yt-dlp", "--no-warnings", *args], check=True, capture_output=True, text=True).stdout
    return [json.loads(line) for line in out.splitlines() if line.strip()]


def recent_vods(channel):
    """Últimos directos guardados del canal, con fecha de inicio y duración."""
    listing = yt_dlp_json(
        "--flat-playlist", "--playlist-end", str(RECENT_VODS), "-j",
        f"https://www.twitch.tv/{channel}/videos?filter=archives&sort=time",
    )
    if not listing:
        # Twitch a veces devuelve la lista vacía; mejor fallar y reintentar que no ver nada.
        raise RuntimeError(f"Twitch no devolvió ningún directo guardado de {channel}")
    vods = []
    for entry in listing:
        info = yt_dlp_json("--skip-download", "-j", f"https://www.twitch.tv/videos/{entry['id'].lstrip('v')}")[0]
        vods.append({
            "id": info["id"].lstrip("v"),
            "title": info.get("title") or entry.get("title") or "Directo",
            "start": datetime.datetime.fromtimestamp(info["timestamp"], datetime.timezone.utc),
            "duration": int(info.get("duration") or 0),
            "thumbnail": info.get("thumbnail"),
            "url": f"https://www.twitch.tv/videos/{info['id'].lstrip('v')}",
        })
    return vods


def write_status(vods):
    """Deja en ultimos_videos.json lo que vio la última pasada, para revisar por qué se publicó o no algo."""
    save_json(STATUS_FILE, [
        {"id": v["id"], "titulo": v["title"], "inicio": v["start"].isoformat(), "duracion_min": v["duration"] // 60}
        for v in vods
    ])


def download_audio(vod, workdir):
    out = workdir / f"{vod['id']}.mp3"
    subprocess.run(
        ["yt-dlp", "--no-warnings", "--quiet",
         # Twitch ofrece una pista "audio_only"; si no está, la calidad de vídeo más baja.
         "-f", "audio_only/worst", "-x", "--audio-format", "mp3", "--audio-quality", "96K",
         # Mono: es una retransmisión hablada y el archivo pesa la mitad.
         "--postprocessor-args", "ExtractAudio:-ac 1",
         "-o", str(workdir / "%(id)s.%(ext)s"), vod["url"]],
        check=True, capture_output=True, text=True,
    )
    # yt-dlp nombra el archivo con el id de Twitch, que empieza por "v".
    return next(workdir.glob("*.mp3"), out)


def trim_start(audio_path, seconds):
    """Quita los primeros segundos (la cuenta atrás) sin recodificar el audio."""
    if seconds <= 0:
        return audio_path
    trimmed = audio_path.with_name(audio_path.stem + "-podcast.mp3")
    subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-y", "-ss", str(seconds), "-i", str(audio_path),
         "-c", "copy", str(trimmed)],
        check=True, capture_output=True, text=True,
    )
    audio_path.unlink()
    return trimmed.rename(audio_path)


def upload_audio(tag, title, audio_path):
    """Sube el MP3 como release de GitHub y devuelve su URL pública de descarga."""
    repo = os.environ["GITHUB_REPOSITORY"]
    exists = subprocess.run(["gh", "release", "view", tag, "--repo", repo], capture_output=True).returncode == 0
    if exists:
        # Un reintento tras un fallo a medias: sustituimos el audio que ya había.
        cmd = ["gh", "release", "upload", tag, str(audio_path), "--repo", repo, "--clobber"]
    else:
        cmd = ["gh", "release", "create", tag, str(audio_path), "--repo", repo,
               "--title", title, "--notes", "Audio del episodio del podcast."]
    subprocess.run(cmd, check=True, capture_output=True, text=True)
    # Si un fallo de GitHub dejó la release como borrador, el audio no sería público.
    subprocess.run(["gh", "release", "edit", tag, "--repo", repo, "--draft=false"],
                   check=True, capture_output=True, text=True)
    return f"https://github.com/{repo}/releases/download/{tag}/{audio_path.name}"


def episode_from_vod(vod, audio_url, audio_bytes, trimmed_seconds, config):
    links = [f"Directo completo en Twitch: {vod['url']}"]
    if config.get("youtube_channel_url"):
        links.append(f"Canal de YouTube: {config['youtube_channel_url']}")
    return {
        "guid": f"twitch:{vod['id']}",
        "source": "twitch",
        "vod_id": vod["id"],
        "title": vod["title"],
        "description": "\n".join(links),
        "published": vod["start"].isoformat(),
        "duration": max(vod["duration"] - int(trimmed_seconds), 0),
        "image": vod["thumbnail"],
        "link": vod["url"],
        "audio_url": audio_url,
        "audio_bytes": audio_bytes,
        "audio_type": "audio/mpeg",
    }


def audio_seconds(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                         check=True, capture_output=True, text=True).stdout
    return int(float(out.strip()))


def apply_manual_trims(episodes, config):
    """Vuelve a publicar, recortado a mano, un directo cuyo inicio no se detectó bien.

    En config.json, "recortes_manuales": {vod: segundo del directo en que empieza}. Se
    parte siempre del directo original de Twitch, así que repetirlo no recorta de más.
    """
    changed = False
    for episode in episodes:
        seconds = config.get("recortes_manuales", {}).get(episode.get("vod_id", ""))
        if seconds is None or episode.get("recorte_manual") == seconds:
            continue
        vod = {"id": episode["vod_id"], "url": f"https://www.twitch.tv/videos/{episode['vod_id']}"}
        with tempfile.TemporaryDirectory() as tmp:
            audio = trim_start(download_audio(vod, pathlib.Path(tmp)), int(seconds))
            upload_audio(f"twitch-{episode['vod_id']}", episode["title"], audio)
            episode["audio_bytes"] = audio.stat().st_size
            episode["duration"] = audio_seconds(audio)
        episode["recorte_manual"] = seconds
        episode.pop("recorte_extra", None)
        changed = True
    return changed


def add_scores(episodes, now):
    """Busca el resultado de los directos recientes que aún no lo tienen. Devuelve si cambió algo."""
    changed = False
    for episode in episodes:
        start = parse_time(episode["published"])
        if episode.get("source") != "twitch" or episode.get("resultado") or now - start > datetime.timedelta(days=30):
            continue
        try:
            score = find_score(clean_title(episode["title"]).split(" | ")[0], start)
        except Exception as error:  # Sin resultado el título sale igual, sin marcador.
            LOG.append(f"Resultado de {episode['vod_id']}: error {error!r}")
            continue
        LOG.append(f"Resultado de {episode['vod_id']}: {score}")
        if score:
            episode["resultado"] = score
            changed = True
    return changed


def main():
    config = load_json(CONFIG_FILE, {})
    episodes = load_json(EPISODES_FILE, [])
    known = {e.get("vod_id") for e in episodes}
    publish_after = parse_time(config["publish_streams_after"])
    min_seconds = int(config.get("min_stream_minutes", 20)) * 60
    now = datetime.datetime.now(datetime.timezone.utc)

    for attempt in range(TWITCH_TRIES):
        try:
            vods = recent_vods(config["twitch_channel"])
            break
        except (RuntimeError, subprocess.CalledProcessError) as error:
            last_error = error
            if attempt + 1 < TWITCH_TRIES:
                time.sleep(30)
    else:
        fails = int(TWITCH_FAILS_FILE.read_text().strip() or 0) + 1 if TWITCH_FAILS_FILE.exists() else 1
        TWITCH_FAILS_FILE.write_text(f"{fails}\n", encoding="utf-8")
        detail = getattr(last_error, "stderr", "") or ""
        ERROR_FILE.write_text(f"No se pudo leer Twitch: {last_error}\n{detail[-2000:]}\n", encoding="utf-8")
        print(f"No se pudo leer Twitch ({fails} pasada(s) seguidas): {last_error}", file=sys.stderr)
        return 1 if fails >= TWITCH_FAILS_BEFORE_ALERT else 0
    TWITCH_FAILS_FILE.unlink(missing_ok=True)
    write_status(vods)
    pending = []
    for vod in vods:
        ended = vod["start"] + datetime.timedelta(seconds=vod["duration"])
        # Los cortes cortos (un directo que se reinicia) no son episodios.
        if vod["id"] in known or vod["start"] < publish_after or vod["duration"] < min_seconds:
            continue
        if now - ended < datetime.timedelta(minutes=MIN_MINUTES_AFTER_END):
            print(f"{vod['id']}: sigue en directo o acaba de terminar; se publicará en otra pasada")
            continue
        pending.append(vod)

    # Si no se encuentra el saludo de bienvenida, se recortan estos segundos.
    fallback_seconds = int(config.get("countdown_seconds", 0))
    # La URL de la portada del programa indica dónde sirve GitHub Pages la carpeta docs/.
    covers_url = config["show"]["image"].rsplit("/", 1)[0]
    title_of = lambda episode: episode_title(episode, config)  # noqa: E731
    failures = 0
    for vod in sorted(pending, key=lambda v: v["start"]):
        print(f"Publicando: {vod['title']} ({vod['id']})")
        try:
            with tempfile.TemporaryDirectory() as tmp:
                audio = download_audio(vod, pathlib.Path(tmp))
                skip, trim_note = intro_offset(audio, fallback_seconds)
                print(f"  {trim_note[:300]}")
                audio = trim_start(audio, skip)
                size = audio.stat().st_size
                url = upload_audio(f"twitch-{vod['id']}", vod["title"], audio)
        except subprocess.CalledProcessError as error:
            # Se reintenta solo en la siguiente ejecución, porque no queda apuntado en episodes.json.
            detail = (error.stderr or "").strip()[-2000:]
            print(f"  Falló ({error}); se reintentará en la próxima pasada\n{detail}", file=sys.stderr)
            ERROR_FILE.write_text(f"{vod['id']} {vod['title']}\n{error}\n{detail}\n", encoding="utf-8")
            failures += 1
            continue
        episode = episode_from_vod(vod, url, size, skip, config)
        episode["recorte"] = trim_note[:3000]
        episodes.append(episode)
        # Guardamos y publicamos tras cada episodio: así sale en Spotify sin esperar al resto
        # del lote, y no se vuelve a subir si algo falla después.
        add_covers(episodes, FEED_FILE.parent, covers_url, title_of)
        save_json(EPISODES_FILE, episodes)
        write_feed(config, episodes, FEED_FILE)
        if os.environ.get("GITHUB_ACTIONS"):
            subprocess.run([sys.executable, str(ROOT / "guardar.py")], cwd=ROOT, check=False)

    # El resultado suele publicarse un rato después del partido; se reintenta en cada pasada.
    try:
        trimmed = apply_manual_trims(episodes, config)
    except Exception as error:
        LOG.append(f"No se pudo recortar a mano: {error!r} {getattr(error, 'stderr', '')}"[:2000])
        trimmed = False
    if trimmed | add_scores(episodes, now) | bool(add_covers(episodes, FEED_FILE.parent, covers_url, title_of)):
        save_json(EPISODES_FILE, episodes)
    write_feed(config, episodes, FEED_FILE)
    LOG_FILE.write_text(f"{now.isoformat()}\n" + "\n".join(LOG) + "\n", encoding="utf-8")
    print(f"{len(pending) - failures} episodio(s) nuevo(s); {len(episodes)} en total")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
