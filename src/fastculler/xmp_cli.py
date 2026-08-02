#!/usr/bin/env python3

import argparse
import sys
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from pathlib import Path

from .cli_progress import render_progress
from .main import get_capture_time, read_xmp_capture_time, write_xmp_capture_time


def _process(cr3_path: Path, force: bool) -> str:
    """Write cr3_path's capture date to its XMP sidecar. Returns 'written', 'skipped'
    (already tagged, force not given), or 'no-exif' (file has no EXIF capture time)."""
    if not force and read_xmp_capture_time(cr3_path):
        return 'skipped'
    capture_time = get_capture_time(cr3_path)
    if not capture_time:
        return 'no-exif'
    write_xmp_capture_time(cr3_path, capture_time)
    return 'written'


def main():
    parser = argparse.ArgumentParser(
        description="Write each CR3's EXIF capture date into its XMP sidecar, so "
                     "FastCuller (and other XMP-aware tools) can sort by capture time "
                     "without re-reading every raw file."
    )
    parser.add_argument("path", help="Folder of CR3 files (scanned recursively)")
    parser.add_argument(
        "--force", action="store_true",
        help="Overwrite sidecars that already have a capture date (default: skip them)",
    )
    args = parser.parse_args()

    root = Path(args.path).expanduser().resolve()
    if not root.exists():
        raise SystemExit(f"Path does not exist: {root}")

    files = [p for p in root.rglob("*") if p.suffix.lower() == ".cr3"]
    if not files:
        raise SystemExit("No CR3 files found.")

    print(f"Found {len(files)} CR3 file(s) under {root}")

    total = len(files)
    show_bar = sys.stdout.isatty()
    counts = {'written': 0, 'skipped': 0, 'no-exif': 0}
    worker = partial(_process, force=args.force)
    workers = min(8, len(files))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for done, result in enumerate(pool.map(worker, files), start=1):
            counts[result] += 1
            if show_bar:
                render_progress(done, total)
            elif done % 50 == 0 or done == total:
                print(f"  {done}/{total} processed")
    if show_bar:
        print()  # move past the in-place progress line

    print(
        f"Wrote {counts['written']} sidecar(s), skipped {counts['skipped']} "
        f"(already tagged), {counts['no-exif']} had no EXIF capture time."
    )


if __name__ == "__main__":
    main()
