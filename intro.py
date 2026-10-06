"""Encuentra en qué segundo empieza a hablar el presentador, para recortar la cuenta atrás.

Todos los directos empiezan con algo como "Buenas tardes, bienvenidos a PickandRoll,
bienvenidos a la magia del baloncesto". Transcribimos solo los primeros minutos con
Whisper y buscamos ese saludo.
"""
import re
import subprocess
import tempfile
import unicodedata

# Minutos del principio que se escuchan como máximo buscando el saludo.
SEARCH_SECONDS = 15 * 60
# Margen antes del saludo para no comerse la primera sílaba.
LEAD_IN_SECONDS = 1.0

GREETING = re.compile(r"\bbuen[oa]s? (tardes|dias|noches)\b")
WELCOME = re.compile(r"bienvenid\w* a (la )?(pick|pic|pi) ?(and|an|en|n|&)? ?r?oll?|magia del baloncesto")


def normalize(text):
    text = unicodedata.normalize("NFKD", text.lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9& ]+", " ", text).strip()


def find_greeting(segments):
    """Recibe (inicio, fin, texto) en orden y devuelve el segundo donde empieza el saludo.

    Vale el primer "bienvenidos a PickandRoll" / "magia del baloncesto"; si justo antes
    (menos de 20 s) hay un "buenas tardes/días/noches", se corta desde ese saludo.
    """
    greeting_start = None
    for start, _end, text in segments:
        text = normalize(text)
        if GREETING.search(text) and greeting_start is None:
            greeting_start = start
        if WELCOME.search(text):
            if greeting_start is not None and start - greeting_start <= 20:
                return greeting_start
            return start
        if greeting_start is not None and start - greeting_start > 20:
            greeting_start = None
    return None


def transcribe_start(audio_path, model_size="small"):
    """Genera (inicio, fin, texto) de los primeros minutos; se para en cuanto se deja de leer."""
    from faster_whisper import WhisperModel

    with tempfile.TemporaryDirectory() as tmp:
        clip = f"{tmp}/inicio.wav"
        subprocess.run(
            ["ffmpeg", "-loglevel", "error", "-y", "-i", str(audio_path), "-t", str(SEARCH_SECONDS),
             "-ac", "1", "-ar", "16000", clip],
            check=True,
        )
        model = WhisperModel(model_size, device="cpu", compute_type="int8")
        segments, _info = model.transcribe(clip, language="es", vad_filter=True, beam_size=1)
        for segment in segments:
            yield segment.start, segment.end, segment.text


def intro_offset(audio_path, fallback_seconds=0):
    """Segundos a recortar del principio, o fallback_seconds si no se encuentra el saludo."""
    try:
        found = find_greeting(transcribe_start(audio_path))
    except Exception as error:  # Sin modelo o sin red: mejor publicar entero que no publicar.
        print(f"  No se pudo buscar el saludo ({error}); uso {fallback_seconds} s")
        return fallback_seconds
    if found is None:
        print(f"  No encontré el saludo en los primeros minutos; uso {fallback_seconds} s")
        return fallback_seconds
    print(f"  Saludo encontrado en {int(found // 60)}:{int(found % 60):02d}")
    return max(found - LEAD_IN_SECONDS, 0)
