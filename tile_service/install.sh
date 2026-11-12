#!/usr/bin/env bash
set -euo pipefail
repo="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
version=2.79.0
src="$HOME/.local/src/city-tippecanoe-$version"
sudo apt-get update
sudo apt-get install -y build-essential libsqlite3-dev zlib1g-dev python3-venv git
mkdir -p "$HOME/.local/src" "$HOME/.local/bin"
if [[ ! -d "$src/.git" ]]; then
  git clone --depth 1 --branch "$version" https://github.com/felt/tippecanoe.git "$src"
fi
[[ "$(git -C "$src" describe --tags --exact-match)" == "$version" ]]
[[ "$(git -C "$src" rev-parse HEAD)" == 68ab8dcc229f95b8b25877697d5e8d66783af503 ]]
make -C "$src" -j2
cp "$src/tippecanoe" "$src/tippecanoe-decode" "$HOME/.local/bin/"
"$HOME/.local/bin/tippecanoe" --version
python3 -m venv "$HOME/.local/share/city-tile-venv"
"$HOME/.local/share/city-tile-venv/bin/pip" install -r "$repo/tile_service/requirements.txt"
