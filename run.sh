#!/usr/bin/env bash
# Crobeye — start the local map viewer.
# Usage:  ./run.sh          (serves on http://localhost:8777)
#         ./run.sh 9000     (serve on a different port)
set -euo pipefail

PORT="${1:-8777}"
DIR="$(cd "$(dirname "$0")" && pwd)/viewer"
URL="http://localhost:${PORT}/index.html"

if [ ! -f "$DIR/index.html" ]; then
  echo "Can't find $DIR/index.html — run this from the project folder." >&2
  exit 1
fi

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
