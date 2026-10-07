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
                      la lista de miembros con el rol MVP (no toca nada más)
"""
import json
import os
import pathlib
import sys
import time
import urllib.error
import urllib.request

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
    "inicio": {"id": "929099438989905961", "name": "📌 Empieza aquí", "position": 0},
    "pickandroll": {"id": "929099439426121728", "name": "🏀 PickandRoll", "position": 1},
    "sub": {"name": "⭐ Zona Sub", "position": 2},
    "staff": {"name": "🔒 Staff", "position": 8},
    "archivo": {"name": "🗄️ Archivo", "position": 9},
}
CHANNELS = [
    # (id o None para crear, nombre, tipo, categoría, acceso, tema)
    ("959459731578167427", "👋-bienvenida", 0, "inicio", "lectura", "Bienvenido a la comunidad de PickandRollTV. Empieza por #normas."),
    ("929099438989905962", "📜-normas", 0, "inicio", "lectura", "Normas del servidor. Léelas antes de escribir."),
    (None, "📢-anuncios", 5, "inicio", "lectura", "Directos, novedades y avisos de PickandRollTV."),
    ("956699792086560768", "📰-noticias-web", 0, "inicio", "lectura", "Cada noticia nueva de pickandroll.tv, al momento."),
    ("929099439426121729", "💬-general", 0, "pickandroll", "abierto", "Charla de Barça, Euroliga, ACB y NBA."),
    (None, "🏟️-partidos", 15, "pickandroll", "abierto", "Un hilo por partido: previa, directo y postpartido."),
    ("1252234382425718805", "🔄-mercado-y-plantilla", 0, "pickandroll", "abierto", "Fichajes, rumores y plantilla del Barça."),
    ("929099439426121731", "💡-ideas-y-propuestas", 0, "pickandroll", "abierto", "¿Qué te gustaría ver en el canal? Propón contenido y mejoras."),
    ("1252586051755573341", "❤️-apoya-el-canal", 0, "pickandroll", "lectura", "Web, donaciones, merchandising y patrocinadores de PickandRollTV."),
    (None, "⭐-zona-sub", 0, "sub", "subs", "Canal exclusivo para suscriptores de Twitch."),
    ("929099439426121730", "material-para-el-canal", 0, "staff", "staff", None),
    ("982406567540441099", "bot-musica", 0, "staff", "staff", None),
    ("1250872435880886324", "merchandising", 0, "staff", "staff", None),
    ("1251187799017787413", "tertulia", 0, "archivo", "oculto", None),
    ("1248574516070846535", "propuestas-contenido", 0, "archivo", "oculto", None),
    ("929099438989905963", "plataformas", 0, "archivo", "oculto", None),
    ("1250163184107655229", "patrocinadores", 0, "archivo", "oculto", None),
    ("929099439426121734", "banquillo", 2, "archivo", "oculto", None),
    ("959257658425225267", "invitado", 2, "archivo", "oculto", None),
]
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


def send_mvp_list(api, guild, roles_list):
    """Manda al dueño del servidor la lista de MVP por mensaje privado: no se guarda en el repositorio."""
    mvp = next(r["id"] for r in roles_list if r["name"] == "MVP 🏆")
    members, after = [], "0"
    while True:
        page = api.call("GET", f"/guilds/{GUILD}/members?limit=1000&after={after}")
        members += page
        if len(page) < 1000:
            break
        after = page[-1]["user"]["id"]
    mvps = sorted((m.get("nick") or m["user"].get("global_name") or m["user"]["username"], m["user"]["username"], m["joined_at"][:10])
                  for m in members if mvp in m["roles"])
    lines = [f"{i}. {shown} (@{user}), en el servidor desde {joined}" for i, (shown, user, joined) in enumerate(mvps, 1)]
    dm = api.call("POST", "/users/@me/channels", {"recipient_id": guild["owner_id"]}, "Abrir mensaje privado con el dueño", force=True)
    chunk = f"**Miembros con el rol MVP 🏆 ({len(mvps)})**"
    for line in lines:
        if len(chunk) + len(line) > 1900:
            api.call("POST", f"/channels/{dm['id']}/messages", {"content": chunk}, "Enviar lista de MVP", force=True)
            chunk = ""
        chunk += "\n" + line
    api.call("POST", f"/channels/{dm['id']}/messages", {"content": chunk}, "Enviar lista de MVP", force=True)
    print(f"Lista de {len(mvps)} MVP enviada al dueño por mensaje privado")
    return 0


def main():
    token = os.environ.get("DISCORD_BOT_TOKEN", "").strip()
    if not token:
        print("Falta el secreto DISCORD_BOT_TOKEN")
        return 1
    apply = os.environ.get("MODO", "").strip().lower() == "aplicar"
    change_roles = os.environ.get("ROLES", "").strip().lower() in ("si", "sí", "true", "1")
    api = Discord(token, apply)

    guild = api.call("GET", f"/guilds/{GUILD}")
    channels = api.call("GET", f"/guilds/{GUILD}/channels")
    roles_list = api.call("GET", f"/guilds/{GUILD}/roles")
    OUT_DIR.mkdir(exist_ok=True)
    if apply:
        snapshot = {"servidor": guild, "canales": channels, "roles": roles_list}
        (OUT_DIR / "antes-de-aplicar.json").write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if os.environ.get("ACCION", "").strip() == "lista-mvp":
        return send_mvp_list(api, guild, roles_list)
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
        if name == "bot-musica" and roles.get("Nekotina"):
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
            {"channel_id": new_ids["📜-normas"], "description": "Lee las normas", "emoji_name": "📜"},
            {"channel_id": new_ids["💬-general"], "description": "Habla de baloncesto", "emoji_name": "💬"},
            {"channel_id": new_ids["📰-noticias-web"], "description": "Las noticias de la web", "emoji_name": "📰"},
            {"channel_id": new_ids["🏟️-partidos"], "description": "Comenta cada partido", "emoji_name": "🏟️"},
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
    sys.exit(main())
