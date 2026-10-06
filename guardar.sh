#!/usr/bin/env bash
# Sube al repositorio el feed y la lista de episodios, para que Spotify vea los cambios.
git config user.name "podcast-bot"
git config user.email "podcast-bot@users.noreply.github.com"
git add episodes.json ultimos_videos.json docs/
git add ultimo_error.txt 2>/dev/null || true
git diff --cached --quiet || (git commit -q -m "Actualizar el podcast" && git pull -q --rebase origin main && git push -q)
