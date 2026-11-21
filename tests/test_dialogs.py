"""对话框冒烟测试：曾经因为 Modal.show 里写了不存在的 app.root，所有对话框一打开就崩。"""
from __future__ import annotations

import tkinter as tk
import unittest

from helpers import temp_path

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config, dialogs  # noqa: E402
from app.store import Store  # noqa: E402
from app.ui import App  # noqa: E402


class DialogTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        config.DB_PATH = Path(temp_path(".db"))
        config.CACHE_DIR = Path(temp_path("cache"))
        config.CACHE_DIR.mkdir(parents=True, exist_ok=True)
        config.LOG_PATH = config.CACHE_DIR / "reader.log"
        config.DATA_DIR = config.CACHE_DIR.parent
        cls.store = Store(config.DB_PATH)
        cls.app = App(cls.store)
        cls.app.update()
        cls._grab = tk.Toplevel.grab_set
        tk.Toplevel.grab_set = lambda self: None  # 测试里不抢焦点

    @classmethod
    def tearDownClass(cls):
        tk.Toplevel.grab_set = cls._grab
        cls.app.destroy()
        cls.store.close()

    def _run(self, dialog, focus: str = ""):
        seen = {}

        def probe():
            seen["w"] = dialog.winfo_width()
            dialog.cancel()

        self.app.after(80, probe)
        result = dialog.ask(focus)
        self.assertIsNone(result)
        # ask() 里算过几何尺寸，说明没在中途抛异常
        self.assertGreater(seen.get("w", 0), 100)
        return dialog

    def test_prompt_dialog(self):
        dlg = dialogs.PromptDialog(self.app, "新建分组", "分组名称：", "技术")
        self.assertEqual(dlg.var.get(), "技术")
        self._run(dlg, "entry")

    def test_choice_dialog(self):
        dlg = dialogs.ChoiceDialog(self.app, "移动到分组", "选择目标分组：", ["未分组", "科技资讯"])
        self._run(dlg, "listbox")

    def test_settings_dialog_result(self):
        dlg = dialogs.SettingsDialog(self.app)
        dlg.theme_var.set("亮色")
        dlg.size_var.set(18)
        dlg.refresh_var.set("45")
        dlg.proxy_var.set(" http://127.0.0.1:7890 ")
        dlg.keep_var.set("1200")
        dlg.images_var.set(False)
        dlg.notify_var.set(True)
        dlg.ok()
        self.assertEqual(dlg.result["theme"], "light")
        self.assertEqual(dlg.result["font_size"], "18")
        self.assertEqual(dlg.result["refresh_minutes"], "45")
        self.assertEqual(dlg.result["proxy"], "http://127.0.0.1:7890")
        self.assertEqual(dlg.result["max_articles"], "1200")
        self.assertEqual(dlg.result["load_images"], "0")
        self.assertEqual(dlg.result["notify"], "1")

    def test_settings_dialog_shows(self):
        dlg = dialogs.SettingsDialog(self.app)
        self._run(dlg)

    def test_add_feed_dialog_shows(self):
        dlg = dialogs.AddFeedDialog(self.app)
        self._run(dlg, "entry")


if __name__ == "__main__":
    unittest.main()
