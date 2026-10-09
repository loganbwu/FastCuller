#!/usr/bin/env python3

import argparse
import sys
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from pathlib import Path

from .cli_progress import render_progress
from .main import (
    get_camera_metadata,
    has_xmp_rating,
    read_xmp_capture_time,
    write_xmp_capture_time,
    write_xmp_rating,
)


def _process(cr3_path: Path, force: bool) -> tuple:
    """Copy cr3_path's capture date and in-camera rating into its XMP sidecar.

    Returns (date_result, rating_result). date_result is 'written', 'skipped'
    (already tagged, force not given) or 'no-exif' (no EXIF capture time).
    rating_result is 'imported' (1-5 stars set on camera), 'kept' (sidecar
    already has a rating, which is never overwritten, even with force) or
    'unrated' (no rating set on camera).
    """
    need_date = force or not read_xmp_capture_time(cr3_path)
    need_rating = not has_xmp_rating(cr3_path)
    if not need_date and not need_rating:
        return 'skipped', 'kept'

    capture_time, camera_rating = get_camera_metadata(cr3_path)

    if not need_date:
        date_result = 'skipped'
    elif capture_time:
        write_xmp_capture_time(cr3_path, capture_time)
        date_result = 'written'
    else:
        date_result = 'no-exif'

    # Unrated-on-camera files get an explicit 0, so re-runs can skip them without
    # re-reading the CR3. Unreadable files (no capture time either) are left alone.
    if not need_rating:
        rating_result = 'kept'
    elif 1 <= camera_rating <= 5:
        write_xmp_rating(cr3_path, camera_rating)
        rating_result = 'imported'
    elif capture_time:
        write_xmp_rating(cr3_path, 0)
        rating_result = 'unrated'
    else:
        rating_result = 'unrated'

    return date_result, rating_result


def main():
    parser = argparse.ArgumentParser(
        description="Copy each CR3's EXIF capture date and in-camera star rating into "
                     "its XMP sidecar, so FastCuller (and other XMP-aware tools) can sort "
                     "by capture time and show camera ratings without re-reading every "
                     "raw file."
    )
    parser.add_argument("path", help="Folder of CR3 files (scanned recursively)")
    parser.add_argument(
        "--force", action="store_true",
        help="Overwrite sidecars that already have a capture date (default: skip them). "
             "Existing sidecar ratings are never overwritten.",
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
    dates = {'written': 0, 'skipped': 0, 'no-exif': 0}
    ratings = {'imported': 0, 'kept': 0, 'unrated': 0}
    worker = partial(_process, force=args.force)
    workers = min(8, len(files))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for done, (date_result, rating_result) in enumerate(pool.map(worker, files), start=1):
            dates[date_result] += 1
            ratings[rating_result] += 1
            if show_bar:
                render_progress(done, total)
            elif done % 50 == 0 or done == total:
                print(f"  {done}/{total} processed")
    if show_bar:
        print()  # move past the in-place progress line

    print(
        f"Capture dates: wrote {dates['written']}, skipped {dates['skipped']} "
        f"(already tagged), {dates['no-exif']} had no EXIF capture time."
    )
    print(
        f"Ratings: imported {ratings['imported']} from camera, kept {ratings['kept']} "
        f"existing sidecar rating(s), {ratings['unrated']} unrated on camera."
    )


if __name__ == "__main__":
    main()
