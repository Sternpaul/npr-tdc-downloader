"""Download core of NPR Tiny Desk Downloader (no GUI code).

Saves NPR Tiny Desk concerts as audio or video in the best quality NPR offers.

NPR pages embed a JW Player video. JW Player's media API exposes a
"Passthrough" source: the original upload (1080p H.264, ~320 kbps AAC at
48 kHz). The streams that browsers and yt-dlp use are re-encoded copies with
~112 kbps audio. This app copies the original streams without re-encoding,
then tags the file (artist, title, date, cover). Pages without a JW Player
video fall back to yt-dlp.
"""
from __future__ import annotations

import html as htmllib
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

try:
    from _version import __version__  # noqa: F401  (written by build.py)
except ImportError:
    __version__ = "dev"

APP_NAME = "NPR Tiny Desk Downloader"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
FROZEN = getattr(sys, "frozen", False)
APP_DIR = os.path.dirname(sys.executable) if FROZEN else os.getcwd()
BUNDLE_DIR = getattr(sys, "_MEIPASS", APP_DIR)
NO_WINDOW = 0x08000000 if os.name == "nt" else 0  # no console window for ffmpeg
ALBUM = "NPR Tiny Desk Concerts"


@dataclass(frozen=True)
class Format:
    key: str
    label: str
    video: bool
    jw_label: str | None  # JW Player source label to use (None = passthrough)
    suffix: str = ""

    @property
    def ext(self):
        return ".mp4" if self.video else ".m4a"


FORMATS = [
    Format("audio", "Audio  ·  original quality  (M4A)", False, None),
    Format("video", "Video  ·  original quality  (MP4, ~2 GB)", True, None),
    Format("video1080", "Video  ·  1080p compressed  (MP4, ~500 MB)", True, "1080p", " (1080p)"),
    Format("video720", "Video  ·  720p compressed  (MP4, ~300 MB)", True, "720p", " (720p)"),
]
FORMAT_BY_KEY = {f.key: f for f in FORMATS}


def find_ffmpeg():
    for p in (os.path.join(BUNDLE_DIR, "ffmpeg.exe"), os.path.join(APP_DIR, "ffmpeg.exe")):
        if os.path.isfile(p):
            return p
    return shutil.which("ffmpeg") or "ffmpeg"


FFMPEG = find_ffmpeg()


# ======================================================================= NPR / JW
def fetch(url, binary=False, timeout=60, tries=3):
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                data = r.read()
            return data if binary else data.decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            if e.code < 500 or attempt == tries - 1:
                raise
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            if attempt == tries - 1:
                raise
        time.sleep(1.5 * (attempt + 1))


def safe_filename(name):
    name = name.replace(":", " -")
    return re.sub(r'[<>"/\\|?*\x00-\x1f]+', "", name).strip(" .") or "Tiny Desk Concert"


def page_title(html):
    m = re.search(r'<meta[^>]+property="og:title"[^>]+content="([^"]+)"', html)
    return htmllib.unescape(m.group(1)).replace(" : NPR", "").strip() if m else None


def split_artist(full):
    """'Jungle: Tiny Desk Concert' -> ('Jungle', 'Tiny Desk Concert')."""
    m = re.match(r"^(.+?)\s*:\s*(Tiny Desk.*)$", full, re.I)
    if m:
        return m.group(1).strip(), m.group(2).strip()
    m = re.match(r"^(Tiny Desk[^:]*?)\s*:\s*(.+)$", full, re.I)
    if m:
        return m.group(2).strip(), m.group(1).strip()
    return None, full


def page_date(html, url):
    m = re.search(r'"(?:datePublished|uploadDate)"\s*:\s*"(\d{4}-\d{2}-\d{2})', html)
    if m:
        return m.group(1)
    m = re.search(r"npr\.org/(\d{4})/(\d{2})/(\d{2})/", url)
    return "-".join(m.groups()) if m else None


def jw_media_id(html):
    # cdn.jwplayer.com today, content.jwplatform.com on ~2018 pages
    m = re.search(r"(?:cdn\.jwplayer\.com|content\.jwplatform\.com)\\?/(?:manifests|v2/media|players)"
                  r"\\?/([A-Za-z0-9]{8})", html)
    return m.group(1) if m else None


def jw_item(mid):
    return json.loads(fetch(f"https://cdn.jwplayer.com/v2/media/{mid}"))["playlist"][0]


def pick_source(item, fmt: Format):
    """Return the JW source dict that best matches the requested format."""
    srcs = item.get("sources", [])
    if fmt.jw_label:
        for s in srcs:
            if s.get("label") == fmt.jw_label:
                return s
    for s in srcs:
        if s.get("label") == "Passthrough":
            return s
    mp4s = [s for s in srcs if s.get("type") == "video/mp4"]
    if not fmt.video:
        mp4s += [s for s in srcs if s.get("type") == "audio/mp4"]
    return max(mp4s, key=lambda s: s.get("filesize", 0), default=None)


def _unescape_json_url(u):
    return htmllib.unescape(u.replace("\\/", "/"))


def quote_url(u):
    return urllib.parse.quote(u, safe=":/?&=%#+,;@")


def npr_direct_source(html):
    """Media file of NPR's own (pre-JW Player) player, or None.

    Returns {"file", "label", "kind": "mp4"|"mp3", "duration"}.
    2014-2018 pages carry a 720p MP4 (often with ~320 kbps AAC); some older
    pages only have an MP3.
    """
    dur = re.search(r'"duration"\s*:\s*"?(\d+)', html)
    duration = float(dur.group(1)) if dur else 0
    files = [_unescape_json_url(f) for f in re.findall(r'"file"\s*:\s*"([^"]+)"', html)]
    mp4s = [f for f in files if re.search(r"\.mp4(\?|$)", f)]
    if mp4s:
        def rate(f):
            m = re.search(r"-n-(\d+)\.mp4", f)
            return int(m.group(1)) if m else 0
        best = max(mp4s, key=rate)
        return {"file": quote_url(best), "label": "NPR video (720p)", "kind": "mp4", "duration": duration}
    m = re.search(r'https?://ondemand\.npr\.org/[^"\'\s<>?]+\.mp3(?:\?[^"\'\s<>]*)?', html)
    if m:
        url = htmllib.unescape(m.group(0))
        d = re.search(r"[?&]d=(\d+)", url)
        return {"file": quote_url(url.split("?")[0]), "label": "NPR audio (MP3, 128 kbps)", "kind": "mp3",
                "duration": duration or (float(d.group(1)) if d else 0)}
    return None


def youtube_url(html):
    m = re.search(r"youtube(?:-nocookie)?\.com(?:\\?/embed\\?/|\\?/watch\?v=)([A-Za-z0-9_-]{11})", html)
    return f"https://www.youtube.com/watch?v={m.group(1)}" if m else None


def collect_meta(html, url, full_title, item):
    """Best effort: missing pieces are simply left out."""
    artist, title = split_artist(full_title)
    meta = {"artist": artist, "title": title, "date": page_date(html, url),
            "url": url, "cover": None}
    imgs = [i for i in (item or {}).get("images", []) if "jpeg" in i.get("type", "")]
    if imgs:
        meta["cover"] = max(imgs, key=lambda i: i.get("width", 0))["src"]
    else:
        m = re.search(r'<meta[^>]+property="og:image"[^>]+content="([^"]+)"', html)
        meta["cover"] = m.group(1) if m else None
    return meta


def write_tags(path, meta, log, video=False):
    """Tag a finished file. Never raises: problems are only logged."""
    try:
        if path.lower().endswith(".mp3"):
            _tag_mp3(path, meta, log)
            return
        if not path.lower().endswith((".m4a", ".mp4")):
            from mutagen import File
            f = File(path, easy=True)
            if f.tags is None:
                f.add_tags()
            for k in ("artist", "title", "date"):
                if meta.get(k):
                    f[k] = meta[k]
            f["album"] = ALBUM
            f.save()
            log("Tags added.")
            return
        from mutagen.mp4 import MP4, MP4Cover
        f = MP4(path)
        tags = {
            "\xa9nam": meta.get("title"), "\xa9ART": meta.get("artist"),
            "aART": meta.get("artist"), "\xa9alb": ALBUM, "\xa9day": meta.get("date"),
            "\xa9gen": "Live", "cprt": "NPR", "\xa9pub": "NPR", "\xa9cmt": meta.get("url"),
        }
        for k, v in tags.items():
            if v:
                f[k] = [v]
        if video:
            f["stik"] = [6]  # media kind: music video
        if meta.get("cover"):
            try:
                data = fetch(meta["cover"], binary=True, timeout=30)
                fmt = MP4Cover.FORMAT_PNG if data[:4] == b"\x89PNG" else MP4Cover.FORMAT_JPEG
                f["covr"] = [MP4Cover(data, imageformat=fmt)]
            except Exception as e:
                log(f"Note: cover picture could not be added ({e}).")
        f.save()
        shown = ", ".join(f"{k}: {meta[k]}" for k in ("artist", "title", "date") if meta.get(k))
        log(f"Tags added ({shown}).")
    except Exception as e:
        log(f"Note: the file is fine, but tags could not be added ({e}).")


def _tag_mp3(path, meta, log):
    from mutagen.id3 import APIC, COMM, ID3, TALB, TCON, TDRC, TIT2, TPE1, TPE2, TPUB, ID3NoHeaderError
    try:
        tags = ID3(path)
    except ID3NoHeaderError:
        tags = ID3()
    frames = [(TIT2, meta.get("title")), (TPE1, meta.get("artist")), (TPE2, meta.get("artist")),
              (TALB, ALBUM), (TDRC, meta.get("date")), (TCON, "Live"), (TPUB, "NPR")]
    for cls, v in frames:
        if v:
            tags.add(cls(encoding=3, text=v))
    if meta.get("url"):
        tags.add(COMM(encoding=3, lang="eng", desc="", text=meta["url"]))
    if meta.get("cover"):
        try:
            data = fetch(meta["cover"], binary=True, timeout=30)
            mime = "image/png" if data[:4] == b"\x89PNG" else "image/jpeg"
            tags.add(APIC(encoding=3, mime=mime, type=3, desc="Cover", data=data))
        except Exception as e:
            log(f"Note: cover picture could not be added ({e}).")
    tags.save(path)
    shown = ", ".join(f"{k}: {meta[k]}" for k in ("artist", "title", "date") if meta.get(k))
    log(f"Tags added ({shown}).")


def _remove(p):
    try:
        os.remove(p)
    except OSError:
        pass


class Cancelled(Exception):
    pass


class Job:
    """One download. Runs in a worker thread; talks to the UI via callbacks."""

    def __init__(self, url, fmt: Format, out_dir, log, progress):
        self.url, self.fmt, self.out_dir = url, fmt, out_dir
        self.log, self.progress = log, progress
        self.proc = None
        self.cancelled = False

    def cancel(self):
        self.cancelled = True
        if self.proc and self.proc.poll() is None:
            self.proc.kill()

    def resolve(self, html):
        """Best source on the page as (source dict, JW item or None); (None, None) if none."""
        mid = jw_media_id(html)
        if mid:
            item = jw_item(mid)
            s = pick_source(item, self.fmt)
            if s:
                passthrough = s.get("label") == "Passthrough"
                return {"file": s["file"], "filesize": s.get("filesize") or 0,
                        "label": "original upload" if passthrough else (s.get("label") or "best"),
                        "passthrough": passthrough, "kind": "mp4",
                        "duration": float(item.get("duration") or 0),
                        "suffix": "" if passthrough else self.fmt.suffix}, item
        s = npr_direct_source(html)
        if s:
            s.update(filesize=0, passthrough=False, suffix="")
            return s, None
        return None, None

    def run(self):
        self.log("Reading the NPR page …")
        html = fetch(self.url)
        src, item = self.resolve(html)
        if src and src["kind"] == "mp3" and self.fmt.video:
            yt = youtube_url(html)
            if yt:
                self.log("NPR only has audio for this concert – getting the video from YouTube …")
                return self.run_ytdlp(html, yt)
            raise RuntimeError("NPR only offers audio for this concert (no video). "
                               "Choose audio instead.")
        if not src:
            yt = youtube_url(html)
            self.log("No NPR player on this page – trying the fallback (yt-dlp) …")
            return self.run_ytdlp(html, yt or self.url)

        full_title = page_title(html) or (item or {}).get("title") or "Tiny Desk Concert"
        try:
            meta = collect_meta(html, self.url, full_title, item)
        except Exception as e:
            meta = None
            self.log(f"Note: could not read concert details ({e}).")

        ext = ".mp4" if self.fmt.video else (".mp3" if src["kind"] == "mp3" else ".m4a")
        duration = src["duration"]
        out = os.path.join(self.out_dir, safe_filename(full_title) + src["suffix"] + ext)
        if os.path.exists(out):
            self.log(f"Already downloaded:\n  {out}")
            self.progress(100, None)
            return out

        size = src["filesize"]
        need = size if self.fmt.video else size * 0.05
        free = shutil.disk_usage(self.out_dir).free
        if need and free < need * 1.1:
            raise RuntimeError(f"Not enough disk space: about {need / 1e9:.1f} GB needed, "
                               f"{free / 1e9:.1f} GB free.")

        self.log(f"Concert:  {full_title}")
        if duration:
            self.log(f"Length:   {int(duration // 60)}:{int(duration % 60):02d} min")
        self.log(f"Source:   {src['label']}" + (f", {size / 1e9:.2f} GB" if size else ""))
        if not self.fmt.video and src["passthrough"]:
            self.log("The whole original file is streamed to extract its audio – "
                     "this takes a few minutes.")

        tmp = out + ".part" + ext
        attempts = 3
        for attempt in range(1, attempts + 1):
            self.log("Downloading …" if attempt == 1 else f"Retrying (attempt {attempt} of {attempts}) …")
            rc, got, err = self._ffmpeg(src["file"], tmp, duration)
            if self.cancelled:
                _remove(tmp)
                raise Cancelled()
            # ffmpeg may treat a dropped connection as end of file: never trust rc alone
            complete = rc == 0 and (not duration or got >= duration - 3)
            if complete:
                break
            _remove(tmp)
            if rc != 0:
                reason = err.strip()[-500:] or f"ffmpeg exit code {rc}"
            else:
                reason = (f"connection dropped after {int(got // 60)}:{int(got % 60):02d} "
                          f"of {int(duration // 60)}:{int(duration % 60):02d}")
            self.log(f"Download incomplete: {reason}")
            if attempt == attempts:
                raise RuntimeError("The download kept getting interrupted. "
                                   "Please check the internet connection and try again.")
            self.progress(0, None)
        os.replace(tmp, out)
        self.progress(100, None)
        if meta:
            self.log("Adding artist, title, date and cover …")
            write_tags(out, meta, self.log, video=self.fmt.video)
        return out

    def _ffmpeg(self, url, tmp, duration):
        """Copy streams from url into tmp. Returns (exit code, seconds written, stderr)."""
        maps = ["-map", "0:v:0", "-map", "0:a:0"] if self.fmt.video else ["-map", "0:a:0", "-vn"]
        cmd = [FFMPEG, "-hide_banner", "-loglevel", "error", "-nostats", "-y",
               "-progress", "pipe:1",
               # resume (HTTP range request) when the server drops the connection
               "-reconnect", "1", "-reconnect_streamed", "1",
               "-reconnect_on_network_error", "1", "-reconnect_delay_max", "30",
               "-rw_timeout", "60000000",
               "-i", url, *maps, "-c", "copy",
               *(["-movflags", "+faststart"] if tmp.endswith((".m4a", ".mp4")) else []), tmp]
        self.proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                     text=True, creationflags=NO_WINDOW)
        err_lines = []
        t = threading.Thread(target=lambda: err_lines.extend(self.proc.stderr), daemon=True)
        t.start()
        start = time.monotonic()
        got = 0.0
        for line in self.proc.stdout:
            if line.startswith("out_time_us="):
                try:
                    got = max(got, int(line.split("=")[1]) / 1e6)
                except ValueError:
                    continue
                if duration:
                    pct = min(99.9, got / duration * 100)
                    elapsed = time.monotonic() - start
                    self.progress(pct, elapsed / pct * (100 - pct) if pct > 1 else None)
        rc = self.proc.wait()
        t.join(timeout=5)
        return rc, got, "".join(err_lines)

    def run_ytdlp(self, html, target=None):
        import yt_dlp

        def hook(d):
            if self.cancelled:
                raise Cancelled()
            if d.get("status") == "downloading":
                total = d.get("total_bytes") or d.get("total_bytes_estimate")
                if total:
                    self.progress(d.get("downloaded_bytes", 0) / total * 100, d.get("eta"))

        log = self.log

        class Logger:
            def debug(self, m): pass
            def info(self, m): pass
            def warning(self, m): log("Warning: " + m)
            def error(self, m): log(m)

        opts = {
            "outtmpl": os.path.join(self.out_dir, (safe_filename(page_title(html)).replace("%", "%%")
                                                   if page_title(html) else "%(title)s") + ".%(ext)s"),
            "ffmpeg_location": FFMPEG,
            "progress_hooks": [hook],
            "logger": Logger(),
            "noplaylist": True,
            "windowsfilenames": True,
        }
        if self.fmt.video:
            height = {"video1080": 1080, "video720": 720}.get(self.fmt.key)
            opts["format"] = f"bv*[height<={height}]+ba/b" if height else "bv*+ba/b"
            opts["merge_output_format"] = "mp4"
        else:
            opts["format"] = "bestaudio/best"
            opts["postprocessors"] = [{"key": "FFmpegExtractAudio", "preferredcodec": "best"}]
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(target or self.url, download=True)
        except yt_dlp.utils.DownloadError as e:
            if self.cancelled:
                raise Cancelled()
            raise RuntimeError(str(e).replace("ERROR: ", ""))
        downloads = info.get("requested_downloads") or [{}]
        path = downloads[0].get("filepath")
        self.progress(100, None)
        if path:
            try:
                meta = collect_meta(html, self.url, page_title(html) or info.get("title", ""), None)
                write_tags(path, meta, self.log, video=self.fmt.video)
            except Exception as e:
                self.log(f"Note: the file is fine, but tags could not be added ({e}).")
        return path or self.out_dir


# ======================================================================= settings
def settings_path():
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    return os.path.join(base, "NPR Tiny Desk Downloader", "settings.json")


def load_settings():
    try:
        with open(settings_path(), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_settings(data):
    try:
        os.makedirs(os.path.dirname(settings_path()), exist_ok=True)
        with open(settings_path(), "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass


def data_path(name):
    return os.path.join(os.path.dirname(settings_path()), name)


def load_json(name, default):
    try:
        with open(data_path(name), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def save_json(name, data):
    try:
        os.makedirs(os.path.dirname(data_path(name)), exist_ok=True)
        tmp = data_path(name) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
        os.replace(tmp, data_path(name))
    except Exception:
        pass


class History:
    """Remembers which concert was saved where: {url: {format_key: path}}."""

    def __init__(self):
        self.data = load_json("history.json", {})

    def add(self, url, fmt_key, path):
        self.data.setdefault(url, {})[fmt_key] = path
        save_json("history.json", self.data)

    def saved(self, url):
        """Format keys of this concert whose files still exist."""
        return {k for k, p in self.data.get(url, {}).items() if p and os.path.exists(p)}
