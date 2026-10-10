#!/usr/bin/env bash
# Waybar power widget.
#   power.sh status   JSON for waybar (prints nothing when there is no system battery,
#                     which hides the module on desktops)
#   power.sh menu     rofi menu: power profile, charging mode/limit, brightness, keep awake
set -uo pipefail

THEME="$HOME/.config/rofi/power.rasi"
PP=(net.hadess.PowerProfiles /net/hadess/PowerProfiles net.hadess.PowerProfiles)
SIGNAL=8   # matches "signal" in the waybar module

# ---------- detection ----------
# First battery that powers the system (scope "Device" = mouse/headset batteries, ignored).
find_battery() {
    local d
    for d in /sys/class/power_supply/*; do
        [[ $(cat "$d/type" 2>/dev/null) == Battery ]] || continue
        [[ $(cat "$d/scope" 2>/dev/null) == Device ]] && continue
        [[ $(cat "$d/present" 2>/dev/null || echo 1) == 1 ]] || continue
        echo "$d"; return 0
    done
    return 1
}
BAT=$(find_battery) || BAT=""

have_profiles() { busctl get-property "${PP[@]}" ActiveProfile >/dev/null 2>&1; }
get_profile()   { busctl get-property "${PP[@]}" ActiveProfile 2>/dev/null | awk -F'"' '{print $2}'; }
list_profiles() { busctl get-property "${PP[@]}" Profiles 2>/dev/null | grep -oE '"(power-saver|balanced|performance)"' | tr -d '"'; }
keep_awake_on() { ! systemctl --user is-active --quiet hypridle.service; }
refresh_bar()   { pkill -RTMIN+$SIGNAL -x waybar 2>/dev/null || true; }
notify()        { notify-send -a "Power" -i battery "$@"; }

profile_icon() {
    case $1 in
        power-saver) printf '\U000F032A' ;;   # leaf
        performance) printf '\U000F04C5' ;;   # speedometer
        *)           printf '\U000F05D1' ;;   # scale
    esac
}
profile_name() {
    case $1 in power-saver) echo "Power saver";; performance) echo "Performance";; *) echo "Balanced";; esac
}
battery_icon() {
    local cap=$1 status=$2
    if [[ $status == Charging ]]; then printf '\U000F0084'; return; fi
    if [[ $status == Full || $status == "Not charging" ]] && (( cap >= 95 )); then printf '\U000F06A5'; return; fi
    local -a icons=($'\U000F008E' $'\U000F007A' $'\U000F007B' $'\U000F007C' $'\U000F007D' \
                    $'\U000F007E' $'\U000F007F' $'\U000F0080' $'\U000F0081' $'\U000F0082' $'\U000F0079')
    echo -n "${icons[$(( cap / 10 ))]}"
}

battery_facts() {   # sets: cap status ac watts timeleft health
    cap=$(cat "$BAT/capacity" 2>/dev/null || echo 0)
    status=$(cat "$BAT/status" 2>/dev/null || echo Unknown)
    ac=0
    local d
    for d in /sys/class/power_supply/*; do
        [[ $(cat "$d/type" 2>/dev/null) == Mains && $(cat "$d/online" 2>/dev/null) == 1 ]] && ac=1
    done
    local up
    up=$(upower -i "/org/freedesktop/UPower/devices/battery_$(basename "$BAT")" 2>/dev/null)
    watts=$(awk '/energy-rate/ {printf "%.1f W", $2}' <<<"$up")
    timeleft=$(awk -F': *' '/time to (empty|full)/ {print $2" "($1 ~ /empty/ ? "left" : "to full")}' <<<"$up" | sed 's/^ *//')
    health=""
    local full design
    full=$(cat "$BAT/charge_full" 2>/dev/null || cat "$BAT/energy_full" 2>/dev/null || true)
    design=$(cat "$BAT/charge_full_design" 2>/dev/null || cat "$BAT/energy_full_design" 2>/dev/null || true)
    [[ -n $full && -n $design && $design -gt 0 ]] && health="$(( full * 100 / design ))%"
}

# ---------- waybar status ----------
status_json() {
    [[ -n $BAT ]] || exit 0                # no battery: print nothing, module stays hidden
    local cap status ac watts timeleft health
    battery_facts
    local prof="" text cls tip
    have_profiles && prof=$(get_profile)

    text="$(battery_icon "$cap" "$status")  ${cap}%"
    [[ -n $prof ]] && text+="  $(profile_icon "$prof")"
    keep_awake_on && text+="  "$'\U000F0176'   # coffee

    cls="normal"
    (( cap <= 25 )) && cls="warning"
    (( cap <= 10 )) && cls="critical"
    [[ $status == Charging ]] && cls="charging"

    tip="Battery ${cap}% · ${status}"
    [[ -n $timeleft ]] && tip+=" · ${timeleft}"
    [[ -n $watts ]] && tip+="\nPower draw: ${watts}"
    [[ -n $health ]] && tip+="\nBattery health: ${health}"
    [[ -n $prof ]] && tip+="\nProfile: $(profile_name "$prof")"
    keep_awake_on && tip+="\nKeep awake is ON (no auto-lock or sleep)"
    tip+="\n\nClick: power menu · Middle: next profile · Right: lock/shutdown"

    jq -cn --arg t "$text" --arg tip "$(printf '%b' "$tip")" --arg c "$cls" --arg p "${prof:-none}" \
        '{text:$t, tooltip:$tip, class:[$c, $p]}'
}

# ---------- actions ----------
set_profile() {
    busctl set-property "${PP[@]}" ActiveProfile s "$1" \
        && notify "Power profile: $(profile_name "$1")" \
        || notify -u critical "Couldn't change power profile"
    refresh_bar
}

cycle_profile() {
    have_profiles || exit 0
    local -a all; mapfile -t all < <(list_profiles)
    local cur i; cur=$(get_profile)
    for i in "${!all[@]}"; do [[ ${all[$i]} == "$cur" ]] && break; done
    set_profile "${all[$(( (i + 1) % ${#all[@]} ))]}"
}

toggle_keep_awake() {
    if keep_awake_on; then
        systemctl --user start hypridle.service && notify "Keep awake off" "Screen will dim, lock and sleep when idle"
    else
        systemctl --user stop hypridle.service && notify "Keep awake on" "No auto-lock or sleep until you turn it off"
    fi
    refresh_bar
}

rofi_menu() { rofi -dmenu -i -theme "$THEME" -markup-rows "$@"; }

charge_mode_menu() {
    local -a modes=() labels=(); local m cur=""
    for m in $(cat "$BAT/charge_types"); do
        [[ $m == \[*\] ]] && { m=${m//[\[\]]/}; cur=$m; }
        modes+=("$m")
        local desc
        case $m in
            Standard) desc="charge fully at normal speed" ;;
            Adaptive) desc="learns your usage to reduce wear" ;;
            Fast)     desc="charge quickly (more wear)" ;;
            Trickle)  desc="slow charge, for always-plugged-in use" ;;
            Custom)   desc="stop at the charge limit you set" ;;
            Long_Life) desc="limit charge for longevity" ;;
            *)        desc="" ;;
        esac
        local name=$m; [[ $m == "$cur" ]] && name="<b>$m</b>  <span alpha='55%'>active</span>"
        labels+=("$name  <span alpha='55%'>$desc</span>")
    done
    local idx
    idx=$(printf '%s\n' "${labels[@]}" | rofi_menu -format i -p $'\U000F0084  Charging mode' -mesg "Current: <b>$cur</b> · needs your password") || return
    [[ -n $idx ]] || return
    local new=${modes[$idx]}
    [[ $new == "$cur" ]] && return
    if pkexec sh -c "echo '$new' > '$BAT/charge_types'"; then
        notify "Charging mode: $new"
    else
        notify -u critical "Couldn't change charging mode"
    fi
}

charge_limit_menu() {
    local end start; end=$(cat "$BAT/charge_control_end_threshold")
    local -a limits=(60 70 80 90 100) labels=()
    local l
    for l in "${limits[@]}"; do
        if [[ $l == "$end" ]]; then labels+=("<b>Stop at ${l}%</b>  <span alpha='55%'>active</span>")
        else labels+=("Stop at ${l}%"); fi
    done
    local idx
    idx=$(printf '%s\n' "${labels[@]}" | rofi_menu -format i -p $'\U000F12A3  Charge limit' \
          -mesg "Keeping the battery below 100% extends its life · needs your password") || return
    [[ -n $idx ]] || return
    local new=${limits[$idx]}
    start=$(( new - 10 )); (( start < 50 )) && start=50
    (( new == 100 )) && start=95
    local cmd=""
    # Dell and similar only honour thresholds in "Custom" charging mode.
    if [[ -w $BAT/charge_types || -e $BAT/charge_types ]] && grep -qw Custom "$BAT/charge_types"; then
        cmd+="echo Custom > '$BAT/charge_types'; "
    fi
    if [[ -e $BAT/charge_control_start_threshold ]]; then
        # Order matters: the firmware rejects start >= end, so try start, set end, then start again.
        cmd+="echo $start > '$BAT/charge_control_start_threshold' 2>/dev/null; "
        cmd+="echo $new > '$BAT/charge_control_end_threshold' && "
        cmd+="echo $start > '$BAT/charge_control_start_threshold'"
    else
        cmd+="echo $new > '$BAT/charge_control_end_threshold'"
    fi
    if pkexec sh -c "$cmd"; then
        notify "Charge limit set to ${new}%" "Charging resumes below ${start}%"
    else
        notify -u critical "Couldn't set charge limit"
    fi
}

brightness_menu() {
    local -a levels=(10 25 50 75 100)
    local cur; cur=$(brightnessctl -m -c backlight 2>/dev/null | cut -d, -f4)
    local idx
    idx=$(printf '%s\n' "${levels[@]/%/%}" | rofi_menu -format i -p $'\U000F00DF  Brightness' -mesg "Current: ${cur}") || return
    [[ -n $idx ]] && brightnessctl -q -c backlight set "${levels[$idx]}%"
}

menu() {
    [[ -n $BAT ]] || { notify "No battery detected" "Power widget is disabled on this system"; exit 0; }
    local pat="^rofi -dmenu .*-theme [^ ]*/power\.rasi"
    if pgrep -u "$USER" -f "$pat" >/dev/null; then pkill -u "$USER" -f "$pat"; exit 0; fi

    local cap status ac watts timeleft health
    battery_facts
    local mesg="<b>${cap}%</b> · ${status}"
    [[ -n $timeleft ]] && mesg+=" · ${timeleft}"
    [[ -n $watts ]] && mesg+=" · ${watts}"
    [[ -n $health ]] && mesg+=" · health ${health}"

    local -a labels=() actions=()
    add() { labels+=("$1"); actions+=("$2"); }

    local cur=""
    if have_profiles; then
        local p; cur=$(get_profile)
        while read -r p; do
            if [[ $p == "$cur" ]]; then
                add "$(profile_icon "$p")  <b>$(profile_name "$p")</b>  <span alpha='55%'>active</span>" "profile:$p"
            else
                add "$(profile_icon "$p")  $(profile_name "$p")" "profile:$p"
            fi
        done < <(list_profiles)
    fi
    if [[ -e $BAT/charge_types ]]; then
        local mode; mode=$(grep -oE '\[[^]]+\]' "$BAT/charge_types" | tr -d '[]')
        add $'\U000F0084'"  Charging mode  <span alpha='55%'>${mode}</span>" "chargemode"
    fi
    if [[ -e $BAT/charge_control_end_threshold ]]; then
        add $'\U000F12A3'"  Charge limit  <span alpha='55%'>$(cat "$BAT/charge_control_end_threshold")%</span>" "chargelimit"
    fi
    if brightnessctl -l -c backlight 2>/dev/null | grep -q backlight; then
        add $'\U000F00DF'"  Screen brightness  <span alpha='55%'>$(brightnessctl -m -c backlight | cut -d, -f4)</span>" "brightness"
    fi
    if keep_awake_on; then
        add $'\U000F0176'"  Keep awake  <span alpha='55%'>on</span>" "awake"
    else
        add $'\U000F0176'"  Keep awake  <span alpha='55%'>off</span>" "awake"
    fi
    add $'\U000F0425'"  Lock, sleep, restart or shut down…" "wlogout"

    local idx sel=0 i
    for i in "${!actions[@]}"; do [[ ${actions[$i]} == "profile:${cur:-}" ]] && sel=$i; done
    idx=$(printf '%s\n' "${labels[@]}" | rofi_menu -format i -selected-row "$sel" -p "$(battery_icon "$cap" "$status")  Power" -mesg "$mesg") || exit 0
    [[ -n $idx ]] || exit 0
    case ${actions[$idx]} in
        profile:*)   set_profile "${actions[$idx]#profile:}" ;;
        chargemode)  charge_mode_menu ;;
        chargelimit) charge_limit_menu ;;
        brightness)  brightness_menu ;;
        awake)       toggle_keep_awake ;;
        wlogout)     wlogout & ;;
    esac
    refresh_bar
}

case ${1:-status} in
    status) status_json ;;
    menu)   menu ;;
    cycle)  cycle_profile ;;
    awake)  toggle_keep_awake ;;
esac
