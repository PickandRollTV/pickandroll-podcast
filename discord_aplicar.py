#!/usr/bin/env python3
"""Aplica al servidor de Discord la nueva estructura propuesta en la auditoría.

Sin MODO=aplicar solo enseña lo que haría, sin tocar nada.

Qué hace:
  - Ordena los canales en categorías claras y les quita las letras decorativas.
  - No borra nada: los canales que sobran pasan a la categoría oculta "Archivo",
    con todos sus mensajes.
  - Crea #anuncios, el foro #partidos y #zona-sub para los suscriptores de Twitch.
  - Pone en solo lectura los canales de información. La categoría de voz, Parquet y
    Lounge no se tocan.
  - Ajustes: notificaciones solo con menciones, filtro de contenido explícito,
    AutoMod, Comunidad con pantalla de bienvenida e invitación permanente.
  - Con ROLES=si, quita al rol MVP los permisos de moderación y crea el rol Moderador
    (vacío: lo asigna el dueño a quien quiera).

Antes de cambiar nada guarda el estado completo en auditoria/antes-de-aplicar.json,
y al acabar apunta cada cambio en auditoria/cambios.md.

Variables de entorno:
  DISCORD_BOT_TOKEN   token del bot (secreto del repositorio)
  MODO                "aplicar" para hacer los cambios; cualquier otra cosa solo los enseña
  ROLES               "si" para cambiar también los roles
  ACCION              "lista-mvp" para enviar al dueño del servidor, por mensaje privado de Discord,
                      la lista de miembros con el rol MVP (no toca nada más);
                      "quitar-mvp" para quitar el rol MVP a los números de esa lista indicados
                      en NUMEROS (por ejemplo "4,5,12"), si la lista sigue teniendo TOTAL_MVP miembros;
                      "avisos" para crear los roles de avisos (Directos, Noticias web, Partidos), el canal
                      #directo y el menú de entrada (Onboarding) en el que cada miembro elige qué avisos quiere
"""
import json
import os
import pathlib
import re
import sys
import time
import urllib.error
import urllib.request

from discord_web import with_utm

ROOT = pathlib.Path(__file__).resolve().parent
OUT_DIR = ROOT / "auditoria"
API = os.environ.get("DISCORD_API", "https://discord.com/api/v10")
GUILD = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))["discord"]["guild_id"]

VIEW, SEND, REACT, HISTORY = 1 << 10, 1 << 11, 1 << 6, 1 << 16
CONNECT, SPEAK = 1 << 20, 1 << 21
THREADS = (1 << 35) | (1 << 36) | (1 << 38)  # crear hilos públicos y privados, escribir en hilos
MODERATION = (1 << 1) | (1 << 2) | (1 << 3) | (1 << 4) | (1 << 5) | (1 << 13) | (1 << 17) | (1 << 28) | (1 << 40)
MEMBER_BASICS = VIEW | SEND | REACT | HISTORY | CONNECT | SPEAK | THREADS | (1 << 14) | (1 << 15)  # + enlaces y archivos

# Canales actuales (ids de la auditoría) y adónde van.
CATEGORIES = {
    "inicio": {"id": "929099438989905961", "name": "📌 𝗜𝗡𝗜𝗖𝗜𝗢", "position": 0},
    "pickandroll": {"id": "929099439426121728", "name": "🏀 𝗣𝗜𝗖𝗞𝗔𝗡𝗗𝗥𝗢𝗟𝗟", "position": 1},
    "sub": {"name": "⭐ 𝗭𝗢𝗡𝗔 𝗦𝗨𝗕", "position": 2},
    "staff": {"name": "🔒 𝗦𝗧𝗔𝗙𝗙", "position": 8},
    "archivo": {"name": "🗄️ 𝗔𝗥𝗖𝗛𝗜𝗩𝗢", "position": 9},
}
CHANNELS = [
    # (id o None para crear, nombre, tipo, categoría, acceso, tema)
    ("959459731578167427", "👋┃bienvenida", 0, "inicio", "lectura", "Te damos la bienvenida a PickandRollTV. Empieza por <#929099438989905962>."),
    ("929099438989905962", "📜┃normas", 0, "inicio", "lectura", "Normas del servidor. Léelas antes de escribir."),
    (None, "📢┃anuncios", 5, "inicio", "lectura", "Directos, novedades y avisos de PickandRollTV."),
    ("956699792086560768", "📰┃noticias-web", 0, "inicio", "lectura", "Cada noticia nueva de pickandroll.tv, al momento."),
    ("929099439426121729", "💬┃general", 0, "pickandroll", "abierto", "Charla de Barça, Euroliga, ACB y NBA."),
    (None, "🏟️┃partidos", 15, "pickandroll", "abierto", "Un hilo por partido: previa, directo y postpartido."),
    ("1252234382425718805", "🔄┃mercado-y-plantilla", 0, "pickandroll", "abierto", "Fichajes, rumores y plantilla del Barça."),
    ("929099439426121731", "💡┃ideas-y-propuestas", 0, "pickandroll", "abierto", "¿Qué te gustaría ver en el canal? Propón contenido y mejoras."),
    ("1252586051755573341", "❤️┃apoya-el-canal", 0, "pickandroll", "lectura", "Web, donaciones, merchandising y patrocinadores de PickandRollTV."),
    (None, "⭐┃zona-sub", 0, "sub", "subs", "Canal exclusivo para suscriptores de Twitch."),
    ("929099439426121730", "🎬┃material-para-el-canal", 0, "staff", "staff", None),
    ("982406567540441099", "🎵┃bot-musica", 0, "staff", "staff", None),
    ("1250872435880886324", "👕┃merchandising", 0, "staff", "staff", None),
    ("1251187799017787413", "tertulia", 0, "archivo", "oculto", None),
    ("1248574516070846535", "propuestas-contenido", 0, "archivo", "oculto", None),
    ("929099438989905963", "plataformas", 0, "archivo", "oculto", None),
    ("1250163184107655229", "patrocinadores", 0, "archivo", "oculto", None),
    ("929099439426121734", "banquillo", 2, "archivo", "oculto", None),
    ("959257658425225267", "invitado", 2, "archivo", "oculto", None),
]
# Roles de avisos que cada miembro elige al entrar (nombre, color, emoji, descripción).
NOTIFY_ROLES = [
    ("📰 Noticias web", 0xA50044, "📰", "Aviso con cada noticia del Barça en pickandroll.tv (recomendado)"),
    ("🔴 Directos", 0xE91916, "🔴", "Aviso cuando PickandRollTV empieza directo"),
    ("🏀 Partidos", 0xEDBB00, "🏀", "Aviso cuando se abre el hilo de cada partido"),
]
DONATIONS_URL = "https://buymeacoffee.com/pickandrolltv"
DONATIONS_CHANNEL = ("☕┃donaciones", "Invítanos a un café en Buy Me a Coffee y ayuda a que PickandRollTV siga creciendo.")
DIRECT_CHANNEL = ("🔴┃directo", "Chat para comentar el directo de PickandRollTV en Twitch mientras está en marcha.")
# Nombres anteriores → nombres con el estilo actual (acción "estetica").
RENAMES = {
    "📌 Empieza aquí": "📌 𝗜𝗡𝗜𝗖𝗜𝗢",
    "🏀 PickandRoll": "🏀 𝗣𝗜𝗖𝗞𝗔𝗡𝗗𝗥𝗢𝗟𝗟",
    "⭐ Zona Sub": "⭐ 𝗭𝗢𝗡𝗔 𝗦𝗨𝗕",
    "🔒 Staff": "🔒 𝗦𝗧𝗔𝗙𝗙",
    "🗄️ Archivo": "🗄️ 𝗔𝗥𝗖𝗛𝗜𝗩𝗢",
    "👋-bienvenida": "👋┃bienvenida",
    "📜-normas": "📜┃normas",
    "📢-anuncios": "📢┃anuncios",
    "📰-noticias-web": "📰┃noticias-web",
    "💬-general": "💬┃general",
    "🔴-directo": "🔴┃directo",
    "🏟️-partidos": "🏟️┃partidos",
    "🔄-mercado-y-plantilla": "🔄┃mercado-y-plantilla",
    "💡-ideas-y-propuestas": "💡┃ideas-y-propuestas",
    "❤️-apoya-el-canal": "❤️┃apoya-el-canal",
    "⭐-zona-sub": "⭐┃zona-sub",
    "material-para-el-canal": "🎬┃material-para-el-canal",
    "bot-musica": "🎵┃bot-musica",
    "merchandising": "👕┃merchandising",
}
FORUM_TAGS = ["Euroliga", "Liga Endesa", "Copa del Rey", "Supercopa", "Amistoso"]


class Discord:
    def __init__(self, token, apply):
        self.token, self.apply, self.log = token, apply, []

    def call(self, method, path, body=None, note=None, force=False):
        if method != "GET" and not force:
            self.log.append(f"- {note or method + ' ' + path}")
            print(("APLICO  " if self.apply else "HARÍA   ") + (note or path))
            if not self.apply:
                return {"id": f"nuevo:{path}"}
        for _ in range(6):
            request = urllib.request.Request(
                API + path, method=method,
                data=json.dumps(body).encode() if body is not None else None,
                headers={"Authorization": f"Bot {self.token}", "Content-Type": "application/json",
                         "User-Agent": "DiscordBot (https://pickandroll.tv, 1.0) PickandRollTV",
                         "X-Audit-Log-Reason": "Reorganizacion PickandRollTV"},
            )
            try:
                with urllib.request.urlopen(request, timeout=30) as response:
                    raw = response.read()
                    time.sleep(0.6)
                    return json.loads(raw) if raw else {}
            except urllib.error.HTTPError as error:
                text = error.read()
                if error.code == 429:
                    time.sleep(float(json.loads(text or b"{}").get("retry_after", 2)) + 0.5)
                    continue
                raise RuntimeError(f"{method} {path}: {error.code} {text[:300]!r}") from error
        raise RuntimeError(f"{method} {path}: demasiados reintentos")


def overwrite(target, allow=0, deny=0, kind=0):
    return {"id": target, "type": kind, "allow": str(allow), "deny": str(deny)}


def access_overwrites(access, roles, channel_type):
    everyone, mvp, sub, mod = GUILD, roles.get("MVP 🏆"), roles.get("Twitch Subscriber"), roles.get("Moderador")
    staff = [r for r in (mvp, mod) if r]
    if access == "abierto":
        return [overwrite(everyone, VIEW | (CONNECT if channel_type == 2 else 0))]
    if access == "lectura":
        return [overwrite(everyone, VIEW | HISTORY | REACT, SEND | THREADS)] + [overwrite(r, SEND) for r in staff]
    if access == "subs":
        return [overwrite(everyone, 0, VIEW)] + [overwrite(r, VIEW | SEND | HISTORY) for r in [sub] + staff if r]
    if access == "staff":
        return [overwrite(everyone, 0, VIEW)] + [overwrite(r, VIEW | SEND | HISTORY) for r in staff]
    return [overwrite(everyone, 0, VIEW | CONNECT)]  # oculto


def mvp_members(api, roles_list):
    """Miembros con el rol MVP, en el mismo orden numerado que la lista enviada al dueño."""
    mvp = next(r["id"] for r in roles_list if r["name"] == "MVP 🏆")
    members, after = [], "0"
    while True:
        page = api.call("GET", f"/guilds/{GUILD}/members?limit=1000&after={after}")
        members += page
        if len(page) < 1000:
            break
        after = page[-1]["user"]["id"]
    rows = sorted((m.get("nick") or m["user"].get("global_name") or m["user"]["username"], m["user"]["username"], m["joined_at"][:10], m["user"]["id"])
                  for m in members if mvp in m["roles"])
    return mvp, rows


def dm_owner(api, guild, title, lines):
    dm = api.call("POST", "/users/@me/channels", {"recipient_id": guild["owner_id"]}, "Abrir mensaje privado con el dueño", force=True)
    chunk = title
    for line in lines:
        if len(chunk) + len(line) > 1900:
            api.call("POST", f"/channels/{dm['id']}/messages", {"content": chunk}, "Mensaje privado al dueño", force=True)
            chunk = ""
        chunk += "\n" + line
    api.call("POST", f"/channels/{dm['id']}/messages", {"content": chunk}, "Mensaje privado al dueño", force=True)


def send_mvp_list(api, guild, roles_list):
    """Manda al dueño del servidor la lista de MVP por mensaje privado: no se guarda en el repositorio."""
    _, mvps = mvp_members(api, roles_list)
    lines = [f"{i}. {shown} (@{user}), en el servidor desde {joined}" for i, (shown, user, joined, _) in enumerate(mvps, 1)]
    dm_owner(api, guild, f"**Miembros con el rol MVP 🏆 ({len(mvps)})**", lines)
    print(f"Lista de {len(mvps)} MVP enviada al dueño por mensaje privado")
    return 0


def remove_mvp(api, guild, roles_list, numbers, expected_total):
    """Quita el rol MVP a los números elegidos de la lista y avisa al dueño por privado de a quién."""
    mvp, mvps = mvp_members(api, roles_list)
    status = OUT_DIR / "quitar-mvp.txt"
    OUT_DIR.mkdir(exist_ok=True)
    me = api.call("GET", "/users/@me")["id"]
    bot_roles = set(api.call("GET", f"/guilds/{GUILD}/members/{me}")["roles"])
    position = {r["id"]: r["position"] for r in roles_list}
    if max((position[r] for r in bot_roles), default=0) <= position[mvp]:
        message = "El rol del bot está por debajo del rol MVP: hay que subirlo en Ajustes del servidor → Roles"
        print(message)
        status.write_text(message + "\n", encoding="utf-8")
        return 1
    if expected_total and len(mvps) != expected_total:
        message = f"La lista ha cambiado ({len(mvps)} MVP en vez de {expected_total}): no se quita nada"
        print(message)
        status.write_text(message + "\n", encoding="utf-8")
        return 1
    chosen = sorted({int(n) for n in numbers.replace(" ", "").split(",") if n})
    if not chosen or chosen[-1] > len(mvps) or chosen[0] < 1:
        print(f"Números fuera de la lista de {len(mvps)}: {chosen}")
        return 1
    removed = []
    for number in chosen:
        shown, user, _, user_id = mvps[number - 1]
        api.call("DELETE", f"/guilds/{GUILD}/members/{user_id}/roles/{mvp}", None, f"Quitar MVP al número {number}", force=True)
        removed.append(f"{number}. {shown} (@{user})")
    dm_owner(api, guild, f"**Rol MVP 🏆 retirado a {len(removed)} miembros**", removed)
    print(f"Rol MVP retirado a {len(removed)} miembros")
    status.write_text(f"Rol MVP retirado a {len(removed)} miembros; quedan {len(mvps) - len(removed)}\n", encoding="utf-8")
    return 0


def setup_notifications(api, channels, roles_list):
    """Roles de avisos, canal #directo y menú de entrada (Onboarding)."""
    roles = {r["name"]: r["id"] for r in roles_list}
    for name, color, _, _ in NOTIFY_ROLES:
        if name not in roles:
            created = api.call("POST", f"/guilds/{GUILD}/roles",
                               {"name": name, "color": color, "permissions": "0", "mentionable": False, "hoist": False},
                               f"Crear rol de avisos {name} (sin permisos)")
            roles[name] = created["id"]

    by_name = {c["name"]: c for c in channels}
    direct = by_name.get(DIRECT_CHANNEL[0])
    if not direct:
        general = by_name.get("💬┃general")
        direct = api.call("POST", f"/guilds/{GUILD}/channels", {
            "name": DIRECT_CHANNEL[0], "type": 0, "topic": DIRECT_CHANNEL[1],
            "parent_id": general["parent_id"] if general else CATEGORIES["pickandroll"]["id"],
            "position": (general or {}).get("position", 0) + 1,
            "permission_overwrites": [overwrite(GUILD, VIEW)],
        }, f"Crear {DIRECT_CHANNEL[0]} (🏀 PickandRoll, abierto)")
        by_name[DIRECT_CHANNEL[0]] = direct

    defaults = ["👋┃bienvenida", "📜┃normas", "📢┃anuncios", "📰┃noticias-web", "💬┃general", DIRECT_CHANNEL[0],
                "🏟️┃partidos", "🔄┃mercado-y-plantilla", "💡┃ideas-y-propuestas", "❤️┃apoya-el-canal"]
    default_ids = [by_name[n]["id"] for n in defaults if n in by_name]
    missing = [n for n in defaults if n not in by_name]
    if missing:
        print("Aviso: no encuentro estos canales para el menú de entrada: " + ", ".join(missing))
    # Discord pide ids con forma de snowflake para las preguntas y opciones nuevas.
    base = (int(time.time() * 1000) - 1420070400000) << 22
    api.call("PUT", f"/guilds/{GUILD}/onboarding", {
        "enabled": True,
        "mode": 0,
        "default_channel_ids": default_ids,
        "prompts": [{
            "id": str(base),
            "type": 0,
            "title": "¿De qué quieres que te avisemos?",
            "single_select": False,
            "required": False,
            "in_onboarding": True,
            "options": [{"id": str(base + i + 1), "title": name, "description": desc, "emoji": {"name": emoji},
                         "role_ids": [roles[name]], "channel_ids": []}
                        for i, (name, _, emoji, desc) in enumerate(NOTIFY_ROLES)],
        }],
    }, "Menú de entrada: elegir avisos (Directos, Noticias web, Partidos) y canales por defecto")

    if api.apply:
        ids = {name: roles[name] for name, *_ in NOTIFY_ROLES}
        (OUT_DIR / "roles-avisos.json").write_text(json.dumps(ids, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    header = "# Avisos aplicados\n\n" if api.apply else "# Avisos que se aplicarían (prueba)\n\n"
    (OUT_DIR / "avisos.md").write_text(header + "\n".join(api.log) + "\n", encoding="utf-8")
    print(f"{len(api.log)} cambios {'aplicados' if api.apply else 'previstos'}")
    return 0


def restyle(api, channels):
    """Pone a categorías y canales el estilo con emote, separador ┃ y negrita. La voz no se toca."""
    for channel in channels:
        new = RENAMES.get(channel["name"])
        if new and channel["type"] != 2:
            api.call("PATCH", f"/channels/{channel['id']}", {"name": new}, f"{channel['name']} → {new}")
    header = "# Estética aplicada\n\n" if api.apply else "# Estética que se aplicaría (prueba)\n\n"
    (OUT_DIR / "estetica.md").write_text(header + "\n".join(api.log) + "\n", encoding="utf-8")
    print(f"{len(api.log)} cambios {'aplicados' if api.apply else 'previstos'}")
    return 0


def build_messages(by_name):
    """Mensajes fijos del servidor: bienvenida, normas y apoyo. Cada uno es una lista de embeds."""
    cfg = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    ch = {name: f"<#{c['id']}>" for name, c in by_name.items()}
    links = " · ".join(f"[{name}]({url})" for name, url in cfg["social_links"])
    color, logo = 0xA50044, cfg["show"]["image"]
    web = lambda campaign: with_utm(cfg["website_url"], campaign)
    return {
        "👋┃bienvenida": [{
            "title": "🏀 Bienvenido a PickandRollTV",
            "url": web("bienvenida"),
            "description": ("La comunidad del **Barça Basket**, la **Euroliga**, la **Liga Endesa** y la **NBA** en español.\n"
                            "Directos de cada partido, postpartidos, noticias y tertulia con gente que vive el baloncesto."),
            "color": color, "thumbnail": {"url": logo},
            "fields": [
                {"name": "🌐 Nuestra casa: pickandroll.tv", "value": f"Noticias, previas, crónicas y análisis del Barça cada día.\n**[👉 Entra en pickandroll.tv]({web('bienvenida')})**", "inline": False},
                {"name": "📌 Para empezar", "value": f"1. Lee las {ch.get('📜┃normas', '#normas')}\n2. Elige tus avisos en <id:customize>\n3. Preséntate en {ch.get('💬┃general', '#general')}", "inline": False},
                {"name": "💬 Dónde hablar", "value": f"{ch.get('💬┃general', '')} charla de baloncesto\n{ch.get('🏟️┃partidos', '')} un hilo por partido\n{ch.get('🔴┃directo', '')} durante los directos\n{ch.get('🔄┃mercado-y-plantilla', '')} fichajes y rumores", "inline": True},
                {"name": "📣 Para estar al día", "value": f"{ch.get('📢┃anuncios', '')} directos y novedades\n{ch.get('📰┃noticias-web', '')} las noticias del Barça de la web\n{ch.get('💡┃ideas-y-propuestas', '')} propón contenido", "inline": True},
                {"name": "🔗 PickandRollTV", "value": links, "inline": False},
            ],
            "footer": {"text": "Bienvenidos a la magia del baloncesto"},
        }],
        "📜┃normas": [{
            "title": "📜 Normas de la comunidad",
            "description": "Para que esto siga siendo el mejor sitio para hablar de baloncesto:",
            "color": color,
            "fields": [
                {"name": "1️⃣ Respeto ante todo", "value": "Debate lo que quieras, pero sin insultos, ataques personales ni discriminación de ningún tipo.", "inline": False},
                {"name": "2️⃣ Cada tema en su canal", "value": f"Partidos en {ch.get('🏟️┃partidos', '#partidos')}, fichajes en {ch.get('🔄┃mercado-y-plantilla', '#mercado')} y el resto en {ch.get('💬┃general', '#general')}.", "inline": False},
                {"name": "3️⃣ Nada de spam ni publicidad", "value": "Ni invitaciones a otros servidores, ni promoción sin permiso, ni menciones masivas. AutoMod las bloquea.", "inline": False},
                {"name": "4️⃣ Cuidado con los spoilers", "value": "Si un partido acaba de terminar, usa ||spoiler|| en el resultado durante la primera hora.", "inline": False},
                {"name": "5️⃣ Contenido apto para todos", "value": "Nada de contenido explícito, violento o ilegal.", "inline": False},
                {"name": "6️⃣ Escucha al staff", "value": "Los moderadores pueden borrar mensajes, aislar o expulsar a quien no cumpla las normas.", "inline": False},
            ],
            "footer": {"text": "Al participar en el servidor aceptas estas normas y las de Discord"},
        }],
        "☕┃donaciones": [{
            "title": "☕ Invítanos a un café",
            "url": DONATIONS_URL,
            "description": ("El baloncesto es nuestra pasión, y PickandRollTV nació con la ilusión de compartirla con toda la comunidad.\n\n"
                            "Si te gusta lo que hacemos, puedes apoyarnos con un café en **Buy Me a Coffee**. Sin cuentas ni suscripciones: "
                            "eliges cuántos cafés y listo."),
            "color": 0xFFDD00, "thumbnail": {"url": logo},
            "fields": [
                {"name": "👉 Apoya aquí", "value": f"**[buymeacoffee.com/pickandrolltv]({DONATIONS_URL})**", "inline": False},
            ],
            "footer": {"text": "Gracias por hacer posible PickandRollTV ❤️"},
        }],
        "❤️┃apoya-el-canal": [{
            "title": "❤️ Apoya a PickandRollTV",
            "description": "PickandRollTV es un proyecto independiente. Así puedes ayudarnos a crecer:",
            "color": color, "thumbnail": {"url": logo},
            "fields": [
                {"name": "☕ Invítanos a un café", "value": f"[buymeacoffee.com/pickandrolltv]({DONATIONS_URL}). ¡Gracias por tu apoyo!", "inline": False},
                {"name": "⭐ Suscríbete en Twitch", "value": f"[twitch.tv/{cfg['twitch_channel']}]({cfg['twitch_url']}). Los subs tenéis acceso a la ⭐ Zona Sub.", "inline": False},
                {"name": "📰 Lee y comparte la web", "value": f"[pickandroll.tv]({web('apoya')}). Cada visita nos ayuda.", "inline": False},
                {"name": "▶️ Síguenos en todas partes", "value": links, "inline": False},
                {"name": "📣 Invita a tus amigos", "value": "https://discord.gg/USweNvJ4tY", "inline": False},
            ],
        }],
    }


def embed_to_text(embed):
    """Pasa una tarjeta a texto con formato de Discord, para que se vea aunque alguien tenga desactivadas las tarjetas."""
    # Los títulos van sin enlace: Discord no pinta enlaces dentro de un encabezado.
    parts = [f"## {embed['title']}"]
    if embed.get("description"):
        parts.append(embed["description"])
    parts += [f"**{field['name']}**\n{field['value']}" for field in embed.get("fields", [])]
    if embed.get("footer"):
        parts.append(f"-# {embed['footer']['text']}")
    # Los <> evitan que cada enlace añada su propia vista previa.
    return re.sub(r"\]\((https?://[^)\s>]+)\)", r"](<\1>)", "\n\n".join(parts))


def post_messages(api, channels, roles_list):
    """Publica (o actualiza, si ya están) los mensajes fijos del servidor."""
    by_name = {c["name"]: c for c in channels}
    if DONATIONS_CHANNEL[0] not in by_name:
        roles = {r["name"]: r["id"] for r in roles_list}
        support = by_name.get("❤️┃apoya-el-canal")
        by_name[DONATIONS_CHANNEL[0]] = api.call("POST", f"/guilds/{GUILD}/channels", {
            "name": DONATIONS_CHANNEL[0], "type": 0, "topic": DONATIONS_CHANNEL[1],
            "parent_id": support["parent_id"] if support else CATEGORIES["pickandroll"]["id"],
            "position": (support or {}).get("position", 0) + 1,
            "permission_overwrites": access_overwrites("lectura", roles, 0),
        }, f"Crear {DONATIONS_CHANNEL[0]} (🏀 PickandRoll, lectura)")
    store = OUT_DIR / "mensajes.json"
    sent = json.loads(store.read_text(encoding="utf-8")) if store.exists() else {}
    for name, embeds in build_messages(by_name).items():
        channel = by_name.get(name)
        if not channel:
            print(f"Aviso: no encuentro {name}")
            continue
        body = {"content": "\n\n".join(embed_to_text(e) for e in embeds)[:2000], "embeds": [], "allowed_mentions": {"parse": []}}
        old = sent.get(channel["id"])
        if old:
            api.call("PATCH", f"/channels/{channel['id']}/messages/{old}", body, f"Actualizar mensaje de {name}")
        else:
            created = api.call("POST", f"/channels/{channel['id']}/messages", body, f"Publicar mensaje en {name}")
            sent[channel["id"]] = created["id"]
    if api.apply:
        store.write_text(json.dumps(sent, indent=2) + "\n", encoding="utf-8")
    print(f"{len(api.log)} mensajes {'publicados' if api.apply else 'previstos'}")
    return 0


def setup_moderation(api, channels, roles_list):
    """Quita a MVP los permisos de moderación y crea el rol Moderador con los mismos accesos de canal que MVP."""
    roles = {r["name"]: r for r in roles_list}
    mvp = roles.get("MVP 🏆")
    if not mvp:
        print("No encuentro el rol MVP 🏆")
        return 1
    if int(mvp["permissions"]) & MODERATION:
        api.call("PATCH", f"/guilds/{GUILD}/roles/{mvp['id']}", {"permissions": str(int(mvp["permissions"]) & ~MODERATION)},
                 "Rol MVP: quitar permisos de moderación (banear, expulsar, aislar, borrar mensajes, gestionar canales y roles)")
    mod = roles.get("Moderador")
    if not mod:
        mod = api.call("POST", f"/guilds/{GUILD}/roles",
                       {"name": "Moderador", "color": 0xA50044, "hoist": True,
                        "permissions": str(MEMBER_BASICS | (1 << 13) | (1 << 40) | (1 << 1))},
                       "Crear rol Moderador (gestionar mensajes, aislar y expulsar; sin banear)")
    # Mismo acceso que MVP en los canales de texto (staff, solo lectura, zona sub). La voz no se toca.
    voice_parents = {c["id"] for c in channels if c["type"] == 4 and any(
        x["parent_id"] == c["id"] and x["type"] == 2 for x in channels if x.get("parent_id"))
        and not any(x["parent_id"] == c["id"] and x["type"] != 2 for x in channels if x.get("parent_id"))}
    for channel in channels:
        if channel["type"] == 2 or channel["id"] in voice_parents:
            continue
        for ow in channel.get("permission_overwrites", []):
            if ow["id"] == mvp["id"] and not any(o["id"] == mod["id"] for o in channel["permission_overwrites"]):
                api.call("PUT", f"/channels/{channel['id']}/permissions/{mod['id']}",
                         {"type": 0, "allow": ow["allow"], "deny": ow["deny"]},
                         f"Moderador: mismo acceso que MVP en {channel['name']}")
    # AutoMod no bloquea a los moderadores.
    for rule in api.call("GET", f"/guilds/{GUILD}/auto-moderation/rules"):
        if mod["id"] not in rule.get("exempt_roles", []) and not str(mod["id"]).startswith("nuevo:"):
            try:
                api.call("PATCH", f"/guilds/{GUILD}/auto-moderation/rules/{rule['id']}",
                         {"exempt_roles": rule.get("exempt_roles", []) + [mod["id"]]}, f"AutoMod {rule['name']}: excluir a Moderador")
            except RuntimeError as error:
                # Algunas reglas (las de Discord o de otros bots) no se dejan editar: no es grave.
                api.log[-1] += f" (no se pudo: {str(error)[-60:]})"
    header = "# Moderación aplicada\n\n" if api.apply else "# Moderación que se aplicaría (prueba)\n\n"
    (OUT_DIR / "moderacion.md").write_text(header + "\n".join(api.log) + "\n", encoding="utf-8")
    print(f"{len(api.log)} cambios {'aplicados' if api.apply else 'previstos'}")
    return 0


def boost_web(api, channels, roles_list):
    """Da protagonismo a pickandroll.tv: noticias arriba del todo, descripción, bienvenida, temas y menú de entrada."""
    by_name = {c["name"]: c for c in channels}
    news = by_name.get("📰┃noticias-web")
    if news:
        api.call("PATCH", f"/channels/{news['id']}", {"position": 0, "topic": "🌐 Las noticias del Barça en pickandroll.tv, al momento: previas, crónicas y análisis."},
                 "📰┃noticias-web: primer canal del servidor y tema nuevo")
    api.call("PATCH", f"/guilds/{GUILD}", {
        "description": "🌐 pickandroll.tv · La comunidad de PickandRollTV: Barça Basket, Euroliga, ACB y NBA. Noticias, directos y tertulia.",
    }, "Servidor: descripción con pickandroll.tv delante")
    welcome = [("📰┃noticias-web", "Lo último de pickandroll.tv", "📰"), ("📜┃normas", "Lee las normas", "📜"),
               ("💬┃general", "Habla de baloncesto", "💬"), ("🏟️┃partidos", "Comenta cada partido", "🏟️")]
    api.call("PATCH", f"/guilds/{GUILD}/welcome-screen", {
        "enabled": True,
        "description": "Baloncesto en español: Barça, Euroliga, ACB y NBA. Todas las noticias en pickandroll.tv",
        "welcome_channels": [{"channel_id": by_name[n]["id"], "description": d, "emoji_name": e} for n, d, e in welcome if n in by_name],
    }, "Pantalla de bienvenida: pickandroll.tv en primer lugar")
    for channel in channels:
        topic = channel.get("topic") or ""
        public = not any(o["id"] == GUILD and int(o["deny"]) & VIEW for o in channel.get("permission_overwrites", []))
        if channel["type"] in (0, 5, 15) and public and "pickandroll.tv" not in topic and channel["name"] in RENAMES.values():
            api.call("PATCH", f"/channels/{channel['id']}", {"topic": (topic + " · " if topic else "") + "🌐 pickandroll.tv"},
                     f"{channel['name']}: tema con pickandroll.tv")
    log = list(api.log)
    setup_notifications(api, channels, roles_list)  # vuelve a guardar el menú con 📰 Noticias web en primer lugar
    api.log = log + api.log[len(log):]
    header = "# Web aplicada\n\n" if api.apply else "# Web que se aplicaría (prueba)\n\n"
    (OUT_DIR / "web.md").write_text(header + "\n".join(api.log) + "\n", encoding="utf-8")
    return 0

# Repaso final: orden, temas y permisos (acción "repaso").
CHANNEL_ORDER = ["📰┃noticias-web", "👋┃bienvenida", "📜┃normas", "📢┃anuncios",
                 "💬┃general", "🏟️┃partidos", "🔴┃directo", "📱┃shorts", "🔄┃mercado-y-plantilla", "💡┃ideas-y-propuestas",
                 "❤️┃apoya-el-canal", "☕┃donaciones", "⭐┃zona-sub",
                 "🎬┃material-para-el-canal", "🎵┃bot-musica", "👕┃merchandising"]
CATEGORY_ORDER = ["📌 𝗜𝗡𝗜𝗖𝗜𝗢", "🏀 𝗣𝗜𝗖𝗞𝗔𝗡𝗗𝗥𝗢𝗟𝗟", "🔊 𝗩𝗢𝗭", "⭐ 𝗭𝗢𝗡𝗔 𝗦𝗨𝗕", "🔒 𝗦𝗧𝗔𝗙𝗙", "🗄️ 𝗔𝗥𝗖𝗛𝗜𝗩𝗢"]
TOPICS = {
    "👋┃bienvenida": "Te damos la bienvenida a PickandRollTV. Empieza por <#929099438989905962>. · 🌐 pickandroll.tv",
    "☕┃donaciones": "Invítanos a un café en Buy Me a Coffee y ayuda a que PickandRollTV siga creciendo. · 🌐 pickandroll.tv",
    "⭐┃zona-sub": "Canal exclusivo para suscriptores de Twitch. ¡Gracias por tu apoyo! · 🌐 pickandroll.tv",
    "🎬┃material-para-el-canal": "Clips, imágenes y material para los directos y la web.",
    "🎵┃bot-musica": "Comandos del bot de música.",
    "👕┃merchandising": "Ideas y diseños del merchandising de PickandRollTV.",
}
MENTION_EVERYONE = 1 << 17


def review(api, channels, roles_list):
    """Deja el servidor fino: categorías y canales en orden, temas completos y sin menciones a @everyone."""
    # Roles: solo el staff puede mencionar a @everyone.
    for role in roles_list:
        if not role.get("managed") and role["name"] not in ("Moderador",) and role["id"] != GUILD \
                and int(role["permissions"]) & MENTION_EVERYONE and not int(role["permissions"]) & 8:
            api.call("PATCH", f"/guilds/{GUILD}/roles/{role['id']}",
                     {"permissions": str(int(role["permissions"]) & ~MENTION_EVERYONE)},
                     f"Rol {role['name']}: sin permiso para mencionar a @everyone")
    # La categoría de voz solo cambia de nombre; Parquet y Lounge no se tocan.
    for channel in channels:
        if channel["type"] == 4 and channel["name"] == "Canales de voz":
            api.call("PATCH", f"/channels/{channel['id']}", {"name": "🔊 𝗩𝗢𝗭"}, "Canales de voz → 🔊 𝗩𝗢𝗭 (Parquet y Lounge sin tocar)")
            channel["name"] = "🔊 𝗩𝗢𝗭"
    by_name = {c["name"]: c for c in channels}
    positions = [{"id": by_name[n]["id"], "position": i} for i, n in enumerate(CATEGORY_ORDER) if n in by_name]
    positions += [{"id": by_name[n]["id"], "position": i} for i, n in enumerate(CHANNEL_ORDER) if n in by_name]
    archived = [c for c in channels if c["type"] in (0, 5, 15) and c["name"] not in CHANNEL_ORDER]
    positions += [{"id": c["id"], "position": len(CHANNEL_ORDER) + i}
                  for i, c in enumerate(sorted(archived, key=lambda c: c["position"]))]
    api.call("PATCH", f"/guilds/{GUILD}/channels", positions, "Ordenar categorías y canales de texto (sin tocar la voz)")
    for name, topic in TOPICS.items():
        channel = by_name.get(name)
        if channel and (channel.get("topic") or "") != topic:
            api.call("PATCH", f"/channels/{channel['id']}", {"topic": topic}, f"{name}: tema revisado")
    header = "# Repaso aplicado\n\n" if api.apply else "# Repaso que se aplicaría (prueba)\n\n"
    (OUT_DIR / "repaso.md").write_text(header + "\n".join(api.log) + "\n", encoding="utf-8")
    print(f"{len(api.log)} cambios {'aplicados' if api.apply else 'previstos'}")
    return 0


def main():
    token = os.environ.get("DISCORD_BOT_TOKEN", "").strip()
    if not token:
        print("Falta el secreto DISCORD_BOT_TOKEN")
        return 1
    action = os.environ.get("ACCION", "").strip()
    if action == "quitar-porra":
        # Borra las encuestas de porra de los hilos de partidos y las olvida.
        state_file = ROOT / "discord_partidos.json"
        state = json.loads(state_file.read_text(encoding="utf-8"))
        api = Discord(token, True)
        for key, entry in state.items():
            if not key.startswith("_") and entry.get("porra"):
                api.call("DELETE", f"/channels/{entry['thread']}/messages/{entry.pop('porra')}", note=f"Borrar porra {key}")
                entry.pop("porra_buena", None)
        state_file.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"{len(api.log)} porras borradas")
        return 0
    if action == "aviso":
        # Publica en #anuncios el texto de MENSAJE; {directos}, {partidos} y {noticias} mencionan a esos roles.
        api = Discord(token, True)
        ids = json.loads((OUT_DIR / "roles-avisos.json").read_text(encoding="utf-8"))
        roles = {"directos": ids["🔴 Directos"], "partidos": ids["🏀 Partidos"], "noticias": ids["📰 Noticias web"]}
        text = os.environ.get("MENSAJE", "").replace("\\n", "\n")
        used = [rid for key, rid in roles.items() if "{" + key + "}" in text]
        for key, rid in roles.items():
            text = text.replace("{" + key + "}", f"<@&{rid}>")
        channel = next(c for c in api.call("GET", f"/guilds/{GUILD}/channels") if c["name"] == "📢┃anuncios")
        api.call("POST", f"/channels/{channel['id']}/messages",
                 {"content": text[:2000], "allowed_mentions": {"parse": [], "roles": used}}, "Aviso en #anuncios")
        print("Aviso publicado")
        return 0
    if action == "partidos":
        # Abre ya los hilos de los partidos de los próximos 14 días.
        os.environ.setdefault("PARTIDOS_DIAS", "14")
        os.environ.setdefault("PARTIDOS_REHACER", "1")
        import discord_partidos
        return discord_partidos.main()
    apply = os.environ.get("MODO", "").strip().lower() == "aplicar" or action in ("avisos", "estetica", "mensajes", "moderacion", "web", "repaso")
    change_roles = os.environ.get("ROLES", "").strip().lower() in ("si", "sí", "true", "1")
    api = Discord(token, apply)

    guild = api.call("GET", f"/guilds/{GUILD}")
    channels = api.call("GET", f"/guilds/{GUILD}/channels")
    roles_list = api.call("GET", f"/guilds/{GUILD}/roles")
    OUT_DIR.mkdir(exist_ok=True)
    if apply and action not in ("avisos", "estetica", "mensajes", "moderacion", "web", "repaso"):
        snapshot = {"servidor": guild, "canales": channels, "roles": roles_list}
        (OUT_DIR / "antes-de-aplicar.json").write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if os.environ.get("ACCION", "").strip() == "lista-mvp":
        return send_mvp_list(api, guild, roles_list)
    if os.environ.get("ACCION", "").strip() == "quitar-mvp":
        return remove_mvp(api, guild, roles_list, os.environ.get("NUMEROS", ""), int(os.environ.get("TOTAL_MVP") or 0))
    if action == "repaso":
        return review(api, channels, roles_list)
    if action == "web":
        return boost_web(api, channels, roles_list)
    if action == "moderacion":
        return setup_moderation(api, channels, roles_list)
    if action == "mensajes":
        return post_messages(api, channels, roles_list)
    if action == "estetica":
        return restyle(api, channels)
    if action == "avisos":
        return setup_notifications(api, channels, roles_list)
    existing = {c["id"]: c for c in channels}
    roles = {r["name"]: r["id"] for r in roles_list}

    # 1. Roles: MVP sin moderación y rol Moderador nuevo (sin miembros).
    if change_roles:
        mvp = next((r for r in roles_list if r["name"] == "MVP 🏆"), None)
        if mvp and int(mvp["permissions"]) & MODERATION:
            api.call("PATCH", f"/guilds/{GUILD}/roles/{mvp['id']}", {"permissions": str(int(mvp["permissions"]) & ~MODERATION)},
                     "Rol MVP: quitar permisos de moderación")
        if "Moderador" not in roles:
            created = api.call("POST", f"/guilds/{GUILD}/roles",
                               {"name": "Moderador", "color": 0xA50044, "hoist": True,
                                "permissions": str(MEMBER_BASICS | (1 << 13) | (1 << 40) | (1 << 1))},
                               "Crear rol Moderador (gestionar mensajes, aislar y expulsar)")
            roles["Moderador"] = created["id"]

    # 2. Ajustes del servidor y Comunidad (antes de crear el foro y el canal de anuncios).
    features = sorted(set(guild.get("features", [])) | {"COMMUNITY"})
    api.call("PATCH", f"/guilds/{GUILD}", {
        "description": "La comunidad de PickandRollTV: Barça Basket, Euroliga, ACB y NBA. Directos, noticias y tertulia.",
        "default_message_notifications": 1,
        "explicit_content_filter": 2,
        "features": features,
        "rules_channel_id": "929099438989905962",
        "public_updates_channel_id": "929099439426121730",
        "system_channel_id": "959459731578167427",
        "preferred_locale": "es-ES",
    }, "Servidor: descripción, notificaciones solo menciones, filtro explícito, Comunidad activada")
    # 3. Categorías: renombrar las que hay y crear las que faltan.
    for key, category in CATEGORIES.items():
        position = category["position"]
        access = {"sub": "subs", "staff": "staff", "archivo": "oculto"}.get(key, "abierto")
        if category.get("id") in existing:
            api.call("PATCH", f"/channels/{category['id']}", {"name": category["name"], "position": position},
                     f"Categoría {existing[category['id']]['name']} → {category['name']}")
        else:
            created = api.call("POST", f"/guilds/{GUILD}/channels",
                               {"name": category["name"], "type": 4, "position": position,
                                "permission_overwrites": access_overwrites(access, roles, 4)},
                               f"Crear categoría {category['name']}")
            category["id"] = created["id"]

    # 4. Canales: renombrar, mover, permisos y tema; crear los nuevos.
    new_ids = {}
    for position, (channel_id, name, kind, category, access, topic) in enumerate(CHANNELS):
        body = {"name": name, "parent_id": CATEGORIES[category]["id"], "position": position,
                "permission_overwrites": access_overwrites(access, roles, kind)}
        if name == "🎵┃bot-musica" and roles.get("Nekotina"):
            body["permission_overwrites"].append(overwrite(roles["Nekotina"], VIEW | SEND | HISTORY))
        if topic and kind in (0, 5, 15):
            body["topic"] = topic
        if channel_id in existing:
            api.call("PATCH", f"/channels/{channel_id}", body, f"#{existing[channel_id]['name']} → {name} ({CATEGORIES[category]['name']}, {access})")
            new_ids[name] = channel_id
        elif channel_id is None:
            body["type"] = kind
            if kind == 15:
                body["available_tags"] = [{"name": tag} for tag in FORUM_TAGS]
                body["default_reaction_emoji"] = {"emoji_name": "🏀"}
            created = api.call("POST", f"/guilds/{GUILD}/channels", body, f"Crear {name} ({CATEGORIES[category]['name']}, {access})")
            new_ids[name] = created["id"]
        else:
            print(f"Aviso: el canal {channel_id} ({name}) ya no existe")

    # 5. Pantalla de bienvenida.
    api.call("PATCH", f"/guilds/{GUILD}/welcome-screen", {
        "enabled": True,
        "description": "Baloncesto en español: Barça, Euroliga, ACB y NBA.",
        "welcome_channels": [
            {"channel_id": new_ids["📜┃normas"], "description": "Lee las normas", "emoji_name": "📜"},
            {"channel_id": new_ids["💬┃general"], "description": "Habla de baloncesto", "emoji_name": "💬"},
            {"channel_id": new_ids["📰┃noticias-web"], "description": "Las noticias de la web", "emoji_name": "📰"},
            {"channel_id": new_ids["🏟️┃partidos"], "description": "Comenta cada partido", "emoji_name": "🏟️"},
        ],
    }, "Pantalla de bienvenida con 4 canales")

    # 6. AutoMod.
    automod = api.call("GET", f"/guilds/{GUILD}/auto-moderation/rules")
    have = {rule["trigger_type"] for rule in automod}
    exempt = [r for r in (roles.get("MVP 🏆"), roles.get("Moderador")) if r and not r.startswith("nuevo:")]
    block = [{"type": 1, "metadata": {"custom_message": "Mensaje bloqueado por las normas del servidor."}}]
    rules = [
        (3, "Bloquear spam", {}),
        (5, "Bloquear menciones masivas", {"mention_total_limit": 5, "mention_raid_protection_enabled": True}),
        (1, "Bloquear invitaciones a otros servidores", {"keyword_filter": ["*discord.gg/*", "*discord.com/invite/*"]}),
    ]
    for trigger, name, metadata in rules:
        if trigger not in have:
            api.call("POST", f"/guilds/{GUILD}/auto-moderation/rules", {
                "name": name, "event_type": 1, "trigger_type": trigger, "trigger_metadata": metadata,
                "actions": block, "enabled": True, "exempt_roles": exempt,
            }, f"AutoMod: {name}")

    # 7. Invitación permanente a #bienvenida.
    invite = api.call("POST", f"/channels/{new_ids['👋-bienvenida']}/invites", {"max_age": 0, "max_uses": 0, "unique": True},
                      "Invitación permanente a #bienvenida")
    if apply:
        (OUT_DIR / "invitacion.txt").write_text(f"https://discord.gg/{invite['code']}\n", encoding="utf-8")

    header = "# Cambios aplicados\n\n" if apply else "# Cambios que se aplicarían (prueba)\n\n"
    (OUT_DIR / "cambios.md").write_text(header + "\n".join(api.log) + "\n", encoding="utf-8")
    print(f"{len(api.log)} cambios {'aplicados' if apply else 'previstos'}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as error:
        # Los registros de GitHub no siempre se pueden leer: dejamos el error en el repositorio.
        OUT_DIR.mkdir(exist_ok=True)
        (OUT_DIR / "error.txt").write_text(f"{os.environ.get('ACCION', '')}: {error}\n", encoding="utf-8")
        raise
