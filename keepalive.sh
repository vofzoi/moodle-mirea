#!/bin/bash
CK=$(cat "$HOME/.zcode/moodle_cookie" 2>/dev/null)
[ -n "$CK" ] || { echo "$(date '+%F %T') DEAD нет cookie-файла" >> "$HOME/.zcode/moodle_keepalive.log"; exit 0; }
case "$CK" in MoodleSession=*) ;; *) CK="MoodleSession=$CK" ;; esac
C=$(curl -s -m 30 -o /tmp/moodle_keepalive.html -w "%{http_code}" -A "Mozilla/5.0" -b "$CK" "https://online-edu.mirea.ru/my/")
if [ "$C" = "200" ] && grep -q "sesskey" /tmp/moodle_keepalive.html; then
  echo "$(date '+%F %T') OK $C" >> "$HOME/.zcode/moodle_keepalive.log"
else
  echo "$(date '+%F %T') DEAD $C — обнови cookie" >> "$HOME/.zcode/moodle_keepalive.log"
fi
