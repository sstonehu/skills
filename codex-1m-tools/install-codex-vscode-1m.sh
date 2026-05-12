#!/usr/bin/env bash
set -euo pipefail

tool_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
wrapper="${CODEX_1M_WRAPPER:-$tool_dir/codex-1m}"
settings_file="${VSCODE_MACHINE_SETTINGS:-$HOME/.vscode-server/data/Machine/settings.json}"

if [ ! -x "$wrapper" ]; then
  chmod +x "$wrapper"
fi

mkdir -p "$(dirname "$settings_file")"

if [ -f "$settings_file" ]; then
  cp "$settings_file" "$settings_file.bak.$(date +%Y%m%d%H%M%S)"
fi

WRAPPER="$wrapper" SETTINGS_FILE="$settings_file" node <<'NODE'
const fs = require("fs");
const path = require("path");

const settingsFile = process.env.SETTINGS_FILE;
const wrapper = process.env.WRAPPER;

let settings = {};
if (fs.existsSync(settingsFile)) {
  const raw = fs.readFileSync(settingsFile, "utf8").trim();
  if (raw.length > 0) {
    settings = JSON.parse(raw);
  }
}

settings["chatgpt.cliExecutable"] = wrapper;

fs.mkdirSync(path.dirname(settingsFile), { recursive: true });
fs.writeFileSync(settingsFile, `${JSON.stringify(settings, null, 4)}\n`);
NODE

printf 'Configured %s\n' "$settings_file"
printf 'chatgpt.cliExecutable -> %s\n' "$wrapper"
printf 'Reload the VSCode window for the Codex extension to respawn through the wrapper.\n'
