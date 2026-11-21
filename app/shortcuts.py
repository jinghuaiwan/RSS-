"""快捷方式与注册表：安装、卸载都用这里，避免装完卸不掉。"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from . import install_info as info

CREATE_NO_WINDOW = 0x08000000


def _quote(value: object) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def create_shortcut(link: Path, target: Path, *, workdir: Path | None = None,
                    icon: Path | None = None, description: str = "") -> bool:
    """用 WScript.Shell 建 .lnk；没有 PowerShell 时退回同目录 .url 快捷方式。"""
    link = Path(link)
    link.parent.mkdir(parents=True, exist_ok=True)
    script_parts = [
        "$ErrorActionPreference='Stop'",
        "$w=New-Object -ComObject WScript.Shell",
        f"$s=$w.CreateShortcut({_quote(link)})",
        f"$s.TargetPath={_quote(target)}",
        f"$s.WorkingDirectory={_quote(workdir or Path(target).parent)}",
        f"$s.Description={_quote(description or info.PRODUCT)}",
    ]
    if icon:
        script_parts.append(f"$s.IconLocation={_quote(f'{icon},0')}")
    script_parts.append("$s.Save()")
    try:
        done = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
             "-Command", ";".join(script_parts)],
            capture_output=True, text=True, timeout=60,
            creationflags=CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        if done.returncode == 0 and link.exists():
            return True
    except (OSError, subprocess.SubprocessError):
        pass
    return False


def remove_shortcut(link: Path) -> None:
    try:
        Path(link).unlink(missing_ok=True)
    except OSError:
        pass


def register_uninstall(install_dir: Path, exe: Path, size_bytes: int) -> None:
    """在「设置 → 应用」里登记一条卸载项（HKCU，不需要管理员）。"""
    import winreg

    values = {
        "DisplayName": f"{info.PRODUCT} {info.VERSION}",
        "DisplayVersion": info.VERSION,
        "Publisher": info.PUBLISHER,
        "InstallLocation": str(install_dir),
        "DisplayIcon": f"{exe},0",
        "UninstallString": f'"{exe}" --uninstall',
        "QuietUninstallString": f'"{exe}" --uninstall --yes',
        "NoModify": 1,
        "NoRepair": 1,
        "EstimatedSize": max(1, size_bytes // 1024),
    }
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, info.REG_SUBKEY, 0,
                            winreg.KEY_WRITE) as key:
        for name, value in values.items():
            if isinstance(value, int):
                winreg.SetValueEx(key, name, 0, winreg.REG_DWORD, value)
            else:
                winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)
        winreg.SetValueEx(key, "InstallDate", 0, winreg.REG_SZ,
                          _today())
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, info.REG_APP_KEY, 0,
                            winreg.KEY_WRITE) as key:
        winreg.SetValueEx(key, "InstallDir", 0, winreg.REG_SZ, str(install_dir))


def _today() -> str:
    from datetime import date

    return date.today().strftime("%Y%m%d")


def unregister() -> None:
    import winreg

    for subkey in (info.REG_SUBKEY, info.REG_APP_KEY):
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, subkey)
        except OSError:
            pass


def registered_install_dir() -> Path | None:
    """从注册表读安装目录，卸载时程序被挪走也能找回。"""
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, info.REG_APP_KEY) as key:
            value, _type = winreg.QueryValueEx(key, "InstallDir")
            return Path(str(value))
    except OSError:
        return None


def running_from_install_dir() -> bool:
    exe = Path(sys.executable).resolve()
    return exe.name.lower() == info.EXE_NAME.lower()
