"""
Windows "start with Windows" support via the HKCU Run registry key.

Uses HKEY_CURRENT_USER, not HKEY_LOCAL_MACHINE, so no admin rights are
needed and the setting only affects the current Windows user account.
"""
import sys
import winreg
from pathlib import Path

from .config import APP_NAME

_RUN_KEY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"


def _get_launch_command() -> str:
    """
    Command written into the registry. Points at the frozen .exe when
    running as a PyInstaller build (the normal case for end users);
    falls back to `pythonw main.py` for dev/interpreter runs.
    """
    if getattr(sys, "frozen", False):
        exe = Path(sys.executable).resolve()
        return f'"{exe}" --minimized'
    else:
        main_py = Path(__file__).resolve().parent.parent / "main.py"
        # pythonw avoids flashing a console window on boot
        pythonw = Path(sys.executable).with_name("pythonw.exe")
        interpreter = pythonw if pythonw.exists() else Path(sys.executable)
        return f'"{interpreter}" "{main_py}" --minimized'


def is_enabled() -> bool:
    """Return True if the app is currently registered to start with Windows."""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY_PATH, 0, winreg.KEY_READ) as key:
            winreg.QueryValueEx(key, APP_NAME)
            return True
    except OSError:
        return False


def set_enabled(enabled: bool) -> None:
    """Add or remove the startup registry entry. Raises OSError on failure."""
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, _RUN_KEY_PATH, 0, winreg.KEY_SET_VALUE) as key:
        if enabled:
            winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, _get_launch_command())
        else:
            try:
                winreg.DeleteValue(key, APP_NAME)
            except FileNotFoundError:
                pass
