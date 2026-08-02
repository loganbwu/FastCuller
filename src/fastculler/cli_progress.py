#!/usr/bin/env python3

"""Shared terminal progress bar for the fastculler-* CLI tools."""

import sys


def render_progress(done: int, total: int, width: int = 30) -> None:
    """Render an in-place progress bar. Only meaningful on a real terminal —
    callers should check sys.stdout.isatty() and fall back to periodic plain
    print()s otherwise, so redirected output doesn't fill up with \\r junk."""
    filled = width * done // total
    bar = '█' * filled + '░' * (width - filled)
    pct = 100 * done // total
    sys.stdout.write(f'\r[{bar}] {pct:3d}%  {done}/{total}')
    sys.stdout.flush()
