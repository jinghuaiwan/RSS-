"""安装信息：安装目录、快捷方式位置、注册表项 —— 安装器和卸载器共用。"""
from __future__ import annotations

import os
from pathlib import Path

PRODUCT = "RSS 阅读器"
EXE_NAME = "RSS阅读器.exe"
PUBLISHER = "本地构建"
VERSION = "1.0.0"

REG_SUBKEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\DSRssReader"
REG_APP_KEY = r"Software\DSRssReader"


def local_appdata() -> Path:
    return Path(os.environ.get("LOCALAPPDATA") or Path.home())


def appdata() -> Path:
    return Path(os.environ.get("APPDATA") or Path.home())


def default_install_dir() -> Path:
    return local_appdata() / "Programs" / PRODUCT


def data_dir() -> Path:
    return appdata() / "DSRssReader"


def start_menu_dir() -> Path:
    return appdata() / "Microsoft" / "Windows" / "Start Menu" / "Programs"


def start_menu_link() -> Path:
    return start_menu_dir() / f"{PRODUCT}.lnk"


def desktop_link() -> Path:
    return Path(os.environ.get("USERPROFILE") or Path.home()) / "Desktop" / f"{PRODUCT}.lnk"


def data_dir_size(path: Path) -> int:
    total = 0
    if not path.exists():
        return 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += (Path(root) / name).stat().st_size
            except OSError:
                pass
    return total
