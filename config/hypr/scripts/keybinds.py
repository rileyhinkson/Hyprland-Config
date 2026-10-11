#!/usr/bin/env python3
"""Searchable cheat-sheet of the Hyprland keybinds, read from hyprland.lua.

Binds written out literally as hl.bind("...", ...) are parsed from the config,
so the list stays current as you edit it. The workspace binds are generated in
a loop and can't be read that way, so they are listed from EXTRA below -- add
to EXTRA if you ever add more loop-generated binds.
"""
import os
import re
import subprocess
import sys

CONFIG = os.path.expanduser("~/.config/hypr/hyprland.lua")
THEME = os.path.expanduser("~/.config/rofi/keybinds.rasi")

# Loop-generated binds (hyprland.lua "Switch workspaces with mainMod + [0-9]").
EXTRA = [
    ("SUPER + 1…0", "Switch to workspace 1-10 on the focused monitor"),
    ("SUPER + SHIFT + 1…0", "Move window to workspace 1-10 on the focused monitor"),
]

VERBS = {
    "window.close": "Close window",
    "window.float": "Toggle floating",
    "window.pseudo": "Toggle pseudo-tiling",
    "window.pin": "Pin window above the others",
    "window.center": "Center window",
    "window.drag": "Drag window with the mouse",
    "window.resize": "Resize window",
    "window.cycle_next": "Cycle through windows",
    "window.fullscreen": "Toggle fullscreen",
    "window.move": "Move window",
    "workspace.toggle_special": "Toggle scratchpad",
    "layout": "Toggle split direction",
    "focus": "Focus",
}


def read_call(line, start):
    """Return the top-level arguments of a call whose '(' just ended at start.

    None if the call doesn't close on this line -- that's a loop-generated or
    multi-line bind, which EXTRA covers instead.
    """
    depth, quote, args, cur = 1, None, [], ""
    for i in range(start, len(line)):
        ch = line[i]
        if quote:
            cur += ch
            if ch == quote and line[i - 1] != "\\":
                quote = None
            continue
        if ch in "\"'":
            quote = ch
        elif ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
            if depth == 0:
                args.append(cur)
                return [a.strip() for a in args], i
        if depth == 1 and ch == ",":
            args.append(cur)
            cur = ""
        else:
            cur += ch
    return None, None


def locals_of(src):
    return dict(re.findall(r'^local\s+(\w+)\s*=\s*"([^"]*)"', src, re.M))


def eval_key(expr, mods):
    """mainMod .. " + Q"  ->  SUPER + Q. None if it needs a runtime value."""
    out = []
    for part in expr.split(".."):
        part = part.strip()
        if part.startswith(('"', "'")):
            out.append(part[1:-1])
        elif part in mods:
            out.append(mods[part])
        else:
            return None
    return re.sub(r"\s+", " ", "".join(out)).strip()


def describe(dispatch, consts):
    m = re.match(r"hl\.dsp\.([\w.]+)\((.*)\)\s*$", dispatch, re.S)
    if not m:
        return dispatch.strip()
    path, inner = m.group(1), m.group(2).strip()

    if path == "exec_cmd":
        if inner.startswith(('"', "'")):
            cmd = inner[1:-1]
        else:                                   # screenshot .. " region", terminal, ...
            head = inner.split("..")[0].strip()
            tail = "".join(re.findall(r'"([^"]*)"', inner)).strip()
            cmd = (consts.get(head, head) + " " + tail).strip()
        cmd = cmd.replace("~/.config/hypr/scripts/", "").replace("~/.config/waybar/scripts/", "")
        return "Run: " + (cmd if len(cmd) <= 52 else cmd[:49] + "…")

    hint = ""
    for field in ("direction", "workspace", "mode", "action"):
        found = re.search(field + r'\s*=\s*"([^"]*)"', inner)
        if found:
            hint = found.group(1)
            break
    if not hint:
        quoted = re.findall(r'"([^"]*)"', inner)
        hint = quoted[0] if quoted else ""

    base = VERBS.get(path, path.replace(".", " "))
    if path == "focus" and hint == "previous":
        return "Back to the previous workspace"
    if path == "focus" and hint.startswith("m"):
        return "Scroll to the %s workspace on this monitor" % ("next" if "+" in hint else "previous")
    if path == "window.move" and hint.startswith("special"):
        return "Move window to the scratchpad"
    if path == "window.cycle_next":
        return "Cycle backwards through windows" if "false" in inner else base
    if path == "window.fullscreen":
        return "Toggle maximized" if hint == "maximized" else "Toggle fullscreen"
    if path == "window.resize":                  # { x = -40, y = 0, relative = true }
        xm = re.search(r"x\s*=\s*(-?\d+)", inner)
        ym = re.search(r"y\s*=\s*(-?\d+)", inner)
        xv = int(xm.group(1)) if xm else 0
        yv = int(ym.group(1)) if ym else 0
        if xv:
            return "Resize window " + ("wider" if xv > 0 else "narrower")
        if yv:
            return "Resize window " + ("taller" if yv > 0 else "shorter")
        return base
    if hint and hint.lower() not in base.lower() and base.endswith(("window", "Focus")):
        return "%s %s" % (base, hint)
    return base


def collect():
    with open(CONFIG) as fh:
        src = fh.read()
    consts = locals_of(src)
    mods = {k: v for k, v in consts.items() if k == "mainMod"}
    mods.setdefault("mainMod", "SUPER")

    rows, group = [], ""
    for line in src.splitlines():
        stripped = line.strip()
        if stripped.startswith("--"):
            text = stripped.lstrip("-").strip()
            if text and not set(text) <= set("- "):     # skip ---- dividers ----
                group = text
            continue
        m = re.search(r"hl\.bindm?\(", line)
        if not m:
            continue
        args, end = read_call(line, m.end())
        if not args:
            continue
        key = eval_key(args[0], mods)
        if not key:
            continue
        note = line[end:].split("--", 1)
        note = note[1].strip() if len(note) > 1 else ""
        desc = describe(args[1], consts) if len(args) > 1 else ""
        if note:            # a trailing comment qualifies the bind, e.g. "dwindle only"
            desc = "%s (%s)" % (desc, note) if desc else note
        rows.append((key, desc or group))
    return rows


def main():
    rows = collect() + EXTRA
    if not rows:
        sys.exit("no binds found in %s" % CONFIG)
    width = max(len(k) for k, _ in rows)
    esc = lambda s: s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    lines = ["<tt><b>%s</b></tt>   <span alpha='65%%'>%s</span>"
             % (esc(k.ljust(width)), esc(d)) for k, d in rows]

    try:
        subprocess.run(
            ["rofi", "-dmenu", "-i", "-markup-rows", "-no-custom", "-theme", THEME,
             "-p", "Keybinds", "-mesg", "%d binds, from hyprland.lua" % len(rows)],
            input="\n".join(lines), text=True, stdout=subprocess.DEVNULL)
    except FileNotFoundError:
        print("\n".join(lines))


if __name__ == "__main__":
    main()
