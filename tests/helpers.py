"""测试公用小工具。

注意：DSH 沙箱下，刚用 mkdtemp 建出来的子目录里 sqlite 打不开数据库
（Windows ACL 问题），所以临时文件一律平铺在 .testtmp/ 下，用唯一文件名区分。
"""
from __future__ import annotations

import os
import shutil
import uuid

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = os.path.join(ROOT, ".testtmp")


def make_temp_dir() -> str:
    os.makedirs(BASE, exist_ok=True)
    return BASE


def temp_path(suffix: str) -> str:
    """在 .testtmp 下生成一个唯一的文件路径。"""
    make_temp_dir()
    return os.path.join(BASE, f"{uuid.uuid4().hex[:10]}{suffix}")


def drop_temp_dir(path: str) -> None:
    for name in os.listdir(path):
        if name.endswith((".db", ".db-wal", ".db-shm", ".log")):
            try:
                os.remove(os.path.join(path, name))
            except OSError:
                pass
    cache = os.path.join(path, "cache")
    if os.path.isdir(cache):
        shutil.rmtree(cache, ignore_errors=True)
