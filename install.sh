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

# Segmented cava visualiser, so it runs as just `cava-bars`
link "$REPO/config/cava/cava-bars" "$HOME/.local/bin/cava-bars"

echo "Done. Add config/hypr/hosts/$(cat /proc/sys/kernel/hostname).lua for this machine's monitors, then: hyprctl reload"
