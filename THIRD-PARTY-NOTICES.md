# Third-party software

The released `NPR-TDC-Downloader.exe` bundles the following software.

| Component | License | Source |
|---|---|---|
| [FFmpeg](https://ffmpeg.org) (LGPL build by [BtbN/FFmpeg-Builds](https://github.com/BtbN/FFmpeg-Builds)) | LGPL 2.1 or later | https://github.com/BtbN/FFmpeg-Builds, https://ffmpeg.org/download.html |
| [Python](https://www.python.org) | PSF License | https://www.python.org |
| [yt-dlp](https://github.com/yt-dlp/yt-dlp) | Unlicense | https://github.com/yt-dlp/yt-dlp |
| [mutagen](https://github.com/quodlibet/mutagen) | GPL 2.0 or later | https://github.com/quodlibet/mutagen |
| [Sun Valley ttk theme (sv-ttk)](https://github.com/rdbende/Sun-Valley-ttk-theme) | MIT | https://github.com/rdbende/Sun-Valley-ttk-theme |
| [PyInstaller](https://pyinstaller.org) bootloader | GPL 2.0 with bootloader exception | https://github.com/pyinstaller/pyinstaller |

FFmpeg is shipped unmodified as `ffmpeg.exe` inside the executable. The exact
FFmpeg build used for each release, together with its license text, is attached
to the GitHub release (`ffmpeg-LICENSE.txt`, and the build name in the release notes).
