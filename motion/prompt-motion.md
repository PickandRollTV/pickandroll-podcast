# Prompt de motion graphics: tarjetas del resumen en vídeo

Prompt para generar o rehacer la animación de las tarjetas que `resumen.py` pega en cada
resumen de partido: la portada (3 s), el cierre (20 s) y el gancho del Short vertical (24 s).
Hoy esas piezas las monta ffmpeg con colores y textos fijos. Este documento fija el diseño
para que una herramienta de motion (Canva, vidIQ u otra) produzca la versión animada con la
misma identidad.

## Prompt (copiar tal cual)

```
Diseña una animación de motion graphics para el canal de baloncesto en español
"PickandRollTV" (Barça Basket). Es una tarjeta de apertura de un vídeo resumen de un
partido, 16:9, 1920x1080, 30 fps, 3 segundos, con audio en silencio (luego se le añade la
narración).

Identidad:
- Fondo: granate sólido #A50044 (sin degradados ni texturas).
- Título principal: amarillo #FFD23F.
- Textos secundarios: blanco #FFFFFF.
- Tipografía: Barlow Condensed Black Italic para los títulos; Bebas Neue para cifras.
  Todo en mayúsculas en los títulos. Itálica con ángulo suave, nunca deformada.
- Logo: la marca "pickandroll.tv" en blanco, esquina superior derecha, con fondo granate
  más oscuro (#8A0037) en caja redondeada de 16 px.
- Acento secundario: azul marino #12082E solo para la tarjeta de cierre.

Secuencia (3 s):
1. 0.0–0.4 s: entra el fondo granate desde la izquierda con un barrido corto.
2. 0.4–1.2 s: "RESUMEN" aparece en amarillo, creciendo desde 90% a 100% con un rebote mínimo.
3. 1.2–2.2 s: debajo, el marcador "EQUIPO LOCAL 98-94 EQUIPO VISITANTE" en blanco, con
   fade-in por palabras. Si no hay marcador, usar "EQUIPO LOCAL VS EQUIPO VISITANTE".
4. 2.2–2.6 s: la competición ("EUROLIGA JORNADA 9") aparece en blanco, pequeña.
5. 2.6–3.0 s: corte limpio a negro o a la primera jugada (sin fundido largo).

Reglas:
- Sin movimiento de cámara, sin partículas, sin brillos de neón, sin fondos de estadio.
- Los textos deben poder leerse con el vídeo en móvil: nada por debajo de 48 px.
- Mantener el texto dentro de un margen de 120 px a cada lado.
- Exporta también una versión de la misma secuencia en 1080x1920 para el Short, con el
  gancho de la jugada ("BARÇA 98-94 VALENCIA") en amarillo sobre caja amarilla #FFD23F,
  texto granate #12082E, en el tercio superior, y "pickandroll.tv" en el tercio inferior.

Entrega: vídeo MP4 H.264, sin audio, 3 s (16:9) y 24 s (9:16, gancho en los primeros 3 s).
```

## Tarjeta de cierre (20 s, para la pantalla final de YouTube)

Fondo azul marino #12082E. Frases centradas, de arriba abajo:

- "GRACIAS POR VERLO" en amarillo #FFD23F (110 px).
- "SUSCRÍBETE A PICKANDROLLTV" en blanco (80 px).
- "pickandroll.tv" en blanco (64 px).

La pantalla final de YouTube se coloca encima de los últimos 20 segundos, así que los textos
deben quedar en el tercio central y no en los bordes.

## Valores de referencia del código

Estos son los valores que usa hoy `resumen.py` (no cambiarlos sin cambiar el prompt):

| Elemento | Valor |
|---|---|
| Granate | `0xa50044` (#A50044) |
| Amarillo | `0xffd23f` (#FFD23F) |
| Azul marino | `0x12082e` (#12082E) |
| Tipografía títulos | `fonts/BarlowCondensed-BlackItalic.ttf` |
| Tipografía marcador de miniatura | `fonts/BebasNeue-Regular.ttf` (en `miniatura_resumen.py`) |
| Duración portada | 3 s |
| Duración cierre | `resumen.segundos_cierre` en `config.json` (20 s) |
| Duración Short | `resumen.segundos_short` en `DEFAULTS` de `resumen.py` (24 s) |
| Formato Short | 1080x1920, directo encajado en el centro con fondo desenfocado |
| Volumen | -14 LUFS, pico -1.5 dBTP |

## Qué hacer con el prompt

- Úsalo como brief en la herramienta de motion que elijas. Si es Canva, `generate-design`
  o `generate-design-structured`; si es otra, pega el bloque entre comillas.
- El resultado es un MP4 sin audio. Para integrarlo, `resumen.py` tendría que aceptar el
  MP4 como tarjeta de intro/cierre en lugar de generarla con `card()`. Esa integración no
  está hecha todavía.
