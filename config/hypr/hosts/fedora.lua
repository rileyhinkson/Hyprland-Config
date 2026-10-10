-- Laptop. Hostname is the Fedora default "fedora"; rename this file if you set one.

hl.monitor({
    output   = "eDP-1",
    mode     = "1920x1080@60.06",
    position = "0x0",
    scale    = 1.5,
})
hl.monitor({
    output   = "HDMI-A-3",
    mode     = "1920x1080@60.0",
    position = "1280x0",
    scale    = 1.0,
    mirror   = "eDP-1",
})

-- Make Steam scale its own UI to match the 1.5 monitor scale.
hl.env("STEAM_FORCE_DESKTOPUI_SCALING", "1.5")
