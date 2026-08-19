"""SpiderMan V1 release builder.

Builds one-file exe, compresses to zip, and splits zip into 48MB parts.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DIST = ROOT / "dist"
BUILD = ROOT / "build"
WORK = ROOT / "work"
APP = ROOT / "app.py"
EXE_NAME = "spiderman"
ZIP_NAME = ROOT / "spiderman.zip"
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


def build_exe() -> Path:
    clean([DIST, BUILD, WORK, ZIP_NAME])
    pyinstaller = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onefile",
        "--noconsole",
        "--name",
        EXE_NAME,
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
