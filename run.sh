#!/usr/bin/env bash
# Crobeye — start the local map viewer.
# Usage:  ./run.sh          (serves on http://localhost:8777)
#         ./run.sh 9000     (serve on a different port)
set -euo pipefail

PORT="${1:-8777}"
DIR="$(cd "$(dirname "$0")" && pwd)/viewer"

if [ ! -f "$DIR/index.html" ]; then
  echo "Can't find $DIR/index.html — run this from the project folder." >&2
  exit 1
fi

# If the port is busy (Errno 48), hop to the next free one so startup never fails.
port_busy() { lsof -i ":$1" -sTCP:LISTEN >/dev/null 2>&1; }
START_PORT="$PORT"
while port_busy "$PORT"; do
  PORT=$((PORT + 1))
  if [ "$PORT" -gt $((START_PORT + 20)) ]; then
    echo "Couldn't find a free port near $START_PORT." >&2; exit 1
  fi
done
[ "$PORT" != "$START_PORT" ] && echo "(port $START_PORT was busy — using $PORT instead)"

URL="http://localhost:${PORT}/index.html"
echo "Crobeye is starting…"
echo "  Open:  $URL"
echo "  Stop:  press Ctrl+C"
echo

# Open the browser automatically once the server is up (macOS = open, Linux = xdg-open).
( sleep 1
  if command -v open >/dev/null 2>&1; then open "$URL"
  elif command -v xdg-open >/dev/null 2>&1; then xdg-open "$URL"
  fi ) &

exec python3 -m http.server "$PORT" --directory "$DIR"
