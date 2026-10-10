#!/usr/bin/env bash
# Rofi Wi-Fi menu backed by NetworkManager (nmcli).
# Usage: wifi-menu.sh          open the menu
#        wifi-menu.sh toggle   turn Wi-Fi radio on/off
set -uo pipefail

THEME="$HOME/.config/rofi/wifi.rasi"
rofi_menu() { rofi -dmenu -i -theme "$THEME" "$@"; }
notify() { notify-send -a "Wi-Fi" -i network-wireless "$@"; }

toggle_radio() {
    if [[ $(nmcli radio wifi) == enabled ]]; then
        nmcli radio wifi off && notify "Wi-Fi turned off"
    else
        nmcli radio wifi on && notify "Wi-Fi turned on"
    fi
}

[[ ${1:-} == toggle ]] && { toggle_radio; exit 0; }

# Single instance: close the menu if it's already open.
pat="^rofi -dmenu .*-theme [^ ]*/wifi\.rasi"
if pgrep -u "$USER" -f "$pat" >/dev/null; then pkill -u "$USER" -f "$pat"; exit 0; fi

sig_icon() {
    local s=$1
    if   (( s >= 75 )); then printf '\U000F0928'
    elif (( s >= 50 )); then printf '\U000F0925'
    elif (( s >= 25 )); then printf '\U000F0922'
    else                     printf '\U000F091F'
    fi
}
LOCK=$'\U000F033E'
UNLOCK=$'\U000F033F'

connect() {
    local ssid=$1 security=$2 out
    # Known network: just bring the saved profile up.
    if nmcli -g NAME connection show | grep -Fxq -- "$ssid"; then
        notify "Connecting to $ssid…"
        if out=$(nmcli connection up id "$ssid" 2>&1); then
            notify "Connected to $ssid"; return
        fi
        # Saved password may be stale; fall through and ask again.
        [[ -n $security ]] || { notify -u critical "Couldn't connect to $ssid" "$out"; return; }
        nmcli connection delete id "$ssid" >/dev/null 2>&1
    fi
    if [[ -n $security ]]; then
        local pw
        pw=$(rofi_menu -password -p "$LOCK  $ssid" -mesg "Enter the Wi-Fi password" -l 0 </dev/null) || return
        [[ -n $pw ]] || return
        notify "Connecting to $ssid…"
        out=$(nmcli device wifi connect "$ssid" password "$pw" 2>&1)
    else
        notify "Connecting to $ssid…"
        out=$(nmcli device wifi connect "$ssid" 2>&1)
    fi
    if [[ $? -eq 0 ]]; then
        notify "Connected to $ssid"
    else
        nmcli connection delete id "$ssid" >/dev/null 2>&1   # don't keep a broken profile
        notify -u critical "Couldn't connect to $ssid" "$out"
    fi
}

hidden_network() {
    local ssid pw out
    ssid=$(rofi_menu -p "SSID" -mesg "Name of the hidden network" -l 0 </dev/null) || return
    [[ -n $ssid ]] || return
    pw=$(rofi_menu -password -p "$LOCK  $ssid" -mesg "Password (leave empty for an open network)" -l 0 </dev/null) || return
    notify "Connecting to $ssid…"
    if [[ -n $pw ]]; then
        out=$(nmcli device wifi connect "$ssid" password "$pw" hidden yes 2>&1)
    else
        out=$(nmcli device wifi connect "$ssid" hidden yes 2>&1)
    fi
    if [[ $? -eq 0 ]]; then notify "Connected to $ssid"; else notify -u critical "Couldn't connect to $ssid" "$out"; fi
}

main() {
    local radio active status
    radio=$(nmcli radio wifi)
    active=$(nmcli -t -f ACTIVE,SSID device wifi list --rescan no 2>/dev/null | sed -n 's/^yes://p' | head -1)

    local -a labels=() actions=()
    add() { labels+=("$1"); actions+=("$2"); }

    if [[ $radio == enabled ]]; then
        status="Connected to <b>${active:-nothing}</b>"
        [[ -z $active ]] && status="Not connected"
        add "󰖪  Turn Wi-Fi off" "toggle"
        [[ -n $active ]] && add "󰅖  Disconnect from $active" "disconnect"
        add "󰑐  Rescan networks" "rescan"

        # Networks, strongest first, one row per SSID.
        local -A seen=()
        local line inuse sig sec ssid
        while IFS= read -r line; do
            inuse=${line%%:*}; line=${line#*:}
            sig=${line%%:*};   line=${line#*:}
            sec=${line%%:*};   ssid=${line#*:}
            ssid=${ssid//\\:/:}
            [[ -z $ssid || -n ${seen[$ssid]:-} ]] && continue
            seen[$ssid]=1
            [[ $sec == "--" ]] && sec=""
            local lock="$UNLOCK" name
            [[ -n $sec ]] && lock="$LOCK"
            name=$(printf '%s' "$ssid" | sed 's/&/\&amp;/g; s/</\&lt;/g; s/>/\&gt;/g')
            if [[ $inuse == "*" ]]; then
                name="<b>$name</b>  <span alpha='55%'>connected</span>"
            fi
            add "$(sig_icon "$sig")  $lock  $name  <span alpha='55%'>${sig}%</span>" "net:$sec:$ssid"
        done < <(nmcli -t -f IN-USE,SIGNAL,SECURITY,SSID device wifi list --rescan "${RESCAN:-auto}" 2>/dev/null | sort -t: -k1,1r -k2,2nr)

        add "󰈈  Connect to hidden network…" "hidden"
    else
        status="Wi-Fi is off"
        add "󰖩  Turn Wi-Fi on" "toggle"
    fi
    add "󰒓  Network settings" "settings"

    local idx
    idx=$(printf '%s\n' "${labels[@]}" | rofi_menu -markup-rows -format i -p "󰖩  Wi-Fi" -mesg "$status") || exit 0
    [[ -n $idx ]] || exit 0
    local act=${actions[$idx]}

    case $act in
        toggle)     toggle_radio ;;
        disconnect) nmcli device disconnect "$(nmcli -t -f DEVICE,TYPE device | sed -n 's/:wifi$//p' | head -1)" >/dev/null && notify "Disconnected from $active" ;;
        rescan)     notify "Scanning…"; nmcli device wifi rescan 2>/dev/null; sleep 2; RESCAN=no main ;;
        hidden)     hidden_network ;;
        settings)   nm-connection-editor & ;;
        net:*)      act=${act#net:}; connect "${act#*:}" "${act%%:*}" ;;
    esac
}

main
