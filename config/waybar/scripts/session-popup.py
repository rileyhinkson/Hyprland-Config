#!/usr/bin/env python3
"""Session panel behind the penguin at the left end of the bar.

Shows who is logged in, with power off / restart / log out / switch user.
The three that end the session need a second click to confirm -- the panel
is one click from the bar, and a misclick here is expensive.

Power off, restart and log out go through hyprshutdown, which closes apps
cleanly before Hyprland exits (and runs the systemctl step afterwards for
the first two). Switch user asks the display manager for its greeter over
D-Bus, which leaves this session running.

    session-popup.py          open / close the panel
    session-popup.py status   waybar JSON for the widget
"""
import json
import os
import pwd
import shutil
import socket
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from popup_common import BASE_CSS, GLib, Gdk, Gtk, mark_closed, place_above_bar, run  # noqa: E402

CONFIRM_S = 4          # how long the "click again" state lasts
WIDTH = 260

TUX = "\U0000F17C"        # nf-fa-linux, the classic Tux (NOT U+F031A, which is a sitemap)
USER_ICON = "\U000F0004"
POWER = "\U000F0425"
RESTART = "\U000F0709"
LOGOUT = "\U000F0343"
SWITCH = "\U000F04E1"

CSS = BASE_CSS + b"""
.name { font-size: 13pt; }
button.action { padding: 9px 12px; }
button.armed { background-image: none; background-color: #e06c75; color: #101010; }
button.armed label { color: #101010; }
"""


def whoami():
    entry = pwd.getpwuid(os.getuid())
    full = entry.pw_gecos.split(",")[0].strip() or entry.pw_name
    return full, "%s@%s" % (entry.pw_name, socket.gethostname())


def actions():
    """(glyph, label, command, needs_confirm). Built at runtime so a missing
    hyprshutdown degrades to the plain commands instead of a broken button."""
    if shutil.which("hyprshutdown"):
        def ending(label, post=None):
            cmd = ["hyprshutdown", "-t", label]
            return cmd + (["-p", post] if post else [])
        power = ending("Powering off…", "systemctl poweroff")
        reboot = ending("Restarting…", "systemctl reboot")
        logout = ending("Logging out…")
    else:
        power = ["systemctl", "poweroff"]
        reboot = ["systemctl", "reboot"]
        logout = ["hyprctl", "dispatch", "hl.dsp.exit()"]
    switch = ["busctl", "call", "org.freedesktop.DisplayManager",
              "/org/freedesktop/DisplayManager/Seat0",
              "org.freedesktop.DisplayManager.Seat", "SwitchToGreeter"]
    return [
        (POWER, "Power off", power, True),
        (RESTART, "Restart", reboot, True),
        (LOGOUT, "Log out", logout, True),
        (SWITCH, "Switch user", switch, False),
    ]


class Panel(Gtk.Window):
    def __init__(self):
        super().__init__(type=Gtk.WindowType.TOPLEVEL)
        self.catcher = None
        self.armed = None            # (button, label, command) awaiting its second click
        self.arm_timer = None
        place_above_bar(self, side="left")

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        root.set_name("root")
        root.set_size_request(WIDTH, -1)
        frame = Gtk.Box()
        frame.set_name("frame")
        frame.add(root)
        self.add(frame)

        root.pack_start(self.header(), False, False, 0)
        root.pack_start(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL), False, False, 4)
        for glyph, label, command, confirm in actions():
            root.pack_start(self.action_button(glyph, label, command, confirm), False, False, 0)

        self.connect("key-press-event", self.on_key)
        self.connect("destroy", Gtk.main_quit)

    def header(self):
        full, at_host = whoami()
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        icon = Gtk.Label(label=USER_ICON)
        icon.get_style_context().add_class("name")
        box.pack_start(icon, False, False, 0)
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        name = Gtk.Label(label=full, xalign=0)
        name.get_style_context().add_class("name")
        name.set_ellipsize(3)
        sub = Gtk.Label(label=at_host, xalign=0)
        sub.get_style_context().add_class("dim")
        sub.set_ellipsize(3)
        text.pack_start(name, False, False, 0)
        text.pack_start(sub, False, False, 0)
        box.pack_start(text, True, True, 0)
        return box

    def action_button(self, glyph, label, command, confirm):
        btn = Gtk.Button()
        btn.get_style_context().add_class("action")
        inner = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        inner.pack_start(Gtk.Label(label=glyph), False, False, 0)
        text = Gtk.Label(label=label, xalign=0)
        inner.pack_start(text, True, True, 0)
        btn.add(inner)
        btn.connect("clicked", self.on_action, text, label, command, confirm)
        return btn

    # ---------- actions ----------
    def on_action(self, btn, text, label, command, confirm):
        if not confirm:
            self.launch(command)
            return
        if self.armed and self.armed[0] is btn:      # second click: go
            self.launch(command)
            return
        self.disarm()
        self.armed = (btn, text, label)
        btn.get_style_context().add_class("armed")
        text.set_text("Click again to %s" % label.lower())
        self.arm_timer = GLib.timeout_add_seconds(CONFIRM_S, self.disarm)

    def disarm(self, *_):
        if self.arm_timer:
            GLib.source_remove(self.arm_timer)
            self.arm_timer = None
        if self.armed:
            btn, text, label = self.armed
            btn.get_style_context().remove_class("armed")
            text.set_text(label)
            self.armed = None
        return False

    def launch(self, command):
        subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.close_panel()

    # ---------- closing ----------
    def on_key(self, _w, event):
        if event.keyval == Gdk.KEY_Escape:
            self.close_panel()
        return False

    def close_panel(self):
        mark_closed(__file__)
        if self.catcher:
            self.catcher.destroy()
            self.catcher = None
        Gtk.main_quit()


def status():
    full, at_host = whoami()
    print(json.dumps({"text": TUX, "tooltip": "%s  (%s)\n\nClick for session menu" % (full, at_host),
                      "class": "session"}))


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "status":
        status()
    else:
        run(Panel, __file__, CSS)
