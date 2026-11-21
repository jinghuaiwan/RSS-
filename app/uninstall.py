"""卸载：删快捷方式、注册表项和程序目录，保留用户数据。"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from . import install_info as info
from . import shortcuts


def _detach(command: str) -> None:
    flags = 0
    if os.name == "nt":
        flags = getattr(subprocess, "DETACHED_PROCESS", 0x00000008) | \
                getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
    subprocess.Popen(command, shell=True, creationflags=flags,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     stdin=subprocess.DEVNULL)


def schedule_removal(install_dir: Path) -> None:
    """退出后删掉安装目录（exe 正在运行，只能交给 cmd 延迟执行）。"""
    if not install_dir.exists():
        return
    _detach(f'cmd /c ping -n 3 127.0.0.1 >nul & rmdir /s /q "{install_dir}"')


def perform_uninstall(install_dir: Path | None = None, *, remove_data: bool = False) -> list[str]:
    """执行卸载，返回做过的动作（给界面显示）。"""
    target = Path(install_dir) if install_dir else (shortcuts.registered_install_dir()
                                                    or Path(sys.executable).resolve().parent)
    done: list[str] = []
    info.start_menu_link()
    shortcuts.remove_shortcut(info.start_menu_link())
    shortcuts.remove_shortcut(info.desktop_link())
    done.append("已删除开始菜单和桌面快捷方式")
    shortcuts.unregister()
    done.append("已移除「应用和功能」里的卸载项")
    if remove_data:
        data = info.data_dir()
        if data.exists():
            import shutil

            shutil.rmtree(data, ignore_errors=True)
            done.append(f"已删除数据目录 {data}")
    schedule_removal(target)
    done.append(f"程序目录将在几秒后删除：{target}")
    return done


def ask_and_uninstall() -> int:
    """带确认框的卸载入口（--uninstall 用）。"""
    import tkinter as tk
    from tkinter import messagebox

    target = shortcuts.registered_install_dir() or Path(sys.executable).resolve().parent
    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    ok = messagebox.askyesno(
        "卸载 RSS 阅读器",
        f"将从下面的位置删除程序：\n{target}\n\n"
        f"你的订阅、收藏和设置保存在：\n{info.data_dir()}\n"
        "卸载后不会删除这些数据（想彻底清理可手动删除该目录）。\n\n确定要卸载吗？",
        icon="question", parent=root,
    )
    if not ok:
        root.destroy()
        return 0
    done = perform_uninstall(target)
    messagebox.showinfo("卸载完成", "\n".join(done), parent=root)
    root.destroy()
    return 0
