#!/usr/bin/env python3

import argparse
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .cli_progress import render_progress
from .main import get_thumbnail_jpeg
from .thumb_cache import read_cached_thumbnail, write_cached_thumbnail


def _process(cr3_path: Path) -> str:
    """Generate cr3_path's thumbnail into the on-disk cache. Returns 'written',
    'skipped' (already cached), or 'error' (failed to decode)."""
    if read_cached_thumbnail(cr3_path) is not None:
        return 'skipped'
    try:
        data = get_thumbnail_jpeg(cr3_path)
    except Exception:
        return 'error'
    write_cached_thumbnail(cr3_path, data)
    return 'written'


def main():
    parser = argparse.ArgumentParser(
        description="Pre-generate filmstrip thumbnails for every CR3 in a folder and "
                     "cache them on disk (~/Library/Caches/FastCuller/thumbnails), so "
                     "FastCuller never has to decode them again — useful for a large "
                     "library where scrolling the filmstrip would otherwise mean "
                     "decoding thumbnails on demand."
    )
    parser.add_argument("path", help="Folder of CR3 files (scanned recursively)")
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
    counts = {'written': 0, 'skipped': 0, 'error': 0}
    workers = min(8, len(files))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for done, result in enumerate(pool.map(_process, files), start=1):
            counts[result] += 1
            if show_bar:
                render_progress(done, total)
            elif done % 50 == 0 or done == total:
                print(f"  {done}/{total} processed")
    if show_bar:
        print()  # move past the in-place progress line

    print(
        f"Cached {counts['written']} thumbnail(s), skipped {counts['skipped']} "
        f"(already cached), {counts['error']} failed to decode."
    )


if __name__ == "__main__":
    main()
