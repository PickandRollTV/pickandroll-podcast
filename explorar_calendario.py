#!/usr/bin/env python3
"""Herramienta temporal: guarda cómo publica fcbarcelona.es su calendario, para poder leerlo."""
import pathlib
import re
import urllib.request

URL = "https://www.fcbarcelona.es/es/baloncesto/primer-equipo/calendario"
OUT = pathlib.Path(__file__).resolve().parent / "auditoria" / "fcb-muestra.txt"


def main():
    request = urllib.request.Request(URL, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/126 Safari/537.36",
                                                   "Accept-Language": "es-ES,es;q=0.9"})
    html = urllib.request.urlopen(request, timeout=30).read().decode("utf-8", "replace")
    parts = [f"Tamaño: {len(html)}", "Scripts:"]
    parts += sorted(set(re.findall(r'<script[^>]+src="([^"]+)"', html)))[:40]
    parts += ["URLs con api/json/ics:"] + sorted(set(re.findall(r'https?://[^"\'\s<>]*(?:api|json|\.ics|calendar)[^"\'\s<>]*', html)))[:40]
    parts += ["data-*:"] + sorted(set(re.findall(r'\sdata-[a-z-]+=', html)))[:60]
    index = html.find("Zalgiris")
    parts += ["Alrededor de Zalgiris:", html[max(0, index - 3000): index + 1500] if index >= 0 else "(no aparece)"]
    index = html.find("Valencia")
    parts += ["Alrededor de Valencia:", html[max(0, index - 1500): index + 800] if index >= 0 else "(no aparece)"]
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text("\n".join(parts) + "\n", encoding="utf-8")
    return 0
