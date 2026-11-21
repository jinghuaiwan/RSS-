import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app import fetcher  # noqa: E402

CANDIDATES = [
    ("https://www.oschina.net/news/rss", "开源中国"),
    ("https://www.solidot.org/index.rss", "Solidot"),
    ("https://feeds.bbci.co.uk/zhongwen/simp/rss.xml", "BBC 中文"),
    ("https://blog.codingnow.com/atom.xml", "云风"),
    ("https://www.cnbeta.com.tw/backend.php", "cnBeta"),
]
for url, name in CANDIDATES:
    try:
        resp = fetcher.http_get(url, timeout=15)
        meta, entries = fetcher.parse_feed(resp.body, resp.url)
        print(f"OK   {name:<10} status={resp.status} title={meta.get('title')!r} entries={len(entries)}")
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL {name:<10} {type(exc).__name__}: {exc}")
