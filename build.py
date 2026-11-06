"""Build the single-file Windows exe.

    python build.py [--version 1.2.3] [--ffmpeg path\\to\\ffmpeg.exe]

Without --ffmpeg, ffmpeg.exe is taken from ./ffmpeg/ffmpeg.exe or from PATH.
Output: dist/NPR-TDC-Downloader.exe
"""
import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
NAME = "NPR-TDC-Downloader"

VERSION_INFO = """VSVersionInfo(
  ffi=FixedFileInfo(filevers={t}, prodvers={t}, mask=0x3f, flags=0x0, OS=0x40004,
                    fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040904B0', [
      StringStruct('CompanyName', 'Sternpaul'),
      StringStruct('FileDescription', 'NPR Tiny Desk Downloader'),
      StringStruct('FileVersion', '{v}'),
      StringStruct('InternalName', '{n}'),
      StringStruct('OriginalFilename', '{n}.exe'),
      StringStruct('ProductName', 'NPR Tiny Desk Downloader'),
      StringStruct('ProductVersion', '{v}'),
      StringStruct('LegalCopyright', 'MIT License. Not affiliated with NPR.')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", default="0.0.0-dev")
    ap.add_argument("--ffmpeg")
    a = ap.parse_args()
    version = a.version.lstrip("v")

    ffmpeg = a.ffmpeg or (ROOT / "ffmpeg" / "ffmpeg.exe" if (ROOT / "ffmpeg" / "ffmpeg.exe").exists()
                          else shutil.which("ffmpeg"))
    if not ffmpeg or not Path(ffmpeg).is_file():
        sys.exit("ffmpeg.exe not found: pass --ffmpeg or put it in ./ffmpeg/")
    ffmpeg = Path(ffmpeg).resolve()  # PyInstaller resolves relative paths from --specpath
    print(f"version {version}\nffmpeg  {ffmpeg}")

    build = ROOT / "build"
    build.mkdir(exist_ok=True)
    (SRC / "_version.py").write_text(f'__version__ = "{version}"\n', encoding="utf-8")
    nums = [int(x) for x in re.findall(r"\d+", version)[:4]]
    nums += [0] * (4 - len(nums))
    vfile = build / "version_info.txt"
    vfile.write_text(VERSION_INFO.format(t=tuple(nums), v=version, n=NAME), encoding="utf-8")

    icon = ROOT / "assets" / "icon.ico"
    cmd = [
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onefile", "--windowed",
        "--name", NAME,
        "--icon", str(icon),
        "--version-file", str(vfile),
        "--add-binary", f"{ffmpeg};.",
        "--add-data", f"{icon};.",
        "--collect-data", "sv_ttk",
        "--collect-submodules", "yt_dlp.extractor",
        "--hidden-import", "mutagen.mp4",
        "--paths", str(SRC),
        "--workpath", str(build / "work"),
        "--specpath", str(build),
        "--distpath", str(ROOT / "dist"),
        str(SRC / "npr_tdc_downloader.py"),
    ]
    subprocess.run(cmd, check=True)
    exe = ROOT / "dist" / f"{NAME}.exe"
    print(f"\nbuilt {exe} ({exe.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
