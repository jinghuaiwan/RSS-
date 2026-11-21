"""渲染层测试：把 HTML 画进 tk.Text，检查标题/段落/链接/列表/表格是否正确落地。"""
from __future__ import annotations

import os
import sys
import tkinter as tk
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import render  # noqa: E402
from app.theme import PALETTES, reader_fonts, ui_font  # noqa: E402

HTML = """
<h1>一级标题</h1>
<p>正文第一段，包含 <strong>加粗</strong> 与 <em>斜体</em>，还有一个
<a href="/relative/link">站内链接</a>。</p>
<ul><li>列表一</li><li>列表二</li></ul>
<ol><li>编号一</li><li>编号二</li></ol>
<blockquote>这是一段引用。</blockquote>
<pre><code>print("hello")</code></pre>
<table><tr><td>格1</td><td>格2</td></tr></table>
<hr>
<p>最后一段。</p>
"""


class RenderTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = tk.Tk()
        cls.root.withdraw()
        cls.pal = PALETTES["dark"]
        cls.fonts = reader_fonts(cls.root, 15)

    @classmethod
    def tearDownClass(cls):
        cls.root.destroy()

    def _render(self, article):
        text = tk.Text(self.root)
        render.render_article(text, article, self.pal, self.fonts, gen=1,
                              images=False, loader=None, on_link=lambda url: None)
        content = text.get("1.0", "end")
        text.destroy()
        return content

    def test_html_rendering(self):
        content = self._render({"content_html": HTML, "url": "https://example.com/post/1"})
        for expected in ("一级标题", "正文第一段", "加粗", "斜体", "站内链接",
                         "列表一", "列表二", "编号一", "引用", "print", "格1", "最后一段"):
            self.assertIn(expected, content, f"缺少：{expected}")
        self.assertNotIn("<p>", content)
        self.assertNotIn("&amp;", content)

    def test_plain_text_fallback(self):
        content = self._render({"content": "纯文本第一段\n纯文本第二段"})
        self.assertIn("纯文本第一段", content)
        self.assertIn("纯文本第二段", content)

    def test_empty_article(self):
        content = self._render({})
        self.assertIn("没有正文", content)

    def test_links_are_registered(self):
        text = tk.Text(self.root)
        seen = []
        render.render_article(text, {"content_html": HTML, "url": "https://example.com/post/1"},
                              self.pal, self.fonts, gen=7, images=False,
                              on_link=seen.append)
        tags = [tag for tag in text.tag_names() if tag.startswith("link")]
        self.assertTrue(tags, "没有生成链接标签")
        text.destroy()

    def test_reading_minutes(self):
        self.assertGreaterEqual(render.reading_minutes("很短的文字"), 1)
        long_cn = "中文句子。" * 800
        self.assertGreater(render.reading_minutes(long_cn), 3)

    def test_images_placeholder_without_loader(self):
        content = self._render({"content_html": '<p>看图：</p><img src="/a.png" alt="示例">',
                                "url": "https://example.com/post"})
        self.assertIn("示例", content)


if __name__ == "__main__":
    unittest.main(verbosity=2)
