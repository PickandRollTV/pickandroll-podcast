#!/usr/bin/env python3
"""Hace una foto completa del servidor de Discord para poder analizarlo y mejorarlo.

Con el bot del servidor (secreto DISCORD_BOT_TOKEN) lee, sin cambiar nada:
  - datos generales, roles, emojis, bots, invitaciones, webhooks, eventos, AutoMod,
    bienvenida y onboarding;
  - cada canal con su categoría, tema, permisos y modo lento;
  - la actividad de los últimos 90 días por canal: mensajes, personas distintas que
    escriben, mensajes de bots y fecha del último mensaje (nunca el texto de los mensajes);
  - los miembros en cifras: altas por mes, cuántos tienen cada rol.

Guarda el resultado en auditoria/discord.json y un resumen legible en auditoria/discord.md.

Variables de entorno:
  DISCORD_BOT_TOKEN   token del bot (secreto del repositorio)
"""
import collections
import datetime
import json
import os
import pathlib
import sys
import time
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent
CONFIG_FILE = ROOT / "config.json"
OUT_DIR = ROOT / "auditoria"
API = os.environ.get("DISCORD_API", "https://discord.com/api/v10")
DAYS = 90
MAX_MESSAGES_PER_CHANNEL = 5000
DISCORD_EPOCH_MS = 1420070400000

CHANNEL_TYPES = {
    0: "texto", 2: "voz", 4: "categoría", 5: "anuncios", 10: "hilo de anuncios",
    11: "hilo", 12: "hilo privado", 13: "escenario", 15: "foro", 16: "multimedia",
}
TEXT_LIKE = {0, 5, 2, 13}  # los canales de voz y escenario también tienen chat
THREAD_PARENTS = {0, 5, 15, 16}
PERMISSIONS = {
    "ver": 1 << 10, "escribir": 1 << 11, "escribir_en_hilos": 1 << 38, "reaccionar": 1 << 6,
    "conectar": 1 << 20, "administrador": 1 << 3, "gestionar_servidor": 1 << 5,
    "gestionar_canales": 1 << 4, "gestionar_roles": 1 << 28, "mencionar_everyone": 1 << 17,
    "gestionar_mensajes": 1 << 13, "expulsar": 1 << 1, "banear": 1 << 2, "aislar": 1 << 40,
}


class Discord:
    def __init__(self, token):
        self.token = token

    def get(self, path, allow=(403, 404)):
        for _ in range(6):
            request = urllib.request.Request(API + path, headers={
                "Authorization": f"Bot {self.token}",
                "User-Agent": "DiscordBot (https://pickandroll.tv, 1.0) PickandRollTV-auditoria",
            })
            try:
                with urllib.request.urlopen(request, timeout=30) as response:
                    return json.loads(response.read())
            except urllib.error.HTTPError as error:
                if error.code == 429:
                    time.sleep(float(json.loads(error.read() or b"{}").get("retry_after", 2)) + 0.5)
                    continue
                if error.code in allow:
                    return {"_error": error.code}
                raise RuntimeError(f"{path}: {error.code} {error.read()[:200]!r}") from error
        raise RuntimeError(f"{path}: demasiados reintentos")


def snowflake_time(snowflake):
    ms = (int(snowflake) >> 22) + DISCORD_EPOCH_MS
    return datetime.datetime.fromtimestamp(ms / 1000, datetime.timezone.utc)


def snowflake_at(when):
    return str(int(when.timestamp() * 1000 - DISCORD_EPOCH_MS) << 22)


def permissions_of(overwrites, guild_id, base):
    """Permisos de @everyone en un canal: los del servidor con las excepciones del canal."""
    value = base
    for overwrite in overwrites:
        if overwrite["id"] == guild_id:
            value = (value & ~int(overwrite["deny"])) | int(overwrite["allow"])
    return {name: bool(value & bit) for name, bit in PERMISSIONS.items() if name in ("ver", "escribir", "escribir_en_hilos", "conectar", "reaccionar")}


def activity(api, channel_id, since):
    """Cuenta los mensajes de un canal desde `since`, sin guardar su texto."""
    stats = {"mensajes": 0, "mensajes_30_dias": 0, "mensajes_de_bots": 0, "personas": set(), "ultimo": None}
    last_30 = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=30)
    after = snowflake_at(since)
    while stats["mensajes"] < MAX_MESSAGES_PER_CHANNEL:
        page = api.get(f"/channels/{channel_id}/messages?limit=100&after={after}")
        if not isinstance(page, list) or not page:
            if isinstance(page, dict):
                stats["error"] = page.get("_error")
            break
        for message in page:
            stats["mensajes"] += 1
            sent = datetime.datetime.fromisoformat(message["timestamp"])
            if sent >= last_30:
                stats["mensajes_30_dias"] += 1
            if message["author"].get("bot") or message.get("webhook_id"):
                stats["mensajes_de_bots"] += 1
            else:
                stats["personas"].add(message["author"]["id"])
            if not stats["ultimo"] or sent > stats["ultimo"]:
                stats["ultimo"] = sent
        after = max(page, key=lambda m: int(m["id"]))["id"]
        if len(page) < 100:
            break
    stats["personas"] = len(stats["personas"])
    stats["ultimo"] = stats["ultimo"].isoformat() if stats["ultimo"] else None
    return stats


def last_message_ever(api, channel):
    if channel.get("last_message_id"):
        return snowflake_time(channel["last_message_id"]).isoformat()
    return None


def main():
    token = os.environ.get("DISCORD_BOT_TOKEN", "").strip()
    if not token:
        print("Falta el secreto DISCORD_BOT_TOKEN")
        return 1
    api = Discord(token)
    config = json.loads(CONFIG_FILE.read_text(encoding="utf-8")).get("discord", {})
    guilds = api.get("/users/@me/guilds")
    guild_id = config.get("guild_id") or (guilds[0]["id"] if guilds else None)
    if not guild_id:
        print("El bot no está en ningún servidor: falta invitarlo")
        return 1

    now = datetime.datetime.now(datetime.timezone.utc)
    since = now - datetime.timedelta(days=DAYS)
    guild = api.get(f"/guilds/{guild_id}?with_counts=true")
    roles = sorted(api.get(f"/guilds/{guild_id}/roles"), key=lambda r: -r["position"])
    everyone = next(r for r in roles if r["id"] == guild_id)
    base = int(everyone["permissions"])
    channels = api.get(f"/guilds/{guild_id}/channels")
    by_id = {c["id"]: c for c in channels}

    threads = api.get(f"/guilds/{guild_id}/threads/active").get("threads", [])
    for channel in channels:
        if channel["type"] in THREAD_PARENTS:
            archived = api.get(f"/channels/{channel['id']}/threads/archived/public?limit=100")
            threads += archived.get("threads", []) if isinstance(archived, dict) else []
    threads = {t["id"]: t for t in threads}.values()

    report_channels = []
    for channel in sorted(channels, key=lambda c: (c["type"] != 4, c.get("position", 0))):
        parent = by_id.get(channel.get("parent_id"), {})
        entry = {
            "id": channel["id"],
            "nombre": channel["name"],
            "tipo": CHANNEL_TYPES.get(channel["type"], channel["type"]),
            "categoria": parent.get("name"),
            "posicion": channel.get("position"),
            "tema": channel.get("topic"),
            "modo_lento_segundos": channel.get("rate_limit_per_user", 0),
            "nsfw": channel.get("nsfw", False),
            "everyone": permissions_of(channel.get("permission_overwrites", []), guild_id, base),
            "excepciones_de_permisos": [
                {"rol": next((r["name"] for r in roles if r["id"] == o["id"]), "miembro concreto" if o["type"] == 1 else o["id"]),
                 "permite": [n for n, b in PERMISSIONS.items() if int(o["allow"]) & b],
                 "deniega": [n for n, b in PERMISSIONS.items() if int(o["deny"]) & b]}
                for o in channel.get("permission_overwrites", [])
            ],
            "ultimo_mensaje": last_message_ever(api, channel),
        }
        if channel["type"] == 15:
            entry["etiquetas_foro"] = [t["name"] for t in channel.get("available_tags", [])]
        if channel["type"] in TEXT_LIKE:
            print(f"Leyendo #{channel['name']}")
            entry["actividad_90_dias"] = activity(api, channel["id"], since)
        child_threads = [t for t in threads if t.get("parent_id") == channel["id"]]
        if child_threads:
            entry["hilos"] = []
            for thread in child_threads:
                stats = activity(api, thread["id"], since)
                entry["hilos"].append({"nombre": thread["name"], "mensajes_totales": thread.get("message_count"), "actividad_90_dias": stats})
        report_channels.append(entry)

    members, after = [], "0"
    while True:
        page = api.get(f"/guilds/{guild_id}/members?limit=1000&after={after}")
        if not isinstance(page, list) or not page:
            members_error = page.get("_error") if isinstance(page, dict) else None
            break
        members += page
        after = page[-1]["user"]["id"]
        members_error = None
        if len(page) < 1000:
            break
    role_names = {r["id"]: r["name"] for r in roles}
    members_report = None
    if members:
        joins = collections.Counter(m["joined_at"][:7] for m in members if not m["user"].get("bot"))
        per_role = collections.Counter(role_names.get(r, r) for m in members for r in m["roles"])
        members_report = {
            "total": len(members),
            "bots": [m["user"]["username"] for m in members if m["user"].get("bot")],
            "altas_por_mes": dict(sorted(joins.items())),
            "miembros_por_rol": dict(per_role.most_common()),
            "sin_ningun_rol": sum(1 for m in members if not m["roles"] and not m["user"].get("bot")),
        }

    def optional(path):
        result = api.get(path)
        return None if isinstance(result, dict) and "_error" in result else result

    invites = optional(f"/guilds/{guild_id}/invites") or []
    report = {
        "fecha": now.isoformat(),
        "servidor": {
            "nombre": guild["name"],
            "descripcion": guild.get("description"),
            "miembros": guild.get("approximate_member_count"),
            "conectados": guild.get("approximate_presence_count"),
            "funciones": guild.get("features"),
            "verificacion": guild.get("verification_level"),
            "filtro_contenido_explicito": guild.get("explicit_content_filter"),
            "notificaciones_por_defecto": "todos los mensajes" if guild.get("default_message_notifications") == 0 else "solo menciones",
            "nivel_mejoras": guild.get("premium_tier"),
            "mejoras": guild.get("premium_subscription_count"),
            "canal_reglas": by_id.get(guild.get("rules_channel_id"), {}).get("name"),
            "canal_sistema": by_id.get(guild.get("system_channel_id"), {}).get("name"),
            "canal_afk": by_id.get(guild.get("afk_channel_id"), {}).get("name"),
            "icono": bool(guild.get("icon")),
            "banner": bool(guild.get("banner")),
            "fondo_invitacion": bool(guild.get("splash")),
            "url_personalizada": guild.get("vanity_url_code"),
        },
        "roles": [
            {"nombre": r["name"], "color": f"#{r['color']:06x}" if r["color"] else None, "separado": r["hoist"],
             "mencionable": r["mentionable"], "gestionado_por_bot": r.get("managed", False),
             "permisos": [n for n, b in PERMISSIONS.items() if int(r["permissions"]) & b]}
            for r in roles
        ],
        "canales": report_channels,
        "miembros": members_report or {"error": members_error},
        "emojis": len(optional(f"/guilds/{guild_id}/emojis") or []),
        "stickers": len(optional(f"/guilds/{guild_id}/stickers") or []),
        "invitaciones": [
            {"canal": i.get("channel", {}).get("name"), "usos": i.get("uses"),
             "max_usos": i.get("max_uses"), "caduca_en_segundos": i.get("max_age"), "creada": i.get("created_at")}
            for i in invites
        ],
        "webhooks": [{"nombre": w.get("name"), "canal": by_id.get(w.get("channel_id"), {}).get("name")}
                     for w in optional(f"/guilds/{guild_id}/webhooks") or []],
        "eventos": [{"nombre": e["name"], "inicio": e["scheduled_start_time"]}
                    for e in optional(f"/guilds/{guild_id}/scheduled-events") or []],
        "automod": [{"nombre": r["name"], "activa": r["enabled"], "tipo": r["trigger_type"]}
                    for r in optional(f"/guilds/{guild_id}/auto-moderation/rules") or []],
        "bienvenida": optional(f"/guilds/{guild_id}/welcome-screen"),
        "onboarding": optional(f"/guilds/{guild_id}/onboarding"),
    }

    OUT_DIR.mkdir(exist_ok=True)
    (OUT_DIR / "discord.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (OUT_DIR / "discord.md").write_text(summary(report), encoding="utf-8")
    print(f"Auditoría guardada: {len(report_channels)} canales, {len(roles)} roles")
    return 0


def summary(report):
    s = report["servidor"]
    lines = [
        f"# Auditoría de {s['nombre']} ({report['fecha'][:10]})", "",
        f"{s['miembros']} miembros, {s['conectados']} conectados. Nivel de mejoras {s['nivel_mejoras']}.", "",
        "| Canal | Tipo | Categoría | Mensajes 90 días | Últimos 30 días | Personas | Último mensaje | @everyone ve/escribe |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for c in report["canales"]:
        a = c.get("actividad_90_dias") or {}
        everyone = c["everyone"]
        lines.append(
            f"| {c['nombre']} | {c['tipo']} | {c['categoria'] or ''} | {a.get('mensajes', '')} | {a.get('mensajes_30_dias', '')} "
            f"| {a.get('personas', '')} | {(c['ultimo_mensaje'] or '')[:10]} | {'sí' if everyone['ver'] else 'no'}/{'sí' if everyone['escribir'] else 'no'} |"
        )
    lines += ["", "## Roles", ""]
    per_role = (report["miembros"] or {}).get("miembros_por_rol", {})
    lines += [f"- {r['nombre']}: {per_role.get(r['nombre'], '?')} miembros" for r in report["roles"]]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    sys.exit(main())
