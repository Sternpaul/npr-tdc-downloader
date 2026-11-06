<div align="center">

<img src="assets/icon.png" width="96" alt="">

# NPR Tiny Desk Downloader

**Save NPR Tiny Desk concerts as audio or video – in the best quality NPR actually has.**
One click, no installation, Windows 10/11.

[![Latest release](https://img.shields.io/github/v/release/Sternpaul/npr-tdc-downloader?label=download&sort=semver)](https://github.com/Sternpaul/npr-tdc-downloader/releases/latest)
[![Build](https://github.com/Sternpaul/npr-tdc-downloader/actions/workflows/release.yml/badge.svg)](https://github.com/Sternpaul/npr-tdc-downloader/actions/workflows/release.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

<img src="assets/screenshot.png" width="620" alt="Screenshot of NPR Tiny Desk Downloader">

</div>

## Why?

The audio you get from the NPR website's player or from `yt-dlp` is a
re-encoded copy at **~112 kbps**. NPR's video player also keeps the **original
upload** around – and its audio track is **~320 kbps AAC at 48 kHz**, roughly
three times the bitrate. This app fetches exactly that file and copies the
streams **without re-encoding**, so nothing is lost.

| | Audio | Video |
|---|---|---|
| NPR website / yt-dlp `bestaudio` | AAC 112 kbps, 44.1 kHz | up to 1080p, 3.5 Mbit/s |
| **This app – original quality** | **AAC ~320 kbps, 48 kHz** | **1080p, ~15 Mbit/s** (the studio upload) |

## Features

- **Paste a link, press Download** – that's it.
- **Audio** (`.m4a`) or **video** (`.mp4`): original quality, or smaller 1080p / 720p versions.
- **Tagged files**: artist, title, date, album *NPR Tiny Desk Concerts* and the cover picture
  – they show up nicely in any music player. If tagging fails, the download is still kept.
- **Progress bar with time left**, cancel at any time (no half-finished files left behind).
- Skips concerts you already have, checks free disk space before big downloads.
- Light and dark mode (follows Windows), remembers your format and folder.
- **Everything is inside one `.exe`** – Python, FFmpeg and all libraries. Nothing to install.
- Fallback to [yt-dlp](https://github.com/yt-dlp/yt-dlp) for older concert pages without NPR's own player.

## Download & use

1. Download **`NPR-TDC-Downloader.exe`** from the
   [latest release](https://github.com/Sternpaul/npr-tdc-downloader/releases/latest).
2. Put it in the folder where your concerts should go (e.g. `Music\Tiny Desk`) and double-click it.
3. Open a concert on [npr.org/series/tiny-desk-concerts](https://www.npr.org/series/tiny-desk-concerts/),
   copy the address from the browser, and paste it into the app
   (if the link is already copied, the app pastes it for you).
4. Pick the format and click **Download**.

Files are saved next to the `.exe` unless you pick another folder with **Change…**.

> [!NOTE]
> **"Windows protected your PC"** – the first time you start it, Windows SmartScreen
> warns about apps that are not code-signed. Click **More info → Run anyway**.
> Each release lists the SHA-256 checksum of the exe if you want to verify your download.

> [!TIP]
> **Why does an audio download take a few minutes?** The original audio only exists
> inside the original video file (~2 GB for a 20-minute concert). The app streams that
> file and keeps only the sound. Speed depends on your internet connection.

### Formats

| Format | File | Typical size (20 min) | Notes |
|---|---|---|---|
| Audio · original quality | `.m4a` | ~45 MB | best audio; download time ≈ original video |
| Video · original quality | `.mp4` | ~2 GB | the unmodified studio upload |
| Video · 1080p compressed | `.mp4` | ~500 MB | NPR's web version, 112 kbps audio |
| Video · 720p compressed | `.mp4` | ~300 MB | NPR's web version, 112 kbps audio |

### Command line

The exe also accepts a link, which fills it in and starts right away:

```bat
NPR-TDC-Downloader.exe "https://www.npr.org/2026/11/02/g-s1-148929/jungle-tiny-desk-concert" --format video
```

`--format` is one of `audio` (default), `video`, `video1080`, `video720`.

## How it works

1. Reads the NPR page and finds the embedded **JW Player** media ID
   (e.g. `cdn.jwplayer.com/manifests/PlKLO4B7.m3u8`), the title and the publish date.
2. Asks the public JW Player API (`cdn.jwplayer.com/v2/media/<id>`) for all renditions.
   Besides the usual 180p–1080p MP4s and HLS stream, it lists a **`Passthrough`** source:
   the originally uploaded file.
3. Runs `ffmpeg -c copy` on that source to remux the audio (or audio + video) into
   `.m4a` / `.mp4` – no re-encoding, so no quality loss.
4. Writes MP4 tags and cover art with [mutagen](https://github.com/quodlibet/mutagen).

If a page has no JW Player video, the app hands the link to yt-dlp instead.

## Build it yourself

Requirements: Windows, Python 3.12+, and an `ffmpeg.exe`.

```bash
git clone https://github.com/Sternpaul/npr-tdc-downloader.git
cd npr-tdc-downloader
pip install -r requirements.txt
python -m unittest discover -s tests       # offline tests
python src/npr_tdc_downloader.py           # run from source (uses ffmpeg from PATH)
python build.py --ffmpeg C:\path\to\ffmpeg.exe   # -> dist/NPR-TDC-Downloader.exe
```

`build.py` looks for `ffmpeg.exe` in `./ffmpeg/` or on `PATH` if `--ffmpeg` is not given.
The icon is generated by `tools/make_icon.py`.

## Releases

Releases are built by GitHub Actions ([`release.yml`](.github/workflows/release.yml)):

```bash
git tag v1.0.0
git push origin v1.0.0
```

The workflow runs the tests, downloads the newest stable LGPL FFmpeg build from
[BtbN/FFmpeg-Builds](https://github.com/BtbN/FFmpeg-Builds) (checksum-verified),
builds the exe with version info, checks that it starts, and publishes a release with
the exe, its SHA-256 checksum and the FFmpeg license. Tags with a `-` (e.g. `v1.1.0-beta.1`)
become pre-releases. Running the workflow manually builds a test exe as an artifact only.

## Disclaimer

This project is not affiliated with, endorsed by, or connected to NPR. Tiny Desk
concerts are © NPR and the performing artists. Use this tool only to save concerts for
your own personal listening, and respect NPR's
[terms of use](https://www.npr.org/about-npr/179876898/terms-of-use). Do not
redistribute downloaded recordings.

## License

[MIT](LICENSE) for the code in this repository. The release exe bundles third-party
software under its own licenses – see [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md).
