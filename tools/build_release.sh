#!/usr/bin/env bash
set -euo pipefail

BLENDER_EXECUTABLE="${1:-blender}"
REPOSITORY_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SOURCE_DIRECTORY="$REPOSITORY_ROOT/frame_by_plane"
OUTPUT_DIRECTORY="$REPOSITORY_ROOT/dist"

mkdir -p "$OUTPUT_DIRECTORY"

"$BLENDER_EXECUTABLE" --factory-startup --command extension build \
  --source-dir "$SOURCE_DIRECTORY" \
  --output-dir "$OUTPUT_DIRECTORY" \
  --split-platforms

"$BLENDER_EXECUTABLE" --background --factory-startup \
  --python "$REPOSITORY_ROOT/tools/normalize_release_archives.py" \
  -- "$OUTPUT_DIRECTORY" --manifest "$SOURCE_DIRECTORY/blender_manifest.toml"

echo "Deterministic platform packages created in: $OUTPUT_DIRECTORY"

"$BLENDER_EXECUTABLE" --background --factory-startup --python-exit-code 1 \
  --python "$REPOSITORY_ROOT/tools/audit_release_packages.py" -- "$OUTPUT_DIRECTORY"
