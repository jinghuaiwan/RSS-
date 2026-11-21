"""OPML 2.0 导入导出。"""
from __future__ import annotations

from lxml import etree

from .fetcher import localname


def parse_opml(data: bytes | str) -> list[dict]:
    """返回 [{url, title, folder}]；folder 为空表示未分组（支持多级嵌套，取最内层名）。"""
    if isinstance(data, str):
        data = data.encode("utf-8")
    parser = etree.XMLParser(recover=True, resolve_entities=False, no_network=True)
    root = etree.fromstring(data, parser=parser)
    body = None
    for child in root.iter():
        if localname(child.tag) == "body":
            body = child
            break
    if body is None:
        body = root

    result: list[dict] = []
    seen: set[str] = set()

    def walk(node, folder: str) -> None:
        for child in node:
            if localname(child.tag) != "outline":
                continue
            url = (child.get("xmlUrl") or child.get("xmlurl") or "").strip()
            title = (child.get("title") or child.get("text") or "").strip()
            if url:
                if url not in seen:
                    seen.add(url)
                    result.append({"url": url, "title": title, "folder": folder or None})
            else:
                name = (child.get("title") or child.get("text") or "").strip()
                walk(child, name or folder)

    walk(body, "")
    return result


def build_opml(folders: list[dict], feeds: list[dict]) -> str:
    root = etree.Element("opml", version="2.0")
    head = etree.SubElement(root, "head")
    etree.SubElement(head, "title").text = "RSS 阅读器 订阅列表"
    body = etree.SubElement(root, "body")

    by_folder: dict[int | None, list[dict]] = {}
    for feed in feeds:
        by_folder.setdefault(feed.get("folder_id"), []).append(feed)

    for feed in by_folder.get(None, []):
        _outline(body, feed["title"] or feed["url"], feed["url"], feed.get("site_url") or "")

    for folder in folders:
        node = etree.SubElement(body, "outline", text=folder["name"], title=folder["name"])
        for feed in by_folder.get(folder["id"], []):
            _outline(node, feed["title"] or feed["url"], feed["url"], feed.get("site_url") or "")

    return etree.tostring(root, pretty_print=True, xml_declaration=True,
                          encoding="utf-8").decode("utf-8")


def _outline(parent, title: str, url: str, site_url: str) -> None:
    etree.SubElement(parent, "outline", type="rss", text=title, title=title,
                     xmlUrl=url, htmlUrl=site_url)
