#!/usr/bin/env bash
# Offline UI Tester — tek komutla başlatıcı (lokal ollama, harici API yok).
# Kullanım:
#   ./start.sh                                  -> URL sorar
#   ./start.sh --url https://example.com        -> direkt başlat
#   ./start.sh --url X --model llama3.1:8b      -> farklı model

set -e
cd "$(dirname "$0")"

if [[ "$*" != *"--url"* ]]; then
  read -r -p "URL: " url
  exec uv run python run.py --url "$url" "$@"
else
  exec uv run python run.py "$@"
fi
