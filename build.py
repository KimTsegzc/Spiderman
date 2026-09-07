"""SpiderMan V2.3 release builder.

Builds one-file exe, compresses to zip, and splits zip into 48MB parts.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent
DIST = ROOT / "dist"
BUILD = ROOT / "build"
WORK = ROOT / "work"
APP = ROOT / "app.py"
APP_VERSION = "V2.3"
EXE_NAME = f"spiderman_{APP_VERSION.lower()}"
ZIP_NAME = ROOT / f"spiderman_{APP_VERSION.lower()}.zip"
ICON_PATH = ROOT / "images.ico"
ICON_SOURCE = ROOT / "images.jfif"
SPLIT_SIZE = 48 * 1024 * 1024


def run(command: list[str]) -> None:
    subprocess.run(command, check=True, cwd=ROOT)


def clean(paths: list[Path]) -> None:
    for path in paths:
        if path.exists():
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()


def build_icon() -> Path:
    if not ICON_SOURCE.exists():
        raise FileNotFoundError(f"Icon source not found: {ICON_SOURCE}")

    img = Image.open(ICON_SOURCE).convert("RGB")
    # Crop near-white outer border aggressively so logo fills the icon canvas.
    gray = img.convert("L")
    bbox = gray.point(lambda p: 255 if p < 252 else 0).getbbox()
    if bbox:
        img = img.crop(bbox)

    w, h = img.size
    side = max(w, h)
    # If aspect ratio is not square, keep content centered and fill remaining area with white.
    square = Image.new("RGB", (side, side), (255, 255, 255))
    square.paste(img, ((side - w) // 2, (side - h) // 2))

    # Keep only a very small safety margin while making the icon look full.
    inner = int(side * 0.98)
    inner = max(inner, 16)
    fitted = square.resize((inner, inner), Image.Resampling.LANCZOS)
    canvas = Image.new("RGB", (side, side), (255, 255, 255))
    canvas.paste(fitted, ((side - inner) // 2, (side - inner) // 2))

    # Use BMP icon entries to avoid PNG-compressed icon artifacts.
    canvas.save(
        ICON_PATH,
        format="ICO",
        bitmap_format="bmp",
        sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)],
    )
    return ICON_PATH


def build_exe() -> Path:
    clean([DIST, BUILD, WORK, ZIP_NAME])
    icon_file = build_icon()
    pyinstaller = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onefile",
        "--noconsole",
        "--noupx",
        "--name",
        EXE_NAME,
        "--icon",
        str(icon_file),
        "--distpath",
        str(DIST),
        "--workpath",
        str(WORK),
        "--specpath",
        str(ROOT),
        str(APP),
    ]
    run(pyinstaller)
    return DIST / f"{EXE_NAME}.exe"


def make_zip(exe_path: Path) -> Path:
    with zipfile.ZipFile(ZIP_NAME, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.write(exe_path, arcname=exe_path.name)
    return ZIP_NAME


def split_file(file_path: Path, chunk_size: int = SPLIT_SIZE) -> list[Path]:
    parts_dir = ROOT / "parts"
    if parts_dir.exists():
        shutil.rmtree(parts_dir)
    parts_dir.mkdir(parents=True, exist_ok=True)

    chunks: list[Path] = []
    with file_path.open("rb") as source:
        index = 1
        while True:
            data = source.read(chunk_size)
            if not data:
                break
            part = parts_dir / f"{file_path.name}.part{index:03d}"
            part.write_bytes(data)
            chunks.append(part)
            index += 1
    return chunks


def main() -> None:
    exe_path = build_exe()
    zip_path = make_zip(exe_path)
    chunks = split_file(zip_path)
    print(f"EXE: {exe_path}")
    print(f"ZIP: {zip_path}")
    print("PARTS:")
    for chunk in chunks:
        print(f" - {chunk}")


if __name__ == "__main__":
    main()
