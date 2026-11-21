"""RSS 阅读器启动入口。

用法：
    python run.py               # 控制台模式，能看到日志
    pythonw run.py              # 无控制台
    RSS阅读器.exe --uninstall    # 卸载（删程序、快捷方式、注册表项，保留数据）

崩溃时会写日志到 data/reader.log（安装版在 %APPDATA%\\DSRssReader\\reader.log）。
"""
from __future__ import annotations

import os
import sys
import traceback
from datetime import datetime


def _enable_dpi_awareness() -> None:
    if os.name != "nt":
        return
    try:
        import ctypes

        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)  # 系统 DPI 感知
        except Exception:
            ctypes.windll.user32.SetProcessDPIAware()
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                "DSH.RssReader.1")
        except Exception:
            pass
    except Exception:
        pass


def _bootstrap_path() -> None:
    if getattr(sys, "frozen", False):
        return
    here = os.path.dirname(os.path.abspath(__file__))
    if here not in sys.path:
        sys.path.insert(0, here)


def _log_crash(exc: BaseException) -> None:
    try:
        _bootstrap_path()
        from app import config

        config.DATA_DIR.mkdir(parents=True, exist_ok=True)
        with open(config.LOG_PATH, "a", encoding="utf-8") as handle:
            handle.write(f"\n===== {datetime.now():%Y-%m-%d %H:%M:%S} =====\n")
            traceback.print_exception(type(exc), exc, exc.__traceback__, file=handle)
    except Exception:
        pass


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    _enable_dpi_awareness()
    _bootstrap_path()
    if "--uninstall" in args:
        try:
            from app.uninstall import ask_and_uninstall

            return ask_and_uninstall()
        except BaseException as exc:  # noqa: BLE001
            traceback.print_exc()
            _log_crash(exc)
            return 1
    try:
        from app import config
        from app.store import Store
        from app.ui import App

        config.ensure_dirs()
        store = Store(config.DB_PATH)
        app = App(store)
        app.mainloop()
        return 0
    except SystemExit:
        raise
    except BaseException as exc:  # noqa: BLE001 - 顶层兜底，避免 pythonw 静默退出
        traceback.print_exc()
        _log_crash(exc)
        try:
            from tkinter import messagebox

            from app import config

            messagebox.showerror("RSS 阅读器启动失败",
                                 f"{type(exc).__name__}: {exc}\n\n"
                                 f"详细信息已写入 {config.LOG_PATH}")
        except Exception:
            pass
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
