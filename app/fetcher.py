"""抓取与解析：HTTP、订阅发现、RSS 2.0 / Atom / RDF 解析、正文提取。

只用标准库 + lxml（DSH 自带），不依赖 requests / feedparser。
"""
from __future__ import annotations

import email.utils
import gzip
import io
import re
import socket
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable

from lxml import etree, html as lhtml

from . import config
from .store import utcnow

XML_PARSER = etree.XMLParser(recover=True, huge_tree=True, resolve_entities=False, no_network=True)
HTML_PARSER = lhtml.HTMLParser(encoding=None, recover=True, remove_comments=True)


class FetchError(Exception):
    """抓取失败，消息面向用户。"""


@dataclass
class Response:
    url: str
    status: int
    headers: dict[str, str] = field(default_factory=dict)
    body: bytes = b""
    charset: str | None = None

    @property
    def content_type(self) -> str:
        return self.headers.get("content-type", "").lower()


# --------------------------------------------------------------------------- HTTP

def _opener(proxy: str = "", *, insecure: bool = False) -> urllib.request.OpenerDirector:
    handlers: list[Any] = []
    if proxy:
        handlers.append(urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
    else:
        # 显式清空，避免继承系统代理导致内网抓取时莫名其妙失败
        handlers.append(urllib.request.ProxyHandler({}))
    ctx = ssl.create_default_context()
    if insecure:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    handlers.append(urllib.request.HTTPSHandler(context=ctx))
    return urllib.request.build_opener(*handlers)


def _decode_body(raw: bytes, headers: dict[str, str]) -> tuple[bytes, str | None]:
    encoding = (headers.get("content-encoding") or "").lower()
    if "gzip" in encoding:
        try:
            raw = gzip.GzipFile(fileobj=io.BytesIO(raw)).read()
        except OSError:
            pass
    elif "deflate" in encoding:
        try:
            raw = zlib.decompress(raw)
        except zlib.error:
            try:
                raw = zlib.decompress(raw, -zlib.MAX_WBITS)
            except zlib.error:
                pass
    charset = None
    ctype = headers.get("content-type", "")
    m = re.search(r"charset=([\w\-]+)", ctype, re.I)
    if m:
        charset = m.group(1).lower()
    return raw, charset


def http_get(url: str, *, etag: str | None = None, modified: str | None = None,
             proxy: str = "", ua: str = "", timeout: int = 25,
             max_bytes: int = 16 * 1024 * 1024) -> Response:
    """GET 一个 URL，支持条件请求（304）与常见压缩。失败抛 FetchError。"""
    headers = {
        "User-Agent": ua or config.DEFAULTS["ua"],
        "Accept": "application/rss+xml, application/atom+xml, application/xml, "
                  "text/xml;q=0.9, text/html;q=0.8, */*;q=0.5",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate",
        "Cache-Control": "no-cache",
    }
    if etag:
        headers["If-None-Match"] = etag
    if modified:
        headers["If-Modified-Since"] = modified

    last_error: Exception | None = None
    for attempt, insecure in ((1, False), (2, True)):
        req = urllib.request.Request(url, headers=headers, method="GET")
        try:
            with _opener(proxy, insecure=insecure).open(req, timeout=timeout) as resp:
                raw = resp.read(max_bytes + 1)[:max_bytes]
                hdrs = {k.lower(): v for k, v in resp.headers.items()}
                body, charset = _decode_body(raw, hdrs)
                return Response(url=resp.geturl(), status=resp.status, headers=hdrs,
                                body=body, charset=charset)
        except urllib.error.HTTPError as exc:
            if exc.code == 304:
                return Response(url=url, status=304,
                                headers={k.lower(): v for k, v in (exc.headers or {}).items()})
            if exc.code in (401, 403):
                raise FetchError(f"HTTP {exc.code}：站点拒绝访问（可能需要代理或该源已失效）") from None
            if exc.code == 404:
                raise FetchError("HTTP 404：订阅地址不存在") from None
            raise FetchError(f"HTTP {exc.code} {exc.reason}") from None
        except ssl.SSLError as exc:
            last_error = exc
            if attempt == 2:
                raise FetchError(f"TLS 握手失败：{exc}") from None
            continue
        except (socket.timeout, TimeoutError):
            raise FetchError(f"连接超时（{timeout}s）") from None
        except urllib.error.URLError as exc:
            last_error = exc
            reason = getattr(exc, "reason", exc)
            if isinstance(reason, ssl.SSLError) and attempt == 1:
                continue
            raise FetchError(_humanize_net_error(reason)) from None
        except (ConnectionError, OSError) as exc:
            last_error = exc
            if attempt == 1:
                continue
            raise FetchError(_humanize_net_error(exc)) from None
    raise FetchError(_humanize_net_error(last_error))


def _humanize_net_error(err: Exception | None) -> str:
    text = str(err or "")
    if "Name or service not known" in text or "getaddrinfo" in text:
        return "域名解析失败：请检查网络或代理设置"
    if "Connection refused" in text or "actively refused" in text:
        return "连接被拒绝：目标站点不可达，或代理端口不对"
    if "certificate" in text.lower():
        return "证书校验失败：站点证书异常"
    if "timed out" in text.lower():
        return "连接超时：可能需要代理"
    return f"网络错误：{text or '未知原因'}"


# --------------------------------------------------------------------------- 工具

def localname(tag: Any) -> str:
    if not isinstance(tag, str):
        return ""
    return tag.rsplit("}", 1)[-1].split(":")[-1].lower()


def _first_text(el, *names: str) -> str:
    for child in el.iter():
        if localname(child.tag) in names and child is not el:
            text = "".join(child.itertext()).strip()
            if text:
                return text
    return ""


def _inner_html(el) -> str:
    if el is None:
        return ""
    try:
        parts = [etree.tostring(c, encoding="unicode", method="html") for c in el]
        return "".join(parts).strip() or (el.text or "").strip()
    except Exception:
        return (el.text or "").strip()


def strip_tags(value: str) -> str:
    if not value:
        return ""
    if "<" in value and ">" in value:
        try:
            frag = lhtml.fragment_fromstring(value, create_parent="div")
            value = frag.text_content()
        except Exception:
            value = re.sub(r"<[^>]+>", " ", value)
    value = lhtml.unescape(value) if hasattr(lhtml, "unescape") else value
    return re.sub(r"\s+", " ", value).strip()


BLOCK_TAGS = {
    "p", "div", "br", "li", "ul", "ol", "tr", "td", "th", "table", "h1", "h2", "h3",
    "h4", "h5", "h6", "blockquote", "pre", "section", "article", "figure", "figcaption",
    "hr", "dd", "dt", "dl", "header", "footer",
}
SKIP_TAGS = {"script", "style", "noscript", "iframe", "svg", "form", "nav", "aside", "footer", "header"}


def html_to_text(fragment: str, limit: int = 60000) -> str:
    """把 HTML 片段转成保留段落结构的纯文本。"""
    if not fragment:
        return ""
    try:
        root = lhtml.fragment_fromstring(fragment, create_parent="div", parser=HTML_PARSER)
    except Exception:
        return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", fragment)).strip()

    parts: list[str] = []

    def walk(el) -> None:
        tag = localname(el.tag)
        if tag in SKIP_TAGS:
            return
        if tag in BLOCK_TAGS:
            parts.append("\n")
        if el.text:
            parts.append(el.text)
        for child in el:
            walk(child)
        if tag in BLOCK_TAGS:
            parts.append("\n")
        if el.tail:
            parts.append(el.tail)

    walk(root)
    text = "".join(parts).replace("\r", "")
    text = "\n".join(re.sub(r"[ \t\u00a0]+", " ", line).strip() for line in text.split("\n"))
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text[:limit]


def parse_date(value: str | None) -> str | None:
    """各种日期格式 → UTC ISO 字符串。"""
    if not value:
        return None
    value = value.strip()
    if not value:
        return None
    dt: datetime | None = None
    try:
        dt = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError, IndexError):
        dt = None
    if dt is None:
        cleaned = re.sub(r"\.\d+", "", value.replace("Z", "+00:00"))
        try:
            dt = datetime.fromisoformat(cleaned)
        except ValueError:
            dt = None
    if dt is None:
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S", "%Y-%m-%d %H:%M",
                    "%Y/%m/%d %H:%M", "%Y-%m-%d", "%Y/%m/%d", "%d %b %Y %H:%M:%S"):
            try:
                dt = datetime.strptime(value[:len(fmt) + 4].strip(), fmt)
                break
            except ValueError:
                continue
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def absolutize(base: str, href: str) -> str:
    if not href:
        return ""
    try:
        return urllib.parse.urljoin(base, href.strip())
    except ValueError:
        return href


def decode_markup(data: bytes) -> str:
    """把网页字节解码成 str：先尊重 meta/xml 里声明的编码，再试 utf-8 / gb18030。"""
    if not data:
        return ""
    head = data[:4096].decode("ascii", "ignore")
    match = re.search(r"""(?:charset|encoding)\s*=\s*["']?([\w\-]+)""", head, re.I)
    if match:
        enc = match.group(1).lower()
        if enc in ("gb2312", "gbk", "gb18030"):
            enc = "gb18030"
        try:
            return data.decode(enc)
        except (LookupError, UnicodeDecodeError):
            pass
    for enc in ("utf-8", "gb18030"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", "replace")


def absolutize_tree(doc, base_url: str) -> None:
    """把文档里的相对链接补成绝对地址（lxml 自带的对 /rel 这种不生效）。"""
    if not base_url:
        return
    for el in doc.iter():
        if not isinstance(el.tag, str):
            continue
        for attr in ("href", "src", "poster"):
            value = (el.get(attr) or "").strip()
            if not value or value.startswith(("data:", "javascript:", "mailto:", "#")):
                continue
            full = absolutize(base_url, value)
            if full != value:
                el.set(attr, full)


# --------------------------------------------------------------------------- 订阅解析

def _entry_from_element(item, base_url: str, feed_is_atom: bool) -> dict:
    title = strip_tags(_first_text(item, "title"))
    link = ""
    for child in item.iter():
        if localname(child.tag) != "link":
            continue
        rel = (child.get("rel") or "alternate").lower()
        href = child.get("href")
        if href and rel in ("alternate", ""):
            link = absolutize(base_url, href)
            break
        if (child.text or "").strip() and not href:
            link = absolutize(base_url, child.text.strip())
            break
    guid = _first_text(item, "guid", "id") or link or title
    summary_raw = _inner_html(_first_child(item, "summary", "description"))
    content_raw = _inner_html(_first_child(item, "encoded", "content"))
    if not content_raw:
        content_raw = summary_raw
    author = _first_text(item, "creator", "author")
    date_raw = _first_text(item, "pubdate", "published", "updated", "date", "issued")
    entry = {
        "guid": guid.strip()[:900],
        "title": title,
        "url": link,
        "author": strip_tags(author)[:120],
        "published": parse_date(date_raw),
        "summary": html_to_text(summary_raw, 4000),
        "content": html_to_text(content_raw),
        "content_html": content_raw,
    }
    if feed_is_atom and not entry["content"]:
        entry["content"] = entry["summary"]
        entry["content_html"] = summary_raw
    return entry


def _first_child(item, *names: str):
    wanted = {n.lower() for n in names}
    for child in item:
        if localname(child.tag) in wanted:
            return child
    return None


def parse_feed(data: bytes, base_url: str) -> tuple[dict, list[dict]]:
    """返回 (feed_meta, entries)。"""
    if not data or not data.strip():
        raise FetchError("响应为空")
    root = None
    for encoding in ("utf-8", "gb18030"):
        try:
            root = etree.fromstring(data, parser=XML_PARSER)
            break
        except etree.XMLSyntaxError:
            try:
                root = etree.fromstring(data.decode(encoding, "replace").encode("utf-8"),
                                        parser=XML_PARSER)
                break
            except (etree.XMLSyntaxError, UnicodeError):
                continue
    if root is None:
        # 有些站点把 HTML 错误页当订阅返回
        raise FetchError("返回内容不是合法的 RSS/Atom（可能是网页或验证页）")

    kind = localname(root.tag)
    meta = {"title": "", "site_url": "", "description": "", "kind": kind or "rss"}
    entries: list[dict] = []
    feed_is_atom = kind == "feed"

    if kind == "feed":
        meta["title"] = strip_tags(_first_text(root, "title"))
        for child in root:
            if localname(child.tag) == "link" and (child.get("rel") or "alternate") == "alternate":
                meta["site_url"] = absolutize(base_url, child.get("href") or "")
                break
        meta["description"] = strip_tags(_first_text(root, "subtitle"))
        entries = [_entry_from_element(e, base_url, True)
                   for e in root if localname(e.tag) == "entry"]
    else:
        channel = None
        for child in root:
            if localname(child.tag) == "channel":
                channel = child
                break
        source = channel if channel is not None else root
        meta["title"] = strip_tags(_first_text(source, "title"))
        meta["description"] = strip_tags(_first_text(source, "description"))
        link_el = _first_child(source, "link")
        if link_el is not None:
            meta["site_url"] = absolutize(base_url, (link_el.text or "").strip()
                                          or link_el.get("href") or "")
        if meta["site_url"] and link_el is not None and link_el.get("href"):
            meta["site_url"] = absolutize(base_url, link_el.get("href"))
        items = [e for e in root.iter() if localname(e.tag) == "item"]
        entries = [_entry_from_element(e, base_url, False) for e in items]

    # 丢弃既无标题又无链接的坏条目，按时间倒序
    entries = [e for e in entries if (e["title"] or e["url"]) and e["guid"]]
    entries.sort(key=lambda e: e["published"] or "", reverse=True)
    if not meta["title"]:
        meta["title"] = urllib.parse.urlsplit(base_url).netloc
    return meta, entries


# --------------------------------------------------------------------------- 订阅发现

FEED_TYPES = ("application/rss+xml", "application/atom+xml", "application/rdf+xml",
              "application/xml", "text/xml")


def looks_like_feed(body: bytes) -> bool:
    head = body[:400].lstrip().lower()
    return head.startswith(b"<?xml") or b"<rss" in head or b"<feed" in head or b"<rdf" in head


def discover(url: str, *, proxy: str = "", ua: str = "",
             timeout: int = 20) -> dict:
    """给任意网页或订阅地址，返回 {feeds:[{url,title}], title, is_feed}。"""
    resp = http_get(url, proxy=proxy, ua=ua, timeout=timeout)
    if resp.status >= 400:
        raise FetchError(f"HTTP {resp.status}")
    return discover_from_markup(resp.body, resp.url)


def discover_from_markup(body: bytes, base_url: str) -> dict:
    """从已经下载好的内容里找订阅地址（方便离线测试）。"""
    if looks_like_feed(body):
        meta, _ = parse_feed(body, base_url)
        return {"is_feed": True, "title": meta["title"], "site_url": meta["site_url"] or base_url,
                "feeds": [{"url": base_url, "title": meta["title"]}]}

    try:
        doc = lhtml.document_fromstring(decode_markup(body))
    except Exception as exc:
        raise FetchError(f"页面无法解析：{exc}") from None
    absolutize_tree(doc, base_url)

    title = ""
    node = doc.find(".//title")
    if node is not None and node.text:
        title = strip_tags(node.text)
    candidates: list[dict] = []
    seen: set[str] = set()
    for link in doc.iter("link"):
        rel = (link.get("rel") or "").lower()
        if "alternate" not in rel:
            continue
        ctype = (link.get("type") or "").lower()
        href = link.get("href")
        if not href:
            continue
        if any(t in ctype for t in FEED_TYPES) or href.lower().endswith((".rss", ".xml", ".atom")):
            full = absolutize(base_url, href)
            if full not in seen:
                seen.add(full)
                candidates.append({"url": full, "title": (link.get("title") or "").strip()})
    for anchor in doc.iter("a"):
        href = (anchor.get("href") or "").lower()
        if href.endswith(("/feed", "/rss", ".rss", "/atom.xml", "/feed.xml", "/rss.xml")):
            full = absolutize(base_url, anchor.get("href"))
            if full not in seen:
                seen.add(full)
                candidates.append({"url": full, "title": strip_tags(anchor.text_content())[:40]})
    if not candidates:
        raise FetchError("这个页面上没找到订阅链接，请直接填 RSS/Atom 地址")
    return {"is_feed": False, "title": title, "site_url": base_url, "feeds": candidates}


# --------------------------------------------------------------------------- 正文提取

BOOST_RE = re.compile(r"article|content|post|entry|main|body|text|markdown|story", re.I)
NEGATIVE_RE = re.compile(r"comment|share|sidebar|footer|header|nav|menu|advert|promo|related|"
                         r"recommend|subscribe|social|widget|banner|copyright|meta", re.I)


def extract_article(data: bytes, url: str, max_html: int = 400_000) -> dict:
    """从原始网页提取正文（readability 简化版）。"""
    try:
        doc = lhtml.document_fromstring(decode_markup(data))
    except Exception as exc:
        raise FetchError(f"网页解析失败：{exc}") from None
    absolutize_tree(doc, url)
    for bad in doc.xpath("//script|//style|//noscript|//iframe|//form|//svg|//nav"):
        bad.drop_tree()

    title = ""
    for xp in ("//meta[@property='og:title']/@content", "//meta[@name='twitter:title']/@content",
               "//h1//text()", "//title/text()"):
        found = doc.xpath(xp)
        if found and str(found[0]).strip():
            title = strip_tags(str(found[0]))
            break

    body = doc.body if doc.body is not None else doc
    best, best_score = None, -1.0
    for el in body.iter():
        if not isinstance(el.tag, str):
            continue
        text = el.text_content()
        n = len(text.strip())
        if n < 120:
            continue
        ident = f"{el.get('class') or ''} {el.get('id') or ''}"
        score = n * 0.6 + 25 * len(el.findall(".//p")) + 12 * len(el.findall(".//li"))
        if BOOST_RE.search(ident):
            score *= 1.6
        if NEGATIVE_RE.search(ident):
            score *= 0.35
        if score > best_score:
            best, best_score = el, score
    target = best if best is not None and len(best.text_content().strip()) > 200 else body

    for el in target.iter():
        if not isinstance(el.tag, str):
            continue
        for attr in list(el.attrib):
            if attr not in ("href", "src", "alt", "title", "colspan", "rowspan"):
                del el.attrib[attr]
    for el in target.xpath(".//a[@href]"):
        if not (el.text or "").strip() and el.get("href", "").startswith("javascript"):
            el.drop_tree()

    html_str = _inner_html(target)
    if len(html_str) > max_html:
        html_str = html_str[:max_html]
    text = html_to_text(html_str)
    if len(text) < 80:
        raise FetchError("没提取到正文（可能是图片站或需要登录）")
    return {"title": title, "html": html_str, "text": text}


# --------------------------------------------------------------------------- 刷新编排

def refresh_feed(store, feed: dict, settings: dict[str, str]) -> dict:
    """抓一个订阅源并写库。返回 {ok, new, error, title}。"""
    feed_id = int(feed["id"])
    proxy = settings.get("proxy", "") or ""
    ua = settings.get("ua", "") or ""
    try:
        resp = http_get(feed["url"], etag=feed.get("etag"), modified=feed.get("modified"),
                        proxy=proxy, ua=ua)
        if resp.status == 304:
            store.update_feed(feed_id, last_fetch=utcnow(), last_status="304", error=None)
            return {"ok": True, "new": 0, "error": "", "title": feed.get("title", "")}

        meta, entries = parse_feed(resp.body, resp.url)
        new = store.insert_articles(feed_id, entries)
        store.update_feed(
            feed_id,
            title=(feed.get("title") or meta["title"] or "")[:200],
            site_url=meta.get("site_url") or feed.get("site_url") or "",
            last_fetch=utcnow(), last_status=str(resp.status), error=None,
            etag=resp.headers.get("etag", ""), modified=resp.headers.get("last-modified", ""),
        )
        keep = int(settings.get("max_articles", "3000") or 0)
        if keep:
            store.prune(feed_id, keep)
        return {"ok": True, "new": new, "error": "", "title": meta["title"]}
    except FetchError as exc:
        store.update_feed(feed_id, last_fetch=utcnow(), last_status="error", error=str(exc)[:300])
        return {"ok": False, "new": 0, "error": str(exc), "title": feed.get("title", "")}
    except Exception as exc:  # 网络层之外的意外，也要保证不拖垮整轮刷新
        message = f"内部错误：{type(exc).__name__}: {exc}"
        store.update_feed(feed_id, last_fetch=utcnow(), last_status="error", error=message[:300])
        return {"ok": False, "new": 0, "error": message, "title": feed.get("title", "")}


def fetch_full_text(article: dict, settings: dict[str, str]) -> dict:
    """补全单篇正文。"""
    if not article.get("url"):
        raise FetchError("这篇文章没有原文链接")
    resp = http_get(article["url"], proxy=settings.get("proxy", "") or "",
                    ua=settings.get("ua", "") or "")
    return extract_article(resp.body, resp.url)
