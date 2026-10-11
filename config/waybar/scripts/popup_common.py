"""Shared scaffolding for the waybar panels.

Everything a panel needs that isn't its own content, in one place:

  - place_above_bar()  layer-shell setup, anchored to a bottom corner
  - theme_colours()    the accent chosen with the Color widget
  - themed_css()       fills @BORDER@ / @ROW@ / @ACCENT@ / @ACCENT_HOVER@
  - ClickCatcher       click-outside-to-close, one surface per monitor
  - run()              pidfile toggle (click the widget again to close) + main loop

A panel subclasses Gtk.Window, builds its content, sets self.catcher = None and
provides close_panel(); then its script calls run(Panel, __file__, CSS).

The older panels (audio/wifi/bt/theme) still carry their own copies of this.
New panels should import from here; migrating the old ones is the follow-up.
"""
import os
import signal
import sys
import time

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GtkLayerShell", "0.1")
from gi.repository import Gdk, GLib, Gtk, GtkLayerShell  # noqa: E402

BAR_HEIGHT = 34          # "height" in config.jsonc
GAP = 12                 # same offsets the rofi menus use
REOPEN_GUARD_S = 0.35    # a launch this soon after a close is the toggle click, not a reopen
ACCENT_FILE = os.path.expanduser("~/.config/theme/accent")
RUN_DIR = os.environ.get("XDG_RUNTIME_DIR", "/tmp")

# CSS every panel starts from. Panels append their own rules.
BASE_CSS = b"""
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
.dim { color: #8a8a8a; font-size: 9pt; }
.warn { color: #e06c75; font-size: 9pt; }
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
button.active label { color: #101010; }
"""


# ---------- theme ----------
def theme_colours():
    """(primary, stops) as chosen with the Color widget; stops is empty for plain colours."""
    primary, stops = "#ff3344", []
    try:
        with open(ACCENT_FILE) as fh:
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


def themed_css(css):
    """Fill the palette holes in a CSS bytes blob.

    Gradient themes (rainbow, trans) paint frames and selected rows with the
    real gradient; single colours become a flat one-stop gradient so the same
    rules serve both.
    """
    primary, stops = theme_colours()
    r, g, b = (int(primary[i:i + 2], 16) for i in (1, 3, 5))
    if stops:
        border = "linear-gradient(135deg, %s)" % ", ".join(stops)
        row = "linear-gradient(90deg, %s)" % ", ".join(stops)
    else:
        border = row = "linear-gradient(0deg, %s, %s)" % (primary, primary)
    return (css.replace(b"@BORDER@", border.encode())
               .replace(b"@ROW@", row.encode())
               .replace(b"@ACCENT@", primary.encode())
               .replace(b"@ACCENT_HOVER@", ("rgba(%d, %d, %d, 0.25)" % (r, g, b)).encode()))


# ---------- placement ----------
def _rgba(window):
    window.set_app_paintable(True)
    visual = Gdk.Screen.get_default().get_rgba_visual()
    if visual:
        window.set_visual(visual)


def place_above_bar(window, side="right"):
    """Make `window` a layer-shell panel sitting just above the bar, in the
    bottom-left or bottom-right corner. It owns the keyboard while open so
    Escape and text entry work."""
    _rgba(window)
    GtkLayerShell.init_for_window(window)
    GtkLayerShell.set_layer(window, GtkLayerShell.Layer.OVERLAY)
    corner = GtkLayerShell.Edge.LEFT if side == "left" else GtkLayerShell.Edge.RIGHT
    GtkLayerShell.set_anchor(window, GtkLayerShell.Edge.BOTTOM, True)
    GtkLayerShell.set_anchor(window, corner, True)
    GtkLayerShell.set_margin(window, GtkLayerShell.Edge.BOTTOM, BAR_HEIGHT + GAP)
    GtkLayerShell.set_margin(window, corner, GAP)
    GtkLayerShell.set_keyboard_mode(window, GtkLayerShell.KeyboardMode.EXCLUSIVE)


# ---------- dismissal ----------
class ClickCatcher:
    """Invisible layers that make a click outside the panel dismiss it.

    One surface per monitor: a layer surface only covers the output it is
    assigned to, so a single one would leave clicks on the other screens doing
    nothing. Each stops short of the bar, which keeps the widget itself
    clickable -- clicking it again re-runs the script, and run() closes the
    panel through its pidfile.
    """

    def __init__(self, on_click):
        self.windows = []
        display = Gdk.Display.get_default()
        for i in range(display.get_n_monitors()):
            self.windows.append(self._surface(display.get_monitor(i), on_click))

    def _surface(self, monitor, on_click):
        win = Gtk.Window(type=Gtk.WindowType.TOPLEVEL)
        _rgba(win)
        GtkLayerShell.init_for_window(win)
        GtkLayerShell.set_monitor(win, monitor)
        GtkLayerShell.set_layer(win, GtkLayerShell.Layer.TOP)   # panels are OVERLAY, so above this
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
        box.connect("button-press-event", self._on_press, on_click)
        win.add(box)
        return win

    def _on_press(self, _widget, _event, on_click):
        on_click()
        return True

    def show(self):
        for win in self.windows:
            win.show_all()

    def destroy(self):
        for win in self.windows:
            win.destroy()
        self.windows = []


# ---------- lifecycle ----------
def _paths(script):
    stem = os.path.splitext(os.path.basename(script))[0]
    return (os.path.join(RUN_DIR, "waybar-%s.closed" % stem),
            os.path.join(RUN_DIR, "waybar-%s.pid" % stem))


def _touch(path):
    try:
        open(path, "w").close()
    except OSError:
        pass


def _open_instance(pidfile, script):
    """PID of this panel if it is already up, else None.

    A pgrep on the script name is no good: waybar launches us through
    `sh -c <path>`, so the wrapper shell would match too and get killed.
    """
    try:
        pid = int(open(pidfile).read().strip())
    except (OSError, ValueError):
        return None
    if pid == os.getpid():
        return None
    try:
        cmdline = open("/proc/%d/cmdline" % pid, "rb").read().decode("utf-8", "replace")
    except OSError:
        return None
    name = os.path.basename(script)
    return pid if name in cmdline and "python" in cmdline else None


def mark_closed(script):
    """Record a close so a widget click arriving right behind it doesn't reopen."""
    _touch(_paths(script)[0])


def run(panel_class, script, css):
    """Toggle-aware entry point: close an open instance, else open one."""
    state, pidfile = _paths(script)

    pid = _open_instance(pidfile, script)
    if pid:                                  # the click that got here is a toggle
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass
        _touch(state)
        return
    try:
        if time.time() - os.path.getmtime(state) < REOPEN_GUARD_S:
            return
    except OSError:
        pass

    provider = Gtk.CssProvider()
    provider.load_from_data(themed_css(css))
    Gtk.StyleContext.add_provider_for_screen(
        Gdk.Screen.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    win = panel_class()
    win.show_all()
    win.catcher = ClickCatcher(win.close_panel)
    win.catcher.show()
    try:
        with open(pidfile, "w") as fh:
            fh.write(str(os.getpid()))
    except OSError:
        pass
    signal.signal(signal.SIGTERM, lambda *_: Gtk.main_quit())
    try:
        Gtk.main()
    finally:
        try:
            os.unlink(pidfile)
        except OSError:
            pass


def script_dir():
    """So scripts can `sys.path.insert(0, script_dir())` before importing this."""
    return os.path.dirname(os.path.abspath(sys.argv[0]))
