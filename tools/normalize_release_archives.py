#!/usr/bin/env python3
"""Normalize Blender extension ZIP metadata for reproducible release hashes."""

from __future__ import annotations

import argparse
import os
import sys
import zipfile
from pathlib import Path


FIXED_ZIP_TIME = (1980, 1, 1, 0, 0, 0)


def normalized_info(source: zipfile.ZipInfo) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(source.filename, date_time=FIXED_ZIP_TIME)
    info.compress_type = source.compress_type
    info.create_system = source.create_system
    info.external_attr = source.external_attr
    info.internal_attr = source.internal_attr
    info.comment = b""
    info.extra = b""
    return info


def normalize_archive(path: Path) -> None:
    temp = path.with_name(f".{path.name}.normalized")
    try:
        with zipfile.ZipFile(path, "r") as source, zipfile.ZipFile(
            temp,
            "w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=9,
            strict_timestamps=True,
        ) as target:
            target.comment = b""
            for entry in sorted(source.infolist(), key=lambda item: item.filename):
                data = b"" if entry.is_dir() else source.read(entry)
                info = normalized_info(entry)
                target.writestr(
                    info,
                    data,
                    compress_type=entry.compress_type,
                    compresslevel=9 if entry.compress_type == zipfile.ZIP_DEFLATED else None,
                )
        os.replace(temp, path)
    finally:
        try:
            temp.unlink()
        except FileNotFoundError:
            pass


def cli_args() -> list[str]:
    if "--" in sys.argv:
        return sys.argv[sys.argv.index("--") + 1 :]
    return sys.argv[1:]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    args = parser.parse_args(cli_args())
    directory = args.directory.expanduser().resolve()
    archives = sorted(directory.glob("frame_by_plane-*.zip"))
    if not archives:
        parser.error(f"No Frame By Plane ZIP archives found in {directory}")
    for archive in archives:
        normalize_archive(archive)
        print(f"normalized: {archive.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
