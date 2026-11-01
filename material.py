#!/usr/bin/env python3
"""Baja de Twitch un tramo del directo en trozos de 720p y transcribe la narración con marcas
por palabra, para montar a mano un resumen editado. Sube todo a la release material-<vod>.

Variables: VOD, DESDE, HASTA (segundos del directo), TROZO (segundos por archivo), MODELO.
"""
import json, os, pathlib, subprocess

vod = os.environ["VOD"]; a0 = int(os.environ["DESDE"]); a1 = int(os.environ["HASTA"])
step = int(os.environ.get("TROZO", "1500")); modelo = os.environ.get("MODELO", "small")
url = f"https://www.twitch.tv/videos/{vod}"
out = pathlib.Path("material"); out.mkdir(exist_ok=True)
repo = os.environ["GITHUB_REPOSITORY"]; tag = f"material-{vod}"

def run(*c):
    print(" ".join(map(str, c)), flush=True); subprocess.run(list(map(str, c)), check=True)

if subprocess.run(["gh", "release", "view", tag, "--repo", repo], capture_output=True).returncode != 0:
    run("gh", "release", "create", tag, "--repo", repo, "--title", f"Material de montaje {vod}",
        "--notes", "Trozos del directo y transcripción para montar el resumen a mano. No se publica.")

for n, s in [(int(os.environ.get("N", "0")), a0)]:
    e = min(a1, s + step)
    f = out / f"parte-{n:02d}-{s}.mp4"
    run("yt-dlp", "--no-warnings", "-f", "best[height<=720]/best", "--download-sections", f"*{s}-{e}",
        "--force-keyframes-at-cuts", "-o", f, url)
    wav = out / f"parte-{n:02d}.wav"
    run("ffmpeg", "-loglevel", "error", "-y", "-i", f, "-ac", "1", "-ar", "16000", wav)
    from faster_whisper import WhisperModel
    m = WhisperModel(modelo, device="cpu", compute_type="int8")
    segs, _ = m.transcribe(str(wav), language="es", word_timestamps=True, vad_filter=False,
                           initial_prompt="Narración en directo de PickandRollTV del Unicaja contra el Barça. Parra, Punter, Kravish, Perry, Hunt, Willy Hernangómez, Evbuomwan, Nkamhoua, Brizuela, Tyrese Martin, Justin Robinson, Umude.")
    data = [{"ini": round(s + g.start, 2), "fin": round(s + g.end, 2), "texto": g.text.strip(),
             "palabras": [[round(s + w.start, 2), round(s + w.end, 2), w.word] for w in (g.words or [])]} for g in segs]
    j = out / f"parte-{n:02d}-{s}.json"
    j.write_text(json.dumps(data, ensure_ascii=False))
    run("gh", "release", "upload", tag, f, j, "--repo", repo, "--clobber")
    f.unlink(); wav.unlink()
