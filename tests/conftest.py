import pytest


@pytest.fixture(scope="session", autouse=True)
def _sandbox_thumbnail_cache(tmp_path_factory):
    """Redirect the on-disk thumbnail cache to a session-scoped tmp dir, for the
    whole test run rather than per-test.

    CullerState's background prefetch worker threads are daemons that are never
    explicitly stopped, so they can outlive the test that created them. A
    per-test monkeypatch reverts at that test's end — leaving a window where a
    leftover thread from an earlier test fires while no patch is active and
    writes into the real ~/Library/Caches/FastCuller. Patching once for the
    whole session (and never reverting — the process exits right after)
    closes that window entirely.
    """
    from fastculler import thumb_cache

    cache_dir = tmp_path_factory.mktemp("thumb_cache")

    def _fake_cache_dir():
        cache_dir.mkdir(parents=True, exist_ok=True)
        return cache_dir

    thumb_cache._cache_dir = _fake_cache_dir
