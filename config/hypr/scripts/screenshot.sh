#!/usr/bin/env bash
# Usage: screenshot.sh region|screen|window|edit
# Saves to ~/Pictures/Screenshots and copies to the clipboard.
set -euo pipefail
dir="$HOME/Pictures/Screenshots"
mkdir -p "$dir"
file="$dir/$(date +%Y-%m-%d_%H-%M-%S).png"

case "${1:-region}" in
  region) geom=$(slurp) || exit 0; grim -g "$geom" "$file" ;;
  screen) grim -o "$(hyprctl monitors -j | jq -r '.[] | select(.focused) | .name')" "$file" ;;
  window) geom=$(hyprctl activewindow -j | jq -r '"\(.at[0]),\(.at[1]) \(.size[0])x\(.size[1])"')
          grim -g "$geom" "$file" ;;
  edit)   geom=$(slurp) || exit 0; grim -g "$geom" - | swappy -f - ; exit 0 ;;
esac

wl-copy < "$file"
notify-send -i "$file" "Screenshot saved" "$(basename "$file") copied to clipboard"
