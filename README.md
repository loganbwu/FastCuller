# FastCuller

A fast photo culling application for CR3 files, implemented as a Flask web application. Inspired by FastRawViewer but fully in your control.

## Features

- Browse CR3 files recursively, sorted by capture date (from an XMP sidecar if present, otherwise file modification time)
- `fastculler-write-dates` CLI tool to pre-populate XMP sidecars with capture date, for fast + accurate sort order on large folders
- Rate photos with 0–5 stars (written to XMP sidecar files)
- Filmstrip view with star overlays and natural aspect ratio thumbnails
- Rating summary in the header (count per star tier)
- EXIF metadata overlay on main image (ISO, shutter, aperture, focal length, lens)
- Keyboard shortcuts for efficient culling
- Background prefetch of images and thumbnails, with in-memory LRU caching
- On-disk thumbnail cache (persists across restarts) + `fastculler-build-thumbnails` CLI tool to pre-generate all of them for a large library
- Copy rated photos (and XMP files) to a chosen destination
- Export XMP sidecar files only (no photos), preserving folder structure — useful for merging a collaborator's ratings into your own copy of the same photos
- Fullscreen mode (button or `F` key)

## Keyboard Shortcuts

| Key | Action |
|-----|--------|
| `1`–`5` | Rate N stars, advance to next photo |
| `` ` `` | Rate 0 stars, advance to next photo |
| `Shift` + `1`–`5` | Rate N stars without advancing |
| `Shift` + `` ` `` | Rate 0 stars without advancing |
| `Right` | Go to next photo |
| `Left` | Go to previous photo |
| `Right` + `1` | Go to next photo with 1 star |
| `Left` + `1` | Go to previous photo with 1 star |
| `Right` + `` ` `` | Go to next photo with 0 stars |
| `Left` + `` ` `` | Go to previous photo with 0 stars |
| `Home` | Jump to first unrated photo |
| `End` | Jump to last unrated photo |
| `Cmd/Ctrl` + `Z` | Undo last rating |
| `F` | Toggle fullscreen |
| `?` | Show keyboard shortcut help |
| `Esc` | Close modals / reset zoom / exit fullscreen |

## Trackpad Gestures (main image)

| Gesture | Action |
|---------|--------|
| Pinch (or `Cmd/Ctrl` + scroll) | Zoom in/out, centred on cursor |
| Two-finger swipe | Pan the image while zoomed in |
| Double-click | Zoom in to point, or reset if already zoomed |

Zoom resets automatically when navigating to a different photo.

## Architecture

```
src/fastculler/
├── main.py        CR3 image reading, capture time, XMP rating/capture-time read/write
├── web.py         Flask app, CullerState, prefetch, API routes
├── thumb_cache.py On-disk thumbnail cache
├── xmp_cli.py     fastculler-write-dates CLI tool
├── thumb_cli.py   fastculler-build-thumbnails CLI tool
├── cli_progress.py  Shared terminal progress bar for the CLI tools
├── templates/
│   └── index.html Folder picker screen, header, main panel, filmstrip
└── static/
    └── style.css  Dark UI (based on AutoCropper)
tests/
├── conftest.py    Sandboxes the on-disk thumbnail cache for the whole test run
└── test_main.py   Unit tests for image and XMP functions
```

## API Routes

| Route | Method | Description |
|-------|--------|-------------|
| `/` | GET | Main page |
| `/api/pick-folder` | GET | macOS folder picker (osascript) |
| `/api/start` | POST | Load folder, sort files by capture time |
| `/api/state` | GET | Full session state (file list, ratings, current index) |
| `/api/events` | GET | SSE stream for live updates |
| `/api/image/<idx>` | GET | Full-size JPEG preview for photo at index |
| `/api/thumbnail/<idx>` | GET | Small thumbnail for filmstrip |
| `/api/exif/<idx>` | GET | EXIF metadata dict for photo at index |
| `/api/navigate` | POST | Navigate to a photo by index |
| `/api/rate` | POST | Rate current photo, optionally advance |
| `/api/copy` | POST | Copy photos by rating to a destination folder |
| `/api/export-xmp` | POST | Export XMP sidecars only to a destination, preserving folder structure |

## Prefetch Strategy

The server prefetches images and thumbnails in the background, prioritizing the current
photo, then nearby photos in sequence, then 0- and 1-star neighbours — so navigation
stays responsive even when flicking through many photos quickly.

## Thumbnail Cache

Generating a filmstrip thumbnail means decoding a CR3's embedded JPEG — cheap for one
photo, expensive across a library of tens of thousands. On top of the in-memory LRU
cache (bounded, cleared on restart), FastCuller also caches every generated thumbnail
on disk at `~/Library/Caches/FastCuller/thumbnails/`, keyed by each photo's path and
modification time. Once a thumbnail's been generated once — through normal use, or by
running:

```bash
fastculler-build-thumbnails ~/Photos/2024-06-14-shoot
```

— it's never decoded again, regardless of restarts or how far you scroll the filmstrip.
Replacing or reprocessing a CR3 changes its modification time, so its old cached
thumbnail is naturally skipped rather than served stale.

There's no automatic cleanup — the cache only grows as you cull more folders (roughly
10 KB per photo). That's intentional: it's ordinary cache data, safe to delete any time
(FastCuller regenerates whatever's missing), and `~/Library/Caches` is exactly the
location macOS's own storage-management tools already know to treat as reclaimable. If
you ever want to reclaim the space yourself:

```bash
rm -rf ~/Library/Caches/FastCuller
```

## XMP Rating Format

Ratings are written as `xmp:Rating` in a standard XMP sidecar (`.xmp`) alongside the CR3 file:

```xml
<xmp:Rating>1</xmp:Rating>
```

Existing XMP files are updated in-place; new ones are created if absent.

## XMP Capture Time Format

Capture date is written as `exif:DateTimeOriginal` in the same XMP sidecar:

```xml
<exif:DateTimeOriginal>2024-06-14 10:30:45</exif:DateTimeOriginal>
```

Reading also understands the ISO `T` separator (e.g. `2024-06-14T10:30:45`), as written by
Lightroom or ExifTool, so a sidecar tagged by those tools sorts correctly too.

## Sorting by Capture Date

FastCuller sorts photos by capture date. For each file it checks, in order:

1. **XMP sidecar** — `exif:DateTimeOriginal`, a small, fast text read.
2. **File modification time** — instant, but wrong if mtimes were reset during a file transfer
   (e.g. copying from a memory card with software that doesn't preserve them).

Reading the true EXIF capture date straight from a CR3 file is accurate but slow (~12 MB read
per file), so FastCuller doesn't do that automatically on every load. Instead, run the
`fastculler-write-dates` CLI tool once per folder to cache each photo's capture date into its
XMP sidecar — after that, loading the folder sorts correctly without the per-file cost:

```bash
fastculler-write-dates ~/Photos/2024-06-14-shoot
```

Files that already have a cached capture date are skipped by default; pass `--force` to
re-tag them (e.g. after the CR3s themselves changed). Files with no readable EXIF capture
time are left alone and fall back to mtime sorting as before.

## Setup

### First-time setup (no developer tools required)

These steps assume a Mac with nothing developer-related installed yet — no Homebrew, no Python, no git.

1. **Open Terminal.** Press `Cmd + Space`, type `Terminal`, press Enter.
2. **Install rye** (manages Python for you — no separate Python install needed). Paste this into Terminal and press Enter:
   ```bash
   curl -sSf https://rye.astral.sh/get | bash
   ```
   Accept the defaults when prompted. When it finishes, close Terminal and reopen it (or run `source "$HOME/.rye/env"`) so the `rye` command is available.
3. **Get the code.** Either:
   - **Download ZIP** (easiest): go to https://github.com/loganbwu/FastCuller, click the green `Code` button → `Download ZIP`, then double-click the downloaded file in Finder to unzip it. Note where it lands (usually `~/Downloads/FastCuller-main`).
   - **Or clone with git** (macOS will prompt you to install Command Line Tools the first time you run `git` — accept and let it install):
     ```bash
     git clone https://github.com/loganbwu/FastCuller.git
     ```
4. **Move into the project folder** in Terminal. If you downloaded the ZIP:
   ```bash
   cd ~/Downloads/FastCuller-main
   ```
   If you cloned it:
   ```bash
   cd FastCuller
   ```
5. **Install dependencies and run:**
   ```bash
   rye sync
   rye run fastculler
   ```
   The first `rye sync` will take a minute or two while it downloads Python and the required packages.

The app opens in the browser at `http://localhost:5002`. Leave the Terminal window open while using FastCuller — closing it stops the app.

### Troubleshooting: `dyld: ... Symbol not found: ___darwin_check_fd_set_overflow`

If step 2 above fails partway through with an error message containing this text, Rye's own
installer can't run on this Mac's macOS version — Rye (and current Python installers generally)
require **macOS 11 (Big Sur) or later**. This isn't a FastCuller problem, and it isn't specific to
whichever Python version you're offered during setup. It shows up on older Macs still running
macOS 10.13 (High Sierra) or earlier that can't be upgraded further.

**First, check if the Mac can just be updated to macOS 11 or later** — that's the simplest fix,
and worth ruling out even if it seems unlikely:

1. Click the Apple menu (top-left corner) → **About This Mac**, and note the macOS version.
2. Check for an available upgrade:
   - **macOS 13 (Ventura) or later:** Apple menu → **System Settings** → **General** → **Software
     Update**.
   - **macOS 10.14–12 (Mojave through Monterey):** Apple menu → **System Preferences** →
     **Software Update**.
   - **macOS 10.13 (High Sierra) or earlier:** open the **App Store** app and click **Updates** in
     the toolbar.
3. If a newer macOS is offered, install it, restart the Mac, then go back to step 1 of Setup above
   and try again from the beginning.

**If no macOS update is available** (common on older hardware — some Macs can't go past a certain
version), **Rye itself can't be used at all** — the `dyld` error is Rye's own program crashing on
startup (look for `"$TEMP_FILE" self install` in the error output: that's Rye's own installer
binary aborting, not a Python it's trying to download). No toolchain setting fixes that, because
Rye never gets far enough to read it. The fix is to skip Rye completely and run FastCuller with a
plain Python instead. This replaces the whole "First-time setup" section above — don't mix the two
sets of steps together, just follow this list start to finish:

1. **Open Terminal.** Press `Cmd + Space`, type `Terminal`, press Enter.
2. **Install Python 3.9.13** — the last Python release with an installer for macOS this old.
   FastCuller supports running on Python 3.9 for exactly this situation. Paste this into Terminal
   and press Enter:
   ```bash
   curl -sSf -o /tmp/python-3.9.13.pkg https://www.python.org/ftp/python/3.9.13/python-3.9.13-macosx10.9.pkg && \
   sudo installer -pkg /tmp/python-3.9.13.pkg -target /
   ```
   Terminal will show `Password:` and wait — type your Mac's login password (it won't show
   anything as you type, that's normal) and press Enter. The last line printed should say
   `The install was successful` or `The upgrade was successful`.
3. **Create a private space for FastCuller's dependencies** (a "virtual environment") using that
   Python. Paste this and press Enter — it only needs to be done once, ever, even if you run
   FastCuller many times later:
   ```bash
   /Library/Frameworks/Python.framework/Versions/3.9/bin/python3.9 -m venv ~/fastculler-env
   ```
4. **Get the code.** Go to https://github.com/loganbwu/FastCuller, click the green `Code` button →
   `Download ZIP`, then double-click the downloaded file in Finder to unzip it. Note where it lands
   (usually `~/Downloads/FastCuller-main`).
5. **Move into the project folder** in Terminal:
   ```bash
   cd ~/Downloads/FastCuller-main
   ```
6. **Install FastCuller's dependencies and run it.** Paste this and press Enter:
   ```bash
   source ~/fastculler-env/bin/activate && pip install -e . && fastculler
   ```
   Once it's active, your Terminal prompt will start with `(fastculler-env)` — that confirms it
   worked. `pip install -e .` will take a minute or so the first time.

The app opens in the browser at `http://localhost:5002`, exactly like the normal setup.

### Every time after that

**If you set up FastCuller normally with Rye:** open Terminal, `cd` into the FastCuller folder, then:

```bash
rye run fastculler
```

**If you used the Python 3.9 fallback above:** open Terminal, then paste this (adjusting the
project folder path to wherever you placed it):

```bash
source ~/fastculler-env/bin/activate && cd ~/Downloads/FastCuller-main && fastculler
```

## Usage

Get your CR3 files onto disk in whatever way suits you:

- Copy them off the memory card to your computer or an external hard drive, **or**
- Leave them on the card and point FastCuller straight at it.

Folder structure is flexible — a common approach is one subfolder per camera (e.g. `R5/`, `R6/`), but any structure works. When you run the app and pick a folder, it searches recursively, so you can select either:

- A specific subfolder (only those photos are loaded), or
- The top-level folder (all CR3 files in every subfolder are loaded together, sorted by capture time).

### Getting accurate sort order for a new folder

FastCuller sorts by file modification time unless a photo's XMP sidecar already has a capture
date cached — and mtime can be wrong if it was reset while copying files off a card. Before
culling a folder for the first time, run `fastculler-write-dates` on it once to cache the real
EXIF capture date into each photo's `.xmp` sidecar:

```bash
rye run fastculler-write-dates ~/Photos/2024-06-14-shoot
```

(Drop `rye run` if you used the Python 3.9 fallback setup — just `fastculler-write-dates ...`
with the same environment activated as when you run `fastculler`.)

### Pre-warming thumbnails for a large folder

For a folder large enough that scrolling the filmstrip visibly waits on thumbnails
decoding, run `fastculler-build-thumbnails` on it once — after that, every thumbnail
loads instantly regardless of library size (see [Thumbnail Cache](#thumbnail-cache)):

```bash
rye run fastculler-build-thumbnails ~/Photos/2024-06-14-shoot
```

### Sharing ratings with a collaborator

If a collaborator has their own copy of the same folder hierarchy (e.g. synced separately rather
than sent to you directly), they don't need to send you the photos back — just their ratings:

1. They point FastCuller at their copy of the folder and rate photos as usual.
2. They click **Export XMP** and choose a destination — this writes only the `.xmp` sidecar files,
   mirroring the same subfolder structure, with no photos included.
3. They send you that (small) folder of `.xmp` files.
4. You copy those files into the matching subfolders of your own copy, overwriting any existing
   `.xmp` files for the same photos.
5. Reload the folder in FastCuller (or open it in Lightroom) to pick up the new ratings.

## Roadmap

- [x] Project setup with rye
- [x] CR3 preview extraction and metadata reading
- [x] XMP rating read/write
- [x] Folder selection screen
- [x] Main image viewer
- [x] Filmstrip with thumbnails and star overlays
- [x] Keyboard shortcuts
- [x] Server-side prefetch with LRU cache
- [x] Copy photos functionality
- [x] Multi-star rating (0–5)
- [x] Rate without advancing (Shift+key)
- [x] Rating summary in header
- [x] EXIF metadata overlay (ISO, shutter, aperture, focal length, lens, capture time)
- [x] Keyboard shortcut help modal
- [x] SSE auto-reconnect on connection drop
- [x] Copy modal: "All photos" option, skip-on-collision, auto-close on success
- [x] Session position remembered per folder (localStorage)
- [x] Undo last rating (Cmd/Ctrl+Z)
- [x] Home/End keys to jump to first/last unrated photo
- [x] Filmstrip prefetch-ready indicator
- [x] Zoom/pan main image
- [x] Fullscreen mode
- [x] Thumbnail prefetch
- [x] Smooth, responsive filmstrip and navigation under rapid input
- [x] Export XMP sidecars only, preserving folder structure
- [x] Jump to a specific photo by number (click the progress counter)
- [x] `fastculler-write-dates` CLI tool + sort by XMP capture date, falling back to mtime
- [x] On-disk thumbnail cache + `fastculler-build-thumbnails` CLI tool
- [ ] Filter filmstrip by rating
- [ ] Reject flag (X key → rating -1)
