"""界面冒烟测试：真实建一次主窗口，检查三栏、列表、主题切换不炸。

不依赖网络：先把数据目录指向临时位置，只加一条假订阅。
"""
from __future__ import annotations

import os
import shutil
import sys
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import config  # noqa: E402
from helpers import temp_path  # noqa: E402


class UiSmokeTest(unittest.TestCase):
    def test_window_builds(self):
        db_path = Path(temp_path(".db"))
        cache_dir = Path(temp_path("-cache"))
        log_path = Path(temp_path(".log"))
        original = (config.DB_PATH, config.CACHE_DIR, config.LOG_PATH)
        config.DB_PATH = db_path
        config.CACHE_DIR = cache_dir
        config.LOG_PATH = log_path
        try:
            from app.store import Store
            from app.ui import App

            store = Store(db_path)
            app = App(store)
            try:
                app.update()
                self.assertTrue(app.sidebar.winfo_exists())
                self.assertTrue(app.alist.winfo_exists())
                self.assertTrue(app.text.winfo_exists())
                feed_id = app.store.add_feed("https://example.com/feed", title="测试源")
                app.store.insert_articles(feed_id, [{
                    "guid": "1", "title": "测试文章", "url": "https://example.com/1",
                    "summary": "这是摘要", "published": "2024-05-01T00:00:00Z"}])
                app.reload_sidebar()
                app.load_articles(reset=True)
                app.update()
                self.assertEqual(len(app.alist.get_children()), 1)
                self.assertIn("测试文章", app.r_title.cget("text"))
                app.set_filter(True)
                app.update()
                app.toggle_theme()
                app.update()
                self.assertEqual(app.settings.get("theme"), "light")
            finally:
                app.destroy()
                app.store.close()
        finally:
            (config.DB_PATH, config.CACHE_DIR, config.LOG_PATH) = original
            for path in (db_path, Path(str(db_path) + "-wal"), Path(str(db_path) + "-shm"),
                         log_path):
                try:
                    path.unlink()
                except OSError:
                    pass
            shutil.rmtree(cache_dir, ignore_errors=True)
