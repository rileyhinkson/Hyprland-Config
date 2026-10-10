-- Desktop PC: ASUS VG249Q1A in the middle, two MSI MP2412s in portrait on either side

-- Layout copied from KDE (~/.config/kwinoutputconfig.json)
-- Left: MSI MP2412, portrait
hl.monitor({
    output    = "HDMI-A-2",
    mode      = "1920x1080@100",
    position  = "0x0",
    scale     = 1,
    transform = 3,
})
-- Middle: ASUS VG249Q1A
hl.monitor({
    output   = "DP-1",
    mode     = "1920x1080@144",
    position = "1080x707",
    scale    = 1,
})
-- Right: MSI MP2412, portrait
hl.monitor({
    output    = "HDMI-A-1",
    mode      = "1920x1080@100",
    position  = "3000x0",
    scale     = 1,
    transform = 1,
})
