# Hyprland-Config
Hyprland (Lua config, 0.56+) synced between my machines.

- `hyprland.lua` — shared config
- `hosts/<hostname>.lua` — per-machine settings (monitor layouts), loaded automatically

## Set up on a new machine

```sh
mv ~/.config/hypr ~/.config/hypr.old   # if one exists
git clone https://github.com/rileyhinkson/Hyprland-Config.git ~/.config/hypr
hyprctl reload
```

Sync: `git pull` to get changes, `git commit -am "..." && git push` to send them.
