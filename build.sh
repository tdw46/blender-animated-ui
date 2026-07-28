#!/bin/bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MANIFEST_PATH="$SCRIPT_DIR/blender_manifest.toml"

find_blender() {
    if [[ -n "${BLENDER_PATH:-}" && -x "${BLENDER_PATH}" ]]; then
        printf '%s\n' "${BLENDER_PATH}"
        return 0
    fi

    local candidate
    local detected
    detected="$(
        python3 - <<'PY'
import glob
import re
from pathlib import Path

candidates = []
for bundle in glob.glob("/Applications/Blender*.app"):
    executable = Path(bundle) / "Contents" / "MacOS" / "Blender"
    if not executable.is_file():
        continue
    match = re.search(r"(\d+(?:\.\d+)*)\.app$", bundle)
    version = tuple(int(value) for value in match.group(1).split(".")) if match else ()
    candidates.append((version, str(executable)))
if candidates:
    print(max(candidates)[1])
PY
    )"
    if [[ -n "$detected" ]]; then
        printf '%s\n' "$detected"
        return 0
    fi

    for candidate in \
        "/Applications/Blender.app/Contents/MacOS/Blender" \
        "/Applications/Blender Dev.app/Contents/MacOS/Blender"
    do
        if [[ -x "$candidate" ]]; then
            printf '%s\n' "$candidate"
            return 0
        fi
    done

    command -v blender
}

BLENDER_BIN="$(find_blender || true)"
if [[ -z "$BLENDER_BIN" ]]; then
    echo "Build failed: Blender was not found."
    echo "Set BLENDER_PATH to the Blender executable and try again."
    exit 1
fi

METADATA="$(
    python3 - "$MANIFEST_PATH" "$SCRIPT_DIR/__init__.py" <<'PY'
import ast
import re
import sys
import tomllib
from pathlib import Path

manifest = tomllib.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
source = Path(sys.argv[2]).read_text(encoding="utf-8")
match = re.search(r'"version"\s*:\s*(\([^)]+\))', source)
if match is None:
    raise SystemExit("Legacy bl_info version was not found")
legacy = ".".join(str(value) for value in ast.literal_eval(match.group(1)))
version = str(manifest["version"])
if legacy != version:
    raise SystemExit(f"Version mismatch: manifest={version}, bl_info={legacy}")
print(manifest["id"])
print(version)
PY
)"

EXTENSION_ID="$(printf '%s\n' "$METADATA" | sed -n '1p')"
EXTENSION_VERSION="$(printf '%s\n' "$METADATA" | sed -n '2p')"
PACKAGE_PATH="$SCRIPT_DIR/${EXTENSION_ID}-${EXTENSION_VERSION}.zip"

rm -f "$PACKAGE_PATH"
"$BLENDER_BIN" \
    --background \
    --factory-startup \
    --command extension build \
    --source-dir "$SCRIPT_DIR" \
    --output-dir "$SCRIPT_DIR"

if [[ ! -f "$PACKAGE_PATH" ]]; then
    echo "Build failed: expected package was not created: $PACKAGE_PATH"
    exit 1
fi

echo "Built: $PACKAGE_PATH"
