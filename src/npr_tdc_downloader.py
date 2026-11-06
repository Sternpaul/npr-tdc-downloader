"""NPR Tiny Desk Downloader.

Saves NPR Tiny Desk concerts as audio or video in the best quality NPR offers.

NPR pages embed a JW Player video. JW Player's media API exposes a
"Passthrough" source: the original upload (1080p H.264, ~320 kbps AAC at
48 kHz). The streams that browsers and yt-dlp use are re-encoded copies with
~112 kbps audio. This app copies the original streams without re-encoding,
then tags the file (artist, title, date, cover). Pages without a JW Player
video fall back to yt-dlp.
"""
from __future__ import annotations

import argparse
import html as htmllib
import json
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
from dataclasses import dataclass

try:
    from _version import __version__  # written by build.py
except ImportError:
    __version__ = "dev"

APP_NAME = "NPR Tiny Desk Downloader"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
FROZEN = getattr(sys, "frozen", False)
APP_DIR = os.path.dirname(sys.executable if FROZEN else os.path.abspath(__file__))
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
def fetch(url, binary=False, timeout=60):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = r.read()
    return data if binary else data.decode("utf-8", "replace")


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
    m = re.search(r"cdn\.jwplayer\.com\\?/(?:manifests|v2/media|players)\\?/([A-Za-z0-9]{8})", html)
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
        if not path.lower().endswith((".m4a", ".mp4")):
            from mutagen import File
            f = File(path, easy=True)
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

    def run(self):
        self.log("Reading the NPR page …")
        html = fetch(self.url)
        mid = jw_media_id(html)
        if not mid:
            self.log("No NPR video player on this page – trying the fallback (yt-dlp) …")
            return self.run_ytdlp(html)

        item = jw_item(mid)
        src = pick_source(item, self.fmt)
        if not src:
            raise RuntimeError("NPR offers no downloadable file for this concert.")
        full_title = page_title(html) or item.get("title") or mid
        try:
            meta = collect_meta(html, self.url, full_title, item)
        except Exception as e:
            meta = None
            self.log(f"Note: could not read concert details ({e}).")

        duration = float(item.get("duration") or 0)
        out = os.path.join(self.out_dir, safe_filename(full_title) + self.fmt.suffix + self.fmt.ext)
        if os.path.exists(out):
            self.log(f"Already downloaded:\n  {out}")
            self.progress(100, None)
            return out

        size = src.get("filesize") or 0
        need = size if self.fmt.video else size * 0.05
        free = shutil.disk_usage(self.out_dir).free
        if need and free < need * 1.1:
            raise RuntimeError(f"Not enough disk space: about {need / 1e9:.1f} GB needed, "
                               f"{free / 1e9:.1f} GB free.")

        label = src.get("label") or "best"
        self.log(f"Concert:  {full_title}")
        self.log(f"Length:   {int(duration // 60)}:{int(duration % 60):02d} min")
        self.log(f"Source:   {'original upload' if label == 'Passthrough' else label}"
                 + (f", {size / 1e9:.2f} GB" if size else ""))
        if not self.fmt.video and label == "Passthrough":
            self.log("The whole original file is streamed to extract its audio – "
                     "this takes a few minutes.")

        tmp = out + ".part" + self.fmt.ext
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
        maps = ["-map", "0:v:0", "-map", "0:a:0?"] if self.fmt.video else ["-map", "0:a:0", "-vn"]
        cmd = [FFMPEG, "-hide_banner", "-loglevel", "error", "-nostats", "-y",
               "-progress", "pipe:1",
               # resume (HTTP range request) when the server drops the connection
               "-reconnect", "1", "-reconnect_streamed", "1",
               "-reconnect_on_network_error", "1", "-reconnect_delay_max", "30",
               "-rw_timeout", "60000000",
               "-i", url, *maps, "-c", "copy", "-movflags", "+faststart", tmp]
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

    def run_ytdlp(self, html):
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
            "outtmpl": os.path.join(self.out_dir, "%(title)s.%(ext)s"),
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
                info = ydl.extract_info(self.url, download=True)
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


# ======================================================================= GUI
def windows_dark_mode():
    try:
        import winreg
        k = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                           r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize")
        return winreg.QueryValueEx(k, "AppsUseLightTheme")[0] == 0
    except Exception:
        return False


def fmt_eta(sec):
    if sec is None:
        return ""
    sec = int(sec)
    return f"{sec // 60}:{sec % 60:02d} min left" if sec >= 60 else f"{sec} s left"


class App:
    def __init__(self, root, url=None, fmt_key=None, autostart=False):
        import tkinter as tk
        from tkinter import ttk, scrolledtext

        self.tk, self.ttk = tk, ttk
        self.root = root
        self.q = queue.Queue()
        self.job = None
        self.settings = load_settings()
        dark = windows_dark_mode()

        root.title(APP_NAME)
        root.geometry("760x560")
        root.minsize(620, 460)
        try:
            root.iconbitmap(default=os.path.join(BUNDLE_DIR, "icon.ico"))
        except Exception:
            pass
        try:
            import sv_ttk
            sv_ttk.set_theme("dark" if dark else "light")
        except Exception:
            pass
        if dark:
            self._dark_titlebar()

        style = ttk.Style()
        style.configure("Title.TLabel", font=("Segoe UI Semibold", 18))
        style.configure("Sub.TLabel", font=("Segoe UI", 10), foreground="#888888")
        style.configure("Field.TLabel", font=("Segoe UI Semibold", 10))
        style.configure("Status.TLabel", font=("Segoe UI", 10))

        outer = ttk.Frame(root, padding=(24, 20, 24, 20))
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(1, weight=1)

        ttk.Label(outer, text="Tiny Desk Downloader", style="Title.TLabel").grid(
            row=0, column=0, columnspan=3, sticky="w")
        ttk.Label(outer, text="Save NPR Tiny Desk concerts in the best quality NPR offers.",
                  style="Sub.TLabel").grid(row=1, column=0, columnspan=3, sticky="w", pady=(0, 18))

        # link
        ttk.Label(outer, text="Concert link", style="Field.TLabel").grid(row=2, column=0, sticky="w", padx=(0, 12))
        self.url = tk.StringVar(value=url or "")
        self.entry = ttk.Entry(outer, textvariable=self.url, font=("Segoe UI", 11))
        self.entry.grid(row=2, column=1, sticky="ew", ipady=2)
        ttk.Button(outer, text="Paste", command=self.paste).grid(row=2, column=2, padx=(8, 0), sticky="ew")

        # format
        ttk.Label(outer, text="Format", style="Field.TLabel").grid(row=3, column=0, sticky="w", pady=(12, 0))
        start_fmt = FORMAT_BY_KEY.get(fmt_key or self.settings.get("format"), FORMATS[0])
        self.fmt = tk.StringVar(value=start_fmt.label)
        self.fmt_box = ttk.Combobox(outer, textvariable=self.fmt, state="readonly",
                                    values=[f.label for f in FORMATS], font=("Segoe UI", 10))
        self.fmt_box.grid(row=3, column=1, columnspan=2, sticky="ew", pady=(12, 0))
        self.fmt_box.bind("<<ComboboxSelected>>", lambda e: self._remember())

        # folder
        ttk.Label(outer, text="Save to", style="Field.TLabel").grid(row=4, column=0, sticky="w", pady=(12, 0))
        out_dir = self.settings.get("out_dir")
        self.out_dir = tk.StringVar(value=out_dir if out_dir and os.path.isdir(out_dir) else APP_DIR)
        ttk.Entry(outer, textvariable=self.out_dir, state="readonly", font=("Segoe UI", 10)).grid(
            row=4, column=1, sticky="ew", pady=(12, 0))
        fbtns = ttk.Frame(outer)
        fbtns.grid(row=4, column=2, padx=(8, 0), pady=(12, 0))
        ttk.Button(fbtns, text="Change…", command=self.choose_folder).pack(side="left")
        ttk.Button(fbtns, text="Open", command=self.open_folder).pack(side="left", padx=(6, 0))

        # actions
        actions = ttk.Frame(outer)
        actions.grid(row=5, column=0, columnspan=3, sticky="ew", pady=(20, 8))
        self.btn = ttk.Button(actions, text="Download", style="Accent.TButton", command=self.start, width=16)
        self.btn.pack(side="left")
        self.cancel_btn = ttk.Button(actions, text="Cancel", command=self.cancel, state="disabled")
        self.cancel_btn.pack(side="left", padx=8)
        self.status = tk.StringVar(value="Ready")
        ttk.Label(actions, textvariable=self.status, style="Status.TLabel").pack(side="right")

        self.bar = ttk.Progressbar(outer, maximum=100)
        self.bar.grid(row=6, column=0, columnspan=3, sticky="ew", pady=(0, 14))

        # log
        ttk.Label(outer, text="Details", style="Field.TLabel").grid(row=7, column=0, sticky="w")
        outer.rowconfigure(8, weight=1)
        self.logbox = scrolledtext.ScrolledText(outer, height=8, font=("Consolas", 9), state="disabled",
                                                wrap="word", relief="flat", borderwidth=0,
                                                padx=10, pady=8)
        if dark:
            self.logbox.configure(bg="#1c1c1c", fg="#e0e0e0", insertbackground="#e0e0e0")
        else:
            self.logbox.configure(bg="#f7f7f7", fg="#202020")
        self.logbox.grid(row=8, column=0, columnspan=3, sticky="nsew", pady=(6, 0))
        ttk.Label(outer, text=f"v{__version__}", style="Sub.TLabel").grid(row=9, column=2, sticky="e", pady=(8, 0))

        self.entry.bind("<Return>", lambda e: self.start())
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.after(100, self.poll)
        self.entry.focus_set()
        if not url:
            self.paste(auto=True)
        if autostart and url:
            root.after(500, self.start)

    def _dark_titlebar(self):
        try:
            import ctypes
            self.root.update()
            hwnd = ctypes.windll.user32.GetParent(self.root.winfo_id())
            val = ctypes.c_int(1)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(val), ctypes.sizeof(val))
        except Exception:
            pass

    # ---------- thread-safe bridge
    def log(self, msg):
        self.q.put(("log", msg))

    def set_progress(self, pct, eta):
        self.q.put(("pct", (pct, eta)))

    def poll(self):
        try:
            while True:
                kind, val = self.q.get_nowait()
                if kind == "log":
                    self.logbox.configure(state="normal")
                    self.logbox.insert("end", val + "\n")
                    self.logbox.see("end")
                    self.logbox.configure(state="disabled")
                elif kind == "pct":
                    pct, eta = val
                    self.bar["value"] = pct
                    if self.job:
                        self.status.set(f"{pct:.0f} %" + (f"  ·  {fmt_eta(eta)}" if eta else ""))
                elif kind == "done":
                    self.finish(*val)
        except queue.Empty:
            pass
        self.root.after(100, self.poll)

    # ---------- actions
    def current_format(self):
        return next((f for f in FORMATS if f.label == self.fmt.get()), FORMATS[0])

    def _remember(self):
        self.settings["format"] = self.current_format().key
        save_settings(self.settings)

    def paste(self, auto=False):
        try:
            clip = self.root.clipboard_get().strip()
        except self.tk.TclError:
            return
        if not auto or re.match(r"https?://(www\.)?npr\.org/", clip):
            self.url.set(clip)

    def choose_folder(self):
        from tkinter import filedialog
        d = filedialog.askdirectory(initialdir=self.out_dir.get(), title="Save downloads to")
        if d:
            self.out_dir.set(os.path.normpath(d))
            self.settings["out_dir"] = self.out_dir.get()
            save_settings(self.settings)

    def open_folder(self):
        os.startfile(self.out_dir.get())

    def start(self):
        if self.job:
            return
        url = self.url.get().strip()
        if not re.match(r"https?://", url):
            self.status.set("Paste a link first")
            self.log("Please paste the link of a Tiny Desk concert page (https://www.npr.org/…).")
            return
        self.bar["value"] = 0
        self.btn.configure(state="disabled")
        self.cancel_btn.configure(state="normal")
        self.fmt_box.configure(state="disabled")
        self.status.set("Starting …")
        self.logbox.configure(state="normal")
        self.logbox.delete("1.0", "end")
        self.logbox.configure(state="disabled")
        self.job = Job(url, self.current_format(), self.out_dir.get(), self.log, self.set_progress)
        threading.Thread(target=self.worker, args=(self.job,), daemon=True).start()

    def worker(self, job):
        try:
            path = job.run()
            self.log(f"\nDone. Saved as:\n  {path}")
            self.q.put(("done", ("Done", True)))
        except Cancelled:
            self.log("\nCancelled.")
            self.q.put(("done", ("Cancelled", False)))
        except Exception as e:
            self.log(f"\nSomething went wrong:\n  {e}")
            self.q.put(("done", ("Failed – see details", False)))

    def finish(self, status, ok):
        self.job = None
        self.status.set(status)
        if not ok:
            self.bar["value"] = 0
        self.btn.configure(state="normal")
        self.cancel_btn.configure(state="disabled")
        self.fmt_box.configure(state="readonly")

    def cancel(self):
        if self.job:
            self.status.set("Cancelling …")
            self.job.cancel()

    def close(self):
        if self.job:
            self.job.cancel()
        self.root.destroy()


def main():
    ap = argparse.ArgumentParser(prog="npr-tdc-downloader", description=APP_NAME)
    ap.add_argument("url", nargs="?", help="Tiny Desk concert page; starts the download right away")
    ap.add_argument("--format", choices=list(FORMAT_BY_KEY), help="audio (default), video, video1080, video720")
    try:
        a, _ = ap.parse_known_args()
    except SystemExit:  # bad arguments: just open the window normally
        a = argparse.Namespace(url=None, format=None)

    if os.name == "nt":
        try:  # crisp text on high-DPI screens
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Sternpaul.NprTdcDownloader")
        except Exception:
            pass
    import tkinter as tk
    root = tk.Tk()
    App(root, url=a.url, fmt_key=a.format, autostart=bool(a.url))
    root.mainloop()


if __name__ == "__main__":
    main()
