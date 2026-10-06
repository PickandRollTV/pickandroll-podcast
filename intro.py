"""Encuentra en qué segundo empieza a hablar el presentador, para recortar la cuenta atrás.

Todos los directos empiezan con algo como "Buenas tardes, bienvenidos a PickandRoll,
bienvenidos a la magia del baloncesto". Transcribimos solo los primeros minutos con
Whisper y buscamos ese saludo.
"""
import re
import subprocess
import unicodedata

# Minutos del principio que se escuchan como máximo buscando el saludo.
SEARCH_SECONDS = 15 * 60
# Margen antes del saludo para no comerse la primera sílaba.
LEAD_IN_SECONDS = 1.0

GREETING = re.compile(r"\bbuen[oa]s? (tardes|dias|noches)\b")
# Whisper escribe "PickandRoll" de mil maneras ("Peak and Road"...), así que basta con
# "bienvenidos": la cuenta atrás es música e himno, y ahí no se dice.
WELCOME = re.compile(r"\bbienvenid[oa]s?\b|magia del (baloncesto|palau)")


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
    import numpy
    from faster_whisper import WhisperModel

    # Decodificamos con ffmpeg a muestras de 16 kHz en lugar de dejar que lo haga
    # faster-whisper con PyAV, que falla con algunas versiones de PyAV.
    pcm = subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-i", str(audio_path), "-t", str(SEARCH_SECONDS),
         "-ac", "1", "-ar", "16000", "-f", "f32le", "-"],
        check=True, capture_output=True,
    ).stdout
    samples = numpy.frombuffer(pcm, dtype=numpy.float32)
    model = WhisperModel(model_size, device="cpu", compute_type="int8")
    segments, _info = model.transcribe(samples, language="es", vad_filter=True, beam_size=1)
    for segment in segments:
        yield segment.start, segment.end, segment.text


def intro_offset(audio_path, fallback_seconds=0):
    """Devuelve (segundos a recortar, nota explicando por qué).

    Si no se encuentra el saludo se recortan fallback_seconds; la nota guarda lo que
    se oyó al principio para poder ajustar la búsqueda.
    """
    heard = []

    def remember(segments):
        for start, end, text in segments:
            heard.append(f"{int(start // 60)}:{int(start % 60):02d} {text.strip()}")
            yield start, end, text

    try:
        found = find_greeting(remember(transcribe_start(audio_path)))
    except Exception as error:  # Sin modelo o sin red: mejor publicar entero que no publicar.
        return fallback_seconds, f"No se pudo buscar el saludo: {error}"
    if found is None:
        return fallback_seconds, "No encontré el saludo. Oí: " + " | ".join(heard[:40])
    return max(found - LEAD_IN_SECONDS, 0), f"Saludo en {int(found // 60)}:{int(found % 60):02d}: " + " | ".join(heard[-3:])
