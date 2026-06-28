#!/bin/bash
# Manually start macaistack user services. Safe to run multiple times.
# Use this when /ext was mounted late and services didn't auto-start at boot.

set -euo pipefail

SERVICES_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DOMAIN="gui/$(id -u)"

SERVICES=(
    "com.macaistack.infinity:${SERVICES_DIR}/com.macaistack.infinity.plist"
    "com.macaistack.wyoming:${SERVICES_DIR}/com.macaistack.wyoming.plist"
    "com.macaistack.vllm-paddle:${SERVICES_DIR}/com.macaistack.vllm-paddle.plist"
    "com.macaistack.memory-health:${SERVICES_DIR}/com.macaistack.memory-health.plist"
)

start_service() {
    local label="$1"
    local plist="$2"

    local state
    state=$(launchctl print "${DOMAIN}/${label}" 2>/dev/null | awk '/^\tstate =/ {print $3}')

    if [[ -z "$state" ]]; then
        launchctl bootstrap "${DOMAIN}" "${plist}"
        echo "bootstrapped: ${label}"
    elif [[ "$state" == "running" ]]; then
        echo "already running: ${label}"
    else
        launchctl kickstart "${DOMAIN}/${label}"
        echo "kickstarted: ${label} (was: ${state})"
    fi
}

# Warn if /ext is not mounted yet
if ! mount | grep -q ' /ext '; then
    echo "warning: /ext is not mounted — services may fail to access data there"
    echo
fi

for entry in "${SERVICES[@]}"; do
    label="${entry%%:*}"
    plist="${entry##*:}"
    start_service "${label}" "${plist}"
done

echo
echo "logs:"
echo "  infinity:       ~/Library/Logs/macaistack-infinity.log"
echo "  wyoming:        ~/Library/Logs/macaistack-wyoming.log"
echo "  vllm-paddle:    ~/Library/Logs/macaistack-vllm-paddle.log"
echo "  memory-health:  ~/Library/Logs/macaistack-memory-health.log"
