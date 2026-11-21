"""关掉所有正在运行的阅读器窗口（发送 WM_CLOSE）。"""
from __future__ import annotations

import ctypes
import time
from ctypes import wintypes

TITLE = "RSS 阅读器"
WM_CLOSE = 0x0010


def windows() -> list[int]:
    user32 = ctypes.windll.user32
    found: list[int] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(hwnd, _lparam):
        length = user32.GetWindowTextLengthW(hwnd)
        if length:
            buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buf, length + 1)
            if TITLE in buf.value and user32.IsWindowVisible(hwnd):
                found.append(hwnd)
        return True

    user32.EnumWindows(cb, 0)
    return found


def main() -> int:
    user32 = ctypes.windll.user32
    for hwnd in windows():
        user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
    for _ in range(20):
        if not windows():
            break
        time.sleep(0.25)
    left = windows()
    print("已关闭窗口，剩余：", len(left))
    return 0 if not left else 1


if __name__ == "__main__":
    raise SystemExit(main())
