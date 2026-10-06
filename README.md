# Podcast automático de PickandRollTV

Cada directo que termina en el canal de YouTube se publica solo como episodio del
podcast **PickandRollTV** en Spotify (y en cualquier app que lea el RSS).

## Cómo funciona

1. Cada 15 minutos, GitHub Actions ejecuta `podcast.py`.
2. El script pregunta a la API de YouTube por los últimos vídeos del canal y se queda
   con los directos públicos que ya han terminado (espera 15 minutos tras el final).
3. Descarga solo el audio (MP3 mono a 96 kbps: unos 45 MB por hora de directo).
4. Sube el MP3 como *release* de este repositorio y añade el episodio a `episodes.json`.
5. Regenera `docs/feed.xml`, que GitHub Pages publica en
   `https://pickandrolltv.github.io/pickandroll-podcast/feed.xml`.
6. Spotify lee ese feed y muestra el episodio nuevo.

Solo se usa YouTube como fuente aunque el directo salga también en Twitch y Kick:
el contenido es el mismo y así no hay episodios duplicados.

## Puesta en marcha (una sola vez)

1. **Clave de la API de YouTube.** En <https://console.cloud.google.com/> crea un proyecto,
   activa *YouTube Data API v3* y en *Credenciales* crea una *clave de API*.
   Guárdala en este repositorio en *Settings → Secrets and variables → Actions* como
   secreto `YT_API_KEY`. Es gratis: el script gasta unas 200 unidades al día de las 10.000 diarias.
2. **Datos del podcast** en `config.json`: el ID del canal (`UC...`, aparece en
   <https://www.youtube.com/account_advanced>) y el email de propietario del podcast.
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

Solo se publican directos que terminen después de `publish_streams_after` en
`config.json`, para no republicar los que ya subiste a mano.

## Si YouTube bloquea la descarga

A veces YouTube pide "confirmar que no eres un robot" a los servidores de GitHub.
Hay dos soluciones:

- Exporta las cookies de YouTube de tu navegador (extensión *Get cookies.txt LOCALLY*)
  y guárdalas como secreto `YT_COOKIES`.
- O ejecuta el mismo script en tu ordenador con el Programador de tareas de Windows
  (`pip install yt-dlp`, ffmpeg y `gh` instalados, y las variables de entorno
  `YT_API_KEY` y `GITHUB_REPOSITORY`).

## Publicar un directo a mano

*Actions → Publicar directos en el podcast → Run workflow* lo ejecuta en el momento.
