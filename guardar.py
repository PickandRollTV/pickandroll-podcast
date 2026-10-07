#!/usr/bin/env python3
"""Sube al repositorio el feed y la lista de episodios, para que Spotify vea los cambios.

Si mientras tanto otra ejecución ha subido cambios, se combinan las dos listas de
episodios (gana la versión que cada una haya modificado), se regenera el feed y se
vuelve a intentar, en lugar de fallar por el conflicto.
"""
import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent
FILES = ["episodes.json", "ultimos_videos.json", "docs/"]


def git(*args, check=True):
    return subprocess.run(["git", *args], cwd=ROOT, check=check, capture_output=True, text=True)


def episodes_at(ref):
    shown = git("show", f"{ref}:episodes.json", check=False)
    return {e["guid"]: e for e in json.loads(shown.stdout)} if shown.returncode == 0 else {}


def merge_remote():
    """Combina episodes.json con el de origin/main y regenera el feed."""
    from feed import write_feed

    git("fetch", "-q", "origin", "main")
    base, remote = episodes_at("HEAD"), episodes_at("origin/main")
    local = {e["guid"]: e for e in json.loads((ROOT / "episodes.json").read_text(encoding="utf-8"))}
    merged = dict(remote)
    for guid, episode in local.items():
        if guid not in remote or episode != base.get(guid):
            merged[guid] = episode
    episodes = sorted(merged.values(), key=lambda e: e["published"])
    (ROOT / "episodes.json").write_text(json.dumps(episodes, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    config = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    write_feed(config, episodes, ROOT / "docs" / "feed.xml")


def main():
    git("config", "user.name", "podcast-bot")
    git("config", "user.email", "podcast-bot@users.noreply.github.com")
    for attempt in range(3):
        merge_remote()
        git("add", *FILES)
        git("add", "ultimo_error.txt", "ultima_pasada.txt", check=False)
        git("add", "twitch_fallos.txt", check=False)
        if git("diff", "--cached", "--quiet", check=False).returncode == 0:
            print("Nada que guardar")
            return 0
        git("commit", "-q", "-m", "Actualizar el podcast")
        # Nuestra versión ya incluye la remota, así que en conflicto gana la nuestra.
        rebased = git("pull", "-q", "--rebase", "-X", "theirs", "origin", "main", check=False)
        if rebased.returncode == 0 and git("push", "-q", check=False).returncode == 0:
            print("Guardado")
            return 0
        print(f"Intento {attempt + 1} fallido: {rebased.stderr.strip()}", file=sys.stderr)
        git("rebase", "--abort", check=False)
        git("reset", "-q", "--soft", "HEAD~1")
    return 1


if __name__ == "__main__":
    sys.exit(main())
