"""打印主窗各区域的实际像素宽度，用来排查布局被裁切的问题。"""
from __future__ import annotations

import ctypes
import sys
import tkinter as tk
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import config  # noqa: E402
from app.store import Store  # noqa: E402
from app.ui import App  # noqa: E402


def enable_dpi() -> None:
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


class WinRect(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


def main() -> int:
    enable_dpi()
    config.ensure_dirs()
    store = Store(config.DB_PATH)
    app = App(store)
    app.update()
    app.after(1500, lambda: report(app))
    app.mainloop()
    return 0


def report(app: App) -> None:
    app.update()
    hwnd = int(app.wm_frame(), 16)
    rect = WinRect()
    ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect))
    print("tk scaling      :", round(app.tk.call("tk", "scaling"), 3))
    print("app.scale       :", app.scale)
    print("screen          :", app.winfo_screenwidth(), "x", app.winfo_screenheight())
    print("geometry()      :", app.geometry())
    print("physical rect   :", rect.right - rect.left, "x", rect.bottom - rect.top)
    print("root winfo      :", app.winfo_width(), "x", app.winfo_height())
    print("paned           :", app.paned.winfo_width(), "x", app.paned.winfo_height())
    print("paned reqwidth  :", app.paned.winfo_reqwidth())
    print("left frame      :", app.left.winfo_width())
    print("mid frame       :", app.mid.winfo_width())
    print("right frame     :", app.right.winfo_width(), "req", app.right.winfo_reqwidth())
    print("reader text     :", app.text.winfo_width(), "req", app.text.winfo_reqwidth())
    print("sash coords     :", [app.paned.sash_coord(i) for i in range(2)])
    app.destroy()


if __name__ == "__main__":
    raise SystemExit(main())
