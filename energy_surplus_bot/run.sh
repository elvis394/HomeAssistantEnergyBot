#!/usr/bin/env sh
set -eu

CONFIG_PATH="${ENERGY_BOT_CONFIG:-/data/options.json}"
RUNTIME_PATH="${ENERGY_BOT_RUNTIME:-/data/runtime.json}"

if [ ! -f "$CONFIG_PATH" ]; then
  CONFIG_PATH="/app/config.example.yaml"
fi

exec python3 -m app.main \
  --config "$CONFIG_PATH" \
  --runtime "$RUNTIME_PATH" \
  --serve \
  --live-ha
