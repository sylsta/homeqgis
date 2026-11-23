#!/bin/sh
# Valetudo for QGIS: Wi-Fi survey recorded on the robot itself.
#
# Runs in the background on the robot (BusyBox sh, sed, grep, wget or curl).
# While the robot moves (cleaning, returning, moving, manual control), it
# appends one line per reading to DATA_FILE:
#     session,time,x,y,signal,state,ssid,frequency
# session = start time of the run (Unix seconds), time = reading time,
# x/y = robot position in the map's own units (cm), signal in dBm.
# Idle, it only checks the robot state every IDLE_S seconds.
#
# Usage: valetudo_wifi_survey.sh DATA_FILE [INTERVAL_S] [MIN_STEP_CM]
#        valetudo_wifi_survey.sh --check      (prints what it can read, then exits)
# Installed, started, read and removed by the QGIS plugin over SSH.

OUT=${1:-/tmp/valetudo_wifi_survey.csv}
INTERVAL=${2:-2}
MIN_STEP=${3:-20}
IDLE_S=10
MAX_LINES=50000          # about 2.5 MB; the oldest lines are dropped beyond
API=${VQ_API:-http://127.0.0.1/api/v2}   # VQ_API: for tests only
PIDFILE=/tmp/valetudo_wifi_survey.pid

fetch() {
    if command -v wget >/dev/null 2>&1; then
        wget -q -O - "$1" 2>/dev/null
    elif command -v curl >/dev/null 2>&1; then
        curl -s "$1"
    else
        busybox wget -q -O - "$1" 2>/dev/null
    fi
}

robot_state() {
    fetch "$API/robot/state/attributes" \
        | grep -o '"StatusStateAttribute".\{0,160\}' \
        | grep -o '"value":"[a-z_]*"' | head -n 1 | sed 's/.*:"\(.*\)"/\1/'
}

# "x y" of the robot, from the map's robot_position entity (any key order).
robot_position() {
    fetch "$API/robot/state/map" \
        | grep -o \
            -e '"points":\[[-0-9.]*,[-0-9.]*\],"type":"robot_position"' \
            -e '"points":\[[-0-9.]*,[-0-9.]*\],"metaData":{[^}]*},"type":"robot_position"' \
            -e '"type":"robot_position"[^]]*"points":\[[-0-9.]*,[-0-9.]*\]' \
        | head -n 1 \
        | sed 's/.*"points":\[\([-0-9]*\)[.0-9]*,\([-0-9]*\)[.0-9]*\].*/\1 \2/'
}

# Signal in dBm: fresh from the kernel, else from Valetudo.
wifi_signal() {
    s=$(sed -n '3s/^ *[^:]*: *[0-9a-fA-F]* *[0-9.]* *\(-[0-9]*\).*/\1/p' /proc/net/wireless 2>/dev/null)
    if [ -z "$s" ]; then
        s=$(fetch "$API/robot/capabilities/WifiConfigurationCapability" \
            | grep -o '"signal":-\{0,1\}[0-9]*' | head -n 1 | sed 's/.*://')
    fi
    echo "$s"
}

# "ssid,frequency" (commas removed from the SSID).
wifi_info() {
    w=$(fetch "$API/robot/capabilities/WifiConfigurationCapability")
    ssid=$(echo "$w" | grep -o '"ssid":"[^"]*"' | head -n 1 | sed 's/.*:"\(.*\)"/\1/' | tr -d ',')
    freq=$(echo "$w" | grep -o '"frequency":"[^"]*"' | head -n 1 | sed 's/.*:"\(.*\)"/\1/')
    echo "$ssid,$freq"
}

if [ "$1" = "--check" ]; then
    for tool in wget curl sed grep; do
        command -v "$tool" >/dev/null 2>&1 && echo "tool=$tool"
    done
    echo "state=$(robot_state)"
    echo "position=$(robot_position)"
    echo "signal=$(wifi_signal)"
    exit 0
fi

# One instance only.
if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
    exit 0
fi
echo $$ > "$PIDFILE"
trap 'rm -f "$PIDFILE"; exit 0' INT TERM
trap '' HUP   # keep running when the SSH session that started it ends

INTERVAL=${INTERVAL%.*}
[ "${INTERVAL:-0}" -ge 1 ] 2>/dev/null || INTERVAL=1
session=""
lastx=""
lasty=""
count=0
while :; do
    state=$(robot_state)
    case "$state" in
        cleaning|returning|moving|manual_control)
            if [ -z "$session" ]; then
                session=$(date +%s)
                info=$(wifi_info)
                lastx=""
            fi
            pos=$(robot_position)
            sig=$(wifi_signal)
            if [ -n "$pos" ] && [ -n "$sig" ]; then
                set -- $pos
                x=$1
                y=$2
                keep=1
                if [ -n "$lastx" ]; then
                    dx=$((x - lastx))
                    dy=$((y - lasty))
                    [ $((dx * dx + dy * dy)) -lt $((MIN_STEP * MIN_STEP)) ] && keep=0
                fi
                if [ "$keep" = 1 ]; then
                    echo "$session,$(date +%s),$x,$y,$sig,$state,$info" >> "$OUT"
                    lastx=$x
                    lasty=$y
                    count=$((count + 1))
                fi
            fi
            sleep "$INTERVAL"
            ;;
        *)
            session=""
            sleep "$IDLE_S"
            ;;
    esac
    if [ "$count" -ge 500 ]; then   # now and then: keep the file bounded
        count=0
        lines=$(wc -l < "$OUT")
        if [ "$lines" -gt "$MAX_LINES" ]; then
            tail -n $((MAX_LINES * 4 / 5)) "$OUT" > "$OUT.tmp" && mv "$OUT.tmp" "$OUT"
        fi
    fi
done
