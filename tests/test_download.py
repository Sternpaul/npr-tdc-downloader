"""Offline tests for the download loop (network and ffmpeg are faked)."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import npr_tdc_downloader as m  # noqa: E402

HTML = ('<meta property="og:title" content="Jungle: Tiny Desk Concert">'
        '"embedUrl":"https:\\/\\/cdn.jwplayer.com\\/manifests\\/PlKLO4B7.m3u8"')
ITEM = {"title": "Jungle TDC", "duration": 1092.5, "images": [],
        "sources": [{"label": "Passthrough", "filesize": 1000, "file": "orig"}]}


class FakeFfmpeg:
    """Each call 'writes' the temp file and returns the next (rc, seconds) result."""

    def __init__(self, results):
        self.results = list(results)
        self.calls = 0

    def __call__(self, url, tmp, duration):
        self.calls += 1
        Path(tmp).write_bytes(b"x")
        rc, got = self.results.pop(0)
        return rc, got, ""


class DownloadLoop(unittest.TestCase):
    def run_job(self, results):
        fake = FakeFfmpeg(results)
        logs = []
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(m, "fetch", return_value=HTML), \
                mock.patch.object(m, "jw_item", return_value=ITEM), \
                mock.patch.object(m, "write_tags"), \
                mock.patch.object(m.Job, "_ffmpeg", fake):
            job = m.Job("https://www.npr.org/x", m.FORMAT_BY_KEY["audio"], d, logs.append,
                        lambda *a: None)
            try:
                out = job.run()
                files = sorted(p.name for p in Path(d).iterdir())
                return out, files, fake.calls, logs
            except RuntimeError as e:
                files = sorted(p.name for p in Path(d).iterdir())
                return e, files, fake.calls, logs

    def test_complete_first_try(self):
        out, files, calls, _ = self.run_job([(0, 1092.5)])
        self.assertEqual(calls, 1)
        self.assertEqual(files, ["Jungle - Tiny Desk Concert.m4a"])

    def test_truncated_then_retry_succeeds(self):
        out, files, calls, logs = self.run_job([(0, 33.8), (0, 1092.4)])
        self.assertEqual(calls, 2)
        self.assertEqual(files, ["Jungle - Tiny Desk Concert.m4a"])
        self.assertTrue(any("connection dropped" in l for l in logs))

    def test_always_truncated_fails_and_leaves_nothing(self):
        err, files, calls, _ = self.run_job([(0, 33.8)] * 3)
        self.assertIsInstance(err, RuntimeError)
        self.assertEqual(calls, 3)
        self.assertEqual(files, [])

    def test_ffmpeg_error_retries(self):
        out, files, calls, _ = self.run_job([(1, 0), (0, 1092.5)])
        self.assertEqual(calls, 2)
        self.assertEqual(files, ["Jungle - Tiny Desk Concert.m4a"])


if __name__ == "__main__":
    unittest.main()
