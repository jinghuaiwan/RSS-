"""主窗口：三栏布局、订阅树、文章列表、阅读区、刷新与通知。"""
from __future__ import annotations

import os
import queue
import re
import webbrowser
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
import tkinter as tk

from . import config, dialogs, fetcher, opml, render
from .images import ImageLoader
from .store import Store
from .theme import PALETTES, apply_theme, reader_fonts, set_titlebar, ui_font

SPECIAL_NODES = ("s:all", "s:unread", "s:starred")
LOAD_MORE_TEXT = "加载更多"


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def human_time(value: str | None) -> str:
    dt = _parse_iso(value)
    if dt is None:
        return ""
    local = dt.astimezone()
    now = datetime.now().astimezone()
    if local.date() == now.date():
        return local.strftime("%H:%M")
    if (now.date() - local.date()).days == 1:
        return "昨天"
    if local.year == now.year:
        return local.strftime("%m-%d")
    return local.strftime("%y-%m-%d")


class App(tk.Tk):
    def __init__(self, store: Store):
        super().__init__()
        self.store = store
        self.settings = {**config.DEFAULTS, **store.settings()}
        self.config_data_dir = str(config.DATA_DIR)
        self.pal = PALETTES["dark"]
        self.fonts = None
        self.scale = 1.0
        self.scope: tuple[str, int | None] = ("all", None)
        self.only_unread = False
        self.search_text = ""
        self.selected_id: int | None = None
        self.loaded = 0
        self.total = 0
        self.gen = 0
        self.refreshing = False
        self.refresh_done = 0
        self.refresh_total = 0
        self.refresh_new = 0
        self.refresh_errors: list[str] = []
        self.tree_map: dict[str, tuple] = {}
        self._timers: dict[str, str] = {}
        self._pump_active = False
        self._loading_list = False
        self._closed = False

        self.bg = ThreadPoolExecutor(max_workers=6, thread_name_prefix="net")
        self.calls: queue.Queue = queue.Queue()

        self.title(config.APP_NAME)
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self._setup_window()
        self.pal = apply_theme(self, self.settings["theme"])
        self.fonts = reader_fonts(self, int(self.settings["font_size"]))
        self.images = ImageLoader(
            self,
            proxy_getter=lambda: self.settings.get("proxy", ""),
            ua_getter=lambda: self.settings.get("ua", ""),
        )
        self._build_ui()
        self._bind_keys()
        self.reload_sidebar()
        self.load_articles(reset=True)
        self.update_counts()
        self._pump_job = self.after(80, self._pump_calls)
        self.after(120, self._restore_layout)
        self._timers["startup"] = self.after(700, self._startup_refresh)

    # ================================================================== 窗口
    def px(self, value: float) -> int:
        return max(1, int(round(value * self.scale)))

    def _setup_window(self) -> None:
        icon = config.asset("app.ico")
        if icon.exists():
            try:
                self.iconbitmap(str(icon))
            except tk.TclError:
                pass
        self.update_idletasks()
        self.scale = max(1.0, self.winfo_fpixels("1i") / 96.0)
        screen_w, screen_h = self.winfo_screenwidth(), self.winfo_screenheight()
        saved = str(self.settings.get("window_geometry") or "")
        match = re.fullmatch(r"(\d+)x(\d+)([+-]-?\d+)([+-]-?\d+)", saved)
        fits = False
        if match:
            width, height = int(match.group(1)), int(match.group(2))
            fits = (self.px(700) <= width <= screen_w
                    and self.px(420) <= height <= screen_h)
        if fits:
            self.geometry(saved)
        else:
            width = min(screen_w - self.px(80), self.px(1400))
            height = min(screen_h - self.px(90), self.px(880))
            self.geometry(f"{width}x{height}+{(screen_w - width) // 2}"
                          f"+{max(0, (screen_h - height) // 2 - 20)}")
        self.minsize(self.px(240 + 420 + 600), self.px(600))
        self.configure(bg=self.pal["bg"])

    # ================================================================== 布局
    def _build_ui(self) -> None:
        pal = self.pal
        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)

        self._build_toolbar()
        self.paned = tk.PanedWindow(self, orient="horizontal", bg=pal["bg"], bd=0,
                                    sashwidth=self.px(5), sashrelief="flat",
                                    sashpad=self.px(2), showhandle=False,
                                    opaqueresize=True)
        self.paned.grid(row=1, column=0, sticky="nsew")

        self.left = tk.Frame(self.paned, bg=pal["panel"], width=self.px(235))
        self.mid = tk.Frame(self.paned, bg=pal["panel"], width=self.px(400))
        self.right = tk.Frame(self.paned, bg=pal["bg"])
        self.paned.add(self.left, minsize=self.px(170), stretch="never")
        self.paned.add(self.mid, minsize=self.px(280), stretch="never")
        self.paned.add(self.right, minsize=self.px(360), stretch="always")

        self._build_sidebar()
        self._build_list()
        self._build_reader()
        self._build_status()

    def _build_toolbar(self) -> None:
        pal = self.pal
        bar = tk.Frame(self, bg=pal["panel"], height=self.px(48))
        bar.grid(row=0, column=0, sticky="ew")
        bar.pack_propagate(False)
        self.toolbar = bar
        line = tk.Frame(self, bg=pal["border"], height=1)
        line.grid(row=0, column=0, sticky="sew")

        inner = tk.Frame(bar, bg=pal["panel"])
        inner.pack(fill="both", expand=True, padx=self.px(12))

        self.btn_add = ttk.Button(inner, text="＋ 添加订阅", style="Accent.TButton",
                                  command=self.add_feed)
        self.btn_add.pack(side="left", pady=self.px(9))
        self.btn_refresh = ttk.Button(inner, text="刷新", style="Ghost.TButton",
                                      command=lambda: self.start_refresh())
        self.btn_refresh.pack(side="left", padx=(self.px(8), 0), pady=self.px(9))
        self.btn_read_all = ttk.Button(inner, text="全部已读", style="Ghost.TButton",
                                       command=self.mark_all_read)
        self.btn_read_all.pack(side="left", padx=(self.px(6), 0), pady=self.px(9))

        # 右侧：设置 / 主题 / 搜索
        self.btn_settings = ttk.Button(inner, text="设置", style="Ghost.TButton",
                                       command=self.open_settings)
        self.btn_settings.pack(side="right", pady=self.px(9))
        self.btn_theme = ttk.Button(inner, text="亮色", style="Ghost.TButton",
                                    command=self.toggle_theme)
        self.btn_theme.configure(text="亮色" if self.settings.get("theme") == "dark" else "暗色")
        self.btn_theme.pack(side="right", padx=(0, self.px(6)), pady=self.px(9))

        search_box = tk.Frame(inner, bg=pal["panel2"], highlightthickness=0)
        search_box.pack(side="right", padx=(0, self.px(12)), pady=self.px(9))
        tk.Label(search_box, text="搜索", bg=pal["panel2"], fg=pal["muted"],
                 font=ui_font(self, 9)).pack(side="left", padx=(self.px(8), 0))
        self.search_var = tk.StringVar(value=self.search_text)
        self.search_entry = tk.Entry(search_box, textvariable=self.search_var, width=22,
                                     bg=pal["panel2"], fg=pal["fg"], insertbackground=pal["fg"],
                                     relief="flat", bd=0, highlightthickness=0,
                                     font=ui_font(self, 10))
        self.search_entry.pack(side="left", padx=(self.px(4), self.px(8)), pady=self.px(5))
        self.search_entry.bind("<Return>", lambda _e: self.apply_search())
        self.search_entry.bind("<Escape>", lambda _e: self.clear_search())
        self._set_search_placeholder()
        self.search_entry.bind("<FocusIn>", self._on_search_focus)
        self.search_entry.bind("<FocusOut>", self._on_search_blur)

    def _build_sidebar(self) -> None:
        pal = self.pal
        head = tk.Frame(self.left, bg=pal["panel"], height=self.px(38))
        head.pack(fill="x")
        head.pack_propagate(False)
        tk.Label(head, text="订阅", bg=pal["panel"], fg=pal["muted"],
                 font=ui_font(self, 9, True)).pack(side="left", padx=self.px(14))

        body = tk.Frame(self.left, bg=pal["panel"])
        body.pack(fill="both", expand=True)
        self.sidebar = ttk.Treeview(body, show="tree", selectmode="browse")
        bar = ttk.Scrollbar(body, orient="vertical", command=self.sidebar.yview)
        self.sidebar.configure(yscrollcommand=bar.set)
        self.sidebar.pack(side="left", fill="both", expand=True)
        bar.pack(side="right", fill="y")
        self.sidebar.tag_configure("special", foreground=pal["fg_soft"], font=ui_font(self, 10))
        self.sidebar.tag_configure("folder", foreground=pal["fg"], font=ui_font(self, 10, True))
        self.sidebar.tag_configure("feed", foreground=pal["muted"], font=ui_font(self, 10))
        self.sidebar.tag_configure("feed_unread", foreground=pal["unread"],
                                   font=ui_font(self, 10, True))
        self.sidebar.tag_configure("feed_error", foreground=pal["danger"], font=ui_font(self, 10))
        self.sidebar.bind("<<TreeviewSelect>>", self._on_sidebar_select)
        self.sidebar.bind("<Button-3>", self._on_sidebar_menu)

        foot = tk.Frame(self.left, bg=pal["panel"])
        foot.pack(fill="x", padx=self.px(8), pady=(0, self.px(6)))
        for col in range(3):
            foot.grid_columnconfigure(col, weight=1, uniform="foot")
        self.btn_folder = ttk.Button(foot, text="＋ 分组", style="Ghost.TButton",
                                     command=self.new_folder)
        self.btn_folder.grid(row=0, column=0, sticky="ew", padx=(0, self.px(3)))
        ttk.Button(foot, text="导入", style="Ghost.TButton",
                   command=self.import_opml).grid(row=0, column=1, sticky="ew",
                                                  padx=self.px(3))
        ttk.Button(foot, text="导出", style="Ghost.TButton",
                   command=self.export_opml).grid(row=0, column=2, sticky="ew",
                                                  padx=(self.px(3), 0))

    def _build_list(self) -> None:
        pal = self.pal
        head = tk.Frame(self.mid, bg=pal["panel"], height=self.px(38))
        head.pack(fill="x")
        head.pack_propagate(False)
        self.scope_label = tk.Label(head, text="全部文章", bg=pal["panel"], fg=pal["fg"],
                                    font=ui_font(self, 10, True))
        self.scope_label.pack(side="left", padx=self.px(14))
        self.list_count = tk.Label(head, text="", bg=pal["panel"], fg=pal["muted"],
                                   font=ui_font(self, 9))
        self.list_count.pack(side="right", padx=self.px(12))

        filt = tk.Frame(self.mid, bg=pal["panel"])
        filt.pack(fill="x", padx=self.px(10), pady=(0, self.px(6)))
        self.btn_all = ttk.Button(filt, text="全部", style="Ghost.TButton",
                                  command=lambda: self.set_filter(False), width=6)
        self.btn_all.pack(side="left")
        self.btn_unread = ttk.Button(filt, text="只看未读", style="Ghost.TButton",
                                     command=lambda: self.set_filter(True), width=10)
        self.btn_unread.pack(side="left", padx=(self.px(6), 0))

        body = tk.Frame(self.mid, bg=pal["panel"])
        body.pack(fill="both", expand=True)
        self.alist = ttk.Treeview(body, columns=("feed", "time"), show="tree headings",
                                  selectmode="browse")
        self.alist.heading("#0", text="标题", anchor="w")
        self.alist.heading("feed", text="来源", anchor="w")
        self.alist.heading("time", text="时间", anchor="e")
        self.alist.column("#0", width=self.px(215), minwidth=self.px(120), stretch=True)
        self.alist.column("feed", width=self.px(86), minwidth=self.px(60), stretch=False)
        self.alist.column("time", width=self.px(62), minwidth=self.px(48), stretch=False,
                          anchor="e")
        bar = ttk.Scrollbar(body, orient="vertical", command=self.alist.yview)
        self.alist.configure(yscrollcommand=bar.set)
        self.alist.pack(side="left", fill="both", expand=True)
        bar.pack(side="right", fill="y")
        self.alist.tag_configure("unread", foreground=pal["unread"], font=ui_font(self, 10, True))
        self.alist.tag_configure("read", foreground=pal["read"], font=ui_font(self, 10))
        # 选中行单独着色：Treeview 的 selected 映射会被 item 自己的 tag 前景色盖掉
        self.alist.tag_configure("sel_unread", background=pal["select"],
                                 foreground=pal["select_fg"], font=ui_font(self, 10, True))
        self.alist.tag_configure("sel_read", background=pal["select"],
                                 foreground=pal["select_fg"], font=ui_font(self, 10))
        self.alist.bind("<<TreeviewSelect>>", self._on_article_select)
        self.alist.bind("<Double-Button-1>", lambda _e: self.open_in_browser())

        self.more_box = tk.Frame(self.mid, bg=pal["panel"])
        self.more_box.pack(fill="x", side="bottom")
        self.btn_more = ttk.Button(self.more_box, text=LOAD_MORE_TEXT, style="Ghost.TButton",
                                   command=lambda: self.load_articles(reset=False))
        self.btn_more.pack(fill="x", padx=self.px(10), pady=self.px(6))

    def _build_reader(self) -> None:
        pal = self.pal
        header = tk.Frame(self.right, bg=pal["bg"])
        header.pack(fill="x", padx=self.px(26), pady=(self.px(16), 0))
        self.r_title = tk.Label(header, text="", bg=pal["bg"], fg=pal["fg"],
                                font=self.fonts["title"], anchor="w", justify="left",
                                wraplength=self.px(560))
        self.r_title.pack(fill="x", anchor="w")
        self.r_meta = tk.Label(header, text="", bg=pal["bg"], fg=pal["muted"],
                               font=self.fonts["small"], anchor="w", justify="left")
        self.r_meta.pack(fill="x", anchor="w", pady=(self.px(6), self.px(4)))

        actions = tk.Frame(header, bg=pal["bg"])
        actions.pack(fill="x", pady=(self.px(4), self.px(8)))
        self.btn_star = ttk.Button(actions, text="☆ 收藏", style="Ghost.TButton",
                                   command=self.toggle_star, width=8)
        self.btn_star.pack(side="left")
        self.btn_open = ttk.Button(actions, text="打开原文", style="Ghost.TButton",
                                   command=self.open_in_browser)
        self.btn_open.pack(side="left", padx=(self.px(6), 0))
        self.btn_full = ttk.Button(actions, text="补全全文", style="Ghost.TButton",
                                   command=self.fetch_full)
        self.btn_full.pack(side="left", padx=(self.px(6), 0))
        self.btn_copy = ttk.Button(actions, text="复制链接", style="Ghost.TButton",
                                   command=self.copy_link)
        self.btn_copy.pack(side="left", padx=(self.px(6), 0))
        self.btn_bigger = ttk.Button(actions, text="A＋", style="Ghost.TButton", width=3,
                                     command=lambda: self.change_font(1))
        self.btn_bigger.pack(side="right")
        self.btn_smaller = ttk.Button(actions, text="A－", style="Ghost.TButton", width=3,
                                      command=lambda: self.change_font(-1))
        self.btn_smaller.pack(side="right", padx=(0, self.px(6)))
        self.r_state = tk.Label(actions, text="", bg=pal["bg"], fg=pal["muted"],
                                font=self.fonts["small"])
        self.r_state.pack(side="right", padx=(0, self.px(14)))

        tk.Frame(self.right, bg=pal["border"], height=1).pack(fill="x", padx=self.px(26))

        text_box = tk.Frame(self.right, bg=pal["bg"])
        text_box.pack(fill="both", expand=True)
        self.text = tk.Text(text_box, width=60, height=30, state="disabled", cursor="xterm",
                            relief="flat", bd=0, highlightthickness=0)
        bar = ttk.Scrollbar(text_box, orient="vertical", command=self.text.yview)
        self.text.configure(yscrollcommand=bar.set)
        self.text.pack(side="left", fill="both", expand=True)
        bar.pack(side="right", fill="y")
        render.configure_tags(self.text, pal, self.fonts)
        self.text.configure(state="normal")
        self.text.insert("end", "　从中间列表选一篇文章开始阅读。\n\n"
                                "小技巧：F5 刷新，Ctrl+F 搜索，Ctrl+N 添加订阅，"
                                "在列表里用 j / k 上下切换。", ("body", "muted"))
        self.text.configure(state="disabled")
        self.text.bind("<Control-MouseWheel>", self._on_ctrl_wheel)
        self.text.bind("<MouseWheel>", self._scroll_reader)

    def _build_status(self) -> None:
        pal = self.pal
        bar = tk.Frame(self, bg=pal["panel"], height=self.px(26))
        bar.grid(row=2, column=0, sticky="ew")
        bar.pack_propagate(False)
        self.status_label = tk.Label(bar, text="就绪", bg=pal["panel"], fg=pal["muted"],
                                     font=ui_font(self, 9), anchor="w")
        self.status_label.pack(side="left", padx=self.px(12))
        self.status_counts = tk.Label(bar, text="", bg=pal["panel"], fg=pal["muted"],
                                      font=ui_font(self, 9), anchor="e")
        self.status_counts.pack(side="right", padx=self.px(12))

    # ================================================================== 按键
    def _bind_keys(self) -> None:
        self.bind("<F5>", lambda _e: self.start_refresh())
        self.bind("<Control-f>", lambda _e: self.focus_search())
        self.bind("<Control-F>", lambda _e: self.focus_search())
        self.bind("<Control-n>", lambda _e: self.add_feed())
        self.bind("<Control-comma>", lambda _e: self.open_settings())
        self.bind("<Escape>", lambda _e: self.clear_search())
        self.alist.bind("<Key-j>", lambda _e: self._move_selection(1))
        self.alist.bind("<Key-k>", lambda _e: self._move_selection(-1))
        self.alist.bind("<Return>", lambda _e: self.open_in_browser())

    def _move_selection(self, delta: int) -> str:
        rows = self.alist.get_children()
        if not rows:
            return "break"
        current = self.alist.selection()
        try:
            index = rows.index(current[0]) if current else 0
        except ValueError:
            index = 0
        index = max(0, min(len(rows) - 1, index + delta))
        self.alist.selection_set(rows[index])
        self.alist.focus(rows[index])
        self.alist.see(rows[index])
        return "break"

    def _on_ctrl_wheel(self, event) -> str:
        self.change_font(1 if event.delta > 0 else -1)
        return "break"

    def _scroll_reader(self, event) -> str:
        self.text.yview_scroll(-1 * int(event.delta / 120), "units")
        return "break"

    # ================================================================== 侧栏
    def reload_sidebar(self) -> None:
        pal = self.pal
        counts = self.store.scope_counts()
        feeds = self.store.feeds()
        folders = self.store.folders()
        current = self.sidebar.selection()
        keep = current[0] if current else None

        self.sidebar.delete(*self.sidebar.get_children())
        self.tree_map.clear()

        def add(iid: str, text: str, tag: str, scope: tuple) -> None:
            self.sidebar.insert("", "end", iid=iid, text=text, tags=(tag,))
            self.tree_map[iid] = scope

        add("s:all", f"全部文章   {counts['total']}", "special", ("all", None))
        add("s:unread", f"未读   {counts['unread']}", "special", ("unread", None))
        add("s:starred", f"★ 收藏   {counts['starred']}", "special", ("starred", None))

        by_folder: dict[int | None, list[dict]] = {}
        for feed in feeds:
            by_folder.setdefault(feed.get("folder_id"), []).append(feed)

        for folder in folders:
            children = by_folder.get(folder["id"], [])
            unread = sum(int(f["unread"] or 0) for f in children)
            label = f"{folder['name']}" + (f"   {unread}" if unread else "")
            iid = f"d:{folder['id']}"
            self.sidebar.insert("", "end", iid=iid, text=label, tags=("folder",), open=True)
            self.tree_map[iid] = ("folder", folder["id"])
            for feed in children:
                self._add_feed_row(feed, iid, pal)

        loose = by_folder.get(None, [])
        if loose:
            if folders:
                self.sidebar.insert("", "end", iid="d:loose", text="未分组", tags=("folder",),
                                    open=True)
                self.tree_map["d:loose"] = ("folder", -1)
                parent = "d:loose"
            else:
                parent = ""
            for feed in loose:
                self._add_feed_row(feed, parent, pal)

        target = self._scope_iid(self.scope)
        if keep and self.sidebar.exists(keep):
            target = keep
        if target and self.sidebar.exists(target):
            self.sidebar.selection_set(target)
            self.sidebar.see(target)

    def _add_feed_row(self, feed: dict, parent: str, pal: dict) -> None:
        iid = f"f:{feed['id']}"
        unread = int(feed["unread"] or 0)
        title = feed["title"] or feed["url"]
        text = title + (f"   {unread}" if unread else "")
        if feed.get("error"):
            tag = "feed_error"
        elif unread:
            tag = "feed_unread"
        else:
            tag = "feed"
        self.sidebar.insert(parent, "end", iid=iid, text=text, tags=(tag,))
        self.tree_map[iid] = ("feed", feed["id"])

    def _scope_iid(self, scope: tuple) -> str | None:
        kind, ident = scope
        if kind in ("all", "unread", "starred"):
            return f"s:{kind}"
        if kind == "feed":
            return f"f:{ident}"
        if kind == "folder":
            return f"d:{ident}"
        return None

    def _on_sidebar_select(self, _event=None) -> None:
        selection = self.sidebar.selection()
        if not selection:
            return
        scope = self.tree_map.get(selection[0])
        if not scope:
            return
        if scope[0] == "folder" and (scope[1] == -1):
            return  # “未分组”只是容器
        if scope == self.scope:
            return
        self.scope = scope
        if scope[0] == "unread":
            self.only_unread = True
        self._update_filter_buttons()
        self.load_articles(reset=True)
        self.update_counts()

    def _on_sidebar_menu(self, event) -> None:
        row = self.sidebar.identify_row(event.y)
        if not row:
            return
        self.sidebar.selection_set(row)
        scope = self.tree_map.get(row)
        if not scope:
            return
        pal = self.pal
        menu = tk.Menu(self, tearoff=0, bg=pal["panel2"], fg=pal["fg"],
                       activebackground=pal["select"], activeforeground=pal["select_fg"],
                       bd=0, font=ui_font(self, 9))
        if scope[0] == "feed":
            feed_id = scope[1]
            feed = self.store.feed(feed_id) or {}
            menu.add_command(label="刷新这个订阅", command=lambda: self.refresh_single(feed_id))
            menu.add_command(label="重命名", command=lambda: self.rename_feed(feed_id))
            menu.add_command(label="移动到分组…", command=lambda: self.move_feed(feed_id))
            menu.add_separator()
            if feed.get("site_url"):
                menu.add_command(label="在浏览器打开官网",
                                 command=lambda: webbrowser.open(feed["site_url"]))
            menu.add_command(label="复制订阅地址",
                             command=lambda: self._copy(feed.get("url", "")))
            menu.add_separator()
            menu.add_command(label="删除订阅", command=lambda: self.delete_feed(feed_id))
        elif scope[0] == "folder":
            menu.add_command(label="重命名分组", command=lambda: self.rename_folder(scope[1]))
            menu.add_command(label="删除分组（保留订阅）",
                             command=lambda: self.delete_folder(scope[1]))
        else:
            menu.add_command(label="全部标为已读", command=self.mark_all_read)
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    # ================================================================== 列表
    def set_filter(self, unread: bool) -> None:
        if self.scope[0] == "unread" and not unread:
            self.scope = ("all", None)
            if self.sidebar.exists("s:all"):
                self.sidebar.selection_set("s:all")
        if self.only_unread == unread:
            return
        self.only_unread = unread
        self._update_filter_buttons()
        self.load_articles(reset=True)

    def _update_filter_buttons(self) -> None:
        self.btn_all.configure(style="Accent.TButton" if not self.only_unread else "Ghost.TButton")
        self.btn_unread.configure(style="Accent.TButton" if self.only_unread else "Ghost.TButton")

    def _effective_scope(self) -> tuple[tuple, bool]:
        if self.scope[0] == "unread":
            return ("all", None), True
        if self.scope[0] == "starred":
            return ("starred", None), False
        return self.scope, self.only_unread

    def load_articles(self, reset: bool = True) -> None:
        scope, unread_only = self._effective_scope()
        page = max(20, int(self.settings.get("page_size", "200") or 200))
        self._loading_list = True
        try:
            if reset:
                self.alist.delete(*self.alist.get_children())
                self.loaded = 0
            rows = self.store.article_list(scope, search=self.search_text,
                                           unread_only=unread_only, limit=page,
                                           offset=self.loaded)
            for row in rows:
                self._insert_article_row(row)
            self.loaded += len(rows)
            self.total = self.store.article_count(scope, search=self.search_text,
                                                  unread_only=unread_only)
        finally:
            self._loading_list = False
        self.scope_label.configure(text=self._scope_title())
        self.list_count.configure(text=f"{self.loaded} / {self.total}" if self.total else "")
        if self.loaded < self.total:
            self.btn_more.pack(fill="x", padx=self.px(10), pady=self.px(6))
            self.btn_more.configure(text=f"{LOAD_MORE_TEXT}（还有 {self.total - self.loaded} 篇）")
        else:
            self.btn_more.pack_forget()
        if reset:
            children = self.alist.get_children()
            if children:
                self.alist.selection_set(children[0])
                self.alist.focus(children[0])
                self.open_article(int(children[0]), auto=True)
            else:
                self._show_empty_reader()

    def _insert_article_row(self, row: dict) -> None:
        star = "★ " if row["is_starred"] else ""
        tag = "read" if row["is_read"] else "unread"
        iid = str(row["id"])
        self.alist.insert("", "end", iid=iid, text=star + (row["title"] or "(无标题)"),
                          values=("  " + (row["feed_title"] or ""), human_time(row["published"])),
                          tags=(tag,))

    def _scope_title(self) -> str:
        kind, ident = self.scope
        base = {
            "all": "全部文章",
            "unread": "未读",
            "starred": "★ 收藏",
        }.get(kind, "文章")
        if kind == "feed":
            feed = self.store.feed(ident) or {}
            base = feed.get("title") or "订阅"
        elif kind == "folder":
            for folder in self.store.folders():
                if folder["id"] == ident:
                    base = folder["name"]
                    break
        if self.only_unread and kind not in ("unread", "starred"):
            base += " · 未读"
        if self.search_text:
            base += f" · 搜索「{self.search_text}」"
        return base

    def _on_article_select(self, _event=None) -> None:
        if self._loading_list:
            return
        selection = self.alist.selection()
        if not selection:
            return
        try:
            article_id = int(selection[0])
        except ValueError:
            return
        if article_id == self.selected_id:
            return
        previous = self.selected_id
        self.open_article(article_id)
        self._update_row_style(article_id)
        if previous:
            self._update_row_style(previous)

    def open_article(self, article_id: int, auto: bool = False) -> None:
        article = self.store.article(article_id)
        if not article:
            return
        self.selected_id = article_id
        self.gen += 1
        pal = self.pal
        self.r_title.configure(text=article["title"] or "(无标题)")
        meta_parts = [article.get("feed_title") or ""]
        if article.get("author"):
            meta_parts.append(article["author"][:60])
        when = _parse_iso(article.get("published"))
        if when:
            meta_parts.append(when.astimezone().strftime("%Y-%m-%d %H:%M"))
        body_text = article.get("content") or article.get("summary") or ""
        meta_parts.append(f"约 {render.reading_minutes(body_text)} 分钟")
        if article.get("full_fetched"):
            meta_parts.append("已补全")
        self.r_meta.configure(text="   ·   ".join(p for p in meta_parts if p))
        self.btn_star.configure(text="★ 已收藏" if article["is_starred"] else "☆ 收藏")
        self._set_reader_buttons(True)
        self.r_state.configure(text="")
        render.render_article(self.text, article, pal, self.fonts, gen=self.gen,
                              images=self.settings.get("load_images", "1") == "1",
                              loader=self.images, on_link=self._open_link)
        self.text.yview_moveto(0)

        if not article["is_read"] and not auto:
            self.store.mark_read([article_id])
            self._update_row_style(article_id, read=True)
            self._debounced_refresh_counts()

    def _set_reader_buttons(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        for btn in (self.btn_star, self.btn_open, self.btn_full, self.btn_copy):
            btn.configure(state=state)

    def _update_row_style(self, article_id: int, read: bool | None = None) -> None:
        iid = str(article_id)
        if not self.alist.exists(iid):
            return
        article = self.store.article(article_id)
        if not article:
            return
        is_read = article["is_read"] if read is None else read
        star = "★ " if article["is_starred"] else ""
        selected = iid in self.alist.selection()
        if selected:
            tag = "sel_read" if is_read else "sel_unread"
        else:
            tag = "read" if is_read else "unread"
        self.alist.item(iid, text=star + (article["title"] or "(无标题)"), tags=(tag,))

    def _show_empty_reader(self) -> None:
        self.selected_id = None
        self.r_title.configure(text="这里还没有文章")
        self.r_meta.configure(text="也许该刷新一下，或者去添加几个订阅源。")
        self._set_reader_buttons(False)
        self.r_state.configure(text="")
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.text.insert("end", "　点左上角「＋ 添加订阅」，把一个 RSS / Atom 地址或者"
                                "网站首页填进去即可。", ("body", "muted"))
        self.text.configure(state="disabled")

    # ================================================================== 阅读区动作
    def toggle_star(self) -> None:
        if not self.selected_id:
            return
        value = self.store.toggle_star(self.selected_id)
        self.btn_star.configure(text="★ 已收藏" if value else "☆ 收藏")
        self._update_row_style(self.selected_id)
        self.update_counts()
        self.set_status("已加入收藏" if value else "已取消收藏", timeout=2500)
        if self.scope[0] == "starred" and not value:
            self.load_articles(reset=True)

    def open_in_browser(self) -> None:
        if not self.selected_id:
            return
        article = self.store.article(self.selected_id)
        if article and article.get("url"):
            webbrowser.open(article["url"])
        else:
            self.set_status("这篇文章没有原文链接", timeout=3000)

    def copy_link(self) -> None:
        if not self.selected_id:
            return
        article = self.store.article(self.selected_id)
        if article and article.get("url"):
            self._copy(article["url"])

    def _copy(self, text: str) -> None:
        if not text:
            return
        self.clipboard_clear()
        self.clipboard_append(text)
        self.set_status("已复制到剪贴板", timeout=2500)

    def _open_link(self, url: str) -> None:
        if url:
            webbrowser.open(url)

    def fetch_full(self) -> None:
        if not self.selected_id:
            return
        article = self.store.article(self.selected_id)
        if not article:
            return
        if not article.get("url"):
            self.set_status("这篇文章没有原文链接，无法补全", timeout=3000)
            return
        article_id = self.selected_id
        self.btn_full.configure(state="disabled")
        self.r_state.configure(text="正在抓取正文…")

        def work() -> None:
            try:
                data = fetcher.fetch_full_text(article, self.settings)
                self.calls.put(("full_ok", article_id, data))
            except Exception as exc:
                self.calls.put(("full_err", str(exc)))

        self.bg.submit(work)

    def change_font(self, delta: int) -> None:
        size = max(11, min(26, int(self.settings.get("font_size", "15")) + delta))
        if size == int(self.settings.get("font_size", "15")):
            return
        self.settings["font_size"] = str(size)
        self.store.set_setting("font_size", str(size))
        self.fonts = reader_fonts(self, size)
        self.r_title.configure(font=self.fonts["title"])
        self.r_meta.configure(font=self.fonts["small"])
        self.r_state.configure(font=self.fonts["small"])
        self._refresh_reader_fonts()
        self.set_status(f"字号 {size} px", timeout=1500)

    def _refresh_reader_fonts(self) -> None:
        if not self.selected_id:
            return
        article = self.store.article(self.selected_id)
        if not article:
            return
        self.gen += 1
        render.render_article(self.text, article, self.pal, self.fonts, gen=self.gen,
                              images=self.settings.get("load_images", "1") == "1",
                              loader=self.images, on_link=self._open_link)

    # ================================================================== 搜索
    def _set_search_placeholder(self) -> None:
        if not self.search_text:
            self.search_var.set("")
            self.search_entry.configure(fg=self.pal["muted"])
            self._placeholder_on = True

    def _on_search_focus(self, _event=None) -> None:
        if getattr(self, "_placeholder_on", False):
            self.search_entry.delete(0, "end")
            self.search_entry.configure(fg=self.pal["fg"])
            self._placeholder_on = False

    def _on_search_blur(self, _event=None) -> None:
        if not self.search_entry.get().strip():
            self._placeholder_on = True
            self.search_entry.configure(fg=self.pal["muted"])

    def focus_search(self) -> None:
        self.search_entry.focus_set()
        self.search_entry.select_range(0, "end")

    def apply_search(self) -> None:
        text = self.search_entry.get().strip()
        if getattr(self, "_placeholder_on", False):
            text = ""
        self.search_text = text
        self.load_articles(reset=True)

    def clear_search(self) -> None:
        if self.search_text:
            self.search_text = ""
            self.search_entry.delete(0, "end")
            self._placeholder_on = True
            self.search_entry.configure(fg=self.pal["muted"])
            self.load_articles(reset=True)

    # ================================================================== 刷新
    def _startup_refresh(self) -> None:
        if self.store.feeds() and not self.refreshing:
            self.start_refresh(reason="startup")

    def start_refresh(self, feeds: list[dict] | None = None, reason: str = "manual") -> None:
        if self.refreshing:
            return
        feeds = feeds if feeds is not None else self.store.feeds()
        if not feeds:
            self.set_status("还没有订阅源，先点「＋ 添加订阅」", timeout=4000)
            return
        self.refreshing = True
        self.refresh_done = 0
        self.refresh_total = len(feeds)
        self.refresh_new = 0
        self.refresh_errors = []
        self.btn_refresh.configure(state="disabled", text="刷新中…")
        self.set_status(f"正在刷新 0/{self.refresh_total} …")
        for feed in feeds:
            self.bg.submit(self._refresh_worker, feed)

    def _refresh_worker(self, feed: dict) -> None:
        try:
            result = fetcher.refresh_feed(self.store, feed, self.settings)
        except Exception as exc:  # 兜底，绝不让异常吞掉进度
            result = {"ok": False, "new": 0, "error": f"{type(exc).__name__}: {exc}",
                      "title": feed.get("title", "")}
        self.calls.put(("refreshed", result))

    def _on_refreshed(self, result: dict) -> None:
        self.refresh_done += 1
        self.refresh_new += int(result.get("new") or 0)
        if not result.get("ok") and result.get("error"):
            self.refresh_errors.append(f"{result.get('title') or '订阅'}: {result['error']}")
        self.set_status(f"正在刷新 {self.refresh_done}/{self.refresh_total} …")
        if self.refresh_done >= self.refresh_total:
            self._finish_refresh()

    def _finish_refresh(self) -> None:
        self.refreshing = False
        self.btn_refresh.configure(state="normal", text="刷新")
        self.reload_sidebar()
        self.load_articles(reset=True)
        self.update_counts()
        if self.refresh_errors:
            self.set_status(f"刷新完成，{len(self.refresh_errors)} 个源失败："
                            f"{self.refresh_errors[0][:60]}", timeout=8000)
        else:
            self.set_status(f"刷新完成，新增 {self.refresh_new} 篇", timeout=5000)
        if self.refresh_new and self.settings.get("notify", "1") == "1" and not self.focus_get():
            newest = self.store.article_list(("all", None), limit=1)
            title = newest[0]["title"] if newest else ""
            self._toast(f"收到 {self.refresh_new} 篇新文章\n{title[:36]}")
            self._flash_taskbar()
        self._schedule_timer()

    def refresh_single(self, feed_id: int) -> None:
        feed = self.store.feed(feed_id)
        if feed:
            self.start_refresh([feed])

    def _schedule_timer(self) -> None:
        try:
            minutes = int(float(self.settings.get("refresh_minutes", "30") or 0))
        except ValueError:
            minutes = 30
        handle = self._timers.pop("refresh", None)
        if handle:
            try:
                self.after_cancel(handle)
            except Exception:
                pass
        if minutes > 0:
            self._timers["refresh"] = self.after(minutes * 60_000, self._auto_tick)

    def _auto_tick(self) -> None:
        if not self.refreshing:
            self.start_refresh(reason="auto")

    def _pump_calls(self) -> None:
        if self._pump_active:
            return
        self._pump_active = True
        try:
            while True:
                try:
                    message = self.calls.get_nowait()
                except queue.Empty:
                    break
                kind = message[0]
                if kind == "refreshed":
                    self._on_refreshed(message[1])
                elif kind == "discovered":
                    self._on_discovered(message[1], message[2])
                elif kind == "discover_failed":
                    self.set_status(f"识别失败：{message[1]}", timeout=8000)
                elif kind == "full_ok":
                    self._on_full_ok(message[1], message[2])
                elif kind == "full_err":
                    self.r_state.configure(text="抓取失败")
                    self.btn_full.configure(state="normal")
                    self.set_status(f"补全失败：{message[1]}", timeout=8000)
                elif kind == "status":
                    self.set_status(message[1], timeout=message[2] if len(message) > 2 else None)
        finally:
            self._pump_active = False
            if not self._closed:
                try:
                    self._pump_job = self.after(80, self._pump_calls)
                except tk.TclError:
                    pass

    def _on_full_ok(self, article_id: int, data: dict) -> None:
        self.store.set_full_content(article_id, data["html"], data["text"])
        self.btn_full.configure(state="normal")
        if self.selected_id == article_id:
            self.r_state.configure(text="正文已补全")
            self._refresh_reader_fonts()
        self.set_status("正文已补全", timeout=3000)

    # ================================================================== 订阅管理
    def add_feed(self) -> None:
        dialog = dialogs.AddFeedDialog(self)
        data = dialog.ask("entry")
        if not data:
            return
        self.set_status("正在识别订阅地址…")
        url = data["url"]

        def work() -> None:
            try:
                info = fetcher.discover(url, proxy=self.settings.get("proxy", ""),
                                        ua=self.settings.get("ua", ""))
                self.calls.put(("discovered", data, info))
            except Exception as exc:
                self.calls.put(("discover_failed", str(exc)))

        self.bg.submit(work)

    def _on_discovered(self, data: dict, info: dict) -> None:
        feeds = info.get("feeds") or []
        if not feeds:
            self.set_status("没找到可用的订阅地址", timeout=5000)
            return
        chosen = feeds[0]
        if len(feeds) > 1:
            picked = dialogs.FeedPickDialog(self, feeds).ask("listbox")
            if not picked:
                self.set_status("已取消添加", timeout=2500)
                return
            chosen = picked
        feed_id = self.store.add_feed(chosen["url"], title=chosen.get("title") or info.get("title", ""),
                                      site_url=info.get("site_url", ""),
                                      folder_id=data.get("folder_id"))
        feed = self.store.feed(feed_id)
        self.reload_sidebar()
        self.set_status(f"已添加：{feed.get('title') or chosen['url']}，正在抓取文章…")
        self.start_refresh([feed])

    def rename_feed(self, feed_id: int) -> None:
        feed = self.store.feed(feed_id) or {}
        name = dialogs.PromptDialog(self, "重命名订阅", "新名称", feed.get("title", "")).ask("entry")
        if name:
            self.store.update_feed(feed_id, title=name)
            self.reload_sidebar()
            self.load_articles(reset=True)

    def move_feed(self, feed_id: int) -> None:
        folders = self.store.folders()
        names = ["未分组"] + [f["name"] for f in folders]
        current = self.store.feed(feed_id) or {}
        current_name = "未分组"
        for folder in folders:
            if folder["id"] == current.get("folder_id"):
                current_name = folder["name"]
                break
        choice = dialogs.ChoiceDialog(self, "移动到分组", "选择目标分组：", names,
                                      current_name).ask("listbox")
        if choice is None:
            return
        target = None
        if choice != "未分组":
            for folder in folders:
                if folder["name"] == choice:
                    target = folder["id"]
                    break
        self.store.move_feed(feed_id, target)
        self.reload_sidebar()
        self.set_status(f"已移动到「{choice}」", timeout=2500)

    def delete_feed(self, feed_id: int) -> None:
        feed = self.store.feed(feed_id) or {}
        if not messagebox.askyesno("删除订阅", f"确定删除「{feed.get('title') or feed_id}」"
                                            "及其所有文章吗？此操作不可撤销。", parent=self):
            return
        self.store.delete_feed(feed_id)
        if self.scope == ("feed", feed_id):
            self.scope = ("all", None)
        self.reload_sidebar()
        self.load_articles(reset=True)
        self.update_counts()
        self.set_status("已删除订阅", timeout=3000)

    def new_folder(self) -> None:
        name = dialogs.PromptDialog(self, "新建分组", "分组名称").ask("entry")
        if name:
            self.store.add_folder(name)
            self.reload_sidebar()

    def rename_folder(self, folder_id: int) -> None:
        folders = {f["id"]: f for f in self.store.folders()}
        old = folders.get(folder_id, {}).get("name", "")
        name = dialogs.PromptDialog(self, "重命名分组", "新名称", old).ask("entry")
        if name:
            self.store.rename_folder(folder_id, name)
            self.reload_sidebar()
            self.load_articles(reset=True)

    def delete_folder(self, folder_id: int) -> None:
        if not messagebox.askyesno("删除分组", "只删除分组，里面的订阅会移到「未分组」。继续？",
                                   parent=self):
            return
        self.store.delete_folder(folder_id)
        self.reload_sidebar()
        self.load_articles(reset=True)

    def mark_all_read(self) -> None:
        scope, unread_only = self._effective_scope()
        if scope[0] == "all" and not self.search_text:
            if not messagebox.askyesno("全部已读", "把所有文章标为已读？", parent=self):
                return
        self.store.mark_all_read(scope)
        self.reload_sidebar()
        self.load_articles(reset=True)
        self.update_counts()
        self.set_status("已全部标记为已读", timeout=3000)

    # ================================================================== OPML
    def import_opml(self) -> None:
        path = filedialog.askopenfilename(parent=self, title="选择 OPML 文件",
                                          filetypes=[("OPML 订阅列表", "*.opml"), ("XML", "*.xml"),
                                                     ("所有文件", "*.*")])
        if not path:
            return
        try:
            data = Path(path).read_bytes()
            items = opml.parse_opml(data)
        except Exception as exc:
            messagebox.showerror("导入失败", f"文件解析失败：{exc}", parent=self)
            return
        if not items:
            messagebox.showinfo("导入", "这个文件里没有订阅项。", parent=self)
            return
        added = 0
        for item in items:
            folder_id = None
            if item["folder"]:
                folder_id = self.store.add_folder(item["folder"])
            if not self.store.feed_by_url(item["url"]):
                self.store.add_feed(item["url"], title=item["title"], folder_id=folder_id)
                added += 1
        self.reload_sidebar()
        self.set_status(f"已导入 {added} 个订阅，正在抓取…")
        self.start_refresh()

    def export_opml(self) -> None:
        path = filedialog.asksaveasfilename(parent=self, title="导出 OPML",
                                            defaultextension=".opml",
                                            initialfile="subscriptions.opml",
                                            filetypes=[("OPML 订阅列表", "*.opml")])
        if not path:
            return
        try:
            text = opml.build_opml(self.store.folders(), self.store.feeds())
            Path(path).write_text(text, encoding="utf-8")
        except Exception as exc:
            messagebox.showerror("导出失败", str(exc), parent=self)
            return
        self.set_status(f"已导出到 {path}", timeout=5000)

    # ================================================================== 设置
    def open_settings(self) -> None:
        values = dialogs.SettingsDialog(self).ask()
        if not values:
            return
        self.save_settings(values)

    def save_settings(self, values: dict) -> None:
        old_theme = self.settings.get("theme", "dark")
        self.settings.update(values)
        self.store.set_settings(values)
        if values.get("theme") and values["theme"] != old_theme:
            self._rebuild_for_theme()
        else:
            self.fonts = reader_fonts(self, int(self.settings.get("font_size", "15")))
            self.r_title.configure(font=self.fonts["title"])
            self.r_meta.configure(font=self.fonts["small"])
            self.r_state.configure(font=self.fonts["small"])
            self._refresh_reader_fonts()
        self._schedule_timer()
        self.set_status("设置已保存", timeout=3000)

    def toggle_theme(self) -> None:
        target = "light" if self.settings.get("theme") == "dark" else "dark"
        self.save_settings({"theme": target})

    def _rebuild_for_theme(self) -> None:
        geometry = self.geometry()
        sash = self._sash_positions()
        selected = self.selected_id
        for name in list(self._timers):
            job = self._timers.pop(name, None)
            if job:
                try:
                    self.after_cancel(job)
                except tk.TclError:
                    pass
        for child in self.winfo_children():
            child.destroy()
        self.pal = apply_theme(self, self.settings.get("theme", "dark"))
        self.fonts = reader_fonts(self, int(self.settings.get("font_size", "15")))
        self._build_ui()
        self.reload_sidebar()
        self.load_articles(reset=True)
        self.update_counts()
        self._apply_sash(sash)
        self.geometry(geometry)
        if selected:
            self.open_article(selected, auto=True)
        self.btn_theme.configure(text="亮色" if self.settings.get("theme") == "dark" else "暗色")

    def _sash_positions(self) -> list[float]:
        """按窗口宽度的比例存盘，换尺寸/缩放时才不会撑破布局。"""
        try:
            width = max(1, self.paned.winfo_width())
            return [round(self.paned.sash_coord(i)[0] / width, 4) for i in range(2)]
        except Exception:
            return [0.19, 0.5]

    def _apply_sash(self, positions: list[float]) -> None:
        try:
            width = max(1, self.paned.winfo_width())
            low = self.px(180)
            high = max(low, width - self.px(600))
            for index, pos in enumerate(positions[:2]):
                x = pos * width if pos <= 1.0 else float(pos)
                self.paned.sash_place(index, int(max(low, min(x, high))), 0)
        except Exception:
            pass

    def _restore_layout(self) -> None:
        set_titlebar(self, self.settings.get("theme", "dark") == "dark")
        saved = str(self.settings.get("sash") or "")
        if saved:
            try:
                positions = [float(p) for p in saved.split(",") if p.strip()]
                if len(positions) == 2:
                    self._apply_sash(positions)
                    return
            except ValueError:
                pass
        width = max(1, self.paned.winfo_width())
        self._apply_sash([self.px(250) / width, self.px(250 + 430) / width])

    # ================================================================== 杂项
    def set_status(self, text: str, timeout: int | None = None) -> None:
        self.status_label.configure(text=text)
        handle = self._timers.pop("status", None)
        if handle:
            try:
                self.after_cancel(handle)
            except Exception:
                pass
        if timeout:
            self._timers["status"] = self.after(timeout, lambda: self.status_label.configure(
                text="就绪"))

    def update_counts(self) -> None:
        counts = self.store.scope_counts()
        feeds = len(self.store.feeds())
        self.status_counts.configure(
            text=f"订阅 {feeds}   ·   未读 {counts['unread']}   ·   文章 {counts['total']}")

    def _debounced_refresh_counts(self) -> None:
        handle = self._timers.pop("counts", None)
        if handle:
            try:
                self.after_cancel(handle)
            except Exception:
                pass

        def run() -> None:
            self.reload_sidebar()
            self.update_counts()

        self._timers["counts"] = self.after(400, run)

    def open_data_dir(self) -> None:
        try:
            os.startfile(str(config.DATA_DIR))  # type: ignore[attr-defined]
        except Exception:
            self.set_status(f"数据目录：{config.DATA_DIR}", timeout=6000)

    def _toast(self, text: str, command=None) -> None:
        pal = self.pal
        old = getattr(self, "_toast_win", None)
        if old is not None:
            try:
                old.destroy()
            except tk.TclError:
                pass
        win = tk.Toplevel(self)
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        frame = tk.Frame(win, bg=pal["panel3"], highlightthickness=1,
                         highlightbackground=pal["accent"])
        frame.pack(fill="both", expand=True)
        tk.Label(frame, text=f"  {config.APP_NAME}", bg=pal["panel3"], fg=pal["accent"],
                 font=ui_font(self, 9, True), anchor="w").pack(fill="x", pady=(8, 0))
        body = tk.Label(frame, text=text, bg=pal["panel3"], fg=pal["fg"], justify="left",
                        wraplength=self.px(260), font=ui_font(self, 9), anchor="w")
        body.pack(fill="x", padx=10, pady=(2, 10))
        win.update_idletasks()
        width = self.px(300)
        height = max(self.px(64), win.winfo_reqheight())
        x = self.winfo_screenwidth() - width - self.px(24)
        y = self.winfo_screenheight() - height - self.px(80)
        win.geometry(f"{width}x{height}+{x}+{y}")

        def clicked(_event=None) -> None:
            try:
                win.destroy()
            except tk.TclError:
                pass
            if command:
                command()

        win.bind("<Button-1>", clicked)
        for child in (frame, body):
            child.bind("<Button-1>", clicked)
        win.after(7000, lambda: win.winfo_exists() and win.destroy())
        self._toast_win = win

    def _flash_taskbar(self) -> None:
        if not config.IS_WINDOWS:
            return
        try:
            import ctypes
            from ctypes import wintypes

            class FLASHWINFO(ctypes.Structure):
                _fields_ = [("cbSize", wintypes.UINT), ("hwnd", wintypes.HWND),
                            ("dwFlags", wintypes.DWORD), ("uCount", wintypes.UINT),
                            ("dwTimeout", wintypes.DWORD)]

            hwnd = ctypes.windll.user32.GetParent(self.winfo_id()) or self.winfo_id()
            info = FLASHWINFO(ctypes.sizeof(FLASHWINFO), hwnd, 0x00000003, 3, 0)
            ctypes.windll.user32.FlashWindowEx(ctypes.byref(info))
        except Exception:
            pass

    def destroy(self) -> None:
        self._closed = True
        try:
            self.after_cancel(self._pump_job)
        except Exception:
            pass
        for job in list(self._timers.values()):
            try:
                self.after_cancel(job)
            except Exception:
                pass
        self._timers.clear()
        try:
            self.images.stop()
        except Exception:
            pass
        try:
            self.bg.shutdown(wait=False, cancel_futures=True)
        except Exception:
            pass
        super().destroy()

    def on_close(self) -> None:
        try:
            self.store.set_settings({
                "window_geometry": self.geometry(),
                "sash": ",".join(str(p) for p in self._sash_positions()),
            })
        except Exception:
            pass
        try:
            self.images.stop()
            self.bg.shutdown(wait=False, cancel_futures=True)
        except Exception:
            pass
        self.store.close()
        self.destroy()
