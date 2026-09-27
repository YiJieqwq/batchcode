#!/bin/bash
# Remove this installation's launcher and private environment; retain user data/source.
set -euo pipefail
BASE=$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
if [[ $# -gt 0 ]]; then
  if [[ $# == 1 && ( $1 == --help || $1 == -h ) ]]; then
    echo 'Usage: bash uninstall.sh'
    echo 'Removes matching PATH launchers and .venv. Preserves source, keys, config, sessions, logs and artifacts.'
    exit 0
  fi
  echo '[uninstall=failed] Unknown argument. No files changed.' >&2; exit 2
fi
# Use system Python: the private environment may be damaged or already removed.
exec python3 "$BASE/src/uninstall.py"
