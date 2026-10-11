#!/usr/bin/env bash
# Rofi Bluetooth menu backed by BlueZ (bluetoothctl).
# Usage: bt-menu.sh          open the menu
#        bt-menu.sh toggle   turn the adapter on/off
set -uo pipefail

THEME="$HOME/.config/rofi/bluetooth.rasi"
rofi_menu() { rofi -dmenu -i -theme "$THEME" "$@"; }
notify() { notify-send -a "Bluetooth" -i bluetooth "$@"; }

SCAN_SECONDS=8

powered() { [[ $(bluetoothctl show 2>/dev/null | awk '/Powered:/ {print $2; exit}') == yes ]]; }

toggle_power() {
    if powered; then
        bluetoothctl power off >/dev/null && notify "Bluetooth turned off"
    else
        bluetoothctl power on >/dev/null && notify "Bluetooth turned on"
    fi
}

[[ ${1:-} == toggle ]] && { toggle_power; exit 0; }

# Single instance: close the menu if it's already open.
pat="^rofi -dmenu .*-theme [^ ]*/bluetooth\.rasi"
if pgrep -u "$USER" -f "$pat" >/dev/null; then pkill -u "$USER" -f "$pat"; exit 0; fi

BT=$'\U000F00AF'
BT_CONN=$'\U000F00B1'
BT_OFF=$'\U000F00B2'
HEADPHONES=$'\U000F02CB'
SPEAKER=$'\U000F04C3'
GAMEPAD=$'\U000F02B4'
KEYBOARD=$'\U000F030C'
MOUSE=$'\U000F037D'
PHONE=$'\U000F03F2'

pango() { printf '%s' "$1" | sed 's/&/\&amp;/g; s/</\&lt;/g; s/>/\&gt;/g'; }

dev_icon() {   # BlueZ icon name
    case $1 in
        audio-headset|audio-headphones) printf '%s' "$HEADPHONES" ;;
        audio-card|multimedia-player)   printf '%s' "$SPEAKER" ;;
        input-gaming)                   printf '%s' "$GAMEPAD" ;;
        input-keyboard)                 printf '%s' "$KEYBOARD" ;;
        input-mouse|input-tablet)       printf '%s' "$MOUSE" ;;
        phone)                          printf '%s' "$PHONE" ;;
        *)                              printf '%s' "$BT" ;;
    esac
}

# Sets: icon connected paired battery -- from one bluetoothctl info call.
device_facts() {
    local mac=$1 info
    info=$(bluetoothctl info "$mac" 2>/dev/null)
    icon=$(dev_icon "$(awk '/^\tIcon:/ {print $2; exit}' <<<"$info")")
    connected=$(awk '/^\tConnected:/ {print $2; exit}' <<<"$info")
    paired=$(awk '/^\tPaired:/ {print $2; exit}' <<<"$info")
    battery=$(sed -n 's/.*Battery Percentage:.*(\([0-9]*\)).*/\1/p' <<<"$info" | head -1)
}

connect_device() {
    local mac=$1 name=$2 out
    notify "Connecting to $name…"
    if out=$(bluetoothctl connect "$mac" 2>&1); then
        notify "Connected to $name"
    else
        notify -u critical "Couldn't connect to $name" "$(tail -1 <<<"$out")"
    fi
}

scan_devices() {
    notify "Scanning for ${SCAN_SECONDS}s…"
    bluetoothctl --timeout "$SCAN_SECONDS" scan on >/dev/null 2>&1
}

main() {
    local status
    local -a labels=() actions=()
    add() { labels+=("$1"); actions+=("$2"); }

    if powered; then
        local connected_names=() mac name icon connected paired battery

        if [[ -n $(bluetoothctl devices Connected 2>/dev/null) ]]; then
            while read -r _ mac name; do
                [[ -n $mac ]] && connected_names+=("$name")
            done < <(bluetoothctl devices Connected 2>/dev/null)
        fi
        if (( ${#connected_names[@]} )); then
            status="Connected to <b>$(pango "$(IFS=,; echo "${connected_names[*]}")")</b>"
        else
            status="No device connected"
        fi

        add "$BT_OFF  Turn Bluetooth off" "toggle"
        add $'\U000F0450'"  Scan for devices" "scan"

        # Known devices first, then anything new that the scan turned up.
        local -A seen=()
        local section
        for section in Paired ""; do
            while read -r _ mac name; do
                [[ -n $mac && -z ${seen[$mac]:-} ]] || continue
                seen[$mac]=1
                device_facts "$mac"
                local row="$icon  $(pango "$name")"
                if [[ $connected == yes ]]; then
                    row="$icon  <b>$(pango "$name")</b>  <span alpha='55%'>connected</span>"
                elif [[ $paired != yes ]]; then
                    row+="  <span alpha='55%'>new</span>"
                fi
                [[ -n $battery ]] && row+="  <span alpha='55%'>${battery}%</span>"
                if [[ $connected == yes ]]; then add "$row" "disconnect:$mac:$name"
                else                             add "$row" "connect:$mac:$name"; fi
            done < <(bluetoothctl devices $section 2>/dev/null)
        done
    else
        status="Bluetooth is off"
        add "$BT  Turn Bluetooth on" "toggle"
    fi
    add $'\U000F0493'"  Bluetooth settings" "settings"

    local idx
    idx=$(printf '%s\n' "${labels[@]}" | rofi_menu -markup-rows -format i -p "$BT_CONN  Bluetooth" -mesg "$status") || exit 0
    [[ -n $idx ]] || exit 0

    local act=${actions[$idx]}
    case $act in
        toggle)   toggle_power ;;
        scan)     scan_devices; main ;;
        settings) blueman-manager & ;;
        connect:*)    act=${act#connect:};    connect_device "${act%%:*}" "${act#*:}" ;;
        disconnect:*) act=${act#disconnect:}; bluetoothctl disconnect "${act%%:*}" >/dev/null && notify "Disconnected from ${act#*:}" ;;
    esac
}

main
