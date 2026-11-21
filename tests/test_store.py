"""数据层测试：订阅、文章去重、范围查询、已读/收藏、裁剪。"""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.store import Store  # noqa: E402
from helpers import temp_path  # noqa: E402


class StoreTest(unittest.TestCase):
    def setUp(self):
        self.db = temp_path(".db")
        self.store = Store(self.db)

    def tearDown(self):
        self.store.close()
        for suffix in ("", "-wal", "-shm"):
            try:
                os.remove(self.db + suffix)
            except OSError:
                pass

    def _feed(self, title="源", url="https://example.com/feed"):
        return self.store.add_feed(url, title=title, site_url="https://example.com")

    def test_folders_and_feeds(self):
        fid = self.store.add_folder("技术")
        self.assertEqual(self.store.add_folder("技术"), fid)  # 幂等
        feed_id = self._feed()
        self.store.move_feed(feed_id, fid)
        self.assertEqual(self.store.feed(feed_id)["folder_id"], fid)
        self.assertEqual(len(self.store.feeds()), 1)
        self.store.rename_folder(fid, "技术圈")
        self.assertEqual(self.store.folders()[0]["name"], "技术圈")
        self.store.delete_folder(fid)
        self.assertIsNone(self.store.feed(feed_id)["folder_id"])

    def test_dedupe_and_scopes(self):
        fid = self._feed()
        rows = [
            {"guid": "a", "title": "第一篇", "url": "https://example.com/a",
             "published": "2024-05-01T08:00:00Z", "summary": "摘要 A"},
            {"guid": "b", "title": "第二篇", "url": "https://example.com/b",
             "published": "2024-05-02T08:00:00Z", "summary": "摘要 B"},
        ]
        self.assertEqual(self.store.insert_articles(fid, rows), 2)
        self.assertEqual(self.store.insert_articles(fid, rows), 0)
        articles = self.store.article_list(("all", None))
        self.assertEqual([a["title"] for a in articles], ["第二篇", "第一篇"])

        first = articles[1]
        self.store.mark_read([first["id"]])
        self.assertEqual(len(self.store.article_list(("all", None), unread_only=True)), 1)
        self.assertEqual(self.store.scope_counts()["unread"], 1)

        self.store.toggle_star(first["id"])
        self.assertTrue(self.store.article(first["id"])["is_starred"])
        self.assertEqual(len(self.store.article_list(("starred", None))), 1)
        self.assertEqual(len(self.store.article_list(("feed", fid))), 2)

        self.store.mark_all_read(("all", None))
        self.assertEqual(self.store.scope_counts()["unread"], 0)

    def test_search_escapes_like(self):
        fid = self._feed()
        self.store.insert_articles(fid, [
            {"guid": "x", "title": "100% 纯果汁", "url": "https://e.com/x"},
            {"guid": "y", "title": "普通文章", "url": "https://e.com/y"},
        ])
        hits = self.store.article_list(("all", None), search="100%")
        self.assertEqual(len(hits), 1)
        self.assertEqual(self.store.article_count(("all", None), search="%"), 1)

    def test_prune(self):
        fid = self._feed()
        for index in range(10):
            self.store.insert_articles(fid, [{
                "guid": f"g{index}", "title": f"第{index}篇", "url": f"https://e.com/{index}",
                "published": f"2024-04-{index + 1:02d}T00:00:00Z"}])
        self.store.prune(fid, 5)
        self.assertEqual(self.store.article_count(("all", None)), 5)

    def test_settings_roundtrip(self):
        self.store.set_settings({"theme": "light", "font_size": "17"})
        self.assertEqual(self.store.get_setting("theme"), "light")
        self.assertEqual(self.store.settings()["font_size"], "17")

    def test_delete_feed_cascades(self):
        fid = self._feed()
        self.store.insert_articles(fid, [{"guid": "z", "title": "文章", "url": "https://e.com/z"}])
        self.store.delete_feed(fid)
        self.assertEqual(self.store.article_count(("all", None)), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
