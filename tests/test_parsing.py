"""Offline tests for the page/metadata parsing. Run: python -m unittest -v"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from tdc import core as m  # noqa: E402

ITEM = {"sources": [
    {"type": "application/vnd.apple.mpegurl", "file": "x.m3u8"},
    {"type": "video/mp4", "label": "720p", "filesize": 290, "file": "720.mp4"},
    {"type": "audio/mp4", "label": "AAC Audio", "filesize": 15, "file": "a.m4a"},
    {"type": "video/mp4", "label": "1080p", "filesize": 490, "file": "1080.mp4"},
    {"label": "Passthrough", "filesize": 2118, "file": "orig"},
]}


class Parsing(unittest.TestCase):
    def test_split_artist(self):
        self.assertEqual(m.split_artist("Jungle: Tiny Desk Concert"), ("Jungle", "Tiny Desk Concert"))
        self.assertEqual(m.split_artist("Usher: Tiny Desk (Home) Concert"), ("Usher", "Tiny Desk (Home) Concert"))
        self.assertEqual(m.split_artist("Tiny Desk Concert: Mac Miller"), ("Mac Miller", "Tiny Desk Concert"))
        self.assertEqual(m.split_artist("Something else"), (None, "Something else"))

    def test_safe_filename(self):
        self.assertEqual(m.safe_filename("Jungle: Tiny Desk Concert"), "Jungle - Tiny Desk Concert")
        self.assertEqual(m.safe_filename('AC/DC "Live"?'), "ACDC Live")
        self.assertEqual(m.safe_filename(" ... "), "Tiny Desk Concert")

    def test_media_id(self):
        html = '{"embedUrl":"https:\\/\\/cdn.jwplayer.com\\/manifests\\/PlKLO4B7.m3u8"}'
        self.assertEqual(m.jw_media_id(html), "PlKLO4B7")
        self.assertIsNone(m.jw_media_id("<html></html>"))
        old = '"file":"https:\\/\\/content.jwplatform.com\\/manifests\\/CiAJyOrx.m3u8"'
        self.assertEqual(m.jw_media_id(old), "CiAJyOrx")

    def test_page_date(self):
        self.assertEqual(m.page_date('"uploadDate":"2026-11-02T05:00:00-05:00"', ""), "2026-11-02")
        self.assertEqual(m.page_date("", "https://www.npr.org/2024/03/05/x/y"), "2024-03-05")

    def test_pick_source(self):
        f = m.FORMAT_BY_KEY
        self.assertEqual(m.pick_source(ITEM, f["audio"])["file"], "orig")
        self.assertEqual(m.pick_source(ITEM, f["video"])["file"], "orig")
        self.assertEqual(m.pick_source(ITEM, f["video1080"])["file"], "1080.mp4")
        self.assertEqual(m.pick_source(ITEM, f["video720"])["file"], "720.mp4")
        no_pt = {"sources": ITEM["sources"][:-1]}
        self.assertEqual(m.pick_source(no_pt, f["video"])["file"], "1080.mp4")
        self.assertIsNone(m.pick_source({"sources": []}, f["audio"]))


if __name__ == "__main__":
    unittest.main()
