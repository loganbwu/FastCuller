# FastCuller

A fast photo culling application for CR3 files, implemented as a Flask web application. Inspired by FastRawViewer but fully in your control.

## Features

- Browse CR3 files recursively, sorted by file modification time
- Rate photos with 0–5 stars (written to XMP sidecar files)
- Filmstrip view with star overlays and natural aspect ratio thumbnails
- Rating summary in the header (count per star tier)
- EXIF metadata overlay on main image (ISO, shutter, aperture, focal length, lens)
- Keyboard shortcuts for efficient culling
- Server-side prefetch with LRU image cache (30 full images, 100 thumbnails)
- Copy rated photos (and XMP files) to a chosen destination

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
| `?` | Show keyboard shortcut help |
| `Esc` | Close modals / reset zoom |

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

## Prefetch Strategy

The server keeps a pool of persistent background workers that continuously pick the
highest-priority not-yet-cached image relative to whatever the *current* index is,
re-evaluating on every pick. Priority (highest first):

- Current image
- Next and previous photos in sequence (nearest first)
- Next and previous photos with 0 stars
- Next and previous photos with 1 star

Because priority is re-evaluated live rather than queued as a fixed batch of tasks per
navigation, rapid navigation (e.g. flicking through many photos quickly) doesn't leave
workers stuck working through a backlog of now-stale requests — they simply retarget to
whatever is now closest to the current photo.

## XMP Rating Format

Ratings are written as `xmp:Rating` in a standard XMP sidecar (`.xmp`) alongside the CR3 file:

```xml
<xmp:Rating>1</xmp:Rating>
```

Existing XMP files are updated in-place; new ones are created if absent.

## Setup

```bash
rye sync
rye run fastculler
```

The app opens in the browser at `http://localhost:5002`.

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
- [ ] Filter filmstrip by rating
- [ ] Reject flag (X key → rating -1)
