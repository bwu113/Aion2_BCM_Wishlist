"""Is this program's window covered by another window?  Used so the overlay follows the program window.

Windows only (ctypes, no extra packages).  Everywhere else the answer is "unknown" and the overlay stays shown.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass

IS_WINDOWS = sys.platform.startswith("win")


@dataclass
class Window:
    pid: int
    title: str
    exe: str

    def describe(self) -> str:
        return f"'{self.title[:60]}' ({self.exe or 'unknown program'})"


_API = None
_exe_cache: dict[int, str] = {}


def _api():
    global _API
    if _API is None:
        import ctypes
        from ctypes import wintypes
        u32, k32 = ctypes.windll.user32, ctypes.windll.kernel32
        u32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
        u32.GetAncestor.restype = wintypes.HWND
        u32.IsIconic.argtypes = [wintypes.HWND]
        u32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        u32.WindowFromPoint.argtypes = [wintypes.POINT]
        u32.WindowFromPoint.restype = wintypes.HWND
        u32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        u32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        k32.OpenProcess.restype = wintypes.HANDLE
        k32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
                                                   ctypes.POINTER(wintypes.DWORD)]
        k32.CloseHandle.argtypes = [wintypes.HANDLE]
        _API = (ctypes, wintypes, u32, k32)
    return _API


def _exe_name(pid: int) -> str:
    if pid in _exe_cache:
        return _exe_cache[pid]
    ctypes, wintypes, _u32, k32 = _api()
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


def program_cover(widget_id: int, own_pid: int) -> tuple[str, Window | None]:
    """How much of this program's window can be seen?

    Returns ("visible", None) when some of it shows, ("covered", window) when only other programs' windows are on
    top of it (``window`` is the first one found), ("minimized", None), or ("unknown", None).
    """
    if not IS_WINDOWS:
        return "unknown", None
    try:
        ctypes, wintypes, u32, _k32 = _api()
        top = u32.GetAncestor(widget_id, 2) or widget_id            # GA_ROOT: the real top-level window
        if u32.IsIconic(top):
            return "minimized", None
        rect = wintypes.RECT()
        if not u32.GetWindowRect(top, ctypes.byref(rect)):
            return "unknown", None
        w, h = rect.right - rect.left, rect.bottom - rect.top
        if w < 80 or h < 80:
            return "unknown", None
        inset = 24                                                  # skip the invisible resize borders
        xs = (rect.left + inset, rect.left + w // 2, rect.right - inset)
        ys = (rect.top + inset, rect.top + h // 2, rect.bottom - inset)
        points = [(xs[1], ys[1]), (xs[0], ys[0]), (xs[2], ys[0]), (xs[0], ys[2]), (xs[2], ys[2])]
        foreign: Window | None = None
        for x, y in points:
            hit = u32.WindowFromPoint(wintypes.POINT(x, y))
            if not hit:
                continue
            hit = u32.GetAncestor(hit, 2) or hit
            pid = wintypes.DWORD(0)
            u32.GetWindowThreadProcessId(hit, ctypes.byref(pid))
            if int(pid.value) == own_pid:
                return "visible", None                              # at least part of the program shows
            if foreign is None:
                buf = ctypes.create_unicode_buffer(256)
                u32.GetWindowTextW(hit, buf, 256)
                foreign = Window(int(pid.value), buf.value, _exe_name(int(pid.value)))
        return ("covered", foreign) if foreign is not None else ("unknown", None)
    except Exception:
        return "unknown", None


def overlay_should_show(state: str, cover: Window | None) -> bool:
    """The overlay simply follows the program window: hidden while another window covers the program."""
    return state != "covered"                                       # visible / unknown / minimised (handled elsewhere)
