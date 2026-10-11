#!/usr/bin/env python3
"""Wi-Fi panel for the waybar network widget.

A layer-shell popup above the bar: the networks in range, connect inline
(password prompt included), and a settings button for anything nmcli can't do
here. Dismissal matches audio-popup.py -- click the widget again, press
Escape, or move the pointer off the panel.
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
import re
import signal
import subprocess
import threading
import time

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GtkLayerShell", "0.1")
from gi.repository import Gdk, GLib, Gtk, GtkLayerShell  # noqa: E402

BAR_HEIGHT = 34
GAP = 12
POLL_MS = 5000          # cheap refresh; the rescan button does a real scan
LIST_HEIGHT = 300

_RUN = os.environ.get("XDG_RUNTIME_DIR", "/tmp")
STATE = os.path.join(_RUN, "waybar-wifi-popup.closed")
PIDFILE = os.path.join(_RUN, "waybar-wifi-popup.pid")

WIFI_ON = "\U000F05A9"
WIFI_OFF = "\U000F05AA"
RESCAN = "\U000F0450"
SETTINGS = "\U000F0493"
DISCONNECT = "\U000F0156"
LOCK = "\U000F033E"
UNLOCK = "\U000F033F"
BARS = ["\U000F091F", "\U000F0922", "\U000F0925", "\U000F0928"]

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
.dim { color: #8a8a8a; font-size: 9pt; }
.ssid { font-size: 12pt; }
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
/* the dim tags sit on the accent here, so they need the dark ink too */
button.active label { color: #101010; }
button.icon { padding: 6px 9px; }
entry {
    background-color: #2a2a2a;
    border: none;
    border-radius: 8px;
    padding: 6px 10px;
    color: #e6e6e6;
}
separator { background-color: #2a2a2a; min-height: 1px; }
scrolledwindow undershoot, scrolledwindow overshoot { background: none; }
"""


def nmcli(*args, timeout=25):
    try:
        p = subprocess.run(["nmcli", *args], capture_output=True, text=True, timeout=timeout)
        return p.returncode, p.stdout.strip(), p.stderr.strip()
    except (OSError, subprocess.SubprocessError) as exc:
        return 1, "", str(exc)


def radio_on():
    return nmcli("radio", "wifi")[1].strip() == "enabled"


def wifi_device():
    out = nmcli("-t", "-f", "DEVICE,TYPE", "device")[1]
    for line in out.splitlines():
        dev, _, kind = line.partition(":")
        if kind == "wifi":
            return dev
    return ""


def known_networks():
    out = nmcli("-g", "NAME", "connection", "show")[1]
    return {line for line in out.splitlines() if line}


def bars(signal_pct):
    return BARS[min(3, int(signal_pct) // 26)]


def scan(rescan=False):
    """One entry per SSID, strongest first."""
    code, out, _ = nmcli("-t", "-f", "IN-USE,SIGNAL,SECURITY,SSID", "device", "wifi",
                         "list", "--rescan", "yes" if rescan else "no",
                         timeout=40 if rescan else 25)
    if code != 0:
        return []
    nets, seen = [], set()
    for line in out.splitlines():
        # nmcli escapes colons inside fields as \:
        parts = re.split(r"(?<!\\):", line)
        if len(parts) < 4:
            continue
        in_use, sig, sec, ssid = parts[0], parts[1], parts[2], ":".join(parts[3:])
        ssid = ssid.replace("\\:", ":")
        if not ssid or ssid in seen:
            continue
        seen.add(ssid)
        nets.append({
            "ssid": ssid,
            "signal": int(sig) if sig.isdigit() else 0,
            "secure": sec not in ("", "--"),
            "active": in_use.strip() == "*",
        })
    nets.sort(key=lambda n: (-n["active"], -n["signal"]))
    return nets


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
        self.pinned = False          # a password box is open; don't close on leave
        self.busy = False
        self.auto_scanned = False
        self.device = wifi_device()

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
        root.set_size_request(400, -1)
        frame = Gtk.Box()
        frame.set_name("frame")
        frame.add(root)
        self.add(frame)

        root.pack_start(self.header(), False, False, 0)
        root.pack_start(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL), False, False, 0)

        self.scroller = Gtk.ScrolledWindow()
        self.scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.scroller.set_min_content_height(LIST_HEIGHT)
        self.list = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.scroller.add(self.list)
        root.pack_start(self.scroller, True, True, 0)

        self.status = Gtk.Label(label="", xalign=0)
        self.status.get_style_context().add_class("dim")
        self.status.set_line_wrap(True)
        root.pack_start(self.status, False, False, 0)

        self.connect("key-press-event", self.on_key)
        self.connect("destroy", Gtk.main_quit)

        self.refresh()
        GLib.timeout_add(POLL_MS, self.refresh)

    # ---------- header ----------
    def header(self):
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        self.title = Gtk.Label(label="Wi-Fi", xalign=0)
        self.title.get_style_context().add_class("ssid")
        self.title.set_ellipsize(3)
        self.subtitle = Gtk.Label(label="", xalign=0)
        self.subtitle.get_style_context().add_class("dim")
        text.pack_start(self.title, False, False, 0)
        text.pack_start(self.subtitle, False, False, 0)
        box.pack_start(text, True, True, 0)

        def icon_button(glyph, tip, handler):
            b = Gtk.Button(label=glyph)
            b.get_style_context().add_class("icon")
            b.set_tooltip_text(tip)
            b.connect("clicked", handler)
            box.pack_start(b, False, False, 0)
            return b

        self.disconnect_btn = icon_button(DISCONNECT, "Disconnect", self.on_disconnect)
        icon_button(RESCAN, "Scan again", self.on_rescan)
        icon_button(SETTINGS, "Advanced Wi-Fi settings", self.on_settings)
        self.radio_btn = icon_button(WIFI_ON, "Turn Wi-Fi on or off", self.on_radio)
        return box

    def on_settings(self, *_):
        subprocess.Popen(["nm-connection-editor"])
        self.close_panel()

    def on_radio(self, *_):
        nmcli("radio", "wifi", "off" if radio_on() else "on")
        self.refresh()

    def on_rescan(self, *_):
        self.set_status("Scanning…")
        self.run_async(lambda: scan(rescan=True), lambda nets: (self.set_status(""), self.fill(nets)))

    def on_disconnect(self, *_):
        if self.device:
            nmcli("device", "disconnect", self.device)
        self.refresh()

    # ---------- network list ----------
    def fill(self, nets):
        for child in self.list.get_children():
            child.destroy()
        known = known_networks()
        for net in nets:
            self.list.pack_start(self.row(net, net["ssid"] in known), False, False, 0)
        self.list.show_all()

    def row(self, net, is_known):
        btn = Gtk.Button()
        inner = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        inner.pack_start(Gtk.Label(label=bars(net["signal"])), False, False, 0)
        inner.pack_start(Gtk.Label(label=LOCK if net["secure"] else UNLOCK), False, False, 0)
        name = Gtk.Label(label=net["ssid"], xalign=0)
        name.set_ellipsize(3)
        inner.pack_start(name, True, True, 0)
        tail = Gtk.Label(label="connected" if net["active"] else "%d%%" % net["signal"])
        tail.get_style_context().add_class("dim")
        inner.pack_start(tail, False, False, 0)
        btn.add(inner)
        if net["active"]:
            btn.get_style_context().add_class("active")
            btn.set_sensitive(False)      # disconnect lives in the header, so a misclick can't drop you
        else:
            btn.connect("clicked", self.on_pick, net, is_known)
        return btn

    def on_pick(self, btn, net, is_known):
        if self.busy:
            return
        if net["secure"] and not is_known:
            self.ask_password(btn, net)
        else:
            self.connect_to(net["ssid"], None, known=is_known)

    def ask_password(self, btn, net):
        """Swap the row for an inline password box."""
        self.pinned = True
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        entry = Gtk.Entry()
        entry.set_visibility(False)
        entry.set_placeholder_text("Password for %s" % net["ssid"])
        entry.set_activates_default(True)
        go = Gtk.Button(label="Connect")
        cancel = Gtk.Button(label="Cancel")
        box.pack_start(entry, True, True, 0)
        box.pack_start(go, False, False, 0)
        box.pack_start(cancel, False, False, 0)

        index = [i for i, c in enumerate(self.list.get_children()) if c is btn]
        self.list.pack_start(box, False, False, 0)
        if index:
            self.list.reorder_child(box, index[0] + 1)
        self.list.show_all()
        entry.grab_focus()

        def submit(*_):
            pw = entry.get_text()
            if pw:
                self.pinned = False
                box.destroy()
                self.connect_to(net["ssid"], pw, known=False)

        def dismiss(*_):
            self.pinned = False
            box.destroy()

        entry.connect("activate", submit)
        go.connect("clicked", submit)
        cancel.connect("clicked", dismiss)

    # ---------- connecting ----------
    def connect_to(self, ssid, password, known):
        self.busy = True
        self.set_status("Connecting to %s…" % ssid)

        def work():
            if known:
                code, _, err = nmcli("connection", "up", "id", ssid, timeout=45)
                if code == 0:
                    return True, ""
            if password:
                code, _, err = nmcli("device", "wifi", "connect", ssid, "password", password, timeout=45)
            else:
                code, _, err = nmcli("device", "wifi", "connect", ssid, timeout=45)
            return code == 0, err

        def done(result):
            ok, err = result
            self.busy = False
            if ok:
                self.set_status("")
            else:
                self.set_status(err.splitlines()[-1] if err else "Couldn't connect", warn=True)
            self.refresh()

        self.run_async(work, done)

    def run_async(self, work, done):
        def runner():
            result = work()
            GLib.idle_add(done, result)
        threading.Thread(target=runner, daemon=True).start()

    def set_status(self, text, warn=False):
        ctx = self.status.get_style_context()
        ctx.remove_class("warn")
        ctx.add_class("warn" if warn else "dim")
        self.status.set_text(text)

    # ---------- state ----------
    def refresh(self):
        on = radio_on()
        self.radio_btn.set_label(WIFI_ON if on else WIFI_OFF)
        if not on:
            self.title.set_text("Wi-Fi is off")
            self.subtitle.set_text("")
            self.disconnect_btn.set_sensitive(False)
            for child in self.list.get_children():
                child.destroy()
            return True

        nets = scan(rescan=False)
        active = next((n for n in nets if n["active"]), None)
        self.disconnect_btn.set_sensitive(active is not None)
        if active:
            self.title.set_text(active["ssid"])
            ip = nmcli("-g", "IP4.ADDRESS", "device", "show", self.device)[1].splitlines()
            self.subtitle.set_text("%s · %d%%" % (ip[0] if ip else "no address", active["signal"]))
        else:
            self.title.set_text("Not connected")
            self.subtitle.set_text("%d networks in range" % len(nets))
        if not self.pinned:          # never rebuild the list out from under a password box
            self.fill(nets)
        # NetworkManager's cached list goes stale; if it's empty on open, scan
        # once rather than making them press the button to see anything.
        if not self.auto_scanned and len(nets) <= 1 and not self.busy:
            self.auto_scanned = True
            self.on_rescan()
        return True

    # ---------- closing ----------
    # Escape, or a click anywhere outside the panel (see ClickCatcher).
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
            Gtk.main_quit()


def open_instance():
    """PID of a panel already up, or None. A pgrep would match waybar's sh -c."""
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
    return pid if "wifi-popup.py" in cmdline and "python" in cmdline else None


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
    main()
