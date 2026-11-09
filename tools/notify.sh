#!/bin/sh
# Host-side alert: play a sound when the human has to touch the phone.
# Usage: notify.sh [short|long]
#   short (default): one bell  — look at the screen / confirm something
#   long:            two bells — hands-on action needed (keys, cable, reboot)
set -u
SOUND=/usr/share/sounds/freedesktop/stereo/bell.oga
[ -r "$SOUND" ] || SOUND=/usr/share/sounds/freedesktop/stereo/message-new-instant.oga
play() {
	if command -v paplay >/dev/null 2>&1; then
		paplay "$SOUND" 2>/dev/null
	elif command -v pw-play >/dev/null 2>&1; then
		pw-play "$SOUND" 2>/dev/null
	elif command -v aplay >/dev/null 2>&1; then
		aplay -q "$SOUND" 2>/dev/null
	fi
}
play
if [ "${1:-short}" = "long" ]; then
	sleep 0.35
	play
fi
exit 0
