#!/usr/bin/env bash
set -euo pipefail

# Quick secret scan using ripgrep when available; fallback to grep.
# Usage: scripts/secret-scan.sh <file1> <file2> ...

if [ "$#" -eq 0 ]; then
  echo "Usage: $0 <paths...>"
  exit 2
fi

PATTERN='(sk-|ey[A-Za-z0-9-_]{20,}|-----BEGIN PRIVATE KEY-----|AKIA[0-9A-Z]{16})'

scan_path() {
  local p="$1"
  if command -v rg >/dev/null 2>&1; then
    rg --hidden --no-ignore-vcs -n "$PATTERN" "$p" >/dev/null 2>&1
  else
    # grep -R is noisier; we still keep it simple and fail-closed on matches
    grep -RInE --exclude-dir=.git -- "$PATTERN" "$p" >/dev/null 2>&1
  fi
}

MATCHES=0
for path in "$@"; do
  if scan_path "$path"; then
    echo "POSSIBLE_SECRET_DETECTED in: $path"
    MATCHES=1
  fi
done

if [ "$MATCHES" -ne 0 ]; then
  echo "Secret scan failed."
  exit 1
fi

echo "Secret scan passed."
exit 0

