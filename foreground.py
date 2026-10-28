"""Which window is in front?  Used to show the overlay only while the game or this program is in front.

Windows only (ctypes, no extra packages).  Everywhere else ``foreground_info()`` returns None and the overlay
is simply always shown.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass

IS_WINDOWS = sys.platform.startswith("win")
GAME_WORDS = ("aion",)                 # in the window title or the program's file name


@dataclass
class Foreground:
    pid: int
    title: str
    exe: str
    fullscreen: bool

    def describe(self) -> str:
        return f"'{self.title[:60]}' ({self.exe or 'unknown program'})" + (", full screen" if self.fullscreen else "")


_API = None
_exe_cache: dict[int, str] = {}


def _api():
    global _API
    if _API is None:
        import ctypes
        from ctypes import wintypes
        u32, k32 = ctypes.windll.user32, ctypes.windll.kernel32
        u32.GetForegroundWindow.restype = wintypes.HWND
        u32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        u32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        u32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        u32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
        u32.MonitorFromWindow.restype = wintypes.HANDLE

        class MONITORINFO(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                        ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]
        u32.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.POINTER(MONITORINFO)]
        k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        k32.OpenProcess.restype = wintypes.HANDLE
        k32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
                                                   ctypes.POINTER(wintypes.DWORD)]
        k32.CloseHandle.argtypes = [wintypes.HANDLE]
        _API = (ctypes, wintypes, u32, k32, MONITORINFO)
    return _API


def _exe_name(pid: int) -> str:
    if pid in _exe_cache:
        return _exe_cache[pid]
    ctypes, wintypes, _u32, k32, _mi = _api()
    name = ""
    handle = k32.OpenProcess(0x1000, False, pid)            # PROCESS_QUERY_LIMITED_INFORMATION
    if handle:
        try:
            buf = ctypes.create_unicode_buffer(520)
            size = wintypes.DWORD(520)
            if k32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
                name = buf.value.replace("/", "\\").rsplit("\\", 1)[-1]
        finally:
            k32.CloseHandle(handle)
    if len(_exe_cache) > 64:
        _exe_cache.clear()
    _exe_cache[pid] = name
    return name


def foreground_info() -> Foreground | None:
    if not IS_WINDOWS:
        return None
    try:
        ctypes, wintypes, u32, _k32, MONITORINFO = _api()
        hwnd = u32.GetForegroundWindow()
        if not hwnd:
            return Foreground(0, "", "", False)               # nothing has focus (desktop / switching)
        buf = ctypes.create_unicode_buffer(256)
        u32.GetWindowTextW(hwnd, buf, 256)
        pid = wintypes.DWORD(0)
        u32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        rect = wintypes.RECT()
        fullscreen = False
        if u32.GetWindowRect(hwnd, ctypes.byref(rect)):
            mon = u32.MonitorFromWindow(hwnd, 2)               # MONITOR_DEFAULTTONEAREST
            info = MONITORINFO()
            info.cbSize = ctypes.sizeof(MONITORINFO)
            if mon and u32.GetMonitorInfoW(mon, ctypes.byref(info)):
                m = info.rcMonitor
                fullscreen = (rect.left <= m.left and rect.top <= m.top
                              and rect.right >= m.right and rect.bottom >= m.bottom)
        return Foreground(int(pid.value), buf.value, _exe_name(int(pid.value)), fullscreen)
    except Exception:
        return None


def overlay_should_show(info: Foreground | None, own_pid: int) -> bool:
    """True while the game (or this program) is the window in front.  Unknown -> show."""
    if info is None:
        return True
    if info.pid == own_pid:
        return True
    text = f"{info.title} {info.exe}".lower()
    if any(word in text for word in GAME_WORDS):
        return True
    return info.fullscreen            # a game in borderless full screen whose title we do not recognise
