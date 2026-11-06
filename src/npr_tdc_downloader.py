"""NPR Tiny Desk Downloader - entry point.

Saves NPR Tiny Desk concerts as audio or video in the best quality NPR offers.
See tdc/core.py for how sources are picked, tdc/catalogue.py for the archive
scan and tdc/gui.py for the window.
"""
import argparse
import os
import sys

from tdc.core import APP_NAME, FORMAT_BY_KEY


def main():
    ap = argparse.ArgumentParser(prog="npr-tdc-downloader", description=APP_NAME)
    ap.add_argument("url", nargs="?", help="concert page; starts the download right away")
    ap.add_argument("--format", choices=list(FORMAT_BY_KEY), help="audio (default), video, video1080, video720")
    try:
        a, _ = ap.parse_known_args()
    except SystemExit:  # bad arguments in a windowed exe: just open the window
        a = argparse.Namespace(url=None, format=None)

    if os.name == "nt":
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Sternpaul.NprTdcDownloader")
        except Exception:
            pass

    import tkinter as tk
    from tdc.gui import App
    root = tk.Tk()
    App(root, url=a.url, fmt_key=a.format, autostart=bool(a.url))
    root.mainloop()


if __name__ == "__main__":
    sys.exit(main())
