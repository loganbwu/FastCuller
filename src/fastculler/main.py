#!/usr/bin/env python3

import io
import re
import struct
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PIL import Image

# ── EXIF / ISOBMFF constants ──────────────────────────────────────────────────

_DTO_TAG         = 36867   # ExifIFD.DateTimeOriginal
_ORIENTATION_TAG = 274     # IFD0.Orientation
_CANON_UUID = bytes.fromhex('85c0b687820f11e08111f4ce462b6a48')

_ORIENTATION_TO_TRANSPOSE = {
    2: Image.Transpose.FLIP_LEFT_RIGHT,
    3: Image.Transpose.ROTATE_180,
    4: Image.Transpose.FLIP_TOP_BOTTOM,
    5: Image.Transpose.TRANSPOSE,
    6: Image.Transpose.ROTATE_270,
    7: Image.Transpose.TRANSVERSE,
    8: Image.Transpose.ROTATE_90,
}

THUMBNAIL_SIZE = (240, 240)   # max dimensions for filmstrip thumbnails; square to support portrait

# ── ISOBMFF parsing ───────────────────────────────────────────────────────────

def _iter_isobmff_boxes(buf, start, end):
    end = min(end, len(buf))
    off = start
    while off + 8 <= end:
        size = struct.unpack_from('>I', buf, off)[0]
        btype = buf[off + 4:off + 8]
        payload = off + 8
        if size == 1:
            if off + 16 > len(buf):
                break
            size = struct.unpack_from('>Q', buf, off + 8)[0]
            payload = off + 16
        if size == 0:
            size = end - off
        yield btype, payload, off + size
        off += size


def _cr3_cmt_box(data: bytes, box_name: bytes):
    """Extract a named CMT box payload from a Canon CR3 ISOBMFF file."""
    moov_start = moov_end = None
    for btype, s, e in _iter_isobmff_boxes(data, 0, len(data)):
        if btype == b'moov':
            moov_start, moov_end = s, e
            break
    if moov_start is None:
        return None
    for btype, s, e in _iter_isobmff_boxes(data, moov_start, moov_end):
        if btype == b'uuid' and data[s:s + 16] == _CANON_UUID:
            for btype2, s2, e2 in _iter_isobmff_boxes(data, s + 16, e):
                if btype2 == box_name:
                    return data[s2:e2]
    return None


def _read_tiff_tag(tiff: bytes, tag: int):
    """Return the value of a TIFF IFD tag, or None."""
    if len(tiff) < 8:
        return None
    endian = '<' if tiff[:2] == b'II' else '>'
    ifd_off = struct.unpack_from(endian + 'I', tiff, 4)[0]
    n = struct.unpack_from(endian + 'H', tiff, ifd_off)[0]
    for i in range(n):
        off = ifd_off + 2 + i * 12
        if off + 12 > len(tiff):
            break
        t, typ, count = struct.unpack_from(endian + 'HHI', tiff, off)
        if t != tag:
            continue
        raw = tiff[off + 8:off + 12]
        if typ == 3 and count == 1:
            return struct.unpack_from(endian + 'H', raw)[0]
        if typ == 4 and count == 1:
            return struct.unpack_from(endian + 'I', raw)[0]
        if typ == 2:
            if count > 4:
                val_off = struct.unpack_from(endian + 'I', raw)[0]
                return tiff[val_off:val_off + count].rstrip(b'\x00').decode('ascii', 'replace')
            return raw[:count].rstrip(b'\x00').decode('ascii', 'replace')
    return None


def _read_cr3_header(cr3_path: Path, max_bytes: int = 12_000_000) -> bytes:
    with open(cr3_path, 'rb') as f:
        return f.read(max_bytes)


# ── Metadata extraction ───────────────────────────────────────────────────────

def get_capture_time(cr3_path: Path) -> str:
    """Return DateTimeOriginal string ('YYYY:MM:DD HH:MM:SS') or '' on failure."""
    try:
        cmt2 = _cr3_cmt_box(_read_cr3_header(cr3_path), b'CMT2')
        if cmt2 is not None:
            ts = _read_tiff_tag(cmt2, _DTO_TAG)
            if ts:
                return str(ts)
    except Exception:
        pass
    return ''


def get_orientation(cr3_path: Path) -> int:
    """Return EXIF Orientation (1–8) from IFD0/CMT1, or 1 on failure."""
    try:
        cmt1 = _cr3_cmt_box(_read_cr3_header(cr3_path), b'CMT1')
        if cmt1 is not None:
            val = _read_tiff_tag(cmt1, _ORIENTATION_TAG)
            if val is not None:
                return int(val)
    except Exception:
        pass
    return 1


def apply_orientation(img: Image.Image, orientation: int) -> Image.Image:
    op = _ORIENTATION_TO_TRANSPOSE.get(orientation)
    return img.transpose(op) if op else img


# ── Image extraction ──────────────────────────────────────────────────────────

def extract_preview_image(cr3_path: Path) -> Image.Image:
    """Extract the largest embedded JPEG preview from a CR3 file using libraw."""
    import rawpy
    with rawpy.imread(str(cr3_path)) as raw:
        thumb = raw.extract_thumb()
        if thumb.format == rawpy.ThumbFormat.JPEG:
            return Image.open(io.BytesIO(bytes(thumb.data))).convert("RGB")
        return Image.fromarray(thumb.data).convert("RGB")


def _extract_preview_and_orientation(cr3_path: Path) -> tuple:
    """Return (PIL Image in RGB, EXIF orientation int) from the embedded JPEG.

    Reads orientation from the JPEG's own IFD0 tag 274 before converting to RGB
    (conversion may lose the EXIF info dict).  Falls back to CMT1 box, then 1.
    """
    import rawpy
    with rawpy.imread(str(cr3_path)) as raw:
        thumb = raw.extract_thumb()
        if thumb.format == rawpy.ThumbFormat.JPEG:
            jpeg_bytes = bytes(thumb.data)
            img = Image.open(io.BytesIO(jpeg_bytes))
            orientation = int(img.getexif().get(_ORIENTATION_TAG, 0) or 0)
            if not orientation:
                orientation = get_orientation(cr3_path)
            return img.convert("RGB"), orientation
        return Image.fromarray(thumb.data).convert("RGB"), get_orientation(cr3_path)


def get_preview_jpeg(cr3_path: Path, quality: int = 85) -> bytes:
    """Return orientation-corrected JPEG bytes for the full preview."""
    img, orientation = _extract_preview_and_orientation(cr3_path)
    img = apply_orientation(img, orientation)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality)
    return buf.getvalue()


def get_thumbnail_jpeg(cr3_path: Path, size: tuple = THUMBNAIL_SIZE) -> bytes:
    """Return a small orientation-corrected JPEG thumbnail."""
    img, orientation = _extract_preview_and_orientation(cr3_path)
    img = apply_orientation(img, orientation)
    img.thumbnail(size, Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=75)
    return buf.getvalue()


def thumbnail_from_jpeg(jpeg_bytes: bytes, size: tuple = THUMBNAIL_SIZE) -> bytes:
    """Return a resized JPEG thumbnail derived from already-decoded JPEG bytes.

    Much cheaper than get_thumbnail_jpeg() when a full preview has already been
    extracted — skips reopening the raw file and re-running the CR3/rawpy decode.
    """
    img = Image.open(io.BytesIO(jpeg_bytes)).convert("RGB")
    img.thumbnail(size, Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=75)
    return buf.getvalue()


def _rational_to_float(v) -> float:
    """Convert a PIL IFRational, (num, den) tuple, or plain number to float."""
    if hasattr(v, 'numerator') and hasattr(v, 'denominator'):
        return float(v.numerator) / float(v.denominator) if v.denominator else 0.0
    if isinstance(v, tuple) and len(v) == 2:
        return float(v[0]) / float(v[1]) if v[1] else 0.0
    return float(v)


def get_exif_info(cr3_path: Path) -> dict:
    """Return key shooting parameters from the embedded JPEG's EXIF.

    Keys present when available: iso, shutter, aperture, focal_length, lens, datetime.
    All values are display strings.  Returns {} on any failure.
    """
    import rawpy
    result = {}
    try:
        with rawpy.imread(str(cr3_path)) as raw:
            thumb = raw.extract_thumb()
            if thumb.format != rawpy.ThumbFormat.JPEG:
                return result
            img = Image.open(io.BytesIO(bytes(thumb.data)))
            exif = img.getexif()
            ifd = exif.get_ifd(0x8769)  # ExifIFD

            iso = ifd.get(34855)
            if iso is not None:
                if isinstance(iso, (list, tuple)):
                    iso = iso[0]
                result['iso'] = f'ISO {int(iso)}'

            et = ifd.get(33434)
            if et is not None:
                val = _rational_to_float(et)
                if val > 0:
                    result['shutter'] = f'1/{round(1/val)}s' if val < 1 else f'{val:.1f}s'

            fn = ifd.get(33437)
            if fn is not None:
                val = _rational_to_float(fn)
                if val > 0:
                    result['aperture'] = f'f/{val:.1f}'

            fl = ifd.get(37386)
            if fl is not None:
                val = _rational_to_float(fl)
                if val > 0:
                    result['focal_length'] = f'{round(val)}mm'

            lens = ifd.get(42036)
            if lens:
                result['lens'] = str(lens).strip()

            dt = ifd.get(36867) or exif.get(36867)
            if dt:
                dt_str = str(dt).strip()
                # EXIF format: "2024:06:14 10:30:45" → "2024-06-14 10:30:45"
                if len(dt_str) >= 10:
                    result['datetime'] = dt_str[:10].replace(':', '-') + dt_str[10:]
                else:
                    result['datetime'] = dt_str
    except Exception:
        pass
    return result


# ── File discovery ────────────────────────────────────────────────────────────

def find_cr3_files(root: Path) -> list:
    """Return CR3 files under root sorted by EXIF capture time (reads each file's CMT2 box).

    Accurate even when file mtimes are reset during transfer, but slow for large
    folders (~12 MB read per file).  The web app uses mtime sorting instead for
    speed; call this directly if you need guaranteed metadata order.
    """
    files = [p for p in root.rglob("*") if p.suffix.lower() == ".cr3"]
    if not files:
        return []
    workers = min(8, len(files))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        times = list(pool.map(get_capture_time, files))
    return [f for _, f in sorted(zip(times, files), key=lambda x: (x[0], x[1].name))]


# ── XMP capture time ──────────────────────────────────────────────────────────

_XMP_DATE_RE = re.compile(r'<exif:DateTimeOriginal>\s*([^<]*?)\s*</exif:DateTimeOriginal>')
_XMP_DATE_ATTR_RE = re.compile(r'exif:DateTimeOriginal\s*=\s*"([^"]*)"')


def read_xmp_capture_time(cr3_path: Path) -> str:
    """Return exif:DateTimeOriginal from the sidecar as 'YYYY-MM-DD HH:MM:SS', or '' if absent/unreadable.

    Normalises the ISO 'T' separator (as written by Lightroom/ExifTool) to a space
    to match our own write_xmp_capture_time() output, and drops any timezone or
    sub-second suffix — only used for relative ordering, so exact precision doesn't
    matter. Lets callers sort by capture time from the (small, fast-to-read) sidecar
    instead of re-reading each CR3's embedded EXIF via get_capture_time(), which is
    accurate but costs a large per-file read. Populate sidecars with the
    fastculler-write-dates CLI tool, or by exporting from Lightroom/ExifTool.
    """
    xmp_path = cr3_path.with_suffix('.xmp')
    if not xmp_path.exists():
        return ''
    try:
        content = xmp_path.read_text()
        m = _XMP_DATE_RE.search(content) or _XMP_DATE_ATTR_RE.search(content)
        if not m:
            return ''
        value = m.group(1).strip()
        if len(value) > 10 and value[10] == 'T':
            value = value[:10] + ' ' + value[11:19]
        return value[:19]
    except Exception:
        pass
    return ''


def write_xmp_capture_time(cr3_path: Path, capture_time: str) -> bool:
    """Write exif:DateTimeOriginal to the XMP sidecar alongside the CR3 file.

    capture_time is in EXIF format ('YYYY:MM:DD HH:MM:SS'), as returned by
    get_capture_time(). Creates the sidecar if absent; otherwise updates the
    existing tag in-place, preserving all other tags (ratings, crs:* crop data,
    etc). Returns False without writing if capture_time is empty/malformed.
    """
    if len(capture_time) < 19:
        return False
    date_str = capture_time[:10].replace(':', '-') + capture_time[10:]
    date_tag = f'   <exif:DateTimeOriginal>{date_str}</exif:DateTimeOriginal>\n'

    xmp_path = cr3_path.with_suffix('.xmp')
    if xmp_path.exists():
        content = xmp_path.read_text()

        # Remove any existing element- or attribute-form date first
        content = _XMP_DATE_RE.sub('', content)
        content = _XMP_DATE_ATTR_RE.sub('', content)

        if 'xmlns:exif=' not in content:
            content = content.replace(
                '<rdf:Description',
                '<rdf:Description\n    xmlns:exif="http://ns.adobe.com/exif/1.0/"',
                1,
            )

        last_close = content.rfind('</rdf:Description>')
        if last_close != -1:
            content = content[:last_close] + date_tag + '  ' + content[last_close:]
        xmp_path.write_text(content)

    else:
        xmp_path.write_text(
            '<?xpacket begin="" id="W5M0MpCehiHzreSzNTczkc9d"?>\n'
            '<x:xmpmeta xmlns:x="adobe:ns:meta/">\n'
            ' <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">\n'
            '  <rdf:Description rdf:about=""\n'
            '    xmlns:exif="http://ns.adobe.com/exif/1.0/">\n'
            + date_tag +
            '  </rdf:Description>\n'
            ' </rdf:RDF>\n'
            '</x:xmpmeta>\n'
            '<?xpacket end="w"?>'
        )
    return True


# ── XMP rating ────────────────────────────────────────────────────────────────

_XMP_RATING_RE = re.compile(r'<xmp:Rating>\s*(-?\d+)\s*</xmp:Rating>')
_XMP_RATING_ATTR_RE = re.compile(r'xmp:Rating\s*=\s*"(-?\d+)"')


def read_xmp_rating(cr3_path: Path) -> int:
    """Return the xmp:Rating from sidecar, or 0 if absent/unreadable."""
    xmp_path = cr3_path.with_suffix('.xmp')
    if not xmp_path.exists():
        return 0
    try:
        content = xmp_path.read_text()
        m = _XMP_RATING_RE.search(content) or _XMP_RATING_ATTR_RE.search(content)
        if m:
            return int(m.group(1))
    except Exception:
        pass
    return 0


def write_xmp_rating(cr3_path: Path, rating: int) -> None:
    """Write xmp:Rating to the XMP sidecar alongside the CR3 file.

    Creates the sidecar if absent; otherwise updates existing rating in-place,
    preserving all other tags (e.g. crs:* crop data from AutoCropper).
    """
    xmp_path = cr3_path.with_suffix('.xmp')
    rating_tag = f'   <xmp:Rating>{rating}</xmp:Rating>\n'

    if xmp_path.exists():
        content = xmp_path.read_text()

        # Remove any existing element-form rating
        content = _XMP_RATING_RE.sub('', content)
        # Remove attribute-form rating
        content = _XMP_RATING_ATTR_RE.sub('', content)

        # Ensure the xmp namespace is declared
        if 'xmlns:xmp=' not in content:
            content = content.replace(
                'xmlns:crs=',
                'xmlns:xmp="http://ns.adobe.com/xap/1.0/"\n    xmlns:crs=',
                1,
            )
            # Fallback: insert before first closing rdf:Description
            if 'xmlns:xmp=' not in content:
                content = content.replace(
                    '<rdf:Description',
                    '<rdf:Description\n    xmlns:xmp="http://ns.adobe.com/xap/1.0/"',
                    1,
                )

        last_close = content.rfind('</rdf:Description>')
        if last_close != -1:
            content = content[:last_close] + rating_tag + '  ' + content[last_close:]
        xmp_path.write_text(content)

    else:
        xmp_path.write_text(
            '<?xpacket begin="" id="W5M0MpCehiHzreSzNTczkc9d"?>\n'
            '<x:xmpmeta xmlns:x="adobe:ns:meta/">\n'
            ' <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">\n'
            '  <rdf:Description rdf:about=""\n'
            '    xmlns:xmp="http://ns.adobe.com/xap/1.0/">\n'
            + rating_tag +
            '  </rdf:Description>\n'
            ' </rdf:RDF>\n'
            '</x:xmpmeta>\n'
            '<?xpacket end="w"?>'
        )
