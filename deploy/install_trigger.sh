#!/bin/bash
# Install, or remove, the launchd jobs that start the refresh from this Mac
# (deploy/trigger_refresh.py says why).
#
#   bash deploy/install_trigger.sh            install, or reinstall after a change
#   bash deploy/install_trigger.sh remove     take both jobs out
#
# The script is copied out of the repository to ~/Library/Application Support, because
# the repository sits in iCloud Drive, which macOS protects from background jobs and
# which can offload a file to a placeholder a job cannot read. The token stays in the
# login keychain. Logs go to ~/Library/Logs/NovatalisLens/trigger.log.
#
# Times are this Mac's local time: the refresh at 06:00 every day and the pulse pass at
# 10:00 on weekdays. In London that is 06:00 UTC in winter and 05:00 UTC in summer,
# before any market the book quotes opens either way. A time missed while the Mac
# sleeps runs at the next wake, which is launchd's own rule; the script then sends
# nothing if GitHub has already done that day's run.
#
# For the Mac to be awake at 06:00 it has to wake itself, which needs your password:
#   sudo pmset repeat wakeorpoweron MTWRFSU 05:58:00
set -euo pipefail

HOME_DIR="$HOME"
APP_DIR="$HOME_DIR/Library/Application Support/NovatalisLens"
LOG_DIR="$HOME_DIR/Library/Logs/NovatalisLens"
AGENTS="$HOME_DIR/Library/LaunchAgents"
UID_NOW="$(id -u)"
SRC="$(cd "$(dirname "$0")" && pwd)/trigger_refresh.py"
LABELS=("com.novatalis.lens.trigger.refresh" "com.novatalis.lens.trigger.pulse")

remove() {
  for label in "${LABELS[@]}"; do
    launchctl bootout "gui/$UID_NOW/$label" 2>/dev/null || true
    rm -f "$AGENTS/$label.plist"
  done
}

if [ "${1:-}" = "remove" ]; then
  remove
  echo "Removed both trigger jobs. The copied script and the log are left in place."
  exit 0
fi

[ -f "$SRC" ] || { echo "trigger_refresh.py not found beside this script"; exit 1; }
mkdir -p "$APP_DIR" "$LOG_DIR" "$AGENTS"
cp "$SRC" "$APP_DIR/trigger_refresh.py"
chmod 700 "$APP_DIR/trigger_refresh.py"

plist() {   # label, kind, calendar entries
  cat > "$AGENTS/$1.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>$1</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/bin/python3</string>
        <string>$APP_DIR/trigger_refresh.py</string>
        <string>$2</string>
    </array>
    <key>StartCalendarInterval</key>
    $3
    <key>StandardOutPath</key><string>$LOG_DIR/trigger.log</string>
    <key>StandardErrorPath</key><string>$LOG_DIR/trigger.log</string>
</dict>
</plist>
PLIST
}

DAILY='<dict><key>Hour</key><integer>6</integer><key>Minute</key><integer>0</integer></dict>'
WEEKDAYS='<array>'
for day in 1 2 3 4 5; do
  WEEKDAYS="$WEEKDAYS<dict><key>Weekday</key><integer>$day</integer><key>Hour</key><integer>10</integer><key>Minute</key><integer>0</integer></dict>"
done
WEEKDAYS="$WEEKDAYS</array>"

remove
plist "${LABELS[0]}" refresh "$DAILY"
plist "${LABELS[1]}" pulse "$WEEKDAYS"
for label in "${LABELS[@]}"; do
  plutil -lint "$AGENTS/$label.plist" >/dev/null
  launchctl bootstrap "gui/$UID_NOW" "$AGENTS/$label.plist"
done

echo "Installed: refresh at 06:00 daily, pulse at 10:00 on weekdays (this Mac's local time)."
echo "Check the token without sending anything:"
echo "  /usr/bin/python3 \"$APP_DIR/trigger_refresh.py\" refresh --dry-run"
echo "Log: $LOG_DIR/trigger.log"
