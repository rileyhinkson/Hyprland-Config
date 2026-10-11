#!/usr/bin/env python3
"""Audio panel for the waybar volume module.

A layer-shell popup that sits above the bar: pick an output or input on the
left, set the volume with the vertical slider on the right. Clicking the
waybar module again, pressing Escape, or clicking away closes it.
"""
import json
import os
import re
import signal
import subprocess
import sys
import time

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GtkLayerShell", "0.1")
from gi.repository import Gdk, GLib, Gtk, GtkLayerShell  # noqa: E402

STEP = 5
BAR_HEIGHT = 34          # "height" in config.jsonc
GAP = 12                 # same offsets the rofi menus use
SLIDER_HEIGHT = 190
POLL_MS = 500            # catch volume changes made elsewhere (media keys)
_RUN = os.environ.get("XDG_RUNTIME_DIR", "/tmp")
STATE = os.path.join(_RUN, "waybar-audio-popup.closed")
PIDFILE = os.path.join(_RUN, "waybar-audio-popup.pid")

SPEAKER = "\U000F04C3"
HEADPHONES = "\U000F02CB"
BLUETOOTH = "\U000F00AF"
MONITOR = "\U000F0379"
MIC = "\U000F036C"
VOL_HIGH = "\U000F057E"
VOL_OFF = "\U000F0581"

CSS = b"""
window { background-color: transparent; }
.catcher { background-color: rgba(0, 0, 0, 0.01); }
#frame {
    background-image: @BORDER@;
    border-radius: 10px;
    padding: 2px;
}
#root {
    background-color: #161616;
    border-radius: 8px;
    padding: 12px;
}
* {
    font-family: "JetBrainsMono Nerd Font", monospace;
    font-size: 11pt;
    color: #e6e6e6;
}
.heading { color: #8a8a8a; font-size: 9pt; }
.vol { font-size: 12pt; }
button {
    background-image: none;
    background-color: #2a2a2a;
    border: none;
    box-shadow: none;
    border-radius: 8px;
    padding: 7px 10px;
}
button:hover { background-color: @ACCENT_HOVER@; }
button.active { background-image: @ROW@; color: #101010; }
/* the dim tags sit on the accent here, so they need the dark ink too */
button.active label { color: #101010; }
button.step { padding: 2px 10px; }
scale { margin: 0; }
scale trough {
    min-width: 10px;
    background-color: #2a2a2a;
    border-radius: 5px;
}
scale highlight { background-image: @ROW@; border-radius: 5px; }
scale slider {
    min-width: 14px;
    min-height: 14px;
    margin: -5px;
    border-radius: 50%;
    background-color: #e6e6e6;
}
"""


def pactl(*args):
    try:
        p = subprocess.run(["pactl", *args], capture_output=True, text=True, timeout=3)
        return p.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def icon_for(props, port):
    if props.get("device.form_factor") in ("headset", "headphone"):
        return HEADPHONES
    if props.get("device.bus") == "bluetooth":
        return BLUETOOTH
    if port in ("HDMI", "DisplayPort"):
        return MONITOR
    return SPEAKER


def devices(kind):
    """kind: "sinks" or "sources". Monitor sources are left out."""
    try:
        data = json.loads(pactl("-f", "json", "list", kind) or "[]")
    except ValueError:
        return []
    out = []
    for d in data:
        props = d.get("properties") or {}
        if kind == "sources" and props.get("device.class") == "monitor":
            continue
        port = next((p.get("type") or "" for p in (d.get("ports") or [])
                     if p.get("name") == d.get("active_port")), "")
        desc = d.get("description") or d.get("name")
        nick = props.get("node.nick") or ""
        # On HDMI/DP the description names the GPU's audio controller, which is
        # identical for every screen; the nick is the monitor itself.
        if port in ("HDMI", "DisplayPort") and nick:
            desc = "%s (%s)" % (nick, port)
        out.append({
            "name": d.get("name", ""),
            "desc": " ".join(desc.split()),
            "icon": icon_for(props, port) if kind == "sinks" else MIC,
        })
    return sorted(out, key=lambda d: d["desc"].lower())


def default_of(kind):
    return pactl("get-default-sink" if kind == "sinks" else "get-default-source")


def set_default(kind, name):
    if kind == "sinks":
        pactl("set-default-sink", name)
        streams, move = "sink-inputs", "move-sink-input"
    else:
        pactl("set-default-source", name)
        streams, move = "source-outputs", "move-source-output"
    # Move whatever is already playing onto the new device.
    for line in pactl("list", "short", streams).splitlines():
        idx = line.split("\t")[0].strip()
        if idx:
            pactl(move, idx, name)


def volume():
    m = re.search(r"(\d+)%", pactl("get-sink-volume", "@DEFAULT_SINK@"))
    return int(m.group(1)) if m else 0


def is_muted():
    return pactl("get-sink-mute", "@DEFAULT_SINK@").endswith("yes")


def theme_colours():
    """(primary, stops) as chosen with the Color widget; stops may be empty."""
    primary, stops = "#ff3344", []
    try:
        with open(os.path.expanduser("~/.config/theme/accent")) as fh:
            for line in fh:
                key, _, value = line.partition("=")
                value = value.strip()
                if key == "accent" and value:
                    primary = value
                elif key == "gradient" and value:
                    stops = value.split()
    except OSError:
        pass
    return primary, stops


def themed_css():
    """Fill the palette holes in CSS.

    Multi-colour themes (rainbow, trans) paint the frame and the selected rows
    with the real gradient; single colours become a flat one-stop gradient so
    the same rules work for both.
    """
    primary, stops = theme_colours()
    r, g, b = (int(primary[i:i + 2], 16) for i in (1, 3, 5))
    if stops:
        border = "linear-gradient(135deg, %s)" % ", ".join(stops)
        row = "linear-gradient(90deg, %s)" % ", ".join(stops)
    else:
        border = row = "linear-gradient(0deg, %s, %s)" % (primary, primary)
    return (CSS.replace(b"@BORDER@", border.encode())
               .replace(b"@ROW@", row.encode())
               .replace(b"@ACCENT@", primary.encode())
               .replace(b"@ACCENT_HOVER@", ("rgba(%d, %d, %d, 0.25)" % (r, g, b)).encode()))


class ClickCatcher:
    """Invisible layers that make a click outside the panel dismiss it.

    One surface per monitor: a layer surface only covers the output it is
    assigned to, so a single one would leave clicks on the other screens doing
    nothing. Each stops short of the bar, which keeps the widget itself
    clickable -- clicking it again re-runs the script, and that closes the
    panel through its pidfile.
    """

    def __init__(self, on_click):
        self.windows = []
        display = Gdk.Display.get_default()
        for i in range(display.get_n_monitors()):
            self.windows.append(self._surface(display.get_monitor(i), on_click))

    def _surface(self, monitor, on_click):
        win = Gtk.Window(type=Gtk.WindowType.TOPLEVEL)
        win.set_app_paintable(True)
        visual = Gdk.Screen.get_default().get_rgba_visual()
        if visual:
            win.set_visual(visual)
        GtkLayerShell.init_for_window(win)
        GtkLayerShell.set_monitor(win, monitor)
        GtkLayerShell.set_layer(win, GtkLayerShell.Layer.TOP)
        for edge in (GtkLayerShell.Edge.TOP, GtkLayerShell.Edge.BOTTOM,
                     GtkLayerShell.Edge.LEFT, GtkLayerShell.Edge.RIGHT):
            GtkLayerShell.set_anchor(win, edge, True)
        GtkLayerShell.set_margin(win, GtkLayerShell.Edge.BOTTOM, BAR_HEIGHT)
        GtkLayerShell.set_keyboard_mode(win, GtkLayerShell.KeyboardMode.NONE)
        GtkLayerShell.set_exclusive_zone(win, -1)
        # An empty window has nothing to click on; an event box with a barely
        # visible background gives the surface a real input region.
        box = Gtk.EventBox()
        box.set_visible_window(True)
        box.get_style_context().add_class("catcher")
        box.add_events(Gdk.EventMask.BUTTON_PRESS_MASK)
        box.connect("button-press-event", self.on_press, on_click)
        win.add(box)
        return win

    def on_press(self, _widget, _event, on_click):
        on_click()
        return True

    def show(self):
        for win in self.windows:
            win.show_all()

    def destroy(self):
        for win in self.windows:
            win.destroy()
        self.windows = []


class Panel(Gtk.Window):
    def __init__(self):
        super().__init__(type=Gtk.WindowType.TOPLEVEL)
        self.catcher = None
        self.syncing = False
        self.dragging = False
        self.last_set = None

        self.set_app_paintable(True)
        visual = Gdk.Screen.get_default().get_rgba_visual()
        if visual:
            self.set_visual(visual)

        GtkLayerShell.init_for_window(self)
        GtkLayerShell.set_layer(self, GtkLayerShell.Layer.OVERLAY)
        GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.BOTTOM, True)
        GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.RIGHT, True)
        GtkLayerShell.set_margin(self, GtkLayerShell.Edge.BOTTOM, BAR_HEIGHT + GAP)
        GtkLayerShell.set_margin(self, GtkLayerShell.Edge.RIGHT, GAP)
        GtkLayerShell.set_keyboard_mode(self, GtkLayerShell.KeyboardMode.EXCLUSIVE)

        root = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
        root.set_name("root")
        frame = Gtk.Box()
        frame.set_name("frame")
        frame.add(root)
        self.add(frame)

        self.lists = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.lists.set_size_request(300, -1)
        root.pack_start(self.lists, True, True, 0)
        root.pack_start(self.volume_column(), False, False, 0)

        self.connect("key-press-event", self.on_key)
        self.connect("destroy", Gtk.main_quit)

        self.build_lists()
        self.sync()
        GLib.timeout_add(POLL_MS, self.sync)

    # ---------- volume column ----------
    def volume_column(self):
        col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        col.set_halign(Gtk.Align.CENTER)

        self.vol_label = Gtk.Label(label="--%")
        self.vol_label.get_style_context().add_class("vol")
        col.pack_start(self.vol_label, False, False, 0)

        up = Gtk.Button(label="+")
        up.get_style_context().add_class("step")
        up.connect("clicked", lambda *_: self.nudge(STEP))
        col.pack_start(up, False, False, 0)

        self.scale = Gtk.Scale.new_with_range(Gtk.Orientation.VERTICAL, 0, 100, 1)
        self.scale.set_inverted(True)          # loud at the top
        self.scale.set_draw_value(False)
        self.scale.set_round_digits(0)         # whole percents, so a drag emits at most 100 changes
        self.scale.set_size_request(-1, SLIDER_HEIGHT)
        self.scale.connect("value-changed", self.on_slide)
        self.scale.connect("button-press-event", self.on_drag, True)
        self.scale.connect("button-release-event", self.on_drag, False)
        col.pack_start(self.scale, True, True, 0)

        down = Gtk.Button(label="−")
        down.get_style_context().add_class("step")
        down.connect("clicked", lambda *_: self.nudge(-STEP))
        col.pack_start(down, False, False, 0)

        self.mute_btn = Gtk.Button(label=VOL_HIGH)
        self.mute_btn.connect("clicked", self.on_mute)
        col.pack_start(self.mute_btn, False, False, 0)
        return col

    def nudge(self, delta):
        self.scale.set_value(max(0, min(100, round(self.scale.get_value()) + delta)))

    def on_drag(self, _w, _event, pressed):
        self.dragging = pressed       # don't let the refresh yank the handle mid-drag
        return False

    def on_slide(self, scale):
        if self.syncing:
            return
        vol = round(scale.get_value())
        if vol == self.last_set:
            return
        self.last_set = vol
        pactl("set-sink-volume", "@DEFAULT_SINK@", "%d%%" % vol)
        self.vol_label.set_text("%d%%" % vol)

    def on_mute(self, *_):
        pactl("set-sink-mute", "@DEFAULT_SINK@", "toggle")
        self.sync()

    # ---------- device lists ----------
    def build_lists(self):
        for child in self.lists.get_children():
            child.destroy()
        self.rows = []
        for kind, title in (("sinks", "OUTPUT"), ("sources", "INPUT")):
            head = Gtk.Label(label=title, xalign=0)
            head.get_style_context().add_class("heading")
            if kind == "sources":
                head.set_margin_top(6)
            self.lists.pack_start(head, False, False, 0)
            for dev in devices(kind):
                btn = Gtk.Button()
                lbl = Gtk.Label(label="%s  %s" % (dev["icon"], dev["desc"]), xalign=0)
                lbl.set_ellipsize(3)  # PANGO_ELLIPSIZE_END
                btn.add(lbl)
                btn.connect("clicked", self.on_pick, kind, dev["name"])
                self.lists.pack_start(btn, False, False, 0)
                self.rows.append((btn, kind, dev["name"]))
        self.lists.show_all()

    def on_pick(self, _btn, kind, name):
        set_default(kind, name)
        self.sync()

    # ---------- state ----------
    def sync(self):
        self.syncing = True
        vol, muted = volume(), is_muted()
        if not self.dragging:
            self.scale.set_value(vol)
            self.last_set = vol
        self.vol_label.set_text("muted" if muted else "%d%%" % vol)
        self.mute_btn.set_label(VOL_OFF if muted else VOL_HIGH)
        defaults = {"sinks": default_of("sinks"), "sources": default_of("sources")}
        for btn, kind, name in self.rows:
            ctx = btn.get_style_context()
            if name == defaults[kind]:
                ctx.add_class("active")
            else:
                ctx.remove_class("active")
        self.syncing = False
        return True

    # ---------- closing ----------
    # Escape, or a click anywhere outside the panel (see ClickCatcher).
    def on_key(self, _w, event):
        if event.keyval == Gdk.KEY_Escape:
            self.close_panel()
        return False

    def close_panel(self):
        try:
            open(STATE, "w").close()   # mtime tells the next launch we just closed
        except OSError:
            pass
        if self.catcher:
            self.catcher.destroy()
            Gtk.main_quit()


def open_instance():
    """PID of a panel that is already up, or None.

    A pgrep for the script name is no good here: waybar launches us through
    `sh -c <path>`, so the wrapper shell matches too and we would kill it.
    """
    try:
        pid = int(open(PIDFILE).read().strip())
    except (OSError, ValueError):
        return None
    if pid == os.getpid():
        return None
    try:
        cmdline = open("/proc/%d/cmdline" % pid, "rb").read().decode("utf-8", "replace")
    except OSError:
        return None
    if "audio-popup.py" in cmdline and "python" in cmdline:
        return pid
    return None


def main():
    # Already open? The click that got here is a toggle: close it and stop.
    pid = open_instance()
    if pid:
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass
        try:
            open(STATE, "w").close()
        except OSError:
            pass
        return
    # Clicking the bar module steals focus, which closes the panel before this
    # instance starts; without this the click would just reopen it.
    try:
        if time.time() - os.path.getmtime(STATE) < 0.35:
            return
    except OSError:
        pass

    provider = Gtk.CssProvider()
    provider.load_from_data(themed_css())
    Gtk.StyleContext.add_provider_for_screen(
        Gdk.Screen.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    win = Panel()
    win.show_all()
    win.catcher = ClickCatcher(win.close_panel)
    win.catcher.show()
    try:
        with open(PIDFILE, "w") as fh:
            fh.write(str(os.getpid()))
    except OSError:
        pass
    signal.signal(signal.SIGTERM, lambda *_: Gtk.main_quit())
    try:
        Gtk.main()
    finally:
        try:
            os.unlink(PIDFILE)
        except OSError:
            pass


if __name__ == "__main__":
    sys.exit(main())
