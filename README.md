# Podcast automático de PickandRollTV

Cada directo que termina en el canal de Twitch se publica solo como episodio del
podcast **PickandRollTV** en Spotify (y en cualquier app que lea el RSS).

## Cómo funciona

1. Cada 15 minutos, GitHub Actions ejecuta `podcast.py`.
2. El script lista los últimos directos guardados (VODs) de twitch.tv/pickandrolltv
   y se queda con los que ya han terminado (15 minutos sin crecer) y duran más de
   `min_stream_minutes` (para saltarse los cortes cuando un directo se reinicia).
3. Descarga solo el audio (MP3 mono a 96 kbps: unos 45 MB por hora de directo).
4. Sube el MP3 como *release* de este repositorio y añade el episodio a `episodes.json`.
5. Regenera `docs/feed.xml`, que GitHub Pages publica en
   `https://pickandrolltv.github.io/pickandroll-podcast/docs/feed.xml`.
6. Spotify lee ese feed y muestra el episodio nuevo.

Se usa Twitch como fuente aunque el directo salga también en YouTube y Kick: el
contenido es el mismo, y YouTube bloquea las descargas desde los servidores de GitHub.
Twitch borra los VODs a los pocos días, pero el programa los publica a los 15 minutos.

## Puesta en marcha (una sola vez)

1. **Activar el guardado de directos en Twitch** (Configuración del creador →
   Transmisión → "Almacenar transmisiones anteriores"), si no lo está ya.
2. **Datos del podcast** en `config.json`: el canal de Twitch y el email de propietario.
3. **GitHub Pages.** *Settings → Pages → Deploy from a branch → main → /docs*.
4. **Importar los episodios antiguos.** *Actions → Importar episodios de Spotify for
   Creators → Run workflow*, pegando el RSS actual (Spotify for Creators →
   Configuración → Disponibilidad → RSS). Copia cada audio aquí y mantiene sus
   identificadores, para que Spotify no los duplique.
5. **Redirigir el feed.** En Spotify for Creators, en la configuración del programa,
   usa la opción de mover el podcast a otro proveedor y pon la URL del feed de arriba.
   Spotify conserva seguidores y episodios.

La cuenta atrás del principio se recorta sola: el programa escucha los primeros
15 minutos con Whisper (reconocimiento de voz) y corta justo antes del saludo
"Buenas tardes, bienvenidos a PickandRoll". Si no lo encuentra, recorta
`countdown_seconds` segundos de `config.json` (0 = no recorta nada).

Solo se publican directos que empiecen después de `publish_streams_after` en
`config.json`, para no republicar los que ya subiste a mano.

## Publicar un directo a mano

*Actions → Publicar directos en el podcast → Run workflow* lo ejecuta en el momento.

## Cómo se ve en Spotify

`presentacion.py` deja los títulos con un formato fijo ("Equipo vs Equipo | Competición
Jornada N"): quita emojis, "EN DIRECTO" y las mayúsculas. Todos los episodios usan la
portada del programa. La descripción del programa y el texto que acompaña a cada directo
están en `config.json` (`show.description` y `show.episode_blurb`).
