"""解析层测试：RSS/Atom 解析、正文抽取、HTML 转文本、日期、OPML。"""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import fetcher, opml  # noqa: E402

RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/">
  <channel>
    <title>示例播客</title>
    <link>https://example.com/</link>
    <description>描述</description>
    <item>
      <title>文章一</title>
      <link>/post/1</link>
      <guid isPermaLink="false">post-1</guid>
      <pubDate>Wed, 01 May 2024 08:00:00 +0800</pubDate>
      <author>张三</author>
      <description>&lt;p&gt;这是&lt;b&gt;摘要&lt;/b&gt;。&lt;/p&gt;</description>
      <content:encoded><![CDATA[<p>这是<strong>正文</strong>。</p><p>第二段。</p>]]></content:encoded>
    </item>
    <item>
      <title>文章二</title>
      <link>https://example.com/post/2</link>
      <guid>post-2</guid>
      <pubDate>Thu, 02 May 2024 08:00:00 GMT</pubDate>
      <description>纯文本摘要</description>
    </item>
  </channel>
</rss>
""".encode("utf-8")

ATOM = """<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Atom 源</title>
  <link href="https://atom.example.com/"/>
  <entry>
    <title>原子文章</title>
    <link rel="alternate" href="/a/1"/>
    <id>tag:atom.example.com,2024:1</id>
    <updated>2024-05-03T10:00:00Z</updated>
    <author><name>李四</name></author>
    <summary>简短摘要</summary>
    <content type="html">&lt;p&gt;原子&lt;em&gt;正文&lt;/em&gt;&lt;/p&gt;</content>
  </entry>
</feed>
""".encode("utf-8")

RDF = """<?xml version="1.0"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
         xmlns="http://purl.org/rss/1.0/" xmlns:dc="http://purl.org/dc/elements/1.1/">
  <channel rdf:about="https://rdf.example.com/">
    <title>RDF 源</title>
    <link>https://rdf.example.com/</link>
  </channel>
  <item rdf:about="https://rdf.example.com/1">
    <title>RDF 文章</title>
    <link>https://rdf.example.com/1</link>
    <dc:date>2024-05-04T12:00:00Z</dc:date>
    <description>RDF 摘要</description>
  </item>
</rdf:RDF>
""".encode("utf-8")

HTML = """<!doctype html><html><head>
<title>我的博客</title>
<link rel="alternate" type="application/rss+xml" title="RSS" href="/feed.xml">
</head><body><a href="/atom.xml">Atom</a></body></html>
""".encode("utf-8")

ARTICLE_HTML = """<!doctype html><html><head><title>文章标题</title></head><body>
<nav>导航栏</nav>
<article>
  <h1>文章标题</h1>
  <p>第一段内容，足够长，用于正文抽取测试。</p>
  <p>第二段内容，也足够长，用于正文抽取测试。</p>
</article>
<footer>版权</footer>
</body></html>
""".encode("utf-8")


class ParseFeedTest(unittest.TestCase):
    def test_rss(self):
        meta, entries = fetcher.parse_feed(RSS, "https://example.com/feed")
        self.assertEqual(meta["title"], "示例播客")
        self.assertEqual(meta["site_url"], "https://example.com/")
        self.assertEqual(len(entries), 2)
        newest, older = entries  # 按时间倒序
        self.assertEqual(newest["title"], "文章二")
        self.assertEqual(newest["published"], "2024-05-02T08:00:00Z")
        self.assertEqual(older["title"], "文章一")
        self.assertEqual(older["url"], "https://example.com/post/1")
        self.assertEqual(older["author"], "张三")
        self.assertEqual(older["published"], "2024-05-01T00:00:00Z")
        self.assertIn("正文", older["content"])
        self.assertIn("摘要", older["summary"])

    def test_atom(self):
        meta, entries = fetcher.parse_feed(ATOM, "https://atom.example.com/feed")
        self.assertEqual(meta["title"], "Atom 源")
        self.assertEqual(len(entries), 1)
        entry = entries[0]
        self.assertEqual(entry["title"], "原子文章")
        self.assertEqual(entry["url"], "https://atom.example.com/a/1")
        self.assertEqual(entry["author"], "李四")
        self.assertEqual(entry["published"], "2024-05-03T10:00:00Z")
        self.assertIn("正文", entry["content"])
        self.assertEqual(entry["guid"], "tag:atom.example.com,2024:1")

    def test_rdf(self):
        meta, entries = fetcher.parse_feed(RDF, "https://rdf.example.com/feed")
        self.assertEqual(meta["title"], "RDF 源")
        self.assertEqual(entries[0]["title"], "RDF 文章")
        self.assertEqual(entries[0]["published"], "2024-05-04T12:00:00Z")

    def test_html_to_text(self):
        text = fetcher.html_to_text("<p>一行</p><p>二行<br>三行</p><script>x</script>")
        self.assertIn("一行", text)
        self.assertIn("二行", text)
        self.assertIn("三行", text)
        self.assertNotIn("<", text)

    def test_dates(self):
        self.assertEqual(fetcher.parse_date("2024-05-01T08:00:00+08:00"),
                         "2024-05-01T00:00:00Z")
        self.assertEqual(fetcher.parse_date("2024-05-01 08:00:00"), "2024-05-01T08:00:00Z")
        self.assertEqual(fetcher.parse_date("Wed, 01 May 2024 00:00:00 GMT"),
                         "2024-05-01T00:00:00Z")
        self.assertIsNone(fetcher.parse_date("不是日期"))


class DiscoverTest(unittest.TestCase):
    def test_html_page(self):
        data = fetcher.discover_from_markup(HTML, "https://blog.example.com/")
        urls = [item["url"] for item in data["feeds"]]
        self.assertIn("https://blog.example.com/feed.xml", urls)
        self.assertIn("https://blog.example.com/atom.xml", urls)

    def test_xml_is_feed(self):
        data = fetcher.discover_from_markup(RSS, "https://example.com/feed")
        self.assertTrue(data["is_feed"])
        self.assertEqual(data["title"], "示例播客")
        self.assertEqual(data["feeds"][0]["url"], "https://example.com/feed")


class ExtractTest(unittest.TestCase):
    def test_extract_article(self):
        filler_a = "第一段内容足够长，用于正文抽取测试。".encode("utf-8") * 20
        filler_b = "第二段内容也足够长，用于正文抽取测试。".encode("utf-8") * 20
        page = ("<html><head><title>文章标题</title></head><body><article>"
                "<h1>文章标题</h1><p>").encode("utf-8")
        page += filler_a + "</p><p>".encode("utf-8") + filler_b + "</p></article></body></html>".encode("utf-8")
        result = fetcher.extract_article(page, "https://example.com/p/1")
        self.assertIn("第一段内容", result["html"])
        self.assertIn("第二段内容", result["html"])
        self.assertNotIn("导航栏", result["html"])
        self.assertNotIn("<script", result["html"])
        self.assertEqual(result["title"], "文章标题")

    def test_extract_article_keeps_links_absolute(self):
        filler = "填充文字足够长，用来确保正文被识别。".encode("utf-8") * 30
        page = ("<html><body><article><p>").encode("utf-8") + filler
        page += "</p><p><a href='/rel'>link</a></p></article></body></html>".encode("utf-8")
        result = fetcher.extract_article(page, "https://example.com/a/b")
        self.assertIn('href="https://example.com/rel"', result["html"])


class OpmlTest(unittest.TestCase):
    def test_roundtrip(self):
        text = opml.build_opml([{"id": 1, "name": "技术"}],
                               [{"title": "源A", "url": "https://a.com/feed", "folder_id": 1},
                                {"title": "源B", "url": "https://b.com/feed", "folder_id": None}])
        items = opml.parse_opml(text)
        self.assertEqual(len(items), 2)
        by_url = {item["url"]: item for item in items}
        self.assertEqual(by_url["https://a.com/feed"]["folder"], "技术")
        self.assertIsNone(by_url["https://b.com/feed"]["folder"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
