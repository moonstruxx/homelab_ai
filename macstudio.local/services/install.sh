#!/bin/bash
set -euo pipefail

SERVICES_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# /ext must exist as a real directory before diskutil can mount to it.
# Add to /etc/synthetic.conf and reboot once if /ext doesn't exist.
if [[ ! -d /ext ]]; then
    echo "Creating /ext mountpoint via /etc/synthetic.conf (requires reboot to take effect)"
    grep -qx 'ext' /etc/synthetic.conf 2>/dev/null || printf 'ext\n' | sudo tee -a /etc/synthetic.conf
    echo "Please reboot and re-run this script to complete installation."
    exit 0
fi

# Mount daemon (runs as root, before login)
sudo cp "${SERVICES_DIR}/com.macaistack.ext-mount.plist" /Library/LaunchDaemons/
sudo chown root:wheel /Library/LaunchDaemons/com.macaistack.ext-mount.plist
sudo chmod 644 /Library/LaunchDaemons/com.macaistack.ext-mount.plist
sudo launchctl bootstrap system /Library/LaunchDaemons/com.macaistack.ext-mount.plist
echo "Installed: com.macaistack.ext-mount"

# User services (run as bjorn, after login)
for plist in com.macaistack.infinity.plist com.macaistack.wyoming.plist com.macaistack.vllm-paddle.plist; do
    cp "${SERVICES_DIR}/${plist}" ~/Library/LaunchAgents/
    chmod 644 ~/Library/LaunchAgents/"${plist}"
    launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/"${plist}"
    echo "Installed: ${plist}"
done

echo ""
echo "All launchd services installed and started."
echo "Mount log:      /var/log/macaistack-ext-mount.log"
echo "Infinity log:   ~/Library/Logs/macaistack-infinity.log"
echo "Wyoming log:    ~/Library/Logs/macaistack-wyoming.log"
echo ""
echo "NOTE: apple-on-device-openai is managed as a macOS Login Item, not a launchd service."
echo "  1. Build in Xcode: open apple-on-device-openai/AppleOnDeviceOpenAI.xcodeproj"
echo "  2. Run the app (Cmd+R), set host to 0.0.0.0 and port to 8080"
echo "  3. Enable 'Launch at Login' in the app's Server Configuration panel"
