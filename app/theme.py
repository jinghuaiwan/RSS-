"""配色与 ttk 样式。暗色为默认，可切亮色。"""
from __future__ import annotations

import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk

PALETTES = {
    "dark": {
        "bg": "#15171c",
        "panel": "#1a1d23",
        "panel2": "#20242b",
        "panel3": "#262b34",
        "fg": "#e8e8e4",
        "fg_soft": "#c3c7cd",
        "muted": "#8b929c",
        "faint": "#61676f",
        "accent": "#5b9dff",
        "accent_dim": "#2f4d78",
        "border": "#2b303a",
        "select": "#31496e",
        "select_fg": "#ffffff",
        "link": "#79b2ff",
        "quote_bg": "#1e232c",
        "quote_bar": "#3d4a5e",
        "code_bg": "#1f242d",
        "code_fg": "#c9d4e2",
        "star": "#f0c05a",
        "unread": "#ffffff",
        "read": "#7f858e",
        "danger": "#e06c6c",
        "ok": "#63c78a",
        "image_border": "#2c323c",
    },
    "light": {
        "bg": "#f6f6f4",
        "panel": "#ffffff",
        "panel2": "#f0f1ee",
        "panel3": "#e7e9e5",
        "fg": "#1e2126",
        "fg_soft": "#3c424a",
        "muted": "#6b7280",
        "faint": "#9aa1a9",
        "accent": "#2f6fd0",
        "accent_dim": "#c9dcf7",
        "border": "#dfe2de",
        "select": "#dbe7fb",
        "select_fg": "#12233a",
        "link": "#1e5fb8",
        "quote_bg": "#f1f2ee",
        "quote_bar": "#c6cbc3",
        "code_bg": "#eef0ec",
        "code_fg": "#2b3138",
        "star": "#c58a12",
        "unread": "#15181c",
        "read": "#8b9199",
        "danger": "#c0392b",
        "ok": "#1f8a52",
        "image_border": "#e2e4e0",
    },
}

_cache: dict[str, str] = {}


def ui_font(root, size_px: int = 10, bold: bool = False) -> tkfont.Font:
    """挑一个存在的中文字体，避免 tk 落到难看的默认字体。"""
    key = f"{root.tk.interpaddr()}-{size_px}-{bold}"
    if key in _cache:
        return _cache[key]
    families = set(tkfont.families(root))
    family = next(
        (f for f in ("Microsoft YaHei UI", "Microsoft YaHei", "微软雅黑", "Segoe UI") if f in families),
        "TkDefaultFont",
    )
    f = tkfont.Font(root=root, family=family, size=size_px, weight="bold" if bold else "normal")
    _cache[key] = f
    return f


def reader_fonts(root, size: int) -> dict[str, tkfont.Font]:
    """阅读区字体族：标题粗、正文常规、代码等宽。"""
    families = set(tkfont.families(root))
    body = next(
        (f for f in ("Microsoft YaHei", "Microsoft YaHei UI", "微软雅黑", "Segoe UI") if f in families),
        "TkDefaultFont",
    )
    mono = next(
        (f for f in ("Cascadia Mono", "Consolas", "Sarasa Mono SC", "Courier New") if f in families),
        "TkFixedFont",
    )
    return {
        "body": tkfont.Font(root=root, family=body, size=size),
        "body_b": tkfont.Font(root=root, family=body, size=size, weight="bold"),
        "body_i": tkfont.Font(root=root, family=body, size=size, slant="italic"),
        "h1": tkfont.Font(root=root, family=body, size=size + 8, weight="bold"),
        "h2": tkfont.Font(root=root, family=body, size=size + 4, weight="bold"),
        "h3": tkfont.Font(root=root, family=body, size=size + 2, weight="bold"),
        "small": tkfont.Font(root=root, family=body, size=max(8, size - 3)),
        "mono": tkfont.Font(root=root, family=mono, size=max(8, size - 1)),
        "title": tkfont.Font(root=root, family=body, size=size + 9, weight="bold"),
    }


def apply_theme(root: tk.Tk, name: str) -> dict[str, str]:
    pal = PALETTES.get(name, PALETTES["dark"])
    style = ttk.Style(root)
    style.theme_use("clam")

    base_font = ui_font(root, 10)
    small_font = ui_font(root, 9)
    list_font = ui_font(root, 10)

    root.configure(bg=pal["bg"])
    style.configure(".", background=pal["bg"], foreground=pal["fg"], fieldbackground=pal["panel2"],
                    bordercolor=pal["border"], darkcolor=pal["panel"], lightcolor=pal["panel"],
                    troughcolor=pal["panel2"], focuscolor=pal["accent"], font=base_font)
    style.configure("TFrame", background=pal["bg"])
    style.configure("Panel.TFrame", background=pal["panel"])
    style.configure("Panel2.TFrame", background=pal["panel2"])
    style.configure("Toolbar.TFrame", background=pal["panel"])
    style.configure("TLabel", background=pal["bg"], foreground=pal["fg"])
    style.configure("Panel.TLabel", background=pal["panel"], foreground=pal["fg"])
    style.configure("Muted.TLabel", background=pal["panel"], foreground=pal["muted"])
    style.configure("Meta.TLabel", background=pal["bg"], foreground=pal["muted"], font=small_font)
    style.configure("Heading.TLabel", background=pal["bg"], foreground=pal["fg"], font=ui_font(root, 11, True))

    style.configure("TButton", background=pal["panel3"], foreground=pal["fg"], borderwidth=0,
                    focusthickness=0, padding=(10, 5), font=base_font)
    style.map("TButton",
              background=[("pressed", pal["accent_dim"]), ("active", pal["panel2"]), ("disabled", pal["panel"])],
              foreground=[("disabled", pal["faint"])])
    style.configure("Accent.TButton", background=pal["accent"], foreground="#ffffff")
    style.map("Accent.TButton", background=[("active", pal["link"]), ("pressed", pal["accent_dim"])])
    style.configure("Ghost.TButton", background=pal["panel"], foreground=pal["fg_soft"], padding=(8, 4))
    style.map("Ghost.TButton", background=[("active", pal["panel3"])])

    style.configure("TEntry", fieldbackground=pal["panel2"], foreground=pal["fg"],
                    insertcolor=pal["fg"], borderwidth=0, padding=(6, 5))
    style.configure("TCombobox", fieldbackground=pal["panel2"], background=pal["panel3"],
                    foreground=pal["fg"], arrowcolor=pal["fg_soft"], padding=(4, 4))
    style.map("TCombobox", fieldbackground=[("readonly", pal["panel2"])],
              foreground=[("readonly", pal["fg"])])

    style.configure("Treeview", background=pal["panel"], fieldbackground=pal["panel"],
                    foreground=pal["fg_soft"], borderwidth=0,
                    rowheight=list_font.metrics("linespace") + 9, font=list_font)
    style.map("Treeview", background=[("selected", pal["select"])],
              foreground=[("selected", pal["select_fg"])])
    style.configure("Treeview.Heading", background=pal["panel2"], foreground=pal["muted"],
                    borderwidth=0, relief="flat", font=small_font, padding=(4, 4))
    style.map("Treeview.Heading", background=[("active", pal["panel3"])])

    style.configure("TScrollbar", background=pal["panel2"], troughcolor=pal["bg"],
                    borderwidth=0, arrowcolor=pal["muted"], width=11)
    style.map("TScrollbar", background=[("active", pal["panel3"])])
    style.configure("TPanedwindow", background=pal["bg"], sashwidth=4)
    style.configure("Sash", background=pal["border"], sashwidth=4)
    style.configure("TSeparator", background=pal["border"])
    style.configure("TCheckbutton", background=pal["panel"], foreground=pal["fg"])
    style.map("TCheckbutton", background=[("active", pal["panel"])])
    style.configure("TRadiobutton", background=pal["panel"], foreground=pal["fg"])
    style.configure("TNotebook", background=pal["bg"], borderwidth=0)
    style.configure("TNotebook.Tab", background=pal["panel2"], foreground=pal["fg_soft"], padding=(12, 6))
    style.map("TNotebook.Tab", background=[("selected", pal["panel3"])],
              foreground=[("selected", pal["fg"])])

    set_titlebar(root, name == "dark")
    return pal


def set_titlebar(window: tk.Misc, dark: bool) -> None:
    """把窗口标题栏切成深色（Win10 2004+ 的 DWMWA_USE_IMMERSIVE_DARK_MODE）。"""
    try:
        import ctypes

        hwnd = int(window.wm_frame(), 16)
        if not hwnd:
            return
        value = ctypes.c_int(1 if dark else 0)
        for attr in (20, 19):
            if ctypes.windll.dwmapi.DwmSetWindowAttribute(
                    hwnd, attr, ctypes.byref(value), ctypes.sizeof(value)) == 0:
                break
    except Exception:
        pass
