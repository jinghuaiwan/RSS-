"""下载 PyInstaller 及其依赖的 wheel，直接解包到 vendor/。

为什么不用 pip：本机沙箱下 `tempfile.mkdtemp()` 新建的目录没有写权限，
pip 解包时会报 `[Errno 13] Permission denied: ...whl.metadata`。
这里只用 urllib 从 PyPI 拉 wheel，再用 zipfile 解到 vendor/，不碰临时目录。
"""
from __future__ import annotations

import json
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VENDOR = ROOT / "vendor"
WHEELS = ROOT / ".wheels"

PACKAGES = [
    "pyinstaller",
    "pyinstaller-hooks-contrib",
    "altgraph",
    "pefile",
    "pywin32-ctypes",
    "packaging",
    "setuptools",
]
TAGS = ("cp312-cp312-win_amd64", "cp312-abi3-win_amd64", "py3-none-win_amd64", "py3-none-any", "py2.py3-none-any")


def pick_file(data: dict) -> dict | None:
    best = None
    best_key = ""
    for item in data.get("urls", []):
        name = item["filename"]
        if not name.endswith(".whl"):
            continue
        if not any(tag in name for tag in TAGS):
            continue
        key = item.get("upload_time", "")
        if key > best_key:
            best, best_key = item, key
    return best


def main() -> int:
    VENDOR.mkdir(exist_ok=True)
    WHEELS.mkdir(exist_ok=True)
    for package in PACKAGES:
        with urllib.request.urlopen(f"https://pypi.org/pypi/{package}/json", timeout=30) as resp:
            data = json.load(resp)
        version = data["info"]["version"]
        file = pick_file(data)
        if not file:
            print(f"! {package}: 没有合适的 wheel")
            continue
        target = WHEELS / file["filename"]
        if not target.exists():
            print(f"↓ {package} {version} -> {file['filename']}")
            with urllib.request.urlopen(file["url"], timeout=120) as resp:
                target.write_bytes(resp.read())
        else:
            print(f"= {package} {version} ({target.name} 已存在)")
        with zipfile.ZipFile(target) as zf:
            zf.extractall(VENDOR)
    print("vendor 就绪:", VENDOR)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
