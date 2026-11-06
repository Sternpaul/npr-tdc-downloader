"""Discover all Tiny Desk concerts from NPR's archive pages.

https://www.npr.org/series/tiny-desk-concerts/archive?date=MM-DD-YYYY lists the
15 most recent concerts published on or before that date (newest first). We
page backwards with that date as a cursor. A full scan runs one cursor per
year in parallel; an update only walks back from today until it meets
concerts it already knows.
"""
from __future__ import annotations

import html as htmllib
import json
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta

from . import core

ARCHIVE = "https://www.npr.org/series/tiny-desk-concerts/archive"
FIRST_YEAR = 2008
CACHE = "catalogue.json"
SEED = "catalogue-seed.json"
MAX_PAGES_PER_YEAR = 80

_ARTICLE = re.compile(r'<article class="item[^"]*">(.*?)</article>', re.S)
_TITLE = re.compile(r'<h2 class="title">\s*<a href="([^"]+)"[^>]*>(.*?)</a>', re.S)
_DATE = re.compile(r'<time datetime="(\d{4}-\d{2}-\d{2})')
_TEASER = re.compile(r'<p class="teaser">(.*?)</p>', re.S)
_TAG = re.compile(r"<[^>]+>")


def _text(s):
    return re.sub(r"\s+", " ", htmllib.unescape(_TAG.sub("", s))).strip()


def parse_archive(html):
    """Return [{url, artist, date, teaser}] for every concert on an archive page."""
    items = []
    for art in _ARTICLE.findall(html):
        t, d = _TITLE.search(art), _DATE.search(art)
        if not t or not d:
            continue
        teaser = ""
        m = _TEASER.search(art)
        if m:
            teaser = _text(re.sub(r"<time.*?</time>", "", m.group(1), flags=re.S))
        items.append({"url": t.group(1).strip(), "artist": _text(t.group(2)),
                      "date": d.group(1), "teaser": teaser})
    return items


def fetch_page(cursor: date):
    return parse_archive(core.fetch(f"{ARCHIVE}?date={cursor:%m-%d-%Y}", timeout=30))


def crawl_year(year, today, get=fetch_page):
    """All concerts published in `year`, walking backwards from Dec 31 (or today)."""
    cursor = min(date(year, 12, 31), today)
    found = {}
    for _ in range(MAX_PAGES_PER_YEAR):
        items = get(cursor)
        if not items:
            break
        new = 0
        for it in items:
            if it["date"].startswith(str(year)) and it["url"] not in found:
                found[it["url"]] = it
                new += 1
        oldest = min(date.fromisoformat(i["date"]) for i in items)
        if oldest.year < year:
            break
        # same day again if it brought something new (a day may span pages), else step back
        cursor = oldest if new else oldest - timedelta(days=1)
    return found


def full_scan(progress=lambda msg: None, today=None, get=fetch_page, workers=6):
    today = today or date.today()
    years = list(range(today.year, FIRST_YEAR - 1, -1))
    found, done = {}, 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(crawl_year, y, today, get): y for y in years}
        for fut in as_completed(futures):
            found.update(fut.result())
            done += 1
            progress(f"Reading NPR's archive … {done} of {len(years)} years, {len(found)} concerts")
    return found


def update_scan(known, today=None, get=fetch_page, max_pages=30):
    """New concerts since the last scan (stops at the first page with nothing new)."""
    cursor = today or date.today()
    new = {}
    for _ in range(max_pages):
        items = get(cursor)
        fresh = [i for i in items if i["url"] not in known and i["url"] not in new]
        for it in fresh:
            new[it["url"]] = it
        if not fresh:
            break
        cursor = min(date.fromisoformat(i["date"]) for i in items)
    return new


def sort_items(items):
    return sorted(items, key=lambda i: (i["date"], i["artist"].lower()), reverse=True)


class Catalogue:
    def __init__(self):
        data = core.load_json(CACHE, {})
        if not data.get("items"):  # first start: use the snapshot bundled with the exe
            try:
                with open(os.path.join(core.BUNDLE_DIR, SEED), encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                data = {}
        self.items = data.get("items", [])
        self.updated = data.get("updated")
        self.complete = data.get("complete", False)

    def age_hours(self):
        try:
            return (datetime.now() - datetime.fromisoformat(self.updated)).total_seconds() / 3600
        except (TypeError, ValueError):
            return None

    def refresh(self, progress=lambda msg: None):
        """Full scan the first time, afterwards only fetch new concerts. Returns # new."""
        known = {i["url"]: i for i in self.items}
        if self.complete and known:
            progress("Checking for new concerts …")
            new = update_scan(known)
        else:
            new = {u: i for u, i in full_scan(progress).items() if u not in known}
            self.complete = True
        known.update(new)
        self.items = sort_items(known.values())
        self.updated = datetime.now().isoformat(timespec="seconds")
        core.save_json(CACHE, self.as_dict())
        return len(new)

    def as_dict(self):
        return {"updated": self.updated, "complete": self.complete, "items": self.items}


def write_seed(path, progress=print):
    """Full scan into a JSON file that build.py bundles into the exe."""
    items = sort_items(full_scan(progress).values())
    data = {"updated": datetime.now().isoformat(timespec="seconds"), "complete": True, "items": items}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    return len(items)
