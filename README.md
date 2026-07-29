# FastCuller

A fast photo culling application for CR3 files, implemented as a Flask web application. Inspired by FastRawViewer but fully in your control.

## Features

- Browse CR3 files recursively, sorted by file modification time
- Rate photos with 0–5 stars (written to XMP sidecar files)
- Filmstrip view with star overlays and natural aspect ratio thumbnails
- Rating summary in the header (count per star tier)
- EXIF metadata overlay on main image (ISO, shutter, aperture, focal length, lens)
- Keyboard shortcuts for efficient culling
- Background prefetch of images and thumbnails, with in-memory LRU caching
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
├── main.py        CR3 image reading, capture time, XMP rating read/write
├── web.py         Flask app, CullerState, prefetch, API routes
├── templates/
│   └── index.html Folder picker screen, header, main panel, filmstrip
└── static/
    └── style.css  Dark UI (based on AutoCropper)
tests/
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

## XMP Rating Format

Ratings are written as `xmp:Rating` in a standard XMP sidecar (`.xmp`) alongside the CR3 file:

```xml
<xmp:Rating>1</xmp:Rating>
```

Existing XMP files are updated in-place; new ones are created if absent.

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

If `curl -sSf https://rye.astral.sh/get | bash` fails during "Bootstrapping rye internals" with
this error, it means the Mac's macOS version is older than what Rye's downloaded Python build
expects (this is a [known issue](https://github.com/indygreg/python-build-standalone/pull/122)
with the prebuilt Python binaries Rye uses, not specific to FastCuller). Two fixes:

1. **Update macOS**, if the Mac supports it — check `Apple menu → About This Mac` for the current
   version and `System Settings → General → Software Update` for available upgrades. This is the
   simplest fix if available.
2. **If the Mac can't be upgraded**, skip Rye's bundled Python and point it at a Python installed
   directly from [python.org](https://www.python.org/downloads/) instead:
   ```bash
   rye toolchain register /Library/Frameworks/Python.framework/Versions/3.12/bin/python3.12
   cd FastCuller   # or wherever the project folder is
   rye pin cpython@3.12
   rye sync
   ```
   (Adjust the version number in the path to whatever you installed from python.org.)

### Every time after that

Open Terminal, `cd` into the FastCuller folder, then:

```bash
rye run fastculler
```

## Usage

Get your CR3 files onto disk in whatever way suits you:

- Copy them off the memory card to your computer or an external hard drive, **or**
- Leave them on the card and point FastCuller straight at it.

Folder structure is flexible — a common approach is one subfolder per camera (e.g. `R5/`, `R6/`), but any structure works. When you run the app and pick a folder, it searches recursively, so you can select either:

- A specific subfolder (only those photos are loaded), or
- The top-level folder (all CR3 files in every subfolder are loaded together, sorted by capture time).

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
- [ ] Filter filmstrip by rating
- [ ] Reject flag (X key → rating -1)
