"""打开某个对话框并停在原地，方便截图验收。

用法：
    python tools/demo_dialog.py settings   # 设置对话框
    python tools/demo_dialog.py add        # 添加订阅对话框
    python tools/demo_dialog.py folder     # 新建分组
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import config  # noqa: E402
from app.store import Store  # noqa: E402
from app.ui import App  # noqa: E402


def _enable_dpi() -> None:
    """和 run.py 一样先声明 DPI 感知，否则窗口会被系统拉伸、截图发虚。"""
    import ctypes

    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def main() -> int:
    which = sys.argv[1] if len(sys.argv) > 1 else "settings"
    _enable_dpi()
    config.ensure_dirs()
    app = App(Store(config.DB_PATH))
    actions = {
        "settings": app.open_settings,
        "add": app.add_feed,
        "folder": lambda: app.new_folder(None),
    }
    action = actions.get(which, app.open_settings)
    app.after(1200, action)
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
