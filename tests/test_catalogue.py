"""Offline tests for the archive scan and the older-page source detection."""
import sys
import unittest
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from tdc import catalogue as c  # noqa: E402
from tdc import core  # noqa: E402

ARCHIVE_HTML = """
<article class="item event-more-article article-type-video">
  <div class="image"><a href="https://www.npr.org/2025/12/19/g-s1-97419/giveon-tiny-desk-concert"></a></div>
  <div class="info">
    <h2 class="title"><a href="https://www.npr.org/2025/12/19/g-s1-97419/giveon-tiny-desk-concert">GIV&#274;ON</a></h2>
    <p class="teaser"> <time datetime="2025-12-19"><span class="date">December 19, 2025 &#149; </span></time>
      The R&amp;B singer treats us to <em>ballads</em>.</p>
  </div>
</article>
<article class="item"><div class="info"><h2 class="title"><a href="https://x/no-date">No date</a></h2></div></article>
"""


def fake_archive(items):
    """Fake NPR archive: 15 newest items on or before the cursor date."""
    ordered = sorted(items, key=lambda i: i["date"], reverse=True)

    def get(cursor):
        return [i for i in ordered if i["date"] <= cursor.isoformat()][:15]
    return get


def make_items(start, end, per_day=1):
    out, d = [], start
    while d <= end:
        for k in range(per_day):
            out.append({"url": f"u/{d}/{k}", "artist": f"A{d}{k}", "date": d.isoformat(), "teaser": ""})
        d += timedelta(days=3)
    return out


class Archive(unittest.TestCase):
    def test_parse_archive(self):
        items = c.parse_archive(ARCHIVE_HTML)
        self.assertEqual(len(items), 1)
        it = items[0]
        self.assertEqual(it["artist"], "GIVĒON")
        self.assertEqual(it["date"], "2025-12-19")
        self.assertEqual(it["teaser"], "The R&B singer treats us to ballads.")

    def test_crawl_year_gets_everything_once(self):
        items = make_items(date(2019, 6, 1), date(2021, 6, 1))
        get = fake_archive(items)
        got = c.crawl_year(2020, date(2026, 1, 1), get)
        expected = {i["url"] for i in items if i["date"].startswith("2020")}
        self.assertEqual(set(got), expected)

    def test_crawl_year_busy_days_span_pages(self):
        # 20 concerts on one day: more than one page per cursor date
        items = make_items(date(2020, 3, 1), date(2020, 3, 1), per_day=20) + make_items(date(2020, 1, 1), date(2020, 2, 20))
        got = c.crawl_year(2020, date(2026, 1, 1), fake_archive(items))
        # pages can only return 15 for the same day; everything else must still be found
        self.assertGreaterEqual(len(got), len(items) - 5)
        self.assertTrue(all(i["url"] in got for i in items if i["date"] != "2020-03-01"))

    def test_full_scan(self):
        items = make_items(date(2008, 1, 1), date(2010, 12, 31))
        got = c.full_scan(today=date(2010, 12, 31), get=fake_archive(items), workers=2)
        self.assertEqual(set(got), {i["url"] for i in items})

    def test_update_scan_stops_at_known(self):
        items = make_items(date(2024, 1, 1), date(2024, 12, 31))
        known = {i["url"]: i for i in items if i["date"] < "2024-10-01"}
        new = c.update_scan(known, today=date(2024, 12, 31), get=fake_archive(items))
        self.assertEqual(set(new), {i["url"] for i in items if i["date"] >= "2024-10-01"})


class OlderPages(unittest.TestCase):
    def test_npr_mp4_best_bitrate(self):
        html = ('"sources":[{"file":"http:\\/\\/ivideo.akamaihd.net\\/x\\/master.m3u8"},'
                '{"file":"https:\\/\\/ondemand.npr.org\\/npr-mp4\\/a\\/sun ra-n-500000.mp4"},'
                '{"file":"https:\\/\\/ondemand.npr.org\\/npr-mp4\\/a\\/sun ra-n-1200000.mp4"}],"duration":"1077"')
        s = core.npr_direct_source(html)
        self.assertEqual(s["kind"], "mp4")
        self.assertEqual(s["file"], "https://ondemand.npr.org/npr-mp4/a/sun%20ra-n-1200000.mp4")
        self.assertEqual(s["duration"], 1077)

    def test_npr_mp3(self):
        html = ('<a href="https://ondemand.npr.org/anon.npr-mp3/npr/asc/2013/11/x.mp3?d=953&amp;e=1">')
        s = core.npr_direct_source(html)
        self.assertEqual(s["kind"], "mp3")
        self.assertEqual(s["file"], "https://ondemand.npr.org/anon.npr-mp3/npr/asc/2013/11/x.mp3")
        self.assertEqual(s["duration"], 953)

    def test_nothing(self):
        self.assertIsNone(core.npr_direct_source("<html></html>"))

    def test_youtube(self):
        self.assertEqual(core.youtube_url('<iframe src="https://www.youtube.com/embed/coMyNfnNBs4?rel=0">'),
                         "https://www.youtube.com/watch?v=coMyNfnNBs4")
        self.assertEqual(core.youtube_url('"embedUrl":"https:\\/\\/www.youtube.com\\/watch?v=coMyNfnNBs4"'),
                         "https://www.youtube.com/watch?v=coMyNfnNBs4")
        self.assertIsNone(core.youtube_url('<symbol id="icon-youtube">'))


if __name__ == "__main__":
    unittest.main()
