#!/usr/bin/env bash
# Launch the JiveTalker editor: ./jivetalker.sh voice_script.txt [more jivetalker edit options]
# Finds the virtual environment in $JIVETALKER_VENV, then ./.venv, then ~/venv/kokoro.
# With no arguments, opens the editor with no script: create one, open one, or try the demo. Other subcommands: ./jivetalker.sh mixer ..., ./jivetalker.sh render ...
set -e
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
for v in "${JIVETALKER_VENV:-}" "$here/.venv" "$HOME/venv/kokoro"; do
  if [ -n "$v" ] && [ -x "$v/bin/jivetalker" ]; then exe="$v/bin/jivetalker"; break; fi
done
if [ -z "$exe" ]; then
  echo "jivetalker not found. Install it (see README.md) or set JIVETALKER_VENV to the venv folder." >&2
  exit 1
fi
if [ $# -eq 0 ]; then
  exec "$exe" edit                       # no script: pick or create one in the page
fi
case "$1" in
  -*|mixer|render|check|preview|sing|voice|edit) exec "$exe" "$@" ;;
  *) exec "$exe" edit "$@" ;;
esac
