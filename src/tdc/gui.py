"""Tk user interface: catalogue browser, paste-a-link tab and a download queue."""
from __future__ import annotations

import os
import queue
import re
import threading
import tkinter as tk
from collections import deque
from tkinter import filedialog, scrolledtext, ttk

from . import core
from .catalogue import Catalogue
from .core import FORMAT_BY_KEY, FORMATS, APP_DIR, BUNDLE_DIR, __version__

ALL_YEARS = "All years"


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
        self.root = root
        self.q = queue.Queue()
        self.settings = core.load_settings()
        self.history = core.History()
        self.catalogue = Catalogue()
        self.pending = deque()          # (url, Format, name)
        self.job = None
        self.job_info = None
        self.batch = {"total": 0, "ok": 0, "failed": 0}
        self.cat_busy = False
        self.sort = ("date", True)
        self.dark = windows_dark_mode()

        self._setup_window()
        self._build()
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.after(100, self.poll)

        self.render_catalogue()
        # full scan if there is no list yet; otherwise a quick check for new concerts (1-2 pages)
        self.refresh_catalogue(quiet=bool(self.catalogue.items))

        if url:
            self.nb.select(self.link_tab)
            self.url.set(url)
            if fmt_key in FORMAT_BY_KEY:
                self.fmt.set(FORMAT_BY_KEY[fmt_key].label)
            if autostart:
                root.after(500, self.download_link)

    # ------------------------------------------------------------------ layout
    def _setup_window(self):
        r = self.root
        r.title(core.APP_NAME)
        r.geometry("940x760")
        r.minsize(760, 600)
        try:
            r.iconbitmap(default=os.path.join(BUNDLE_DIR, "icon.ico"))
        except Exception:
            pass
        try:
            import sv_ttk
            sv_ttk.set_theme("dark" if self.dark else "light")
        except Exception:
            pass
        if self.dark:
            try:
                import ctypes
                r.update()
                hwnd = ctypes.windll.user32.GetParent(r.winfo_id())
                v = ctypes.c_int(1)
                ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(v), ctypes.sizeof(v))
            except Exception:
                pass
        s = ttk.Style()
        s.configure("Title.TLabel", font=("Segoe UI Semibold", 18))
        s.configure("Sub.TLabel", font=("Segoe UI", 10), foreground="#888888")
        s.configure("Field.TLabel", font=("Segoe UI Semibold", 10))
        s.configure("Status.TLabel", font=("Segoe UI", 10))
        s.configure("Treeview", rowheight=28, font=("Segoe UI", 10))
        s.configure("Treeview.Heading", font=("Segoe UI Semibold", 10))

    def _build(self):
        outer = ttk.Frame(self.root, padding=(20, 16, 20, 14))
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(1, weight=1)

        head = ttk.Frame(outer)
        head.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        ttk.Label(head, text="Tiny Desk Downloader", style="Title.TLabel").pack(anchor="w")
        ttk.Label(head, text="Save NPR Tiny Desk concerts in the best quality NPR offers.",
                  style="Sub.TLabel").pack(anchor="w")

        self.nb = ttk.Notebook(outer)
        self.nb.grid(row=1, column=0, sticky="nsew")
        self.cat_tab = ttk.Frame(self.nb, padding=12)
        self.link_tab = ttk.Frame(self.nb, padding=12)
        self.nb.add(self.cat_tab, text="  Catalogue  ")
        self.nb.add(self.link_tab, text="  Paste a link  ")
        self._build_catalogue(self.cat_tab)
        self._build_link(self.link_tab)

        bottom = ttk.Frame(outer)
        bottom.grid(row=2, column=0, sticky="nsew", pady=(12, 0))
        self._build_bottom(bottom)

    def _build_catalogue(self, f):
        f.columnconfigure(1, weight=1)
        f.rowconfigure(1, weight=1)

        bar = ttk.Frame(f)
        bar.grid(row=0, column=0, columnspan=3, sticky="ew", pady=(0, 10))
        bar.columnconfigure(1, weight=1)
        ttk.Label(bar, text="Search", style="Field.TLabel").grid(row=0, column=0, padx=(0, 8))
        self.search = tk.StringVar()
        e = ttk.Entry(bar, textvariable=self.search, font=("Segoe UI", 10))
        e.grid(row=0, column=1, sticky="ew")
        self.search.trace_add("write", lambda *a: self.render_catalogue())
        self.year = tk.StringVar(value=ALL_YEARS)
        self.year_box = ttk.Combobox(bar, textvariable=self.year, state="readonly", width=10,
                                     values=[ALL_YEARS])
        self.year_box.grid(row=0, column=2, padx=8)
        self.year_box.bind("<<ComboboxSelected>>", lambda e: self.render_catalogue())
        self.only_new = tk.BooleanVar(value=False)
        ttk.Checkbutton(bar, text="Not saved yet", variable=self.only_new,
                        command=self.render_catalogue).grid(row=0, column=3, padx=(0, 8))
        self.refresh_btn = ttk.Button(bar, text="Refresh", command=self.refresh_catalogue)
        self.refresh_btn.grid(row=0, column=4)

        cols = ("date", "artist", "saved")
        tv = ttk.Treeview(f, columns=cols, show="headings", selectmode="extended")
        for c, w, anchor, title in (("date", 110, "w", "Date"), ("artist", 520, "w", "Artist"),
                                    ("saved", 140, "center", "Saved")):
            tv.heading(c, text=title, command=lambda c=c: self.sort_by(c))
            tv.column(c, width=w, anchor=anchor, stretch=(c == "artist"))
        tv.grid(row=1, column=0, columnspan=2, sticky="nsew")
        sb = ttk.Scrollbar(f, orient="vertical", command=tv.yview)
        sb.grid(row=1, column=2, sticky="ns")
        tv.configure(yscrollcommand=sb.set)
        tv.bind("<<TreeviewSelect>>", lambda e: self.show_selection())
        tv.bind("<Control-a>", lambda e: tv.selection_set(tv.get_children()))
        self.tree = tv

        self.teaser = tk.StringVar(value="")
        ttk.Label(f, textvariable=self.teaser, wraplength=820, justify="left",
                  style="Sub.TLabel").grid(row=2, column=0, columnspan=3, sticky="ew", pady=(8, 6))

        act = ttk.Frame(f)
        act.grid(row=3, column=0, columnspan=3, sticky="ew")
        self.btn_audio = ttk.Button(act, text="Download best audio", style="Accent.TButton",
                                    command=lambda: self.enqueue_selected("audio"))
        self.btn_audio.pack(side="left")
        self.btn_video = ttk.Button(act, text="Download best video",
                                    command=lambda: self.enqueue_selected("video"))
        self.btn_video.pack(side="left", padx=8)
        self.cat_status = tk.StringVar(value="")
        ttk.Label(act, textvariable=self.cat_status, style="Sub.TLabel").pack(side="right")

    def _build_link(self, f):
        f.columnconfigure(1, weight=1)
        ttk.Label(f, text="Concert link", style="Field.TLabel").grid(row=0, column=0, sticky="w", padx=(0, 12))
        self.url = tk.StringVar()
        self.entry = ttk.Entry(f, textvariable=self.url, font=("Segoe UI", 11))
        self.entry.grid(row=0, column=1, sticky="ew", ipady=2)
        self.entry.bind("<Return>", lambda e: self.download_link())
        ttk.Button(f, text="Paste", command=self.paste).grid(row=0, column=2, padx=(8, 0), sticky="ew")

        ttk.Label(f, text="Format", style="Field.TLabel").grid(row=1, column=0, sticky="w", pady=(12, 0))
        start = FORMAT_BY_KEY.get(self.settings.get("format"), FORMATS[0])
        self.fmt = tk.StringVar(value=start.label)
        box = ttk.Combobox(f, textvariable=self.fmt, state="readonly",
                           values=[x.label for x in FORMATS], font=("Segoe UI", 10))
        box.grid(row=1, column=1, columnspan=2, sticky="ew", pady=(12, 0))
        box.bind("<<ComboboxSelected>>", lambda e: self._remember_format())

        ttk.Button(f, text="Download", style="Accent.TButton", width=16,
                   command=self.download_link).grid(row=2, column=0, columnspan=3, sticky="w", pady=(18, 0))
        ttk.Label(f, text="Tip: copy a concert's address from your browser – it is pasted "
                          "automatically when you open this tab.", style="Sub.TLabel").grid(
            row=3, column=0, columnspan=3, sticky="w", pady=(18, 0))
        self.nb.bind("<<NotebookTabChanged>>", self._tab_changed)

    def _build_bottom(self, f):
        f.columnconfigure(1, weight=1)
        ttk.Label(f, text="Save to", style="Field.TLabel").grid(row=0, column=0, sticky="w", padx=(0, 12))
        d = self.settings.get("out_dir")
        self.out_dir = tk.StringVar(value=d if d and os.path.isdir(d) else APP_DIR)
        ttk.Entry(f, textvariable=self.out_dir, state="readonly", font=("Segoe UI", 10)).grid(
            row=0, column=1, sticky="ew")
        b = ttk.Frame(f)
        b.grid(row=0, column=2, padx=(8, 0))
        ttk.Button(b, text="Change…", command=self.choose_folder).pack(side="left")
        ttk.Button(b, text="Open", command=lambda: os.startfile(self.out_dir.get())).pack(side="left", padx=(6, 0))

        row = ttk.Frame(f)
        row.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(12, 4))
        self.status = tk.StringVar(value="Ready")
        ttk.Label(row, textvariable=self.status, style="Status.TLabel").pack(side="left")
        self.cancel_btn = ttk.Button(row, text="Cancel all", command=self.cancel, state="disabled")
        self.cancel_btn.pack(side="right")
        self.bar = ttk.Progressbar(f, maximum=100)
        self.bar.grid(row=2, column=0, columnspan=3, sticky="ew", pady=(0, 8))

        self.logbox = scrolledtext.ScrolledText(f, height=6, font=("Consolas", 9), state="disabled",
                                                wrap="word", relief="flat", borderwidth=0, padx=10, pady=6)
        if self.dark:
            self.logbox.configure(bg="#1c1c1c", fg="#e0e0e0")
        else:
            self.logbox.configure(bg="#f7f7f7", fg="#202020")
        self.logbox.grid(row=3, column=0, columnspan=3, sticky="ew")
        ttk.Label(f, text=f"v{__version__}", style="Sub.TLabel").grid(row=4, column=2, sticky="e", pady=(6, 0))

    # ------------------------------------------------------------------ bridge
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
                    self._show_progress(*val)
                elif kind == "job_done":
                    self._job_done(*val)
                elif kind == "cat_status":
                    self.cat_status.set(val)
                elif kind == "cat_done":
                    self._catalogue_done(*val)
        except queue.Empty:
            pass
        self._poll_id = self.root.after(100, self.poll)

    # ------------------------------------------------------------------ catalogue
    def refresh_catalogue(self, quiet=False):
        if self.cat_busy:
            return
        self.cat_busy = True
        self.refresh_btn.configure(state="disabled")
        first = not self.catalogue.items
        self.cat_status.set("Reading NPR's archive – the first time takes about a minute …"
                            if first else "Checking for new concerts …")

        def work():
            try:
                new = self.catalogue.refresh(progress=lambda m: self.q.put(("cat_status", m)))
                self.q.put(("cat_done", (new, None, quiet)))
            except Exception as e:
                self.q.put(("cat_done", ([], e, quiet)))

        threading.Thread(target=work, daemon=True).start()

    def _catalogue_done(self, new, err, quiet):
        self.cat_busy = False
        self.refresh_btn.configure(state="normal")
        total = len(self.catalogue.items)
        if err:
            self.log(f"Catalogue: could not check for new concerts ({err}).")
        elif not new:
            self.log(f"Catalogue checked: no new concerts ({total:,} in total).")
        else:
            n = len(new)
            names = ", ".join(f"{i['artist']} ({i['date']})" for i in new[:8])
            more = f" and {n - 8} more" if n > 8 else ""
            self.log(f"Catalogue updated: {n} new concert{'s' if n != 1 else ''} – {names}{more}.")
        self.render_catalogue()

    def filtered_items(self):
        words = self.search.get().lower().split()
        year = self.year.get()
        out = []
        for it in self.catalogue.items:
            if year != ALL_YEARS and not it["date"].startswith(year):
                continue
            hay = (it["artist"] + " " + it.get("teaser", "")).lower()
            if words and not all(w in hay for w in words):
                continue
            if self.only_new.get() and self.history.saved(it["url"]):
                continue
            out.append(it)
        key, rev = self.sort
        if key == "artist":
            out.sort(key=lambda i: i["artist"].lower(), reverse=rev)
        elif key == "saved":
            out.sort(key=lambda i: self.saved_label(i["url"]), reverse=rev)
        else:
            out.sort(key=lambda i: i["date"], reverse=rev)
        return out

    def saved_label(self, url):
        s = self.history.saved(url)
        audio, video = "audio" in s, bool(s & {"video", "video1080", "video720"})
        return "Audio + Video" if audio and video else "Audio" if audio else "Video" if video else ""

    def render_catalogue(self):
        years = sorted({i["date"][:4] for i in self.catalogue.items}, reverse=True)
        self.year_box.configure(values=[ALL_YEARS] + years)
        sel = set(self.tree.selection())
        self.tree.delete(*self.tree.get_children())
        items = self.filtered_items()
        self.items_by_url = {i["url"]: i for i in self.catalogue.items}
        for it in items:
            self.tree.insert("", "end", iid=it["url"],
                             values=(it["date"], it["artist"], self.saved_label(it["url"])))
        keep = [u for u in sel if self.tree.exists(u)]
        if keep:
            self.tree.selection_set(keep)
        if not self.cat_busy:
            total = len(self.catalogue.items)
            shown = f"{len(items):,} of {total:,} concerts" if len(items) != total else f"{total:,} concerts"
            upd = (self.catalogue.updated or "")[:16].replace("T", " ")
            self.cat_status.set(shown + (f"  ·  checked {upd}" if upd else ""))

    def sort_by(self, col):
        key, rev = self.sort
        self.sort = (col, not rev if key == col else col != "artist")
        self.render_catalogue()

    def show_selection(self):
        sel = self.tree.selection()
        if len(sel) == 1:
            it = self.items_by_url.get(sel[0], {})
            self.teaser.set(it.get("teaser", ""))
        elif sel:
            self.teaser.set(f"{len(sel)} concerts selected")
        else:
            self.teaser.set("")

    def enqueue_selected(self, fmt_key):
        sel = self.tree.selection()
        if not sel:
            self.teaser.set("Select one or more concerts first (Ctrl or Shift + click to select several).")
            return
        fmt = FORMAT_BY_KEY[fmt_key]
        items = [self.items_by_url[u] for u in sel if u in self.items_by_url]
        items.sort(key=lambda i: i["date"], reverse=True)
        self.enqueue([(i["url"], fmt, i["artist"]) for i in items])

    # ------------------------------------------------------------------ link tab
    def _tab_changed(self, _e):
        if self.nb.select() == str(self.link_tab) and not self.url.get().strip():
            self.paste(auto=True)

    def paste(self, auto=False):
        try:
            clip = self.root.clipboard_get().strip()
        except tk.TclError:
            return
        if not auto or re.match(r"https?://(www\.)?npr\.org/", clip):
            self.url.set(clip)

    def current_format(self):
        return next((f for f in FORMATS if f.label == self.fmt.get()), FORMATS[0])

    def _remember_format(self):
        self.settings["format"] = self.current_format().key
        core.save_settings(self.settings)

    def download_link(self):
        url = self.url.get().strip()
        if not re.match(r"https?://", url):
            self.status.set("Paste a link first")
            self.log("Please paste the link of a Tiny Desk concert page (https://www.npr.org/…).")
            return
        self.enqueue([(url, self.current_format(), url.rstrip("/").rsplit("/", 1)[-1])])

    # ------------------------------------------------------------------ queue
    def enqueue(self, jobs):
        busy = {(u, f.key) for u, f, _ in self.pending}
        if self.job_info:
            busy.add((self.job_info[0], self.job_info[1].key))
        added = [j for j in jobs if (j[0], j[1].key) not in busy]
        if not added:
            self.status.set("Already in the queue")
            return
        if not self.job and not self.pending:
            self.batch = {"total": 0, "ok": 0, "failed": 0}
        self.pending.extend(added)
        self.batch["total"] += len(added)
        if len(added) > 1:
            self.log(f"Added {len(added)} concerts to the queue.")
        self.cancel_btn.configure(state="normal")
        self.start_next()

    def start_next(self):
        if self.job or not self.pending:
            return
        url, fmt, name = self.pending.popleft()
        self.job_info = (url, fmt, name)
        self.bar["value"] = 0
        n = self.batch["ok"] + self.batch["failed"] + 1
        self.log(f"\n── {name}  ({'video' if fmt.video else 'audio'}"
                 + (f", {n} of {self.batch['total']}" if self.batch["total"] > 1 else "") + ")")
        self.job = core.Job(url, fmt, self.out_dir.get(), self.log, self.set_progress)
        self._show_progress(0, None)
        threading.Thread(target=self._worker, args=(self.job,), daemon=True).start()

    def _worker(self, job):
        try:
            path = job.run()
            self.log(f"Saved: {path}")
            self.q.put(("job_done", (True, path, None)))
        except core.Cancelled:
            self.q.put(("job_done", (False, None, "Cancelled.")))
        except Exception as e:
            self.log(f"Failed: {e}")
            self.q.put(("job_done", (False, None, str(e))))

    def _show_progress(self, pct, eta):
        self.bar["value"] = pct
        if not self.job_info:
            return
        name = self.job_info[2]
        total = self.batch["total"]
        n = self.batch["ok"] + self.batch["failed"] + 1
        prefix = f"{n} of {total}  ·  " if total > 1 else ""
        self.status.set(f"{prefix}{name}  ·  {pct:.0f} %" + (f"  ·  {fmt_eta(eta)}" if eta else ""))

    def _job_done(self, ok, path, err):
        url, fmt, _ = self.job_info
        self.job, self.job_info = None, None
        if ok:
            self.batch["ok"] += 1
            if path and os.path.isfile(path):
                self.history.add(url, fmt.key, path)
                if self.tree.exists(url):
                    self.tree.set(url, "saved", self.saved_label(url))
        elif err == "Cancelled.":
            pass
        else:
            self.batch["failed"] += 1
        if self.pending:
            self.start_next()
            return
        self.cancel_btn.configure(state="disabled")
        b = self.batch
        if err == "Cancelled.":
            self.status.set("Cancelled")
            self.bar["value"] = 0
        elif b["total"] > 1:
            self.status.set(f"Finished: {b['ok']} saved" + (f", {b['failed']} failed" if b["failed"] else ""))
        else:
            self.status.set("Done" if ok else "Failed – see details below")
        if self.only_new.get():
            self.render_catalogue()

    def cancel(self):
        self.pending.clear()
        if self.job:
            self.status.set("Cancelling …")
            self.job.cancel()

    # ------------------------------------------------------------------ misc
    def choose_folder(self):
        d = filedialog.askdirectory(initialdir=self.out_dir.get(), title="Save downloads to")
        if d:
            self.out_dir.set(os.path.normpath(d))
            self.settings["out_dir"] = self.out_dir.get()
            core.save_settings(self.settings)

    def close(self):
        self.pending.clear()
        if self.job:
            self.job.cancel()
        try:
            self.root.after_cancel(self._poll_id)
        except Exception:
            pass
        self.root.destroy()
