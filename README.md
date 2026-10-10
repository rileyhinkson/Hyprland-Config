# Hyprland-Config

Hyprland (Lua config, 0.56+) and its companion apps, synced between my laptop and desktop.

- `config/` holds hypr, waybar, rofi, kitty, btop, cava and fastfetch. They are symlinked into `~/.config`.
- `config/hypr/hosts/<hostname>.lua` holds per-machine settings like monitor layouts and Steam scaling. It loads automatically.
- `wallpapers/` is linked to `~/Pictures/Wallpapers`.

## Set up on a new machine

```sh
git clone git@github.com:rileyhinkson/Hyprland-Config.git ~/dotfiles
~/dotfiles/install.sh
hyprctl reload
```

The install script moves any existing config folders to `~/dotfiles-backups/` before linking.

## Sync

```sh
cd ~/dotfiles && git pull                                   # get changes
cd ~/dotfiles && git add -A && git commit -m "..." && git push   # send changes
```
