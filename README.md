# Hyprland-Config

My Hyprland setup (Lua config, 0.56+) and its companion apps, synced between my
laptop and my desktop. Black base, one accent colour on top — change the colour
from the bar and the whole rig follows.

- `config/` holds hypr, waybar, rofi, kitty, btop, cava and fastfetch. It all
  gets symlinked into `~/.config`.
- `config/hypr/hosts/<hostname>.lua` holds the per-machine stuff — monitor
  layout, Steam scaling. It loads automatically.
- `wallpapers/` is linked to `~/Pictures/Wallpapers`. It's SR-71s, because
  SR-71s are cool as fuck.

## Set up on a new machine

```sh
git clone git@github.com:rileyhinkson/Hyprland-Config.git ~/dotfiles
~/dotfiles/install.sh
hyprctl reload
```

The install script moves any existing config folders to `~/dotfiles-backups/`
before linking, so it won't eat anything. It also drops a `cava-bars` symlink
into `~/.local/bin`.

## Sync

```sh
cd ~/dotfiles && git pull                                        # get changes
cd ~/dotfiles && git add -A && git commit -m "..." && git push   # send changes
```

---

## The bar

Waybar, bottom edge, on every monitor. The right-hand side, left to right:

| Widget | Click | Middle | Right | Scroll |
|---|---|---|---|---|
| tray | — | — | — | — |
| `● Color` | colour picker panel | — | — | — |
| `VOL 45%` | audio panel | mute | — | volume ±5% |
| bluetooth | bluetooth panel | toggle adapter | — | — |
| Wi-Fi | Wi-Fi panel | toggle radio | `nm-connection-editor` | — |
| `ETH` | — | — | `nm-connection-editor` | — |
| power | power menu | cycle profile | `wlogout` | — |

Two things in there that look weird but are on purpose:

- **Ethernet and Wi-Fi are separate modules.** Waybar's `network` module only
  shows the *primary* interface, so when I was on both it showed `ETH` and quietly
  hid the fact that Wi-Fi was up too. So `network` is pinned to `en*`,
  `network#wifi` to `wl*`, and the ethernet one collapses to nothing on a
  machine with no cable (i.e. the laptop).
- **The power widget prints nothing when there's no battery**, which hides it
  on the desktop. That's `power.sh status` returning an empty string on purpose,
  not a broken script.

### Panels vs menus

There are two different UI styles here and it's not an accident:

- **GTK panels** (`audio-popup.py`, `wifi-popup.py`, `bt-popup.py`,
  `theme-popup.py`) are layer-shell popups that expand above the bar. They can
  do gradients, sliders and inline password boxes, so they get the nice look.
- **rofi menus** (`wifi-menu.sh`, `power.sh menu`, `bt-menu.sh`, `keybinds.py`)
  are keyboard-driven and type-to-search. rofi flat out cannot draw a gradient,
  so accents there are solid colours.

All the panels behave the same way, because they share the same scaffolding
copy-pasted between them:

- **Open**: click the widget. Click it again to close.
- **Close**: Escape, click anywhere outside, or click the widget again.
  Moving the mouse away deliberately does *not* close them — with
  `follow_mouse = 1`, just dragging the cursor across the desktop would dismiss
  a panel before I ever reached it. That bug was annoying as hell to track down.
- **The click-outside catcher** is one invisible fullscreen layer *per monitor*.
  A layer surface only covers the output it's assigned to, so with one catcher
  on a three-monitor setup, clicking on the other two screens did nothing. Each
  catcher also stops short of the bar so the widget itself stays clickable.

If you fix a dismissal bug in one panel, fix it in all four or they'll start
behaving differently from each other.

---

## Colour: the `● Color` widget

Black stays the base everywhere. The widget swaps the secondary colour across
the whole system at once — bar, menus, panels, window borders, lock screen and
the audio visualiser.

Twelve options: white, red, orange, yellow, matrix green, sky, blue, indigo,
violet, pink, and two gradients — **rainbow** and **trans**. Trans and pride,
FUCK YEAH.

### One source of truth

`config/theme/accent` is the only place the choice is stored. Everything else
reads from it:

```
            config/theme/accent          <- written by theme.sh
                     │
     ┌───────────────┼────────────────┬──────────────┬─────────────┐
     │               │                │              │             │
 accent.rasi    accent.css        the panels    hyprland.lua    cava config
 (generated)    (generated)     (parsed at      (parsed at     (generated
     │               │            startup)        load)          block)
  rofi menus     waybar CSS      GTK popups    window borders   cava-bars
                                               + hyprlock
```

`theme.sh` owns the palette and does all the file rewriting:

```sh
theme.sh list           # palette, one "name primary stops..." per line
theme.sh get            # current primary hex
theme.sh current        # current palette name
theme.sh set <name>     # switch, regenerate, reload
theme.sh apply          # regenerate from whatever is stored
theme.sh status         # waybar JSON
```

**To add a colour**, add one line to `PALETTE` in `theme.sh` and that's it — the
picker reads the list from the script, so nothing else needs touching. Format is
`name|primary|stop stop stop...`, and adding the optional stop list is what
makes it a gradient theme.

### What the gradients can and can't reach

The gradient themes drive everything that can actually draw a gradient: window
borders, the hyprlock input outline, the Color widget itself, the panel frames
and their selected rows, and cava. Anywhere a single colour is required, it uses
the primary.

rofi is the one exception, because rasi has no gradient type at all. The stops
get spread across its elements instead — first colour on the border, middle on
the prompt, last on the selected row. Near-white stops get skipped for the
selected row, because a full-width white block is blinding.

---

## Keybinds

`SUPER + /` opens a searchable list of every keybind, parsed live out of
`hyprland.lua`. Edit a bind and the list follows automatically.

The workspace binds are generated in a `for` loop so they can't be parsed. They
get listed by hand in `EXTRA` at the top of `config/hypr/scripts/keybinds.py` —
add to it if I ever add more loop-generated binds.

## cava-bars

```sh
cava-bars
```

Segmented LED-style visualiser, themed from the same accent file. Ctrl+C quits.

This one was a complete pain in the ass, so here's why it exists and why it's
not just cava:

- Fedora's cava is built **without OpenGL**, so cava's own shader renderer —
  the thing that would draw segmented bars — just errors out. There's a working
  GLSL shader sitting at `config/cava/shaders/segmented_bars.frag` that does
  exactly the right thing and is completely useless unless cava gets rebuilt.
- So `cava-bars` runs cava in raw mode and draws the bars itself, using a
  lower-half-block glyph so every segment gets a gap above it.
- It captures the **default sink's monitor**, worked out at launch, so the bars
  follow whatever output the audio panel is pointed at. cava's own default
  grabs the default *source*, which is usually a damn microphone, so it sits
  there showing silence while music is playing.
- Silent bars still draw a dim ghost grid and a lit bottom row, so a quiet
  moment doesn't look like a crashed program.

---

## Shit I learned the hard way

- **`hyprctl keyword` does nothing under the Lua config parser.** It prints
  `keyword can't work with non-legacy parsers` and then exits 0 anyway, so it
  looks like it worked. Use `hyprctl reload` — `hyprland.lua` re-reads the accent
  file on load.
- **Lua's `%w` doesn't include underscores.** `line:match("^(%w+)=")` will never
  match `accent_dark=`. Use `[%w_]+`.
- **cava's reload keys segfault** any time the colours change — both `r` and `c`,
  on 0.10.2. Just restart it (Ctrl+C, run it again).
- **`JetBrainsMono Nerd Font` isn't actually installed**, even though the rofi
  themes all ask for it. Fontconfig falls back to Noto Sans and pulls the icons
  out of FantasqueSansM Nerd Font, which is what waybar names directly. Worth
  either installing the font or fixing the themes.
- **Never `pkill -f` a script path from inside a script.** The shell running it
  has that same path in its own command line, so it kills itself. Match on the
  process name with `pkill -x` instead.

## Depends on

Hyprland 0.56+ with `hyprpaper`, `hypridle`, `hyprlock`, `hyprpolkitagent`,
`hyprshutdown`, `hyprpicker`, `hyprlauncher` · waybar 0.15+ · rofi · kitty ·
dolphin · swaync · wlogout · cliphist + wl-clipboard · grim + slurp + swappy ·
jq · PipeWire (`pactl`, `wpctl`) · NetworkManager (`nmcli`) ·
BlueZ (`bluetoothctl`) + blueman · brightnessctl · playerctl ·
power-profiles-daemon · cava · FantasqueSansM Nerd Font ·
python3 + python3-gobject + gtk3 + gtk-layer-shell (for the panels).
