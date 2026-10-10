#!/usr/bin/env bash
# Symlink this repo's configs into ~/.config. Existing real folders are moved
# to ~/dotfiles-backups/<timestamp>/ first, never deleted.
set -euo pipefail
REPO="$(cd "$(dirname "$0")" && pwd)"
BACKUP="$HOME/dotfiles-backups/$(date +%Y%m%d-%H%M%S)"

link() {
    local src="$1" dst="$2"
    if [ -L "$dst" ]; then
        rm "$dst"
    elif [ -e "$dst" ]; then
        mkdir -p "$BACKUP"
        mv "$dst" "$BACKUP/"
        echo "backed up $dst -> $BACKUP/"
    fi
    mkdir -p "$(dirname "$dst")"
    ln -s "$src" "$dst"
    echo "linked $dst"
}

for dir in "$REPO"/config/*/; do
    name="$(basename "$dir")"
    link "$REPO/config/$name" "$HOME/.config/$name"
done
link "$REPO/wallpapers" "$HOME/Pictures/Wallpapers"

# Each machine keeps its own monitor layout. Start from defaults if missing.
for f in monitors.lua monitors.conf; do
    [ -e "$REPO/config/hypr/$f" ] || cp "$REPO/config/hypr/$f.example" "$REPO/config/hypr/$f"
done
echo "Done. Run nwg-displays to set this machine's monitors, then: hyprctl reload"
