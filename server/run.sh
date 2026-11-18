#!/bin/sh
# Start home-display if it is not already running. Safe to call from cron every few minutes.
# Layout on the Pi:  ~/home-display/server/ (this folder), ~/home-display/.venv/, ~/home-display/home-display.log
cd "$(dirname "$0")" || exit 1
ROOT="$(cd .. && pwd)"
PIDFILE="$ROOT/run.pid"
LOG="$ROOT/home-display.log"

if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
  exit 0
fi

# Keep the log small.
if [ -f "$LOG" ] && [ "$(wc -c < "$LOG")" -gt 1000000 ]; then
  tail -n 200 "$LOG" > "$LOG.tmp" && mv "$LOG.tmp" "$LOG"
fi

# Optional settings (HD_ALLOW=..., HD_PORT=..., HD_TZ=...): put them in server/config.env (git-ignored).
if [ -f "$ROOT/server/config.env" ]; then
  set -a
  . "$ROOT/server/config.env"
  set +a
fi

# Until the real calendar URL is in secret.url, show clearly fake SAMPLE events.
if [ ! -s "$ROOT/server/secret.url" ]; then
  export HD_SAMPLE=1
fi

nohup "$ROOT/.venv/bin/python" "$ROOT/server/app.py" >> "$LOG" 2>&1 &
echo $! > "$PIDFILE"
