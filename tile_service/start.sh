#!/usr/bin/env bash
set -euo pipefail
repo="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="$repo/map_back:$repo${PYTHONPATH:+:$PYTHONPATH}"
export PATH="$HOME/.local/bin:$PATH"
exec "${CITY_TILE_PYTHON:-$HOME/.local/share/city-tile-venv/bin/python}" -m tile_service.launcher "$@"
