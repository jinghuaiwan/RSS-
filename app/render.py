"""把文章 HTML 渲染进 tk.Text：标题层级、列表、引用、代码、表格、链接、图片。"""
from __future__ import annotations

import re
import tkinter as tk

from lxml import html as lhtml

from .fetcher import absolutize, localname

MAX_CHARS = 150_000
SKIP_TAGS = {"script", "style", "noscript", "iframe", "svg", "form", "nav", "aside",
             "footer", "header", "button", "input", "video", "audio", "canvas"}
CONTAINER_BLOCKS = {"div", "section", "article", "main", "body", "figure", "dl", "dd", "dt"}
HEADINGS = {"h1": "h1", "h2": "h2", "h3": "h3", "h4": "h3", "h5": "h3", "h6": "h3"}


class _Ctx:
    def __init__(self, widget: tk.Text, pal: dict, fonts: dict, *, gen: int, base_url: str,
                 images: bool, loader, on_link):
        self.w = widget
        self.pal = pal
        self.fonts = fonts
        self.gen = gen
        self.base_url = base_url
        self.images = images
        self.loader = loader
        self.on_link = on_link
        self.used = 0
        self.trailing = 0
        self.image_count = 0
        self.link_count = 0
        self.links: dict[str, str] = {}

    def put(self, text: str, tags: tuple[str, ...] = ("body",)) -> None:
        if not text:
            return
        if "pre" not in tags and text != "\n":
            # HTML 里源码换行/缩进要折叠成一个空格，否则正文会莫名断行
            text = re.sub(r"[ \t\r\n]+", " ", text)
            if self.trailing or self.used == 0:
                text = text.lstrip(" ")
            if not text:
                return
        if self.used >= MAX_CHARS:
            return
        if self.used + len(text) > MAX_CHARS:
            text = text[: MAX_CHARS - self.used]
        self.w.insert("end", text, tags)
        self.used += len(text)
        if text.endswith("\n"):
            self.trailing = len(text) - len(text.rstrip("\n"))
        else:
            self.trailing = 0

    def newlines(self, count: int = 1) -> None:
        if self.used == 0 or self.trailing >= count:
            return
        pad = "\n" * (count - self.trailing)
        self.w.insert("end", pad)
        self.used += len(pad)
        self.trailing = count


def configure_tags(w: tk.Text, pal: dict, fonts: dict) -> None:
    w.configure(background=pal["bg"], foreground=pal["fg"], insertbackground=pal["fg"],
                selectbackground=pal["select"], selectforeground=pal["select_fg"],
                wrap="char", padx=26, pady=16, bd=0, highlightthickness=0,
                spacing1=0, spacing2=0, spacing3=0, tabs="28")
    w.tag_configure("body", font=fonts["body"], foreground=pal["fg"], spacing1=1, spacing3=7)
    w.tag_configure("p", font=fonts["body"], foreground=pal["fg"], spacing3=9)
    w.tag_configure("bold", font=fonts["body_b"])
    w.tag_configure("italic", font=fonts["body_i"])
    w.tag_configure("h1", font=fonts["h1"], foreground=pal["fg"], spacing1=16, spacing3=10)
    w.tag_configure("h2", font=fonts["h2"], foreground=pal["fg"], spacing1=14, spacing3=8)
    w.tag_configure("h3", font=fonts["h3"], foreground=pal["fg"], spacing1=10, spacing3=6)
    w.tag_configure("li", lmargin1=26, lmargin2=40, spacing3=5)
    w.tag_configure("li_prefix", font=fonts["body_b"], foreground=pal["accent"], lmargin1=26,
                    lmargin2=40)
    w.tag_configure("quote", lmargin1=22, lmargin2=22, rmargin=20, background=pal["quote_bg"],
                    foreground=pal["fg_soft"], spacing1=6, spacing3=6, font=fonts["body_i"])
    w.tag_configure("code", font=fonts["mono"], background=pal["code_bg"],
                    foreground=pal["code_fg"])
    w.tag_configure("pre", font=fonts["mono"], background=pal["code_bg"],
                    foreground=pal["code_fg"], lmargin1=18, lmargin2=18, rmargin=16,
                    spacing1=8, spacing3=8)
    w.tag_configure("link", foreground=pal["link"], underline=True)
    w.tag_configure("muted", foreground=pal["muted"], font=fonts["small"])
    w.tag_configure("caption", foreground=pal["muted"], font=fonts["small"], spacing3=10)
    w.tag_configure("hr", foreground=pal["border"])
    w.tag_configure("imgph", foreground=pal["faint"], font=fonts["small"], spacing1=6, spacing3=6)
    w.tag_configure("img", spacing1=6, spacing3=10)


def _text_of(el) -> str:
    text = "".join(el.itertext())
    return re.sub(r"\s+", " ", text).strip()


def _emit_image(ctx: _Ctx, el) -> None:
    src = (el.get("src") or "").strip()
    alt = (el.get("alt") or "").strip()
    if not src or src.startswith("data:"):
        return
    try:
        width_attr = int(float(el.get("width") or 0))
    except (TypeError, ValueError):
        width_attr = 0
    if 0 < width_attr < 60:
        return  # 统计像素 / 分隔线之类的小图
    if not ctx.images or ctx.loader is None or ctx.image_count >= 10:
        if alt:  # 不加载图片时至少留个说明，别让图凭空消失
            ctx.newlines(1)
            ctx.put(f"［图片：{alt}］", ("imgph",))
            ctx.put("\n")
        return
    ctx.image_count += 1
    tag = f"imgph{ctx.gen}_{ctx.image_count}"
    ctx.newlines(1)
    ctx.put("⏳ 图片加载中…", ("imgph", tag))
    ctx.put("\n")
    url = absolutize(ctx.base_url, src)
    try:
        width = max(240, ctx.w.winfo_width() - 90)
    except tk.TclError:
        width = 700

    def done(image) -> None:
        try:
            if not ctx.w.winfo_exists():
                return
            ranges = ctx.w.tag_ranges(tag)
            if not ranges:
                return
            start = str(ranges[0])
            ctx.w.configure(state="normal")
            ctx.w.delete(ranges[0], ranges[-1])
            if image is None:
                ctx.w.insert(start, "（图片未能加载）\n", ("imgph", "muted"))
            else:
                ctx.w.image_create(start, image=image, align="baseline", padx=2)
                ctx.w.insert(f"{start} + 1c", "\n")
            ctx.w.configure(state="disabled")
        except tk.TclError:
            pass

    ctx.loader.load(url, width, done)


def _emit_link(ctx: _Ctx, el, tags: tuple[str, ...]) -> None:
    href = (el.get("href") or "").strip()
    label = _text_of(el) or href
    if not label:
        return
    if not href or href.lower().startswith(("javascript:", "#")):
        ctx.put(label, tags)
        return
    url = absolutize(ctx.base_url, href)
    ctx.link_count += 1
    tag = f"link{ctx.gen}_{ctx.link_count}"
    ctx.links[tag] = url
    ctx.put(label, tags + ("link", tag))
    ctx.w.tag_bind(tag, "<Button-1>", lambda _e, u=url: ctx.on_link and ctx.on_link(u))
    ctx.w.tag_bind(tag, "<Enter>", lambda _e: ctx.w.configure(cursor="hand2"))
    ctx.w.tag_bind(tag, "<Leave>", lambda _e: ctx.w.configure(cursor="xterm"))


def _render_table(ctx: _Ctx, el, tags: tuple[str, ...]) -> None:
    ctx.newlines(2)
    for row in el.iter("tr"):
        cells = [re.sub(r"\s+", " ", "".join(c.itertext())).strip()
                 for c in row if localname(c.tag) in ("td", "th")]
        if cells:
            ctx.put("　|　".join(cells) + "\n", tags + ("body",))
    ctx.newlines(2)


def _render_element(ctx: _Ctx, el, tags: tuple[str, ...]) -> None:
    tag = localname(el.tag)
    if tag in SKIP_TAGS:
        return
    if tag in HEADINGS:
        ctx.newlines(2)
        ctx.put(_text_of(el), tags + (HEADINGS[tag],))
        ctx.newlines(2)
        return
    if tag in ("ul", "ol"):
        ctx.newlines(1)
        ordered = tag == "ol"
        index = 1
        for child in el:
            if localname(child.tag) != "li":
                continue
            ctx.newlines(1)
            prefix = f"{index}. " if ordered else "• "
            ctx.put(prefix, ("li_prefix",))
            _render_children(ctx, child, tags + ("li",))
            ctx.w.insert("end", "\n")
            ctx.trailing = 1
            index += 1
        ctx.newlines(1)
        return
    if tag == "li":
        ctx.newlines(1)
        ctx.put("• ", ("li_prefix",))
        _render_children(ctx, el, tags + ("li",))
        return
    if tag == "blockquote":
        ctx.newlines(2)
        _render_children(ctx, el, tags + ("quote",))
        ctx.newlines(2)
        return
    if tag == "pre":
        ctx.newlines(2)
        ctx.put(el.text_content().rstrip("\n"), ("pre",))
        ctx.newlines(2)
        return
    if tag == "code":
        ctx.put(_text_of(el) or el.text or "", tags + ("code",))
        return
    if tag == "a":
        _emit_link(ctx, el, tags)
        return
    if tag in ("strong", "b"):
        _render_children(ctx, el, tags + ("bold",))
        return
    if tag in ("em", "i"):
        _render_children(ctx, el, tags + ("italic",))
        return
    if tag in ("s", "del", "strike"):
        _render_children(ctx, el, tags)  # 删除线在 tk 里不支持，忽略样式
        return
    if tag == "img":
        _emit_image(ctx, el)
        return
    if tag == "br":
        ctx.put("\n", tags)
        return
    if tag == "hr":
        ctx.newlines(1)
        ctx.put("─" * 46, ("hr",))
        ctx.newlines(1)
        return
    if tag == "table":
        _render_table(ctx, el, tags)
        return
    if tag == "figcaption":
        ctx.newlines(1)
        _render_children(ctx, el, tags + ("caption",))
        ctx.newlines(1)
        return
    if tag == "p":
        ctx.newlines(2)
        _render_children(ctx, el, tags + ("p",))
        ctx.newlines(2)
        return
    if tag in CONTAINER_BLOCKS:
        block = any(localname(c.tag) in CONTAINER_BLOCKS | {"p", "ul", "ol", "table", "pre",
                                                            "blockquote", "h1", "h2", "h3"}
                    for c in el)
        if block:
            ctx.newlines(2)
        _render_children(ctx, el, tags)
        if block:
            ctx.newlines(2)
        return
    _render_children(ctx, el, tags)


def _render_children(ctx: _Ctx, el, tags: tuple[str, ...]) -> None:
    if el.text:
        ctx.put(el.text, tags)
    for child in el:
        if not isinstance(child.tag, str):
            continue
        _render_element(ctx, child, tags)
        if child.tail:
            ctx.put(child.tail, tags)


def reading_minutes(text: str) -> int:
    if not text:
        return 1
    cjk = len(re.findall(r"[\u4e00-\u9fff]", text))
    words = len(re.findall(r"[A-Za-z0-9']+", text))
    return max(1, round((cjk / 380 + words / 220) + 0.3))


def render_article(widget: tk.Text, article: dict, pal: dict, fonts: dict, *,
                   gen: int, images: bool = True, loader=None, on_link=None,
                   configure: bool = True) -> None:
    """把一篇文章画进 Text。gen 用于让旧的图片回调自动失效。"""
    base_url = article.get("url") or article.get("feed_site") or ""
    html_str = article.get("content_html") or ""
    text_str = article.get("content") or article.get("summary") or ""

    widget.configure(state="normal")
    widget.delete("1.0", "end")
    if configure:
        configure_tags(widget, pal, fonts)
    ctx = _Ctx(widget, pal, fonts, gen=gen, base_url=base_url, images=images,
               loader=loader, on_link=on_link)

    rendered = False
    if html_str and "<" in html_str:
        try:
            root = lhtml.fragment_fromstring(html_str, create_parent="div")
            _render_children(ctx, root, ("body",))
            rendered = True
        except Exception:
            rendered = False
    if not rendered:
        for para in (text_str or "").split("\n"):
            para = para.strip()
            if para:
                ctx.put(para + "\n", ("body",))
                ctx.trailing = 1
    if ctx.used == 0:
        ctx.put("（这篇没有正文，点右上角 “打开原文” 查看）", ("muted",))
    ctx.newlines(1)
    widget.configure(state="disabled")
