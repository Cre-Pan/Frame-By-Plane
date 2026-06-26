#!/usr/bin/env bash
set -euo pipefail

BLENDER_EXECUTABLE="${1:-blender}"
REPOSITORY_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SOURCE_DIRECTORY="$REPOSITORY_ROOT/frame_by_plane"
OUTPUT_DIRECTORY="$REPOSITORY_ROOT/dist"

mkdir -p "$OUTPUT_DIRECTORY"

"$BLENDER_EXECUTABLE" --command extension build \
  --source-dir "$SOURCE_DIRECTORY" \
  --output-dir "$OUTPUT_DIRECTORY" \
  --split-platforms

echo "Platform packages created in: $OUTPUT_DIRECTORY"
