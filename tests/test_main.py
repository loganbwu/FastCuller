"""Tests for fastculler.main — XMP rating and metadata functions.

These tests do not require real CR3 files; they exercise the pure-Python
XMP reading/writing logic and the ISOBMFF/TIFF tag parsers with synthetic
byte sequences.
"""

import struct
import tempfile
from pathlib import Path

import pytest

from fastculler.main import (
    _cr3_cmt_box,
    _read_tiff_tag,
    read_xmp_capture_time,
    read_xmp_rating,
    write_xmp_capture_time,
    write_xmp_rating,
)


# ── XMP rating tests ──────────────────────────────────────────────────────────

class TestReadXmpRating:
    def test_returns_zero_when_no_sidecar(self, tmp_path):
        cr3 = tmp_path / "photo.cr3"
        cr3.touch()
        assert read_xmp_rating(cr3) == 0

    def test_reads_element_form_rating(self, tmp_path):
        cr3 = tmp_path / "photo.cr3"
        cr3.touch()
        xmp = tmp_path / "photo.xmp"
        xmp.write_text(
            '<?xpacket begin="" id="W5M0MpCehiHzreSzNTczkc9d"?>\n'
            '<x:xmpmeta xmlns:x="adobe:ns:meta/">\n'
            ' <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">\n'
            '  <rdf:Description rdf:about="" xmlns:xmp="http://ns.adobe.com/xap/1.0/">\n'
            '   <xmp:Rating>1</xmp:Rating>\n'
            '  </rdf:Description>\n'
            ' </rdf:RDF>\n'
            '</x:xmpmeta>\n'
        )
        assert read_xmp_rating(cr3) == 1

    def test_reads_attribute_form_rating(self, tmp_path):
        cr3 = tmp_path / "photo.cr3"
        cr3.touch()
        xmp = tmp_path / "photo.xmp"
        xmp.write_text(
            '<rdf:Description xmlns:xmp="http://ns.adobe.com/xap/1.0/" xmp:Rating="3">\n'
            '</rdf:Description>\n'
        )
        assert read_xmp_rating(cr3) == 3

    def test_returns_zero_when_no_rating_tag(self, tmp_path):
        cr3 = tmp_path / "photo.cr3"
        cr3.touch()
        xmp = tmp_path / "photo.xmp"
        xmp.write_text(
            '<?xpacket begin="" id="W5M0MpCehiHzreSzNTczkc9d"?>\n'
            '<x:xmpmeta xmlns:x="adobe:ns:meta/">\n'
            '  <rdf:Description rdf:about="">\n'
            '  </rdf:Description>\n'
            '</x:xmpmeta>\n'
        )
        assert read_xmp_rating(cr3) == 0


class TestWriteXmpRating:
    def test_creates_new_sidecar(self, tmp_path):
        cr3 = tmp_path / "photo.cr3"
        cr3.touch()
        write_xmp_rating(cr3, 1)
        xmp = tmp_path / "photo.xmp"
        assert xmp.exists()
        content = xmp.read_text()
        assert '<xmp:Rating>1</xmp:Rating>' in content
        assert 'xmlns:xmp=' in content

    def test_writes_zero_rating(self, tmp_path):
        cr3 = tmp_path / "photo.cr3"
        cr3.touch()
        write_xmp_rating(cr3, 0)
        xmp = tmp_path / "photo.xmp"
        assert '<xmp:Rating>0</xmp:Rating>' in xmp.read_text()

    def test_updates_existing_sidecar(self, tmp_path):
        cr3 = tmp_path / "photo.cr3"
        cr3.touch()
        xmp = tmp_path / "photo.xmp"
        xmp.write_text(
            '<?xpacket begin="" id="W5M0MpCehiHzreSzNTczkc9d"?>\n'
            '<x:xmpmeta xmlns:x="adobe:ns:meta/">\n'
            ' <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">\n'
            '  <rdf:Description rdf:about="" xmlns:xmp="http://ns.adobe.com/xap/1.0/">\n'
            '   <xmp:Rating>0</xmp:Rating>\n'
            '  </rdf:Description>\n'
            ' </rdf:RDF>\n'
            '</x:xmpmeta>\n'
            '<?xpacket end="w"?>'
        )
        write_xmp_rating(cr3, 1)
        content = xmp.read_text()
        # Old rating removed, new one present
        assert content.count('<xmp:Rating>') == 1
        assert '<xmp:Rating>1</xmp:Rating>' in content

    def test_roundtrip(self, tmp_path):
        cr3 = tmp_path / "photo.cr3"
        cr3.touch()
        for rating in (0, 1, 0, 1):
            write_xmp_rating(cr3, rating)
            assert read_xmp_rating(cr3) == rating

    def test_preserves_existing_crs_tags(self, tmp_path):
        """Writing a rating must not destroy pre-existing crs:* tags (e.g. from AutoCropper)."""
        cr3 = tmp_path / "photo.cr3"
        cr3.touch()
        xmp = tmp_path / "photo.xmp"
        xmp.write_text(
            '<?xpacket begin="" id="W5M0MpCehiHzreSzNTczkc9d"?>\n'
            '<x:xmpmeta xmlns:x="adobe:ns:meta/">\n'
            ' <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">\n'
            '  <rdf:Description rdf:about=""\n'
            '    xmlns:crs="http://ns.adobe.com/camera-raw-settings/1.0/">\n'
            '   <crs:HasCrop>True</crs:HasCrop>\n'
            '   <crs:CropLeft>0.1</crs:CropLeft>\n'
            '  </rdf:Description>\n'
            ' </rdf:RDF>\n'
            '</x:xmpmeta>\n'
            '<?xpacket end="w"?>'
        )
        write_xmp_rating(cr3, 1)
        content = xmp.read_text()
        assert '<crs:HasCrop>True</crs:HasCrop>' in content
        assert '<crs:CropLeft>0.1</crs:CropLeft>' in content
        assert '<xmp:Rating>1</xmp:Rating>' in content


# ── XMP capture time tests ────────────────────────────────────────────────────

class TestReadXmpCaptureTime:
    def test_returns_empty_when_no_sidecar(self, tmp_path):
        cr3 = tmp_path / "photo.cr3"
        cr3.touch()
        assert read_xmp_capture_time(cr3) == ''

    def test_reads_element_form(self, tmp_path):
        cr3 = tmp_path / "photo.cr3"
        cr3.touch()
        xmp = tmp_path / "photo.xmp"
        xmp.write_text(
            '<rdf:Description xmlns:exif="http://ns.adobe.com/exif/1.0/">\n'
            '   <exif:DateTimeOriginal>2024-06-14 10:30:45</exif:DateTimeOriginal>\n'
            '</rdf:Description>\n'
        )
        assert read_xmp_capture_time(cr3) == '2024-06-14 10:30:45'

    def test_reads_attribute_form(self, tmp_path):
        cr3 = tmp_path / "photo.cr3"
        cr3.touch()
        xmp = tmp_path / "photo.xmp"
        xmp.write_text(
            '<rdf:Description xmlns:exif="http://ns.adobe.com/exif/1.0/" '
            'exif:DateTimeOriginal="2024-06-14 10:30:45">\n'
            '</rdf:Description>\n'
        )
        assert read_xmp_capture_time(cr3) == '2024-06-14 10:30:45'

    def test_normalises_iso_t_separator(self, tmp_path):
        """Lightroom/ExifTool write the ISO 'T' separator — normalise to match our
        own space-separated format so both sort/compare the same way."""
        cr3 = tmp_path / "photo.cr3"
        cr3.touch()
        xmp = tmp_path / "photo.xmp"
        xmp.write_text(
            '<rdf:Description xmlns:exif="http://ns.adobe.com/exif/1.0/">\n'
            '   <exif:DateTimeOriginal>2024-06-14T10:30:45+10:00</exif:DateTimeOriginal>\n'
            '</rdf:Description>\n'
        )
        assert read_xmp_capture_time(cr3) == '2024-06-14 10:30:45'

    def test_returns_empty_when_no_date_tag(self, tmp_path):
        cr3 = tmp_path / "photo.cr3"
        cr3.touch()
        xmp = tmp_path / "photo.xmp"
        xmp.write_text('<rdf:Description>\n   <xmp:Rating>1</xmp:Rating>\n</rdf:Description>\n')
        assert read_xmp_capture_time(cr3) == ''


class TestWriteXmpCaptureTime:
    def test_creates_new_sidecar(self, tmp_path):
        cr3 = tmp_path / "photo.cr3"
        cr3.touch()
        write_xmp_capture_time(cr3, '2024:06:14 10:30:45')
        xmp = tmp_path / "photo.xmp"
        assert xmp.exists()
        content = xmp.read_text()
        assert '<exif:DateTimeOriginal>2024-06-14 10:30:45</exif:DateTimeOriginal>' in content
        assert 'xmlns:exif=' in content

    def test_returns_false_and_skips_empty_capture_time(self, tmp_path):
        cr3 = tmp_path / "photo.cr3"
        cr3.touch()
        assert write_xmp_capture_time(cr3, '') is False
        assert not (tmp_path / "photo.xmp").exists()

    def test_updates_existing_sidecar(self, tmp_path):
        cr3 = tmp_path / "photo.cr3"
        cr3.touch()
        xmp = tmp_path / "photo.xmp"
        xmp.write_text(
            '<rdf:Description xmlns:exif="http://ns.adobe.com/exif/1.0/">\n'
            '   <exif:DateTimeOriginal>2020-01-01 00:00:00</exif:DateTimeOriginal>\n'
            '</rdf:Description>\n'
        )
        write_xmp_capture_time(cr3, '2024:06:14 10:30:45')
        content = xmp.read_text()
        assert content.count('<exif:DateTimeOriginal>') == 1
        assert '<exif:DateTimeOriginal>2024-06-14 10:30:45</exif:DateTimeOriginal>' in content

    def test_roundtrip(self, tmp_path):
        cr3 = tmp_path / "photo.cr3"
        cr3.touch()
        write_xmp_capture_time(cr3, '2024:06:14 10:30:45')
        assert read_xmp_capture_time(cr3) == '2024-06-14 10:30:45'

    def test_preserves_existing_rating_and_crs_tags(self, tmp_path):
        cr3 = tmp_path / "photo.cr3"
        cr3.touch()
        xmp = tmp_path / "photo.xmp"
        xmp.write_text(
            '<?xpacket begin="" id="W5M0MpCehiHzreSzNTczkc9d"?>\n'
            '<x:xmpmeta xmlns:x="adobe:ns:meta/">\n'
            ' <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">\n'
            '  <rdf:Description rdf:about=""\n'
            '    xmlns:xmp="http://ns.adobe.com/xap/1.0/"\n'
            '    xmlns:crs="http://ns.adobe.com/camera-raw-settings/1.0/">\n'
            '   <xmp:Rating>3</xmp:Rating>\n'
            '   <crs:HasCrop>True</crs:HasCrop>\n'
            '  </rdf:Description>\n'
            ' </rdf:RDF>\n'
            '</x:xmpmeta>\n'
            '<?xpacket end="w"?>'
        )
        write_xmp_capture_time(cr3, '2024:06:14 10:30:45')
        content = xmp.read_text()
        assert '<xmp:Rating>3</xmp:Rating>' in content
        assert '<crs:HasCrop>True</crs:HasCrop>' in content
        assert '<exif:DateTimeOriginal>2024-06-14 10:30:45</exif:DateTimeOriginal>' in content

    def test_compose_with_write_xmp_rating(self, tmp_path):
        """Rating and capture-time writers must not clobber each other regardless
        of which runs first — both touch the same sidecar file independently."""
        cr3 = tmp_path / "photo.cr3"
        cr3.touch()
        write_xmp_capture_time(cr3, '2024:06:14 10:30:45')
        write_xmp_rating(cr3, 4)
        assert read_xmp_capture_time(cr3) == '2024-06-14 10:30:45'
        assert read_xmp_rating(cr3) == 4


# ── On-disk thumbnail cache tests ─────────────────────────────────────────────
# The autouse _sandbox_thumbnail_cache fixture (conftest.py) redirects the cache
# directory to tmp_path for every test in this file, so these never touch the
# real ~/Library/Caches.

class TestThumbCache:
    def test_returns_none_when_not_cached(self, tmp_path):
        from fastculler.thumb_cache import read_cached_thumbnail

        cr3 = tmp_path / "photo.cr3"
        cr3.touch()
        assert read_cached_thumbnail(cr3) is None

    def test_roundtrip(self, tmp_path):
        from fastculler.thumb_cache import read_cached_thumbnail, write_cached_thumbnail

        cr3 = tmp_path / "photo.cr3"
        cr3.touch()
        write_cached_thumbnail(cr3, b'\xff\xd8\xff fake jpeg bytes')
        assert read_cached_thumbnail(cr3) == b'\xff\xd8\xff fake jpeg bytes'

    def test_stale_after_file_modified(self, tmp_path):
        """A changed mtime (e.g. the CR3 was reprocessed/replaced) must miss the
        old cache entry rather than serve a stale thumbnail."""
        import os
        from fastculler.thumb_cache import read_cached_thumbnail, write_cached_thumbnail

        cr3 = tmp_path / "photo.cr3"
        cr3.touch()
        write_cached_thumbnail(cr3, b'old thumbnail')
        assert read_cached_thumbnail(cr3) == b'old thumbnail'

        # Bump mtime forward to simulate the file changing
        new_mtime = cr3.stat().st_mtime + 10
        os.utime(cr3, (new_mtime, new_mtime))

        assert read_cached_thumbnail(cr3) is None

    def test_different_files_same_basename_dont_collide(self, tmp_path):
        """Two files with the same name in different folders (a common CR3
        naming collision — see the export-XMP subfolder tests) must cache
        independently, since the key is the full resolved path, not the name."""
        from fastculler.thumb_cache import read_cached_thumbnail, write_cached_thumbnail

        (tmp_path / "100CANON").mkdir()
        (tmp_path / "101CANON").mkdir()
        cr3_a = tmp_path / "100CANON" / "IMG_0001.CR3"
        cr3_b = tmp_path / "101CANON" / "IMG_0001.CR3"
        cr3_a.touch()
        cr3_b.touch()

        write_cached_thumbnail(cr3_a, b'thumb a')
        write_cached_thumbnail(cr3_b, b'thumb b')
        assert read_cached_thumbnail(cr3_a) == b'thumb a'
        assert read_cached_thumbnail(cr3_b) == b'thumb b'

    def test_write_leaves_no_temp_file_behind(self, tmp_path):
        from fastculler import thumb_cache
        from fastculler.thumb_cache import write_cached_thumbnail

        cr3 = tmp_path / "photo.cr3"
        cr3.touch()
        write_cached_thumbnail(cr3, b'thumb')
        assert list(thumb_cache._cache_dir().glob('*.tmp')) == []

    def test_write_never_leaves_a_partial_file_on_failure(self, tmp_path, monkeypatch):
        """A write that dies partway through (e.g. disk full) must not leave a
        corrupt file at the final path for a concurrent reader to see — this is
        exactly the scenario of the app and fastculler-build-thumbnails writing
        the same cache at once."""
        from fastculler import thumb_cache
        from fastculler.thumb_cache import read_cached_thumbnail, write_cached_thumbnail

        cr3 = tmp_path / "photo.cr3"
        cr3.touch()

        real_replace = thumb_cache.os.replace

        def failing_replace(*a, **kw):
            raise OSError("simulated disk failure")

        monkeypatch.setattr(thumb_cache.os, 'replace', failing_replace)
        with pytest.raises(OSError):
            write_cached_thumbnail(cr3, b'thumb')
        monkeypatch.setattr(thumb_cache.os, 'replace', real_replace)

        assert read_cached_thumbnail(cr3) is None
        assert list(thumb_cache._cache_dir().glob('*.tmp')) == []


# ── TIFF tag reader tests ─────────────────────────────────────────────────────

def _make_tiff_ifd(endian: str, tag: int, typ: int, value: int) -> bytes:
    """Minimal TIFF with one IFD entry of SHORT or LONG type."""
    fmt = endian + 'HHI'
    header = b'II' if endian == '<' else b'MM'
    # TIFF header: magic, ifd_offset
    header += struct.pack(endian + 'HI', 42, 8)
    # IFD: n_entries=1
    ifd = struct.pack(endian + 'H', 1)
    count = 1
    if typ == 3:   # SHORT
        raw = struct.pack(endian + 'HHI', tag, 3, count)
        raw += struct.pack(endian + 'H', value) + b'\x00\x00'
    else:          # LONG
        raw = struct.pack(endian + 'HHI', tag, 4, count)
        raw += struct.pack(endian + 'I', value)
    ifd += raw
    # next IFD offset = 0
    ifd += struct.pack(endian + 'I', 0)
    return header + ifd


class TestReadTiffTag:
    def test_reads_short_little_endian(self):
        data = _make_tiff_ifd('<', 274, 3, 6)
        assert _read_tiff_tag(data, 274) == 6

    def test_reads_short_big_endian(self):
        data = _make_tiff_ifd('>', 274, 3, 8)
        assert _read_tiff_tag(data, 274) == 8

    def test_reads_long(self):
        data = _make_tiff_ifd('<', 36867, 4, 12345)
        assert _read_tiff_tag(data, 36867) == 12345

    def test_returns_none_for_missing_tag(self):
        data = _make_tiff_ifd('<', 274, 3, 6)
        assert _read_tiff_tag(data, 999) is None

    def test_returns_none_for_empty_data(self):
        assert _read_tiff_tag(b'', 274) is None


# ── Flask app integration tests ───────────────────────────────────────────────

class TestFlaskApp:
    @pytest.fixture()
    def client(self):
        from fastculler.web import create_app
        app = create_app()
        app.config["TESTING"] = True
        with app.test_client() as c:
            yield c

    def test_index_returns_200(self, client):
        resp = client.get('/')
        assert resp.status_code == 200
        assert b'FastCuller' in resp.data

    def test_state_returns_waiting_without_session(self, client):
        resp = client.get('/api/state')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['status'] == 'waiting'

    def test_start_with_nonexistent_path(self, client):
        resp = client.post('/api/start',
                           json={'path': '/nonexistent/path/that/does/not/exist'})
        assert resp.status_code == 400
        data = resp.get_json()
        assert 'error' in data

    def test_start_with_real_folder_produces_ready_state(self, tmp_path, monkeypatch):
        """End-to-end: /api/start with a folder of fake CR3 files reaches status=ready
        and the session files are Path objects (not strings)."""
        import time
        from fastculler.web import create_app
        from fastculler import main as main_mod

        # Create fake CR3 files
        for i in range(3):
            (tmp_path / f"photo_{i:03d}.cr3").touch()

        # Stub out the heavy operations so the test stays fast
        monkeypatch.setattr(main_mod, 'get_capture_time', lambda p: f'2024:01:01 00:00:0{p.stem[-1]}')
        monkeypatch.setattr('fastculler.web.get_preview_jpeg', lambda p, **kw: b'\xff\xd8\xff' + b'\x00' * 10)
        monkeypatch.setattr('fastculler.web.get_thumbnail_jpeg', lambda p, **kw: b'\xff\xd8\xff' + b'\x00' * 5)
        monkeypatch.setattr('fastculler.web.get_exif_info', lambda p: {})

        app = create_app()
        app.config["TESTING"] = True
        with app.test_client() as c:
            resp = c.post('/api/start', json={'path': str(tmp_path)})
            assert resp.status_code == 200

            # Poll until the background thread finishes (max 5 s)
            deadline = time.monotonic() + 5
            state = None
            while time.monotonic() < deadline:
                r = c.get('/api/state').get_json()
                if r['status'] == 'ready':
                    state = r
                    break
                if r['status'] == 'error':
                    pytest.fail(f"Session startup error: {r.get('message')}")
                time.sleep(0.05)

            assert state is not None, "Session never reached status=ready"
            assert state['total'] == 3
            assert len(state['ratings']) == 3
            # filename comes from path.name — would be empty/wrong if files were strings
            assert state['filename'].endswith('.cr3')
            assert isinstance(state['current_idx'], int)

    def test_start_sorts_by_xmp_capture_time_over_mtime(self, tmp_path):
        """A photo whose file mtime is out of order (e.g. reset during transfer)
        should still sort correctly if its XMP sidecar has a capture date."""
        import time
        from fastculler.main import write_xmp_capture_time
        from fastculler.web import create_app

        # Touched in reverse capture order, so mtime alone would sort them wrong.
        first = tmp_path / "IMG_0002.cr3"
        second = tmp_path / "IMG_0001.cr3"
        first.touch()
        second.touch()

        write_xmp_capture_time(first, '2024:01:01 00:00:01')
        write_xmp_capture_time(second, '2024:01:01 00:00:02')

        app = create_app()
        app.config["TESTING"] = True
        with app.test_client() as c:
            resp = c.post('/api/start', json={'path': str(tmp_path)})
            assert resp.status_code == 200

            deadline = time.monotonic() + 5
            state = None
            while time.monotonic() < deadline:
                r = c.get('/api/state').get_json()
                if r['status'] == 'ready':
                    state = r
                    break
                if r['status'] == 'error':
                    pytest.fail(f"Session startup error: {r.get('message')}")
                time.sleep(0.05)

            assert state is not None, "Session never reached status=ready"
            assert state['filename'] == 'IMG_0002.cr3'

    def test_navigate_without_session(self, client):
        resp = client.post('/api/navigate', json={'idx': 0})
        assert resp.status_code == 400

    def test_rate_without_session(self, client):
        resp = client.post('/api/rate', json={'idx': 0, 'rating': 1, 'advance': False})
        assert resp.status_code == 400

    def test_image_without_session(self, client):
        resp = client.get('/api/image/0')
        assert resp.status_code == 404

    def test_thumbnail_without_session(self, client):
        resp = client.get('/api/thumbnail/0')
        assert resp.status_code == 404

    def test_copy_without_session(self, client):
        resp = client.post('/api/copy', json={'rating': 1, 'destination': '/tmp'})
        assert resp.status_code == 400

    def test_copy_preserves_subfolder_structure(self, tmp_path, monkeypatch):
        """Camera folders (100CANON, 101CANON, ...) reset file numbering per
        folder, so two source subfolders can share a filename. Copy must mirror
        the subfolder layout into the destination rather than flattening — a
        flattened copy would silently skip the second file as 'already exists'."""
        import json
        import time
        from fastculler.web import create_app
        from fastculler import main as main_mod

        src_root = tmp_path / "src"
        dest = tmp_path / "dest"
        (src_root / "100CANON").mkdir(parents=True)
        (src_root / "101CANON").mkdir(parents=True)
        dest.mkdir()

        f1 = src_root / "100CANON" / "IMG_0001.CR3"
        f2 = src_root / "101CANON" / "IMG_0001.CR3"
        f1.touch()
        f2.touch()

        monkeypatch.setattr(main_mod, 'get_capture_time',
                             lambda p: '2024:01:01 00:00:01' if '100CANON' in str(p) else '2024:01:01 00:00:02')
        monkeypatch.setattr('fastculler.web.get_preview_jpeg', lambda p, **kw: b'\xff\xd8\xff' + b'\x00' * 10)
        monkeypatch.setattr('fastculler.web.get_thumbnail_jpeg', lambda p, **kw: b'\xff\xd8\xff' + b'\x00' * 5)
        monkeypatch.setattr('fastculler.web.get_exif_info', lambda p: {})

        app = create_app()
        app.config["TESTING"] = True
        with app.test_client() as c:
            resp = c.post('/api/start', json={'path': str(src_root)})
            assert resp.status_code == 200

            deadline = time.monotonic() + 5
            state = None
            while time.monotonic() < deadline:
                r = c.get('/api/state').get_json()
                if r['status'] == 'ready':
                    state = r
                    break
                if r['status'] == 'error':
                    pytest.fail(f"Session startup error: {r.get('message')}")
                time.sleep(0.05)
            assert state is not None
            assert state['total'] == 2

            resp = c.post('/api/copy', json={'rating': -1, 'destination': str(dest)})
            assert resp.status_code == 200
            lines = [line for line in resp.data.decode().splitlines() if line]
            final = json.loads(lines[-1])
            assert final['copied'] == 2
            assert final['skipped'] == 0

        assert (dest / "100CANON" / "IMG_0001.CR3").exists()
        assert (dest / "101CANON" / "IMG_0001.CR3").exists()

    def test_export_xmp_preserves_subfolder_structure_and_overwrites(self, tmp_path, monkeypatch):
        """Export XMP should mirror the source subfolder layout, only export
        sidecars for rated photos, and overwrite a stale destination sidecar
        with the latest rating on re-export (unlike Copy, which skips)."""
        import json
        import time
        from fastculler.web import create_app
        from fastculler import main as main_mod

        src_root = tmp_path / "src"
        dest = tmp_path / "dest"
        (src_root / "100CANON").mkdir(parents=True)
        (src_root / "101CANON").mkdir(parents=True)
        (src_root / "102CANON").mkdir(parents=True)
        dest.mkdir()

        f1 = src_root / "100CANON" / "IMG_0001.CR3"
        f2 = src_root / "101CANON" / "IMG_0001.CR3"
        f3 = src_root / "102CANON" / "IMG_0001.CR3"  # left unrated
        f1.touch()
        f2.touch()
        f3.touch()

        capture_times = {
            '100CANON': '2024:01:01 00:00:01',
            '101CANON': '2024:01:01 00:00:02',
            '102CANON': '2024:01:01 00:00:03',
        }
        monkeypatch.setattr(
            main_mod, 'get_capture_time',
            lambda p: next(t for folder, t in capture_times.items() if folder in str(p)))
        monkeypatch.setattr('fastculler.web.get_preview_jpeg', lambda p, **kw: b'\xff\xd8\xff' + b'\x00' * 10)
        monkeypatch.setattr('fastculler.web.get_thumbnail_jpeg', lambda p, **kw: b'\xff\xd8\xff' + b'\x00' * 5)
        monkeypatch.setattr('fastculler.web.get_exif_info', lambda p: {})

        app = create_app()
        app.config["TESTING"] = True
        with app.test_client() as c:
            resp = c.post('/api/start', json={'path': str(src_root)})
            assert resp.status_code == 200

            deadline = time.monotonic() + 5
            state = None
            while time.monotonic() < deadline:
                r = c.get('/api/state').get_json()
                if r['status'] == 'ready':
                    state = r
                    break
                if r['status'] == 'error':
                    pytest.fail(f"Session startup error: {r.get('message')}")
                time.sleep(0.05)
            assert state is not None
            assert state['total'] == 3

            # Rate the first two photos (sorted by capture time: f1, f2, f3);
            # leave f3 unrated so it has no sidecar to export.
            resp = c.post('/api/rate', json={'idx': 0, 'rating': 3, 'advance': False})
            assert resp.status_code == 200
            resp = c.post('/api/rate', json={'idx': 1, 'rating': 1, 'advance': False})
            assert resp.status_code == 200

            resp = c.post('/api/export-xmp', json={'destination': str(dest)})
            assert resp.status_code == 200
            lines = [line for line in resp.data.decode().splitlines() if line]
            final = json.loads(lines[-1])
            assert final['exported'] == 2
            assert final['missing'] == 1

            dst1 = dest / "100CANON" / "IMG_0001.xmp"
            dst2 = dest / "101CANON" / "IMG_0001.xmp"
            assert dst1.exists()
            assert dst2.exists()
            assert not (dest / "102CANON" / "IMG_0001.xmp").exists()
            assert '<xmp:Rating>3</xmp:Rating>' in dst1.read_text()

            # Re-rate the first photo and re-export: the destination sidecar
            # should be overwritten with the new rating, not skipped.
            resp = c.post('/api/rate', json={'idx': 0, 'rating': 5, 'advance': False})
            assert resp.status_code == 200

            resp = c.post('/api/export-xmp', json={'destination': str(dest)})
            assert resp.status_code == 200
            lines = [line for line in resp.data.decode().splitlines() if line]
            final = json.loads(lines[-1])
            assert final['exported'] == 2

            assert '<xmp:Rating>5</xmp:Rating>' in dst1.read_text()

    def test_export_xmp_without_session(self, client):
        resp = client.post('/api/export-xmp', json={'destination': '/tmp'})
        assert resp.status_code == 400


# ── CullerState unit tests ────────────────────────────────────────────────────

class TestCullerState:
    @pytest.fixture()
    def state_with_mock_files(self, tmp_path, monkeypatch):
        """CullerState with 5 synthetic CR3 files (no real CR3 needed)."""
        from fastculler.web import CullerState

        files = []
        for i in range(5):
            p = tmp_path / f"photo_{i:03d}.cr3"
            p.touch()
            files.append(p)

        # Patch image functions so we don't need libraw
        monkeypatch.setattr('fastculler.web.get_preview_jpeg', lambda p, **kw: b'\xff\xd8\xff' + b'\x00' * 10)
        monkeypatch.setattr('fastculler.web.get_thumbnail_jpeg', lambda p, **kw: b'\xff\xd8\xff' + b'\x00' * 5)
        monkeypatch.setattr('fastculler.web.get_exif_info', lambda p: {})

        state = CullerState(files, tmp_path)
        return state

    def test_initial_idx_is_zero(self, state_with_mock_files):
        assert state_with_mock_files.current_idx == 0

    def test_navigate_changes_idx(self, state_with_mock_files):
        state = state_with_mock_files
        state.navigate(3)
        assert state.current_idx == 3

    def test_navigate_out_of_bounds_returns_false(self, state_with_mock_files):
        state = state_with_mock_files
        assert not state.navigate(10)
        assert not state.navigate(-1)

    def test_rate_and_advance(self, state_with_mock_files, tmp_path):
        state = state_with_mock_files
        new_idx, err = state.rate_and_advance(0, 1)
        assert err == ''
        assert new_idx == 1
        assert state.current_idx == 1
        assert state.ratings[state.files[0]] == 1
        # XMP sidecar created
        xmp = state.files[0].with_suffix('.xmp')
        assert xmp.exists()

    def test_rate_only_does_not_advance(self, state_with_mock_files):
        state = state_with_mock_files
        err = state.rate_only(2, 1)
        assert err == ''
        assert state.current_idx == 0
        assert state.ratings[state.files[2]] == 1

    def test_next_with_rating(self, state_with_mock_files):
        state = state_with_mock_files
        # Rate photos 2 and 4 as 1 star
        state.ratings[state.files[2]] = 1
        state.ratings[state.files[4]] = 1
        assert state._next_with_rating(1, 1, 1) == 2   # next 1-star from idx 1
        assert state._next_with_rating(2, 1, 1) == 4   # next 1-star from idx 2
        assert state._next_with_rating(4, 1, 1) == -1  # none beyond idx 4
        assert state._next_with_rating(3, 1, -1) == 2  # prev 1-star from idx 3

    def test_get_state_shape(self, state_with_mock_files):
        state = state_with_mock_files
        s = state.get_state()
        assert s['status'] == 'ready'
        assert s['total'] == 5
        assert len(s['ratings']) == 5
        assert 'current_idx' in s
        assert 'prefetch_ready' in s

    def test_get_image_returns_bytes(self, state_with_mock_files):
        data = state_with_mock_files.get_image(0)
        assert isinstance(data, bytes)
        assert data[:3] == b'\xff\xd8\xff'

    def test_get_thumbnail_returns_bytes(self, state_with_mock_files):
        data = state_with_mock_files.get_thumbnail(0)
        assert isinstance(data, bytes)

    def test_thumbnail_lru_eviction(self, tmp_path, monkeypatch):
        from fastculler.web import CullerState
        from fastculler import web as web_module

        files = []
        for i in range(5):
            p = tmp_path / f"photo_{i:03d}.cr3"
            p.touch()
            files.append(p)

        monkeypatch.setattr('fastculler.web.get_thumbnail_jpeg', lambda p, **kw: b'\xff\xd8\xff' + b'\x00' * 5)
        monkeypatch.setattr(web_module, 'THUMBNAIL_CACHE_MAX', 3)
        # Disable background prefetch workers so the cache starts empty and we control all insertions
        monkeypatch.setattr(CullerState, '_run_prefetch_worker', lambda self, *a: None)

        state = CullerState(files, tmp_path)
        # Access 4 thumbnails — first should be evicted
        for i in range(4):
            state.get_thumbnail(i)
        assert 0 not in state._thumb_cache
        assert 3 in state._thumb_cache

    def test_thumbnail_disk_cache_persists_across_instances(self, tmp_path, monkeypatch):
        """A thumbnail generated by one CullerState should be servable by a fresh
        instance (e.g. after an app restart) without re-decoding the CR3."""
        from fastculler.web import CullerState

        p = tmp_path / "photo_000.cr3"
        p.touch()

        call_count = {'n': 0}

        def fake_get_thumbnail_jpeg(path, **kw):
            call_count['n'] += 1
            return b'\xff\xd8\xff' + b'\x00' * 5

        monkeypatch.setattr('fastculler.web.get_thumbnail_jpeg', fake_get_thumbnail_jpeg)
        monkeypatch.setattr(CullerState, '_run_prefetch_worker', lambda self, *a: None)

        state1 = CullerState([p], tmp_path)
        data1 = state1.get_thumbnail(0)
        assert call_count['n'] == 1

        # Fresh instance, same file — should hit the on-disk cache, not re-decode
        state2 = CullerState([p], tmp_path)
        data2 = state2.get_thumbnail(0)
        assert call_count['n'] == 1
        assert data2 == data1

    def test_image_cache_lru_eviction(self, tmp_path, monkeypatch):
        from fastculler.web import CullerState
        from fastculler import web as web_module

        files = []
        for i in range(5):
            p = tmp_path / f"photo_{i:03d}.cr3"
            p.touch()
            files.append(p)

        monkeypatch.setattr('fastculler.web.get_preview_jpeg', lambda p, **kw: b'\xff\xd8\xff' + b'\x00' * 10)
        monkeypatch.setattr('fastculler.web.get_exif_info', lambda p: {})
        monkeypatch.setattr(web_module, 'IMAGE_CACHE_MAX', 3)
        # Disable background prefetch workers so the cache starts empty and we control all insertions
        monkeypatch.setattr(CullerState, '_run_prefetch_worker', lambda self, *a: None)

        state = CullerState(files, tmp_path)
        for i in range(4):
            state.get_image(i)
        assert 0 not in state._image_cache
        assert 3 in state._image_cache

    def test_get_exif_returns_dict(self, state_with_mock_files):
        result = state_with_mock_files.get_exif(0)
        assert isinstance(result, dict)
