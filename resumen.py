#!/usr/bin/env python3
"""Monta el vídeo resumen y un Short de cada directo de partido ya publicado en el podcast.

Flujo de cada ejecución (lo lanza resumen.yml al acabar "Publicar directos en el podcast"):
  1. Busca en episodes.json el directo de partido más reciente que aún no tenga resumen.
  2. Baja su MP3 del podcast y mide, segundo a segundo, cuánto sube la voz de la narración.
     Los gritos de la narración marcan las jugadas buenas.
  3. Localiza el partido (el tramo de ~2 h 15 min con más emoción) y elige ahí los picos
     hasta llenar entre 8 y 10 minutos.
  4. Baja de Twitch SOLO esos trozos de vídeo, los une con portada y cierre (20 s para la
     pantalla final de YouTube) y hace un Short vertical con el mejor pico.
  5. Sube resumen.mp4, short.mp4, miniatura.jpg y datos.json a la release "resumen-<vod>"
     y lo apunta en resumenes.json. Lo publica en YouTube la tarea de PickandRollTV.

Variables de entorno: GITHUB_REPOSITORY y GH_TOKEN (las pone GitHub Actions).
Para rehacer uno: RESUMEN_VOD=<id del directo>.
"""
import datetime
import json
import os
import pathlib
import re
import statistics
import subprocess
import sys
import tempfile

from miniaturas import render as render_cover
from presentacion import episode_title

ROOT = pathlib.Path(__file__).resolve().parent
CONFIG_FILE = ROOT / "config.json"
EPISODES_FILE = ROOT / "episodes.json"
RESUMENES_FILE = ROOT / "resumenes.json"
FONT = ROOT / "fonts" / "BarlowCondensed-BlackItalic.ttf"

DEFAULTS = {
    "desde": "2026-10-30T00:00:00Z",   # solo directos a partir de esta fecha
    "minutos_objetivo": 9,             # duración del resumen (sin portada ni cierre)
    "minutos_partido": 135,            # lo que dura un partido narrado, más o menos
    "antes_del_grito": 14,             # segundos de jugada antes del pico de la narración
    "despues_del_grito": 6,            # segundos de reacción después del pico
    "separacion_minima": 35,           # entre dos picos elegidos
    "segundos_cierre": 20,             # tarjeta final (pantalla final de YouTube)
    "segundos_short": 24,
}
GARNET = "0xa50044"
YELLOW = "0xffd23f"
NAVY = "0x12082e"


def load_json(path, default):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def save_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def run(*cmd, **kw):
    return subprocess.run([str(c) for c in cmd], check=True, capture_output=True, text=True, **kw)


def is_match(episode):
    return bool(re.search(r"\s(v|vs)\s", episode["title"])) and episode.get("source") == "twitch"


# --- 1) Emoción de la narración, segundo a segundo -------------------------------------

def loudness_per_second(mp3):
    """Nivel RMS (dB) de cada segundo del audio. Se baja a 8 kHz mono para ir rápido."""
    out = run("ffmpeg", "-nostats", "-i", mp3, "-vn", "-ac", "1", "-ar", "8000", "-af",
              "aresample=8000,highpass=f=150,lowpass=f=3500,asetnsamples=8000,astats=metadata=1:reset=1,"
              "ametadata=print:key=lavfi.astats.Overall.RMS_level:file=-", "-f", "null", "-").stdout
    values = []
    for line in out.splitlines():
        if "RMS_level=" in line:
            v = line.split("=", 1)[1].strip()
            values.append(-90.0 if v in ("-inf", "inf", "nan") else max(float(v), -90.0))
    return values


def excitement(levels, window=90):
    """Cuánto sube cada segundo sobre lo normal de su entorno (mediana de ±window s)."""
    smooth = [statistics.fmean(levels[max(0, i - 1):i + 2]) for i in range(len(levels))]
    base = []
    step = 10  # la mediana se recalcula cada 10 s para no tardar con directos de 5 h
    for i in range(0, len(smooth), step):
        chunk = smooth[max(0, i - window):i + window]
        base.extend([statistics.median(chunk)] * step)
    return [max(0.0, s - b) for s, b in zip(smooth, base)]


def game_window(score, minutes):
    """El tramo de `minutes` con más emoción acumulada: ahí está el partido."""
    width = min(len(score), minutes * 60)
    total = sum(score[:width])
    best, best_start = total, 0
    for start in range(1, len(score) - width + 1):
        total += score[start + width - 1] - score[start - 1]
        if total > best:
            best, best_start = total, start
    return best_start, best_start + width


# Palabras de narración de partido: donde más se dicen por minuto, ahí está el partido
# (antes y después hay previa, entrevistas y ambiente del Palau, que también suenan fuerte).
GAME_WORDS = re.compile(
    r"\b(canasta|triple|rebote|falta|tiros? libres?|bloqueo|asistencia|contraataque|tap[oó]n|mate|"
    r"p[eé]rdida|robo|posesi[oó]n|cuarto|segundos|puntos|defensa|ataque|bal[oó]n|tiempo muerto|"
    r"suspensi[oó]n|bandeja|alley|aro|tablero|zona|banquillo|lanza|anota|fallo|falla|dentro)\b", re.I)


def game_window_by_words(mp3, minutes, workdir):
    """Transcribe con Whisper tiny y busca los `minutes` con más palabras de partido.

    Devuelve (inicio, fin, palabras por minuto) en segundos del podcast, o None si falla.
    """
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        return None
    wav = workdir / "voz.wav"
    run("ffmpeg", "-loglevel", "error", "-y", "-i", mp3, "-ac", "1", "-ar", "16000", wav)
    model = WhisperModel("tiny", device="cpu", compute_type="int8", cpu_threads=os.cpu_count() or 4)
    segments, _ = model.transcribe(str(wav), language="es", beam_size=1, vad_filter=True,
                                   condition_on_previous_text=False)
    per_minute = {}
    for seg in segments:
        per_minute[int(seg.start // 60)] = per_minute.get(int(seg.start // 60), 0) + len(GAME_WORDS.findall(seg.text))
    wav.unlink()
    if not per_minute:
        return None
    last = max(per_minute) + 1
    counts = [per_minute.get(m, 0) for m in range(last)]
    width = min(minutes, last)
    best, best_start = -1, 0
    for start in range(0, last - width + 1):
        total = sum(counts[start:start + width])
        if total > best:
            best, best_start = total, start
    # Se ajustan los bordes al primer y último minuto con narración de verdad (≥2 palabras).
    lo, hi = best_start, best_start + width
    while lo < hi and counts[lo] < 2:
        lo += 1
    while hi > lo and counts[hi - 1] < 2:
        hi -= 1
    return lo * 60, hi * 60, counts


def pick_peaks(score, lo, hi, cfg):
    """Picos más altos dentro del partido hasta llenar los minutos objetivo."""
    clip = cfg["antes_del_grito"] + cfg["despues_del_grito"]
    want = int(cfg["minutos_objetivo"] * 60 / clip)
    order = sorted(range(lo, hi), key=lambda i: score[i], reverse=True)
    chosen = []
    for i in order:
        if score[i] <= 0 or len(chosen) >= want:
            break
        if all(abs(i - j) >= cfg["separacion_minima"] for j in chosen):
            chosen.append(i)
    return sorted(chosen)


# --- 2) Vídeo -----------------------------------------------------------------------

def download_sections(vod_url, sections, workdir):
    """Baja de Twitch solo los trozos pedidos [(inicio, fin)] en segundos del directo."""
    files = []
    for n, (a, b) in enumerate(sections):
        out = workdir / f"trozo-{n:03d}.mp4"
        run("yt-dlp", "--no-warnings", "--quiet", "-f", "best[height<=1080]/best",
            "--download-sections", f"*{a:.1f}-{b:.1f}", "-o", out, vod_url)
        files.append(out)
    return files


NORMALIZE = ("scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2,"
             "setsar=1,fps=30,format=yuv420p")


def esc(text):
    return text.replace("\\", "\\\\").replace(":", "\\:").replace("'", "’").replace("%", "\\%")


def card(path, seconds, lines, color=NAVY):
    """Tarjeta de color con texto centrado (portada y cierre), con audio en silencio."""
    draws = []
    total = len(lines)
    for k, (text, size, fill) in enumerate(lines):
        y = f"(h-text_h)/2+{(k - (total - 1) / 2) * size * 1.25:.0f}"
        draws.append(f"drawtext=fontfile='{FONT}':text='{esc(text)}':fontsize={size}:fontcolor={fill}:x=(w-text_w)/2:y={y}")
    run("ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", f"color=c={color}:s=1920x1080:r=30:d={seconds}",
        "-f", "lavfi", "-i", f"anullsrc=r=48000:cl=stereo", "-t", seconds, "-vf", ",".join(draws) + ",format=yuv420p",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-c:a", "aac", "-b:a", "160k", "-ar", "48000", path)


def build_resumen(clips, intro, outro, out, workdir):
    """Une portada + jugadas (con un fundido corto) + cierre, con la marca arriba a la derecha."""
    normal = []
    for n, clip in enumerate(clips):
        fixed = workdir / f"n-{n:03d}.mp4"
        run("ffmpeg", "-loglevel", "error", "-y", "-i", clip, "-vf",
            f"{NORMALIZE},fade=t=in:st=0:d=0.25,drawtext=fontfile='{FONT}':text='pickandroll.tv':fontsize=46:"
            f"fontcolor=white:box=1:boxcolor={GARNET}@0.9:boxborderw=16:x=w-tw-40:y=40",
            "-af", "aresample=48000,afade=t=in:st=0:d=0.25", "-ac", "2",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-c:a", "aac", "-b:a", "160k", fixed)
        normal.append(fixed)
    lista = workdir / "lista.txt"
    lista.write_text("".join(f"file '{p}'\n" for p in [intro, *normal, outro]))
    joined = workdir / "unido.mp4"
    run("ffmpeg", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0", "-i", lista, "-c", "copy", joined)
    # Volumen de YouTube (-14 LUFS) en una sola pasada.
    run("ffmpeg", "-loglevel", "error", "-y", "-i", joined, "-c:v", "copy", "-af", "loudnorm=I=-14:TP=-1.5:LRA=11",
        "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", out)


def build_short(clip, hook, out):
    """9:16: el directo encajado en el centro sobre su propio fondo desenfocado, con el gancho arriba."""
    run("ffmpeg", "-loglevel", "error", "-y", "-i", clip, "-filter_complex",
        "[0:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=30:5,eq=brightness=-0.15[bg];"
        "[0:v]scale=1080:-2[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2,"
        f"drawtext=fontfile='{FONT}':text='{esc(hook)}':fontsize=92:fontcolor={NAVY}:box=1:boxcolor={YELLOW}:"
        "boxborderw=26:x=(w-text_w)/2:y=330,"
        f"drawtext=fontfile='{FONT}':text='pickandroll.tv':fontsize=60:fontcolor=white:box=1:boxcolor={GARNET}:"
        "boxborderw=18:x=(w-text_w)/2:y=h-420,fps=30,format=yuv420p[v]",
        "-map", "[v]", "-map", "0:a", "-af", "loudnorm=I=-14:TP=-1.5", "-ar", "48000",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-c:a", "aac", "-b:a", "160k",
        "-movflags", "+faststart", out)


# --- 3) Textos ---------------------------------------------------------------------

def teams_and_comp(episode, config):
    title = episode_title(episode, config)
    match, _, comp = title.partition(" | ")
    found = re.match(r"(.+?)\s+(\d{2,3}-\d{2,3}|vs)\s+(.+)$", match)
    home, score, away = found.groups() if found else (match, "vs", "")
    comp = comp.replace("EuroLeague", "Euroliga")
    return home, (None if score == "vs" else score), away, comp, title


def short_team(name):
    return re.sub(r"\s+(Basket(ball)?|Bàsquet|Baloncesto)$", "", name).strip()


def texts(episode, config, chapters):
    home, score, away, comp, _ = teams_and_comp(episode, config)
    h, a = short_team(home), short_team(away)
    marcador = f"{h} {score} {a}" if score else f"{h} vs {a}"
    titulo = f"RESUMEN {marcador} | {comp} narrado en directo"
    if len(titulo) > 100:
        titulo = f"RESUMEN {marcador} | {comp}"[:100]
    fecha = datetime.datetime.fromisoformat(episode["published"]).strftime("%d/%m/%Y")
    desc = [
        f"Resumen del {marcador} ({comp}, {fecha}) con las mejores jugadas tal y como las vivimos en la narración en directo de PickandRollTV.",
        "",
        "Capítulos:",
        *chapters,
        "",
        f"Directo completo: {episode['link']}",
        "Podcast en Spotify: busca PickandRollTV",
        "Noticias y crónicas del Barça Basket: https://pickandroll.tv",
        "Suscríbete y activa la campana para no perderte ningún directo: https://www.youtube.com/@PickandRollTV?sub_confirmation=1",
        "",
        f"#BarçaBasket #{re.sub(r'[^A-Za-z]', '', comp.split()[0])} #PickandRollTV",
    ]
    comp_tag = comp.split(" Jornada")[0]
    etiquetas = [
        f"{h} {a}", f"{h} vs {a}", f"resumen {h} {a}", f"{h} {a} resumen", f"{h} {a} {comp_tag.lower()}",
        "barça basket", "fc barcelona basket", "barça baloncesto", comp_tag.lower(),
        f"{comp_tag.lower()} resumen", "resumen baloncesto", "narración en directo", "pickandrolltv",
        "pickandroll", "baloncesto", "basket",
    ]
    hook = f"{h} {score} {a}".upper() if score else f"{h} - {a}".upper()
    titulo_short = f"{marcador}: ¡así lo cantamos! #shorts"[:100]
    return {
        "titulo": titulo,
        "descripcion": "\n".join(desc),
        "etiquetas": list(dict.fromkeys(t for t in etiquetas if t.strip())),
        "titulo_short": titulo_short,
        "descripcion_short": f"La jugada del {marcador} ({comp}) narrada en directo por PickandRollTV. Resumen completo en el canal.\n#BarçaBasket #PickandRollTV #shorts",
        "gancho_short": hook,
        "marcador": marcador,
        "competicion": comp,
    }


def mmss(seconds):
    seconds = int(seconds)
    return f"{seconds // 60}:{seconds % 60:02d}"


# --- 4) Principal -------------------------------------------------------------------

def vod_offset(episode):
    """Segundos que el podcast recortó al principio: duración del directo menos la del MP3."""
    info = json.loads(run("yt-dlp", "--no-warnings", "--skip-download", "-j", episode["link"]).stdout)
    return max(0, int(info.get("duration") or 0) - int(episode["duration"]))


def upload(tag, title, files):
    repo = os.environ["GITHUB_REPOSITORY"]
    if subprocess.run(["gh", "release", "view", tag, "--repo", repo], capture_output=True).returncode == 0:
        run("gh", "release", "upload", tag, *files, "--repo", repo, "--clobber")
    else:
        run("gh", "release", "create", tag, *files, "--repo", repo, "--title", title,
            "--notes", "Resumen y Short del directo (se publican en YouTube automáticamente).")
    run("gh", "release", "edit", tag, "--repo", repo, "--draft=false")
    base = f"https://github.com/{repo}/releases/download/{tag}"
    return {pathlib.Path(f).name: f"{base}/{pathlib.Path(f).name}" for f in files}


def make(episode, config, cfg, workdir):
    vod = episode["vod_id"]
    mp3 = workdir / "audio.mp3"
    run("curl", "-sSL", "--fail", "-o", mp3, episode["audio_url"])
    levels = loudness_per_second(mp3)
    score = excitement(levels)
    found = game_window_by_words(mp3, cfg["minutos_partido"], workdir)
    if found:
        lo, hi, counts = found
        print("Palabras de partido por minuto:", counts)
    else:
        lo, hi = game_window(score, cfg["minutos_partido"])
    peaks = pick_peaks(score, lo, hi, cfg)
    if len(peaks) < 8:
        raise RuntimeError(f"Solo {len(peaks)} picos en el partido; no hay material para un resumen")
    offset = vod_offset(episode)
    sections = [(offset + max(0, p - cfg["antes_del_grito"]), offset + p + cfg["despues_del_grito"]) for p in peaks]
    print(f"{vod}: partido en {mmss(lo)}-{mmss(hi)} del podcast, {len(peaks)} jugadas, recorte inicial {offset} s")

    clips = download_sections(episode["link"], sections, workdir)
    home, score_txt, away, comp, _ = teams_and_comp(episode, config)
    h, a = short_team(home), short_team(away)
    intro = workdir / "intro.mp4"
    card(intro, 3, [("RESUMEN", 150, YELLOW), (f"{h} {score_txt or 'vs'} {a}".upper(), 110, "white"),
                    (comp.upper(), 64, "white")], color=GARNET)
    outro = workdir / "cierre.mp4"
    card(outro, cfg["segundos_cierre"], [("GRACIAS POR VERLO", 110, YELLOW), ("SUSCRÍBETE A PICKANDROLLTV", 80, "white"),
                                         ("pickandroll.tv", 64, "white")])
    resumen = workdir / "resumen.mp4"
    build_resumen(clips, intro, outro, resumen, workdir)

    # Capítulos de YouTube: portada en 0:00 y un capítulo cada ~4 jugadas, en tiempos del resumen.
    clip_len = cfg["antes_del_grito"] + cfg["despues_del_grito"]
    chapters = ["0:00 Inicio"]
    for k in range(0, len(peaks), 4):
        game_min = (peaks[k] - lo) // 60
        chapters.append(f"{mmss(3 + k * clip_len)} Jugadas desde el minuto {game_min} del directo")
    chapters.append(f"{mmss(3 + len(peaks) * clip_len)} Final")

    # Short: el pico más alto de todos, con más contexto antes del grito.
    best = max(peaks, key=lambda p: score[p])
    s_a = offset + max(0, best - (cfg["segundos_short"] - 7))
    (workdir / "short").mkdir()
    raw = download_sections(episode["link"], [(s_a, s_a + cfg["segundos_short"])], workdir / "short")[0]
    data = texts(episode, config, chapters)
    short = workdir / "short.mp4"
    build_short(raw, data["gancho_short"], short)

    thumb = workdir / "miniatura.jpg"
    published = datetime.datetime.fromisoformat(episode["published"])
    img = render_cover(episode_title(episode, config), published, True, pie="RESUMEN  ·  NARRADO EN DIRECTO", podcast=False)
    img.convert("RGB").resize((1280, 720)).save(thumb, quality=90, optimize=True)

    data.update({"vod_id": vod, "jugadas": len(peaks), "picos_podcast": peaks, "partido_podcast": [lo, hi],
                 "recorte_inicial": offset, "duracion": float(run("ffprobe", "-v", "error", "-show_entries",
                 "format=duration", "-of", "csv=p=0", resumen).stdout.strip())})
    datos = workdir / "datos.json"
    save_json(datos, data)
    urls = upload(f"resumen-{vod}", f"Resumen {data['marcador']}", [resumen, short, thumb, datos])
    return data, urls


def finished(entry):
    """Ya hecho, o fallado 3 veces (se deja de intentar para no gastar minutos de Actions)."""
    return bool(entry) and (entry.get("estado") != "error" or entry.get("intentos", 0) >= 3)


def main():
    config = load_json(CONFIG_FILE, {})
    cfg = {**DEFAULTS, **config.get("resumen", {})}
    episodes = load_json(EPISODES_FILE, [])
    done = load_json(RESUMENES_FILE, {})
    since = datetime.datetime.fromisoformat(cfg["desde"].replace("Z", "+00:00"))
    wanted = os.environ.get("RESUMEN_VOD", "").strip()
    pending = [e for e in episodes if is_match(e) and (
        e["vod_id"] == wanted if wanted else
        not finished(done.get(e["vod_id"])) and datetime.datetime.fromisoformat(e["published"]) >= since)]
    if not pending:
        print("Ningún directo nuevo para resumir")
        return 0
    episode = sorted(pending, key=lambda e: e["published"])[-1]
    with tempfile.TemporaryDirectory() as tmp:
        try:
            data, urls = make(episode, config, cfg, pathlib.Path(tmp))
        except Exception as error:
            detail = getattr(error, "stderr", "") or ""
            done[episode["vod_id"]] = {"estado": "error", "error": f"{error!r} {detail[-1500:]}",
                                       "intentos": done.get(episode["vod_id"], {}).get("intentos", 0) + 1}
            save_json(RESUMENES_FILE, done)
            print(f"Falló el resumen de {episode['vod_id']}: {error!r}\n{detail[-3000:]}", file=sys.stderr)
            return 1
    done[episode["vod_id"]] = {"estado": "listo", "titulo": data["titulo"], "marcador": data["marcador"],
                               "creado": datetime.datetime.now(datetime.timezone.utc).isoformat(), "archivos": urls}
    save_json(RESUMENES_FILE, done)
    print(f"Resumen listo: {data['titulo']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
