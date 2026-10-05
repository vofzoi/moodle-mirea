#!/bin/bash
# Ставит LaunchAgent автопродления сессии Moodle МИРЭА (пинг /my/ каждые 20 минут).
# macOS: launchd. Linux-аналог — cron: */20 * * * * /путь/к/keepalive.sh
set -e
SRC="$(cd "$(dirname "$0")" && pwd)"
LABEL="ru.mirea.moodle-keepalive"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
mkdir -p "$HOME/Library/LaunchAgents" "$HOME/.zcode"
cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key><array>
    <string>/bin/bash</string>
    <string>$SRC/keepalive.sh</string>
  </array>
  <key>StartInterval</key><integer>1200</integer>
  <key>RunAtLoad</key><true/>
  <key>StandardErrorPath</key><string>$HOME/.zcode/moodle_keepalive.err</string>
</dict></plist>
EOF
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
echo "Установлено: $PLIST"
echo "Лог: $HOME/.zcode/moodle_keepalive.log (OK / DEAD — DEAD значит обнови cookie)"
