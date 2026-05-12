#!/usr/bin/env bash
# Offline UI Tester — başlatıcı. URL'i her zaman sorar.
# Kullanım:
#   ./start.sh                  -> URL sorar
#   ./start.sh --no-vision      -> URL sorar + ek bayraklar geçer

set -e
cd "$(dirname "$0")"

read -r -p "URL: " url
exec uv run python run.py --url "$url" "$@"
