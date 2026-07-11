#!/bin/bash
# Show the status of all macaistack services:
#   - launchd state (+ pid) for the managed agents/daemons
#   - reachability of each documented service endpoint
# Read-only and safe to run anytime.

set -uo pipefail

DOMAIN="gui/$(id -u)"

# Colours (only when stdout is a terminal)
if [[ -t 1 ]]; then
    GREEN=$'\033[0;32m'; RED=$'\033[0;31m'; YELLOW=$'\033[0;33m'; DIM=$'\033[2m'; RST=$'\033[0m'
else
    GREEN=""; RED=""; YELLOW=""; DIM=""; RST=""
fi

up()   { printf '%sUP%s'   "$GREEN" "$RST"; }
down() { printf '%sDOWN%s' "$RED"   "$RST"; }

# --- launchd state -----------------------------------------------------------

# Print "<state> (pid <n>)" / "<state> (last exit <rc>)" for a launchd label, or "not loaded".
launchd_state() {
    local fulllabel="$1" out state pid rc
    out=$(launchctl print "$fulllabel" 2>/dev/null) || { echo "not loaded"; return; }
    state=$(awk -F' = ' '/^\tstate = / {print $2; exit}' <<<"$out")
    pid=$(awk -F' = ' '/^\tpid = / {print $2; exit}' <<<"$out")
    rc=$(awk -F' = ' '/last exit code = / {print $2; exit}' <<<"$out")
    if [[ -n "$pid" ]]; then
        echo "${state} (pid ${pid})"
    elif [[ -n "$rc" && "$rc" != "(never exited)" ]]; then
        echo "${state} (last exit ${rc})"
    else
        echo "${state:-unknown}"
    fi
}

# Set $MARK to a visually 4-wide UP/DOWN/? marker for a state string. A one-shot
# daemon that exited 0 counts as healthy (it did its job and quit).
mark_for() {
    case "$1" in
        running*)        MARK="$(up)  " ;;
        "not loaded")    MARK="$(down)" ;;
        *"last exit 0"*) MARK="$(up)  " ;;
        *)               MARK="${YELLOW}? ${RST}  " ;;
    esac
}

echo "launchd services"
echo "================"

# User LaunchAgents (label  -> friendly name)
for entry in \
    "com.macaistack.infinity:infinity (embed/rerank)" \
    "com.macaistack.wyoming:wyoming (whisper STT)" \
    "com.macaistack.mineru:mineru (PDF/OCR parsing)" \
    "com.macaistack.memory-health:memory-health (swap/mem)"; do
    label="${entry%%:*}"; name="${entry##*:}"
    state=$(launchd_state "${DOMAIN}/${label}")
    mark_for "$state"
    printf '  %s  %-22s %s%s%s\n' "$MARK" "$name" "$DIM" "$state" "$RST"
done

# System LaunchDaemon: ext-mount (one-shot — mounts /ext then exits)
state=$(launchd_state "system/com.macaistack.ext-mount")
mark_for "$state"
printf '  %s  %-22s %s%s%s\n' "$MARK" "ext-mount (daemon)" "$DIM" "$state" "$RST"

# /ext mount check
if mount | grep -q ' /ext '; then
    printf '  %s  %-22s %s%s%s\n' "$(up)  " "/ext volume" "$DIM" "mounted" "$RST"
else
    printf '  %s  %-22s %s%s%s\n' "$(down)" "/ext volume" "$DIM" "NOT mounted" "$RST"
fi

# --- endpoint reachability ---------------------------------------------------

echo
echo "service endpoints"
echo "================="

# HTTP probe: UP if curl gets any HTTP response (even 401/404 = listening).
probe_http() {
    local url="$1" code
    code=$(curl -s -m 3 -o /dev/null -w '%{http_code}' "$url" 2>/dev/null)
    if [[ $? -eq 0 && -n "$code" && "$code" != "000" ]]; then
        echo "HTTP ${code}"; return 0
    fi
    return 1
}

# Raw TCP probe (for non-HTTP protocols like Wyoming). Local addrs => instant.
probe_tcp() {
    ( exec 3<>"/dev/tcp/$1/$2" ) >/dev/null 2>&1
}

# name | host:port | managed-by | probe (http URL or "tcp")
ENDPOINTS=(
    "infinity            |192.168.1.114:7997|launchd     |http://192.168.1.114:7997/health"
    "apple-on-device     |127.0.0.1:8080    |Login Item  |http://127.0.0.1:8080/health"
    "anemll-server       |127.0.0.1:8000    |manual      |http://127.0.0.1:8000/v1/models"
    "wyoming-whisper-cpp |127.0.0.1:10300   |launchd     |tcp"
    "mineru-api          |192.168.1.114:8086|launchd     |http://192.168.1.114:8086/health"
    "memory-health       |192.168.1.114:9101|launchd     |http://192.168.1.114:9101/health"
)

for entry in "${ENDPOINTS[@]}"; do
    IFS='|' read -r name addr managed probe <<<"$entry"
    name="${name// /}"; addr="${addr// /}"; managed="${managed%% }"; managed="${managed## }"; probe="${probe// /}"

    if [[ "$probe" == "tcp" ]]; then
        host="${addr%%:*}"; port="${addr##*:}"
        if probe_tcp "$host" "$port"; then result="$(up)  "; detail="tcp open"; else result="$(down)"; detail="-"; fi
    else
        if detail=$(probe_http "$probe"); then result="$(up)  "; else result="$(down)"; detail="-"; fi
    fi

    printf '  %s  %-20s %-19s %s%-11s %s%s\n' \
        "$result" "$name" "$addr" "$DIM" "$managed" "$detail" "$RST"
done

echo
echo "${DIM}logs: ~/Library/Logs/macaistack-*.log    daemon: /var/log/macaistack-ext-mount.log${RST}"
echo "${DIM}memory-health endpoint: http://192.168.1.114:9101/health  (swap threshold: 2048 MB)${RST}"
