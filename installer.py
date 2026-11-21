"""RSS 阅读器安装程序。

打包后是一个单文件 exe：双击 → 选安装位置 → 复制文件 → 建快捷方式 →
在「设置 → 应用」里登记卸载项。装完可以直接启动。

开发时直接跑 python installer.py 也行（payload 取 dist/RSS阅读器）。
"""
from __future__ import annotations

import ctypes
import os
import queue
import shutil
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app import install_info as info  # noqa: E402
from app import shortcuts  # noqa: E402

BG = "#15171c"
PANEL = "#1a1d23"
FIELD = "#20242b"
FG = "#e8e8e4"
MUTED = "#8b929c"
BORDER = "#2b303a"
ACCENT = "#5b9dff"
ACCENT_ACTIVE = "#4a8ef0"


def enable_dpi() -> None:
    if os.name != "nt":
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def payload_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "payload" / "app"  # type: ignore[attr-defined]
    return Path(__file__).resolve().parent / "dist" / "RSS阅读器"


def bundled_icon() -> Path | None:
    if getattr(sys, "frozen", False):
        candidate = Path(sys._MEIPASS) / "assets" / "app-256.png"  # type: ignore[attr-defined]
    else:
        candidate = Path(__file__).resolve().parent / "assets" / "app-256.png"
    return candidate if candidate.exists() else None


def tree_size(path: Path) -> tuple[int, int]:
    files = 0
    total = 0
    for root, _dirs, names in os.walk(path):
        for name in names:
            files += 1
            try:
                total += (Path(root) / name).stat().st_size
            except OSError:
                pass
    return files, total


def human(bytes_: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if bytes_ < 1024 or unit == "GB":
            return f"{bytes_:.1f} {unit}"
        bytes_ /= 1024
    return f"{bytes_:.1f} GB"


class Installer(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(f"安装 {info.PRODUCT}")
        self.configure(bg=BG)
        self.resizable(False, False)
        self.scale = max(1.0, self.winfo_fpixels("1i") / 96.0)
        self.target_var = tk.StringVar(value=str(info.default_install_dir()))
        self.desktop_var = tk.BooleanVar(value=True)
        self.launch_var = tk.BooleanVar(value=True)
        self.status_var = tk.StringVar(value="准备就绪")
        self.installing = False
        self.events: queue.Queue[tuple[str, object]] = queue.Queue()
        self._build()
        self._place()
        self.after(60, self._drain)

    # ---------------------------------------------------------------- 尺寸
    def px(self, value: float) -> int:
        return max(1, int(round(value * self.scale)))

    def _place(self) -> None:
        self.update_idletasks()
        width, height = 720, 470
        screen_w, screen_h = self.winfo_screenwidth(), self.winfo_screenheight()
        x = (screen_w - self.px(width)) // 2
        y = (screen_h - self.px(height)) // 2
        self.geometry(f"{self.px(width)}x{self.px(height)}+{max(0, x)}+{max(0, y)}")
        try:
            self.iconbitmap(str(Path(payload_root()).parent.parent / "assets" / "app.ico"))
        except Exception:
            pass

    def _style(self) -> None:
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("TButton", background=FIELD, foreground=FG, bordercolor=BORDER,
                        lightcolor=FIELD, darkcolor=FIELD, focuscolor=BORDER,
                        padding=(self.px(14), self.px(6)))
        style.map("TButton", background=[("active", "#262b34")],
                  foreground=[("disabled", MUTED)])
        style.configure("Install.TButton", background=ACCENT, foreground="#ffffff",
                        bordercolor=ACCENT, lightcolor=ACCENT, darkcolor=ACCENT,
                        padding=(self.px(20), self.px(8)), font=("Microsoft YaHei UI", 10, "bold"))
        style.map("Install.TButton",
                  background=[("active", ACCENT_ACTIVE), ("disabled", "#33507d")],
                  foreground=[("disabled", "#c3c7cd")])
        style.configure("TCheckbutton", background=PANEL, foreground=FG,
                        focuscolor=PANEL)
        style.map("TCheckbutton", background=[("active", PANEL)])
        style.configure("Install.Horizontal.TProgressbar", background=ACCENT,
                        troughcolor=FIELD, bordercolor=BORDER, lightcolor=ACCENT,
                        darkcolor=ACCENT, thickness=self.px(6))

    def _build(self) -> None:
        self._style()
        card = tk.Frame(self, bg=PANEL, highlightbackground=BORDER, highlightthickness=1)
        card.pack(fill="both", expand=True, padx=self.px(18), pady=self.px(18))

        head = tk.Frame(card, bg=PANEL)
        head.pack(fill="x", padx=self.px(22), pady=(self.px(20), 0))
        icon = bundled_icon()
        if icon:
            try:
                self._icon = tk.PhotoImage(file=str(icon)).subsample(2, 2)
                tk.Label(head, image=self._icon, bg=PANEL).pack(side="left", padx=(0, self.px(14)))
            except tk.TclError:
                self._icon = None
        text = tk.Frame(head, bg=PANEL)
        text.pack(side="left", fill="x", expand=True)
        tk.Label(text, text=info.PRODUCT, bg=PANEL, fg=FG,
                 font=("Microsoft YaHei UI", 15, "bold")).pack(anchor="w")
        tk.Label(text, text=f"版本 {info.VERSION} · 本地阅读，不登录、不上传",
                 bg=PANEL, fg=MUTED, font=("Microsoft YaHei UI", 9)).pack(anchor="w",
                                                                          pady=(self.px(4), 0))

        tk.Frame(card, bg=BORDER, height=1).pack(fill="x", padx=self.px(22),
                                                 pady=(self.px(16), 0))

        form = tk.Frame(card, bg=PANEL)
        form.pack(fill="x", padx=self.px(22), pady=(self.px(16), 0))
        tk.Label(form, text="安装到", bg=PANEL, fg=MUTED,
                 font=("Microsoft YaHei UI", 9)).pack(anchor="w")
        row = tk.Frame(form, bg=PANEL)
        row.pack(fill="x", pady=(self.px(6), 0))
        entry = tk.Entry(row, textvariable=self.target_var, bg=FIELD, fg=FG,
                         insertbackground=FG, relief="flat",
                         highlightbackground=BORDER, highlightcolor=ACCENT,
                         highlightthickness=1, font=("Microsoft YaHei UI", 10))
        entry.pack(side="left", fill="x", expand=True, ipady=self.px(5))
        ttk.Button(row, text="浏览…", command=self.browse).pack(side="left",
                                                               padx=(self.px(8), 0))

        tk.Label(card, text="装到当前用户目录，不需要管理员权限；占用约 "
                            f"{human(tree_size(payload_root())[1])}",
                 bg=PANEL, fg=MUTED, font=("Microsoft YaHei UI", 9)).pack(
            anchor="w", padx=self.px(22), pady=(self.px(8), 0))

        opts = tk.Frame(card, bg=PANEL)
        opts.pack(fill="x", padx=self.px(22), pady=(self.px(10), 0))
        ttk.Checkbutton(opts, text="创建桌面快捷方式", variable=self.desktop_var).pack(anchor="w")
        ttk.Checkbutton(opts, text="安装完成后立即启动", variable=self.launch_var).pack(
            anchor="w", pady=(self.px(4), 0))

        tk.Frame(card, bg=BORDER, height=1).pack(fill="x", padx=self.px(22),
                                                 pady=(self.px(14), 0))
        foot = tk.Frame(card, bg=PANEL)
        foot.pack(fill="x", padx=self.px(22), pady=(self.px(12), self.px(18)),
                  side="bottom")
        self.progress = ttk.Progressbar(foot, style="Install.Horizontal.TProgressbar",
                                        maximum=100, value=0)
        self.progress.pack(fill="x")
        tk.Label(foot, textvariable=self.status_var, bg=PANEL, fg=MUTED,
                 font=("Microsoft YaHei UI", 9)).pack(anchor="w", pady=(self.px(6), 0))
        buttons = tk.Frame(foot, bg=PANEL)
        buttons.pack(fill="x", pady=(self.px(10), 0))
        self.install_btn = ttk.Button(buttons, text="安装", style="Install.TButton",
                                      command=self.start_install)
        self.install_btn.pack(side="right")
        self.cancel_btn = ttk.Button(buttons, text="取消", command=self.destroy)
        self.cancel_btn.pack(side="right", padx=(0, self.px(8)))

    # ---------------------------------------------------------------- 交互
    def browse(self) -> None:
        chosen = filedialog.askdirectory(title="选择安装位置",
                                         initialdir=str(Path(self.target_var.get()).parent))
        if chosen:
            self.target_var.set(str(Path(chosen) / info.PRODUCT))

    def start_install(self) -> None:
        if self.installing:
            return
        target = Path(self.target_var.get().strip())
        if not str(target):
            messagebox.showwarning("还没选位置", "请先选择安装位置。", parent=self)
            return
        if "windows" in str(target).lower().partition("system32")[0] and \
                str(target).lower().startswith(str(Path(os.environ.get("WINDIR", "C:\\Windows"))).lower()):
            messagebox.showwarning("换个位置", "不要装到 Windows 目录里。", parent=self)
            return
        if target.exists() and any(target.iterdir()):
            exe = target / info.EXE_NAME
            if exe.exists():
                if not messagebox.askyesno("已经装过", f"{target} 里已有安装，覆盖更新吗？",
                                           parent=self):
                    return
            elif not messagebox.askyesno("目录非空", f"{target} 不是空的，继续安装会把文件写进去。继续吗？",
                                         parent=self):
                return
        self.installing = True
        self.install_btn.state(["disabled"])
        self.cancel_btn.state(["disabled"])
        self.status_var.set("正在复制文件…")
        thread = threading.Thread(target=self._work, args=(target,), daemon=True)
        thread.start()

    def _work(self, target: Path) -> None:
        try:
            source = payload_root()
            files, total = tree_size(source)
            copied_bytes = 0
            if target.exists():
                shutil.rmtree(target, ignore_errors=False)
            target.mkdir(parents=True, exist_ok=True)
            for root, dirs, names in os.walk(source):
                rel = Path(root).relative_to(source)
                (target / rel).mkdir(parents=True, exist_ok=True)
                for name in names:
                    src = Path(root) / name
                    dst = target / rel / name
                    shutil.copy2(src, dst)
                    copied_bytes += src.stat().st_size
                    percent = 90 * copied_bytes / max(1, total)
                    self.events.put(("progress", (percent, f"正在复制 {rel / name}")))
            exe = target / info.EXE_NAME
            self.events.put(("progress", (92, "正在创建快捷方式…")))
            ok = shortcuts.create_shortcut(info.start_menu_link(), exe,
                                           workdir=target, icon=exe,
                                           description=f"{info.PRODUCT} {info.VERSION}")
            if self.desktop_var.get():
                shortcuts.create_shortcut(info.desktop_link(), exe,
                                          workdir=target, icon=exe,
                                          description=f"{info.PRODUCT} {info.VERSION}")
            size = sum(p.stat().st_size for p in target.rglob("*") if p.is_file())
            self.events.put(("progress", (96, "正在登记卸载信息…")))
            shortcuts.register_uninstall(target, exe, size)
            self.events.put(("progress", (100, "安装完成")))
            self.events.put(("done", (target, exe, ok)))
        except BaseException as exc:  # noqa: BLE001
            self.events.put(("error", exc))

    def _drain(self) -> None:
        try:
            while True:
                kind, payload = self.events.get_nowait()
                if kind == "progress":
                    percent, text = payload  # type: ignore[misc]
                    self.progress["value"] = percent
                    self.status_var.set(text)
                elif kind == "done":
                    self._finish(*payload)  # type: ignore[misc]
                elif kind == "error":
                    self._failed(payload)  # type: ignore[arg-type]
        except queue.Empty:
            pass
        if self.winfo_exists():
            self.after(60, self._drain)

    def _finish(self, target: Path, exe: Path, shortcut_ok: bool) -> None:
        self.installing = False
        self.status_var.set("安装完成")
        try:
            self.iconbitmap(str(exe))
        except Exception:
            pass
        message = f"已安装到：\n{target}\n\n开始菜单里有「{info.PRODUCT}」。"
        if not shortcut_ok:
            message += "\n\n（快捷方式创建失败，可以直接运行目录里的 exe）"
        messagebox.showinfo("安装完成", message, parent=self)
        if self.launch_var.get() and exe.exists():
            try:
                subprocess.Popen([str(exe)], cwd=str(target), close_fds=True)
            except OSError as exc:
                messagebox.showwarning("启动失败", str(exc), parent=self)
        self.destroy()

    def _failed(self, exc: BaseException) -> None:
        self.installing = False
        self.progress["value"] = 0
        self.status_var.set("安装失败")
        self.install_btn.state(["!disabled"])
        self.cancel_btn.state(["!disabled"])
        hint = ""
        if isinstance(exc, PermissionError):
            hint = "\n\n没有写入权限。换个用户可写的目录，或用管理员身份运行安装程序。"
        messagebox.showerror("安装失败", f"{type(exc).__name__}: {exc}{hint}", parent=self)


def silent_install(target: Path, *, desktop: bool = True, launch: bool = False) -> int:
    """命令行静默安装：--silent [--dir 目标] [--no-desktop] [--launch]。"""
    source = payload_root()
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True, exist_ok=True)
    for root, _dirs, names in os.walk(source):
        rel = Path(root).relative_to(source)
        (target / rel).mkdir(parents=True, exist_ok=True)
        for name in names:
            shutil.copy2(Path(root) / name, target / rel / name)
    exe = target / info.EXE_NAME
    payload = f"{info.PRODUCT}"
    shortcuts.create_shortcut(info.start_menu_link(), exe, workdir=target, icon=exe,
                              description=f"{payload} {info.VERSION}")
    if desktop:
        shortcuts.create_shortcut(info.desktop_link(), exe, workdir=target, icon=exe,
                                  description=f"{payload} {info.VERSION}")
    size = sum(p.stat().st_size for p in target.rglob("*") if p.is_file())
    shortcuts.register_uninstall(target, exe, size)
    print(f"已安装到 {target}")
    print(f"开始菜单：{info.start_menu_link()}")
    if desktop:
        print(f"桌面：{info.desktop_link()}")
    if launch and exe.exists():
        subprocess.Popen([str(exe)], cwd=str(target), close_fds=True)
    return 0


def main() -> int:
    enable_dpi()
    if not payload_root().exists():
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("安装包损坏", f"找不到安装文件：{payload_root()}")
        return 1
    args = sys.argv[1:]
    if "--silent" in args:
        target = info.default_install_dir()
        if "--dir" in args:
            index = args.index("--dir")
            if index + 1 < len(args):
                target = Path(args[index + 1])
        return silent_install(target, desktop="--no-desktop" not in args,
                              launch="--launch" in args)
    app = Installer()
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
