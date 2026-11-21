"""对话框：订阅、设置、选择订阅地址、文本输入。"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from .theme import set_titlebar, ui_font


class Modal(tk.Toplevel):
    def __init__(self, app, title: str, width: int = 520, height: int = 0):
        super().__init__(app)
        self.app = app
        self.pal = app.pal
        self.result = None
        self.title(title)
        self.configure(bg=self.pal["bg"])
        self.resizable(False, False)
        self.transient(app)
        self.protocol("WM_DELETE_WINDOW", self.cancel)
        self.body = ttk.Frame(self, padding=18, style="TFrame")
        self.body.pack(fill="both", expand=True)
        self.width = width
        self.height = height

    # -- 布局工具 -----------------------------------------------------------
    def label(self, text: str, **kw) -> ttk.Label:
        lab = ttk.Label(self.body, text=text, style="TLabel", **kw)
        return lab

    def hint(self, text: str) -> ttk.Label:
        return ttk.Label(self.body, text=text, style="Meta.TLabel", wraplength=self.app.px(self.width - 48),
                         justify="left")

    def buttons(self, ok_text: str = "确定", cancel_text: str = "取消") -> ttk.Frame:
        bar = ttk.Frame(self.body, style="TFrame")
        ttk.Button(bar, text=cancel_text, command=self.cancel, style="Ghost.TButton").pack(
            side="right", padx=(8, 0))
        ttk.Button(bar, text=ok_text, command=self.ok, style="Accent.TButton").pack(side="right")
        return bar

    def show(self, focus: tk.Widget | None = None, height: int | None = None):
        self.update_idletasks()
        w = self.app.px(self.width) if self.width else self.winfo_reqwidth()
        raw_h = height or self.height
        h = self.app.px(raw_h) if raw_h else self.winfo_reqheight()
        self.app.update_idletasks()
        x = self.app.winfo_rootx() + (self.app.winfo_width() - w) // 2
        y = self.app.winfo_rooty() + (self.app.winfo_height() - h) // 3
        sw, sh = self.app.winfo_screenwidth(), self.app.winfo_screenheight()
        x = max(0, min(x, sw - w))
        y = max(0, min(y, sh - h))
        self.geometry(f"{w}x{h}+{x}+{y}")
        set_titlebar(self, self.app.settings.get("theme", "dark") == "dark")
        self.grab_set()
        if focus is not None:
            focus.focus_set()
        self.wait_window(self)
        return self.result

    def ask(self, focus: str = "") -> dict | None:
        """显示对话框并等用户关闭，focus 是属性名（如 "entry"）。"""
        return self.show(focus=getattr(self, focus, None))

    def ok(self):
        self.destroy()

    def cancel(self):
        self.result = None
        self.destroy()


class PromptDialog(Modal):
    def __init__(self, app, title: str, label: str, initial: str = ""):
        super().__init__(app, title, width=420)
        self.label(label).pack(anchor="w", pady=(0, 8))
        self.var = tk.StringVar(value=initial)
        entry = ttk.Entry(self.body, textvariable=self.var)
        entry.pack(fill="x")
        self.buttons().pack(fill="x", pady=(18, 0))
        entry.bind("<Return>", lambda _e: self.ok())
        self.entry = entry

    def ok(self):
        text = self.var.get().strip()
        self.result = text or None
        self.destroy()


class FeedPickDialog(Modal):
    def __init__(self, app, candidates: list[dict]):
        super().__init__(app, "发现多个订阅地址", width=540, height=380)
        self.candidates = candidates
        ttk.Label(self.body, text="这个页面上有多个订阅源，选一个：", style="TLabel").pack(
            anchor="w", pady=(0, 10))
        box = ttk.Frame(self.body, style="TFrame")
        box.pack(fill="both", expand=True)
        self.listbox = tk.Listbox(
            box, bg=self.pal["panel2"], fg=self.pal["fg"], selectbackground=self.pal["select"],
            selectforeground=self.pal["select_fg"], bd=0, highlightthickness=0,
            activestyle="none", font=ui_font(app, 10))
        bar = ttk.Scrollbar(box, orient="vertical", command=self.listbox.yview)
        self.listbox.configure(yscrollcommand=bar.set)
        self.listbox.pack(side="left", fill="both", expand=True)
        bar.pack(side="right", fill="y")
        for c in candidates:
            self.listbox.insert("end", f"{c.get('title') or '(未命名)'}   —   {c['url']}")
        self.listbox.selection_set(0)
        self.listbox.bind("<Double-Button-1>", lambda _e: self.ok())
        self.buttons("使用这个").pack(fill="x", pady=(14, 0))

    def ok(self):
        sel = self.listbox.curselection()
        if sel:
            self.result = self.candidates[sel[0]]
        self.destroy()


class ChoiceDialog(Modal):
    """从列表里挑一项（用于“移动到分组”）。"""

    def __init__(self, app, title: str, label: str, options: list[str],
                 initial: str | None = None):
        super().__init__(app, title, width=420, height=360)
        self.options = options
        ttk.Label(self.body, text=label, style="TLabel").pack(anchor="w", pady=(0, 8))
        box = ttk.Frame(self.body, style="TFrame")
        box.pack(fill="both", expand=True)
        self.listbox = tk.Listbox(
            box, bg=self.pal["panel2"], fg=self.pal["fg"], selectbackground=self.pal["select"],
            selectforeground=self.pal["select_fg"], bd=0, highlightthickness=0,
            activestyle="none", exportselection=False, font=ui_font(app, 10))
        bar = ttk.Scrollbar(box, orient="vertical", command=self.listbox.yview)
        self.listbox.configure(yscrollcommand=bar.set)
        self.listbox.pack(side="left", fill="both", expand=True)
        bar.pack(side="right", fill="y")
        for option in options:
            self.listbox.insert("end", option)
        if initial in options:
            index = options.index(initial)
            self.listbox.selection_set(index)
            self.listbox.see(index)
        elif options:
            self.listbox.selection_set(0)
        self.listbox.bind("<Double-Button-1>", lambda _e: self.ok())
        self.buttons("确定").pack(fill="x", pady=(14, 0))

    def ok(self):
        selection = self.listbox.curselection()
        if selection:
            self.result = self.options[selection[0]]
        self.destroy()


class AddFeedDialog(Modal):
    def __init__(self, app):
        super().__init__(app, "添加订阅", width=500)
        ttk.Label(self.body, text="订阅地址", style="TLabel").pack(anchor="w")
        self.url_var = tk.StringVar()
        entry = ttk.Entry(self.body, textvariable=self.url_var)
        entry.pack(fill="x", pady=(6, 4))
        ttk.Label(self.body, text="可以填 RSS/Atom 地址，也可以直接填网站首页，程序会自动找订阅链接。",
                  style="Meta.TLabel", wraplength=app.px(430), justify="left").pack(anchor="w", pady=(0, 14))

        ttk.Label(self.body, text="放进分组", style="TLabel").pack(anchor="w")
        row = ttk.Frame(self.body, style="TFrame")
        row.pack(fill="x", pady=(6, 0))
        self.folder_names = ["未分组"] + [f["name"] for f in app.store.folders()]
        self.folder_var = tk.StringVar(value="未分组")
        self.combo = ttk.Combobox(row, textvariable=self.folder_var, values=self.folder_names,
                                  state="readonly")
        self.combo.pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="新建分组", style="Ghost.TButton",
                   command=self._new_folder).pack(side="left", padx=(8, 0))

        self.buttons("添加", "取消").pack(fill="x", pady=(20, 0))
        self.entry = entry
        entry.bind("<Return>", lambda _e: self.ok())

    def _new_folder(self):
        name = PromptDialog(self.app, "新建分组", "分组名称").ask("entry")
        if not name:
            return
        self.app.store.add_folder(name)
        self.app.reload_sidebar()
        self.folder_names = ["未分组"] + [f["name"] for f in self.app.store.folders()]
        self.combo.configure(values=self.folder_names)
        self.folder_var.set(name)

    def ok(self):
        url = self.url_var.get().strip()
        if not url:
            self.cancel()
            return
        if not url.lower().startswith(("http://", "https://")):
            url = "https://" + url
        name = self.folder_var.get()
        folder_id = None
        if name and name != "未分组":
            for f in self.app.store.folders():
                if f["name"] == name:
                    folder_id = f["id"]
                    break
        self.result = {"url": url, "folder_id": folder_id}
        self.destroy()


class SettingsDialog(Modal):
    def __init__(self, app):
        super().__init__(app, "设置", width=600)
        self.values = dict(app.settings)
        body = ttk.Frame(self.body, style="TFrame")
        body.pack(fill="both", expand=True)

        def row(label: str, widget_factory, hint: str = "") -> tk.Widget:
            box = ttk.Frame(body, style="TFrame")
            box.pack(fill="x", pady=(0, 12))
            ttk.Label(box, text=label, style="TLabel").pack(anchor="w")
            widget = widget_factory(box)
            widget.pack(fill="x", pady=(4, 0))
            if hint:
                ttk.Label(box, text=hint, style="Meta.TLabel", wraplength=self.app.px(520),
                          justify="left").pack(anchor="w", pady=(3, 0))
            return widget

        # 主题
        self.theme_var = tk.StringVar(value="暗色" if self.values.get("theme") == "dark" else "亮色")
        row("外观主题", lambda p: ttk.Combobox(p, textvariable=self.theme_var, state="readonly",
                                             values=["暗色", "亮色"]))

        # 字号
        size_box = ttk.Frame(body, style="TFrame")
        size_box.pack(fill="x", pady=(0, 12))
        ttk.Label(size_box, text="阅读字号", style="TLabel").pack(anchor="w")
        content = ttk.Frame(size_box, style="TFrame")
        content.pack(fill="x", pady=(4, 0))
        self.size_var = tk.IntVar(value=int(self.values.get("font_size", "15")))
        ttk.Scale(content, from_=11, to=24, orient="horizontal", variable=self.size_var,
                  command=lambda v: self.size_label.configure(text=f"{int(float(v))} px")).pack(
            side="left", fill="x", expand=True)
        self.size_label = ttk.Label(content, text=f"{self.size_var.get()} px", style="Meta.TLabel",
                                    width=7)
        self.size_label.pack(side="left", padx=(8, 0))

        # 刷新间隔
        self.refresh_var = tk.StringVar(value=self.values.get("refresh_minutes", "30"))
        row("自动刷新间隔（分钟，0 表示关闭）",
            lambda p: ttk.Entry(p, textvariable=self.refresh_var))

        # 代理
        self.proxy_var = tk.StringVar(value=self.values.get("proxy", ""))
        row("HTTP 代理", lambda p: ttk.Entry(p, textvariable=self.proxy_var),
            "形如 http://127.0.0.1:7890；留空表示直连。")

        # 保留篇数
        self.keep_var = tk.StringVar(value=self.values.get("max_articles", "3000"))
        row("每个订阅最多保留文章数（0 表示不限）",
            lambda p: ttk.Entry(p, textvariable=self.keep_var))

        # 开关
        toggles = ttk.Frame(body, style="TFrame")
        toggles.pack(fill="x", pady=(0, 12))
        self.images_var = tk.BooleanVar(value=self.values.get("load_images", "1") == "1")
        self.notify_var = tk.BooleanVar(value=self.values.get("notify", "1") == "1")
        ttk.Checkbutton(toggles, text="正文加载图片", variable=self.images_var).pack(anchor="w")
        ttk.Checkbutton(toggles, text="新文章桌面提醒", variable=self.notify_var).pack(anchor="w",
                                                                                     pady=(4, 0))

        # 数据
        data_row = ttk.Frame(body, style="TFrame")
        data_row.pack(fill="x", pady=(6, 0))
        stats = app.store.stats()
        ttk.Label(data_row, text=f"数据目录：{app.config_data_dir}", style="Meta.TLabel",
                  wraplength=app.px(430), justify="left").pack(side="left")
        ttk.Button(data_row, text="打开目录", style="Ghost.TButton",
                   command=app.open_data_dir).pack(side="right")

        self.buttons("保存", "取消").pack(fill="x", pady=(18, 0))

    def ok(self):
        try:
            refresh = max(0, int(float(self.refresh_var.get() or 0)))
        except ValueError:
            refresh = 30
        try:
            keep = max(0, int(float(self.keep_var.get() or 0)))
        except ValueError:
            keep = 3000
        self.result = {
            "theme": "dark" if self.theme_var.get() == "暗色" else "light",
            "font_size": str(int(float(self.size_var.get()))),
            "refresh_minutes": str(refresh),
            "proxy": self.proxy_var.get().strip(),
            "max_articles": str(keep),
            "load_images": "1" if self.images_var.get() else "0",
            "notify": "1" if self.notify_var.get() else "0",
        }
        self.destroy()
