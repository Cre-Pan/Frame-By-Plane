#!/usr/bin/env python3
"""Verify one Blender archive against Blender's official SHA-256 listing."""

from __future__ import annotations

import argparse
import hashlib
import re
from pathlib import Path


SHA256_LINE = re.compile(
    r"^(?P<digest>[0-9a-fA-F]{64})\s+[*]?(?P<filename>.+?)\s*$"
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def expected_digest(checksum_file: Path, archive_name: str) -> str:
    matches = []
    for line in checksum_file.read_text(encoding="utf-8-sig").splitlines():
        match = SHA256_LINE.match(line.strip())
        if match is None:
            continue
        listed_name = Path(match.group("filename").strip()).name
        if listed_name == archive_name:
            matches.append(match.group("digest").lower())
    if len(matches) != 1:
        raise ValueError(
            f"Expected exactly one checksum for {archive_name}, found {len(matches)}"
        )
    return matches[0]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("checksum_file", type=Path)
    args = parser.parse_args()

    archive = args.archive.expanduser().resolve()
    checksum_file = args.checksum_file.expanduser().resolve()
    if not archive.is_file():
        parser.error(f"Archive not found: {archive}")
    if not checksum_file.is_file():
        parser.error(f"Checksum listing not found: {checksum_file}")

    expected = expected_digest(checksum_file, archive.name)
    actual = sha256(archive)
    if actual != expected:
        raise SystemExit(
            f"SHA-256 mismatch for {archive.name}: expected {expected}, got {actual}"
        )
    print(f"SHA-256 verified: {archive.name} {actual}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
