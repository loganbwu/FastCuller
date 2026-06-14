#!/usr/bin/env python3

import argparse
import json
import shutil
import subprocess
import sys
import threading
import webbrowser
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from flask import Flask, Response, jsonify, render_template, request, stream_with_context

from .main import (
    find_cr3_files,
    get_exif_info,
    get_preview_jpeg,
    get_thumbnail_jpeg,
    read_xmp_rating,
    write_xmp_rating,
)

THUMBNAIL_CACHE_MAX = 100   # max thumbnails kept in memory
IMAGE_CACHE_MAX = 150       # max full-size images kept in memory
PREFETCH_WINDOW = 10        # sequential backward and per-rating neighbours to prefetch
PREFETCH_FORWARD = 50       # sequential forward neighbours to prefetch

# ── Colour helpers ────────────────────────────────────────────────────────────

_TTY     = sys.stdout.isatty()
_GREEN   = "\033[32m"  if _TTY else ""
_YELLOW  = "\033[33m"  if _TTY else ""
_RED     = "\033[31m"  if _TTY else ""
_CYAN    = "\033[36m"  if _TTY else ""
_MAGENTA = "\033[35m"  if _TTY else ""
_DIM     = "\033[2m"   if _TTY else ""
_BOLD    = "\033[1m"   if _TTY else ""
_RESET   = "\033[0m"   if _TTY else ""

STAR = "★"

def _rating_str(rating: int) -> str:
    return f"{_YELLOW}{STAR * rating}{_RESET}" if rating else f"{_DIM}unrated{_RESET}"

# ── SSE notification ──────────────────────────────────────────────────────────

_sse_condition = threading.Condition()


def _notify_sse():
    with _sse_condition:
        _sse_condition.notify_all()


# ── Session state ─────────────────────────────────────────────────────────────

class CullerState:
    """All mutable state for one culling session."""

    def __init__(self, files: list):
        self.files = files                    # list[Path], sorted by capture time
        self.ratings: dict = {}               # Path → int (0 or 1)
        self.current_idx: int = 0

        self._image_cache: dict = {}          # idx → bytes (full JPEG)
        self._image_order: list = []          # insertion order for LRU eviction
        self._exif_cache: dict = {}           # idx → dict
        self._thumb_cache: dict = {}          # idx → bytes (thumbnail JPEG)
        self._thumb_order: list = []          # insertion order for LRU eviction
        self._lock = threading.Lock()
        self._prefetch_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix='prefetch')

        # Load existing ratings from XMP sidecars
        pre_rated = 0
        for path in files:
            r = read_xmp_rating(path)
            if r != 0:
                self.ratings[path] = r
                pre_rated += 1
        if pre_rated:
            print(f"  {_CYAN}Loaded existing ratings: {pre_rated} file(s) already rated{_RESET}")

        # Kick off initial prefetch
        self._trigger_prefetch(self.current_idx)

    # ── Navigation helpers ────────────────────────────────────────────────────

    def _next_with_rating(self, start: int, rating: int, direction: int) -> int:
        """Return index of next/prev photo with given rating, or -1 if none."""
        n = len(self.files)
        idx = start + direction
        while 0 <= idx < n:
            path = self.files[idx]
            r = self.ratings.get(path, 0)
            if r == rating:
                return idx
            idx += direction
        return -1

    def _n_with_rating(self, start: int, rating: int, direction: int, count: int) -> list:
        """Return up to `count` indices in `direction` whose rating matches."""
        n = len(self.files)
        results = []
        idx = start + direction
        while 0 <= idx < n and len(results) < count:
            if self.ratings.get(self.files[idx], 0) == rating:
                results.append(idx)
            idx += direction
        return results

    def navigate(self, idx: int) -> bool:
        if not (0 <= idx < len(self.files)):
            return False
        with self._lock:
            self.current_idx = idx
        name = self.files[idx].name
        rating = self.ratings.get(self.files[idx], 0)
        print(f"  {_DIM}→ {idx + 1}/{len(self.files)}  {name}  {_rating_str(rating)}{_RESET}")
        self._trigger_prefetch(idx)
        _notify_sse()
        return True

    def rate_and_advance(self, idx: int, rating: int) -> tuple:
        """Rate photo at idx, write XMP, advance to next. Returns (new_idx, error_str)."""
        if not (0 <= idx < len(self.files)):
            return self.current_idx, 'invalid index'
        path = self.files[idx]
        try:
            write_xmp_rating(path, rating)
        except Exception as e:
            err = str(e)
            print(f"  {_RED}XMP write error {path.name}: {err}{_RESET}")
            next_idx = min(idx + 1, len(self.files) - 1)
            self.navigate(next_idx)
            return next_idx, err
        with self._lock:
            self.ratings[path] = rating
        print(f"  {_GREEN}Rated{_RESET}  {path.name}  {_rating_str(rating)}")
        next_idx = min(idx + 1, len(self.files) - 1)
        self.navigate(next_idx)
        _notify_sse()
        return next_idx, ''

    def rate_only(self, idx: int, rating: int) -> str:
        """Rate photo at idx without navigating. Returns error_str ('' on success)."""
        if not (0 <= idx < len(self.files)):
            return 'invalid index'
        path = self.files[idx]
        try:
            write_xmp_rating(path, rating)
        except Exception as e:
            err = str(e)
            print(f"  {_RED}XMP write error {path.name}: {err}{_RESET}")
            return err
        with self._lock:
            self.ratings[path] = rating
        print(f"  {_GREEN}Rated{_RESET}  {path.name}  {_rating_str(rating)}")
        _notify_sse()
        return ''

    # ── Prefetch ──────────────────────────────────────────────────────────────

    def _prefetch_indices(self, current: int) -> list:
        """Indices to keep warm in the image cache."""
        n = len(self.files)
        indices = set()
        indices.add(current)
        # Sequential neighbours — deeper look-ahead going forward
        for d, window in ((-1, PREFETCH_WINDOW), (1, PREFETCH_FORWARD)):
            for step in range(1, window + 1):
                nxt = current + d * step
                if 0 <= nxt < n:
                    indices.add(nxt)
        # Rating-tier neighbours
        for rating in (0, 1):
            for d in (-1, 1):
                for i in self._n_with_rating(current, rating, d, PREFETCH_WINDOW):
                    indices.add(i)
        return list(indices)

    def _trigger_prefetch(self, current: int):
        indices = self._prefetch_indices(current)
        queued = [i for i in indices if i not in self._image_cache]
        if queued:
            print(f"  {_DIM}Prefetch queued: {sorted(i + 1 for i in queued)}{_RESET}")
        for idx in queued:
            self._prefetch_executor.submit(self._load_image, idx)

    def _load_image(self, idx: int):
        if idx in self._image_cache:
            return
        name = self.files[idx].name
        try:
            data = get_preview_jpeg(self.files[idx])
        except Exception as e:
            print(f"  {_RED}Prefetch error [{idx + 1}] {name}: {e}{_RESET}")
            return
        exif = {}
        try:
            exif = get_exif_info(self.files[idx])
        except Exception:
            pass
        with self._lock:
            self._image_order.append(idx)
            if len(self._image_order) > IMAGE_CACHE_MAX:
                evict = self._image_order.pop(0)
                self._image_cache.pop(evict, None)
            self._image_cache[idx] = data
            self._exif_cache[idx] = exif
        kb = len(data) // 1024
        print(f"  {_DIM}Prefetched [{idx + 1}] {name} ({kb} KB){_RESET}")

    def get_image(self, idx: int) -> bytes:
        if idx in self._image_cache:
            return self._image_cache[idx]
        # On-demand load on cache miss
        data = get_preview_jpeg(self.files[idx])
        with self._lock:
            self._image_order.append(idx)
            if len(self._image_order) > IMAGE_CACHE_MAX:
                evict = self._image_order.pop(0)
                self._image_cache.pop(evict, None)
            self._image_cache[idx] = data
        return data

    def get_exif(self, idx: int) -> dict:
        if idx in self._exif_cache:
            return self._exif_cache[idx]
        exif = get_exif_info(self.files[idx])
        with self._lock:
            self._exif_cache[idx] = exif
        return exif

    def get_thumbnail(self, idx: int) -> bytes:
        if idx in self._thumb_cache:
            return self._thumb_cache[idx]
        data = get_thumbnail_jpeg(self.files[idx])
        with self._lock:
            # LRU eviction
            if idx in self._thumb_order:
                self._thumb_order.remove(idx)
            self._thumb_order.append(idx)
            if len(self._thumb_order) > THUMBNAIL_CACHE_MAX:
                evict = self._thumb_order.pop(0)
                self._thumb_cache.pop(evict, None)
            self._thumb_cache[idx] = data
        return data

    # ── Serialisation ─────────────────────────────────────────────────────────

    def get_state(self) -> dict:
        with self._lock:
            idx = self.current_idx
            n = len(self.files)
            path = self.files[idx] if n else None
            ratings_list = [self.ratings.get(f, 0) for f in self.files]
            prefetch_ready = list(self._image_cache.keys())
        return {
            "status": "ready",
            "current_idx": idx,
            "total": n,
            "filename": path.name if path else "",
            "ratings": ratings_list,
            "prefetch_ready": prefetch_ready,
        }


# ── Flask application ─────────────────────────────────────────────────────────

def create_app() -> Flask:
    app = Flask(__name__)
    app.config["culler_state"] = None
    app.config["start_error"] = None
    app.config["start_stage"] = None

    # ── Pages ──────────────────────────────────────────────────────────────

    @app.route("/")
    def index():
        return render_template("index.html", thumb_cache_max=THUMBNAIL_CACHE_MAX)

    # ── Folder management ──────────────────────────────────────────────────

    @app.route("/api/pick-folder")
    def api_pick_folder():
        result = subprocess.run(
            ["osascript", "-e", 'POSIX path of (choose folder with prompt "Select a folder of CR3 files")'],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            return jsonify({"path": None})
        return jsonify({"path": result.stdout.strip()})

    @app.route("/api/start", methods=["POST"])
    def api_start():
        data = request.json or {}
        path_str = data.get("path", "")
        root = Path(path_str).expanduser().resolve()

        if not root.exists():
            return jsonify({"error": f"Path does not exist: {root}"}), 400

        app.config["culler_state"] = None
        app.config["start_error"] = None
        app.config["start_stage"] = "Scanning folder..."
        _notify_sse()

        def _do_start():
            try:
                print(f"\n{_BOLD}Scanning{_RESET} {_CYAN}{root}{_RESET}")

                raw_files = [p for p in root.rglob("*") if p.suffix.lower() == ".cr3"]
                if not raw_files:
                    print(f"  {_RED}No CR3 files found.{_RESET}")
                    app.config["start_error"] = "No CR3 files found in that folder"
                    app.config["start_stage"] = None
                    _notify_sse()
                    return

                n = len(raw_files)

                # Sort by file modification time (set by the camera to capture time).
                # This is essentially instant — one stat() per file, no file reads.
                # To sort by EXIF capture time instead (slower but more accurate for
                # files whose mtime was reset during transfer), use find_cr3_files()
                # from main.py which reads each file's CMT2 box.
                files = sorted(raw_files, key=lambda f: (f.stat().st_mtime, f.name))
                print(f"  {_GREEN}Found {n} CR3 file(s){_RESET}"
                      f"  {_DIM}sorted by mtime  {files[0].name} … {files[-1].name}{_RESET}")

                app.config["start_stage"] = f"Loading {n} photos..."
                _notify_sse()
                state = CullerState(files)
                app.config["culler_state"] = state
                print(f"  {_GREEN}Session ready.{_RESET}")
            except Exception as e:
                print(f"  {_RED}Error during startup: {e}{_RESET}")
                app.config["start_error"] = str(e)
            finally:
                app.config["start_stage"] = None
                _notify_sse()

        threading.Thread(target=_do_start, daemon=True).start()
        return jsonify({"ok": True})

    # ── State & SSE ────────────────────────────────────────────────────────

    @app.route("/api/state")
    def api_state():
        error = app.config.get("start_error")
        if error:
            app.config["start_error"] = None
            return jsonify({"status": "error", "message": error})
        stage = app.config.get("start_stage")
        if stage:
            return jsonify({"status": "starting", "stage": stage})
        state = app.config["culler_state"]
        if state is None:
            return jsonify({"status": "waiting"})
        return jsonify(state.get_state())

    @app.route("/api/events")
    def api_events():
        def snapshot():
            error = app.config.get("start_error")
            if error:
                app.config["start_error"] = None
                return {"status": "error", "message": error}
            stage = app.config.get("start_stage")
            if stage:
                return {"status": "starting", "stage": stage}
            state = app.config["culler_state"]
            if state is None:
                return {"status": "waiting"}
            return state.get_state()

        def generate():
            yield f"data: {json.dumps(snapshot())}\n\n"
            while True:
                with _sse_condition:
                    _sse_condition.wait(timeout=25)
                yield f"data: {json.dumps(snapshot())}\n\n"

        return Response(
            stream_with_context(generate()),
            content_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    # ── Image serving ──────────────────────────────────────────────────────

    @app.route("/api/image/<int:idx>")
    def api_image(idx):
        state = app.config["culler_state"]
        if state is None or not (0 <= idx < len(state.files)):
            return "", 404
        data = state.get_image(idx)
        return Response(data, content_type="image/jpeg")

    @app.route("/api/thumbnail/<int:idx>")
    def api_thumbnail(idx):
        state = app.config["culler_state"]
        if state is None or not (0 <= idx < len(state.files)):
            return "", 404
        data = state.get_thumbnail(idx)
        return Response(data, content_type="image/jpeg",
                        headers={"Cache-Control": "no-store"})

    @app.route("/api/exif/<int:idx>")
    def api_exif(idx):
        state = app.config["culler_state"]
        if state is None or not (0 <= idx < len(state.files)):
            return jsonify({}), 200
        return jsonify(state.get_exif(idx))

    # ── Navigation & rating ────────────────────────────────────────────────

    @app.route("/api/navigate", methods=["POST"])
    def api_navigate():
        state = app.config["culler_state"]
        if state is None:
            return jsonify({"error": "no active session"}), 400
        idx = request.json.get("idx")
        if not isinstance(idx, int):
            return jsonify({"error": "invalid idx"}), 400
        ok = state.navigate(idx)
        return jsonify({"ok": ok, "idx": state.current_idx})

    @app.route("/api/rate", methods=["POST"])
    def api_rate():
        state = app.config["culler_state"]
        if state is None:
            return jsonify({"error": "no active session"}), 400
        data = request.json or {}
        idx = data.get("idx")
        rating = data.get("rating")
        advance = data.get("advance", False)
        if not isinstance(idx, int) or not isinstance(rating, int):
            return jsonify({"error": "invalid params"}), 400
        if not (0 <= rating <= 5):
            return jsonify({"error": "rating must be 0–5"}), 400
        if advance:
            new_idx, err = state.rate_and_advance(idx, rating)
        else:
            err = state.rate_only(idx, rating)
            new_idx = state.current_idx
        result = {"ok": True, "idx": new_idx}
        if err:
            result["warning"] = err
        return jsonify(result)

    @app.route("/api/navigate-by-rating", methods=["POST"])
    def api_navigate_by_rating():
        state = app.config["culler_state"]
        if state is None:
            return jsonify({"error": "no active session"}), 400
        data = request.json or {}
        rating = data.get("rating")
        direction = data.get("direction")  # 1 or -1
        if not isinstance(rating, int) or direction not in (1, -1):
            return jsonify({"error": "invalid params"}), 400
        if not (0 <= rating <= 5):
            return jsonify({"error": "rating must be 0–5"}), 400
        i = state._next_with_rating(state.current_idx, rating, direction)
        if i < 0:
            arrow = "→" if direction > 0 else "←"
            print(f"  {_YELLOW}{arrow} No {_rating_str(rating)} photo in that direction{_RESET}")
            return jsonify({"ok": False, "message": "no photo with that rating in that direction"})
        state.navigate(i)
        return jsonify({"ok": True, "idx": i})

    # ── Copy photos ────────────────────────────────────────────────────────

    @app.route("/api/pick-destination")
    def api_pick_destination():
        result = subprocess.run(
            ["osascript", "-e", 'POSIX path of (choose folder with prompt "Choose destination folder")'],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            return jsonify({"path": None})
        return jsonify({"path": result.stdout.strip()})

    @app.route("/api/copy", methods=["POST"])
    def api_copy():
        import json as _json
        state = app.config["culler_state"]
        if state is None:
            return jsonify({"error": "no active session"}), 400
        data = request.json or {}
        rating = data.get("rating")
        dest_str = data.get("destination", "")

        if not isinstance(rating, int):
            return jsonify({"error": "invalid rating"}), 400
        if rating != -1 and not (0 <= rating <= 5):
            return jsonify({"error": "rating must be 0–5 (or -1 for all)"}), 400
        dest = Path(dest_str).expanduser().resolve()
        if not dest.exists():
            return jsonify({"error": f"Destination does not exist: {dest}"}), 400

        with state._lock:
            if rating == -1:
                to_copy = list(state.files)
            elif rating == 0:
                to_copy = [f for f in state.files if state.ratings.get(f, 0) == 0]
            else:
                to_copy = [f for f in state.files if state.ratings.get(f, 0) >= rating]

        rating_label = "all" if rating == -1 else _rating_str(rating)
        total = len(to_copy)
        print(f"\n{_BOLD}Copying{_RESET} {total} file(s) ({rating_label})"
              f" → {_CYAN}{dest}{_RESET}")

        def generate():
            copied = 0
            skipped = 0
            errors = []
            for i, src in enumerate(to_copy):
                try:
                    dst_path = dest / src.name
                    if dst_path.exists():
                        print(f"  {_YELLOW}Skipped{_RESET} {src.name}  (already exists)")
                        skipped += 1
                    else:
                        shutil.copy2(src, dst_path)
                        xmp = src.with_suffix('.xmp')
                        if xmp.exists():
                            shutil.copy2(xmp, dest / xmp.name)
                            print(f"  {_GREEN}Copied{_RESET}  {src.name}  +xmp")
                        else:
                            print(f"  {_GREEN}Copied{_RESET}  {src.name}")
                        copied += 1
                except Exception as e:
                    print(f"  {_RED}Error{_RESET}   {src.name}: {e}")
                    errors.append(str(e))
                yield _json.dumps({
                    "progress": i + 1, "total": total,
                    "copied": copied, "skipped": skipped, "errors": errors,
                }) + '\n'

            parts = [f"{copied} copied"]
            if skipped:
                parts.append(f"{skipped} skipped (already exist)")
            if errors:
                parts.append(f"{len(errors)} error(s)")
            colour = _YELLOW if (skipped or errors) else _GREEN
            print(f"  {colour}Done: {', '.join(parts)}.{_RESET}")
            yield _json.dumps({
                "ok": True, "progress": total, "total": total,
                "copied": copied, "skipped": skipped, "errors": errors,
            }) + '\n'

        return Response(stream_with_context(generate()), mimetype='application/x-ndjson')

    return app


# ── Entry point ───────────────────────────────────────────────────────────────

def web_main():
    parser = argparse.ArgumentParser(description="FastCuller — CR3 photo culling web UI")
    parser.add_argument("path", nargs="?", default="", help="Folder of CR3 files (optional)")
    parser.add_argument("--port", type=int, default=5002, help="Port (default: 5002)")
    args = parser.parse_args()

    app = create_app()

    if args.path:
        root = Path(args.path).expanduser().resolve()
        if not root.exists():
            raise SystemExit(f"Path does not exist: {root}")
        app.config["_initial_path"] = str(root)

    url = f"http://localhost:{args.port}"
    print(f"{_BOLD}{_CYAN}FastCuller{_RESET}  {url}")
    print(f"{_DIM}Select a folder in the browser to begin.  Ctrl-C to quit.{_RESET}\n")
    webbrowser.open(url)
    app.run(host="0.0.0.0", port=args.port, debug=False, use_reloader=False)


if __name__ == "__main__":
    web_main()
