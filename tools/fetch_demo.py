"""抓几个真实订阅源写进 data/reader.db，用于人工验收 / 截图。

用法： python tools/fetch_demo.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import config, fetcher  # noqa: E402
from app.store import Store  # noqa: E402

FEEDS = [
    ("https://sspai.com/feed", "少数派"),
    ("https://www.ithome.com/rss/", "IT之家"),
    ("https://www.oschina.net/news/rss", "开源中国"),
    ("https://www.solidot.org/index.rss", "Solidot"),
    ("https://blog.codingnow.com/atom.xml", "云风的 BLOG"),
]


def main() -> int:
    config.ensure_dirs()
    store = Store(config.DB_PATH)
    settings = {**config.DEFAULTS, **store.settings()}
    folder_id = store.add_folder("科技资讯") if not any(
        f["name"] == "科技资讯" for f in store.folders()
    ) else next(f["id"] for f in store.folders() if f["name"] == "科技资讯")

    # 清掉早期探测时留下的抓取失败订阅
    for bad in ("https://www.zhihu.com/rss", "https://feeds.feedburner.com/ruanyifeng"):
        row = store.feed_by_url(bad)
        if row:
            store.delete_feed(int(row["id"]))

    for url, title in FEEDS:
        try:
            if store.feed_by_url(url) is None:
                store.add_feed(url, title, "", folder_id)
            feed = store.feed_by_url(url)
            if feed["folder_id"] != folder_id:
                store.move_feed(int(feed["id"]), folder_id)
            result = fetcher.refresh_feed(store, feed, settings)
            print(f"{title:<14} ok={result['ok']} new={result['new']} "
                  f"title={result.get('title')!r} err={result.get('error')!r}")
        except Exception as exc:  # noqa: BLE001
            print(f"{title:<14} 失败：{exc}")

    print("文章总数：", store.stats()["articles"])
    # 取第一篇做正文提取，验证 readability 走通
    rows = store.article_list(("all", None), limit=1)
    if rows:
        article = store.article(rows[0]["id"])
        try:
            data = fetcher.extract_article(
                fetcher.http_get(article["url"], proxy="", ua=settings["ua"]).body,
                article["url"],
            )
            print("正文提取 OK：", data["title"], len(data["text"]), "字")
        except Exception as exc:  # noqa: BLE001
            print("正文提取失败：", exc)
    store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
