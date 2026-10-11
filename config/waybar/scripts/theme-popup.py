#!/usr/bin/env python3
"""Colour picker for the waybar accent widget.

Black stays the base everywhere; this swaps the secondary colour. The palette
and all the file rewriting live in theme.sh -- this is only the swatch grid.
"""

# ---------------------------------------------------------------------------
# Shared scaffolding note: ClickCatcher, theme_colours/themed_css and
# the pidfile dance below are duplicated verbatim across audio-popup.py,
# wifi-popup.py, bt-popup.py and theme-popup.py. They are kept in lockstep on
# purpose -- if you fix a dismissal or theming bug here, fix it in the others
# too, or the panels start behaving differently from each other.
#
# Colours come from ~/.config/theme/accent, written by waybar/scripts/theme.sh.
# Never hardcode an accent in these files; use the @ACCENT@ / @BORDER@ / @ROW@
# placeholders in CSS so the Color widget keeps working.
# ---------------------------------------------------------------------------

import os
import signal
import subprocess

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GtkLayerShell", "0.1")
from gi.repository import Gdk, Gtk, GtkLayerShell  # noqa: E402

BAR_HEIGHT = 34
GAP = 12
COLUMNS = 5
THEME_SH = os.path.expanduser("~/.config/waybar/scripts/theme.sh")

_RUN = os.environ.get("XDG_RUNTIME_DIR", "/tmp")
STATE = os.path.join(_RUN, "waybar-theme-popup.closed")
PIDFILE = os.path.join(_RUN, "waybar-theme-popup.pid")

BASE_CSS = """
window { background-color: transparent; }
.catcher { background-color: rgba(0, 0, 0, 0.01); }
#frame {
    background-image: %(border)s;
    border-radius: 10px;
    padding: 2px;
}
#root {
    background-color: #161616;
    border-radius: 8px;
    padding: 14px;
}
* { font-family: "JetBrainsMono Nerd Font", monospace; font-size: 11pt; color: #e6e6e6; }
.heading { color: #8a8a8a; font-size: 9pt; }
button.swatch {
    background-image: none;
    min-width: 42px;
    min-height: 42px;
    padding: 0;
    border-radius: 21px;
    border: 2px solid transparent;
    box-shadow: none;
}
button.swatch:hover { border-color: #8a8a8a; }
button.swatch.current { border-color: #e6e6e6; }
"""


def theme(*args):
    try:
        p = subprocess.run([THEME_SH, *args], capture_output=True, text=True, timeout=20)
        return p.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def palette():
    """(name, primary, stops) per entry -- stops is empty for plain colours."""
    out = []
    for line in theme("list").splitlines():
        parts = line.split()
        if len(parts) >= 2:
            out.append((parts[0], parts[1], parts[2:]))
    return out


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
        self.current = theme("current")

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

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        root.set_name("root")
        frame = Gtk.Box()
        frame.set_name("frame")
        frame.add(root)
        self.add(frame)

        head = Gtk.Label(label="ACCENT COLOUR", xalign=0)
        head.get_style_context().add_class("heading")
        root.pack_start(head, False, False, 0)

        grid = Gtk.Grid(row_spacing=8, column_spacing=8)
        for i, (name, hex_, _stops) in enumerate(palette()):
            grid.attach(self.swatch(name, hex_), i % COLUMNS, i // COLUMNS, 1, 1)
        root.pack_start(grid, False, False, 0)

        self.name_label = Gtk.Label(label=self.name_for(self.current), xalign=0)
        self.name_label.get_style_context().add_class("heading")
        root.pack_start(self.name_label, False, False, 0)

        self.connect("key-press-event", self.on_key)
        self.connect("destroy", Gtk.main_quit)

    def name_for(self, current):
        for name, value, stops in palette():
            if name == current:
                return "%s  %s" % (name, " ".join(stops) if stops else value)
        return current

    def swatch(self, name, hex_):
        btn = Gtk.Button()
        ctx = btn.get_style_context()
        ctx.add_class("swatch")
        ctx.add_class("sw-" + name)
        if name == self.current:
            ctx.add_class("current")
        btn.set_tooltip_text(name)
        btn.connect("clicked", self.on_pick, name)
        return btn

    def on_pick(self, _btn, name):
        theme("set", name)
        self.close_panel()

    def on_key(self, _w, event):
        if event.keyval == Gdk.KEY_Escape:
            self.close_panel()
        return False

    def close_panel(self):
        try:
            open(STATE, "w").close()
        except OSError:
            pass
        if self.catcher:
            self.catcher.destroy()
            self.catcher = None
        Gtk.main_quit()


def open_instance():
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
    return pid if "theme-popup.py" in cmdline and "python" in cmdline else None


def main():
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
    try:
        import time
        if time.time() - os.path.getmtime(STATE) < 0.35:
            return
    except OSError:
        pass

    colours = palette()
    primary = theme("get") or "#ff3344"
    current = theme("current")
    stops = next((st for n, _h, st in colours if n == current and st), [])
    border = ("linear-gradient(135deg, %s)" % ", ".join(stops) if stops
              else "linear-gradient(0deg, %s, %s)" % (primary, primary))
    css = BASE_CSS % {"border": border}
    for name, hex_, stops in colours:
        if stops:
            css += "button.swatch.sw-%s { background-image: linear-gradient(90deg, %s); }\n" % (
                name, ", ".join(stops))
        else:
            css += "button.swatch.sw-%s { background-color: %s; }\n" % (name, hex_)

    provider = Gtk.CssProvider()
    provider.load_from_data(css.encode())
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
    main()
