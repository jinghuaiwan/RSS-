"""全局配置：应用信息、便携数据目录、默认设置项。"""
from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "RSS 阅读器"
APP_ID = "dsrssreader"
APP_VERSION = "1.0.0"

# 项目根目录（run.py 所在目录），数据默认与程序放在一起，整个文件夹拷走即可迁移。
BASE_DIR = Path(__file__).resolve().parents[1]


def _pick_data_dir() -> Path:
    """优先使用程序目录下的 data/（便携）；不可写时退回 %APPDATA%。"""
    portable = BASE_DIR / "data"
    try:
        portable.mkdir(parents=True, exist_ok=True)
        probe = portable / ".write-test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return portable
    except OSError:
        fallback = Path(os.environ.get("APPDATA", Path.home())) / "DSRssReader"
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback


DATA_DIR = _pick_data_dir()
DB_PATH = DATA_DIR / "reader.db"
CACHE_DIR = DATA_DIR / "cache"
LOG_PATH = DATA_DIR / "reader.log"


def ensure_dirs() -> None:
    """确保数据目录与图片缓存目录存在。"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

# 默认设置（会被数据库里的用户设置覆盖）
DEFAULTS = {
    "theme": "dark",              # dark | light
    "font_size": "15",            # 阅读区字号
    "list_font_size": "11",       # 列表字号
    "refresh_minutes": "30",      # 0 = 关闭自动刷新
    "proxy": "",                  # 例：http://127.0.0.1:7890
    "load_images": "1",           # 正文图片
    "notify": "1",                # 新文章提醒
    "page_size": "200",           # 列表每次加载条数
    "max_articles": "3000",       # 每个订阅最多保留文章数，0 = 不限
    "ua": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "window_geometry": "",
    "sash": "",                   # 三栏宽度记忆
    "last_scope": "all",
}

IS_WINDOWS = sys.platform.startswith("win")


def asset(name: str) -> Path:
    return BASE_DIR / "assets" / name
