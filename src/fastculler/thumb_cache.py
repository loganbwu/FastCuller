#!/usr/bin/env python3

"""On-disk thumbnail cache.

Generating a filmstrip thumbnail means decoding a CR3's embedded JPEG via
rawpy — cheap for one photo, but expensive across a library of tens of
thousands. CullerState's in-memory cache (THUMBNAIL_CACHE_MAX in web.py) only
holds a small working set, so scrolling back through a large filmstrip keeps
re-decoding thumbnails that already scrolled out of it. This on-disk cache
persists across both eviction and app restarts — once a photo's thumbnail is
generated once (by normal use, or by the fastculler-build-thumbnails CLI
tool), it's never decoded again unless the CR3 file itself changes.

Entries are keyed by the CR3's resolved path and mtime, so replacing or
reprocessing a photo naturally invalidates its cached thumbnail (the old
entry is simply orphaned — nothing currently prunes stale entries).
"""

import hashlib
import os
import tempfile
from pathlib import Path

_CACHE_DIR = Path.home() / "Library" / "Caches" / "FastCuller" / "thumbnails"


def _cache_dir() -> Path:
    """Return the cache directory, creating it if needed. A separate function
    (rather than a module-level constant) so tests can monkeypatch it."""
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return _CACHE_DIR


def _cache_path(cr3_path: Path) -> Path:
    key = f"{cr3_path.resolve()}:{cr3_path.stat().st_mtime}"
    digest = hashlib.sha1(key.encode()).hexdigest()
    return _cache_dir() / f"{digest}.jpg"


def read_cached_thumbnail(cr3_path: Path):
    """Return cached thumbnail JPEG bytes for cr3_path, or None if not cached."""
    path = _cache_path(cr3_path)
    if path.exists():
        try:
            return path.read_bytes()
        except OSError:
            return None
    return None


def write_cached_thumbnail(cr3_path: Path, data: bytes) -> None:
    """Persist thumbnail JPEG bytes for cr3_path to the on-disk cache.

    Writes via a temp file + atomic rename rather than directly to the final
    path — the running app and the fastculler-build-thumbnails CLI tool may
    populate the same cache at once, and a direct write could let a concurrent
    read land mid-write and see a truncated file. os.replace() guarantees a
    reader only ever sees the old state (a clean miss) or the fully-written
    new one, never a partial one.
    """
    final_path = _cache_path(cr3_path)
    fd, tmp_name = tempfile.mkstemp(dir=final_path.parent, suffix='.tmp')
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(data)
        os.replace(tmp_name, final_path)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise
