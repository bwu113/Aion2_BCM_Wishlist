"""Dark colour theme for the main window (the overlay has its own matching colours)."""
from __future__ import annotations

import sys
import tkinter as tk
from tkinter import ttk

BG = "#10131a"          # window background
PANEL = "#161a22"
FIELD = "#0b0e13"       # text boxes, lists
TEXT = "#d7deee"
DIM = "#8793ab"
LINE = "#2d3442"
BTN = "#222938"
BTN_HOVER = "#2e384c"
BTN_DOWN = "#3a4660"
ACCENT = "#5b8cff"
HIT = "#14573a"         # "found" row
HIT_TEXT = "#e8fff3"
FONT = ("Segoe UI", 10)


def apply_theme(root: tk.Misc) -> None:
    """Style every ttk widget used by the program in dark colours."""
    root.configure(bg=BG)
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass
    style.configure(".", background=BG, foreground=TEXT, fieldbackground=FIELD, bordercolor=LINE,
                    lightcolor=BG, darkcolor=BG, troughcolor=FIELD, focuscolor=BG, insertcolor=TEXT, font=FONT)
    style.configure("TFrame", background=BG)
    style.configure("TLabel", background=BG, foreground=TEXT)
    style.configure("Title.TLabel", font=("Segoe UI", 15, "bold"), foreground="white")
    style.configure("Dim.TLabel", foreground=DIM)
    style.configure("TButton", background=BTN, foreground=TEXT, bordercolor=LINE, lightcolor=BTN, darkcolor=BTN,
                    padding=(12, 5), relief="flat", focusthickness=0)
    style.map("TButton",
              background=[("disabled", PANEL), ("pressed", BTN_DOWN), ("active", BTN_HOVER)],
              foreground=[("disabled", "#566074")],
              bordercolor=[("active", ACCENT)],
              lightcolor=[("pressed", BTN_DOWN), ("active", BTN_HOVER)],
              darkcolor=[("pressed", BTN_DOWN), ("active", BTN_HOVER)])
    style.configure("Accent.TButton", background=ACCENT, foreground="white", bordercolor=ACCENT,
                    lightcolor=ACCENT, darkcolor=ACCENT)
    style.map("Accent.TButton", background=[("disabled", PANEL), ("pressed", "#3d68d6"), ("active", "#7aa2ff")],
              foreground=[("disabled", "#566074")], lightcolor=[("active", "#7aa2ff")], darkcolor=[("active", "#7aa2ff")])
    style.configure("TEntry", fieldbackground=FIELD, foreground=TEXT, bordercolor=LINE, lightcolor=LINE,
                    darkcolor=LINE, insertcolor=TEXT, padding=5)
    style.map("TEntry", bordercolor=[("focus", ACCENT)], lightcolor=[("focus", ACCENT)], darkcolor=[("focus", ACCENT)])
    style.configure("TCombobox", fieldbackground=FIELD, background=BTN, foreground=TEXT, arrowcolor=DIM,
                    bordercolor=LINE, lightcolor=FIELD, darkcolor=FIELD, insertcolor=TEXT, padding=5)
    style.map("TCombobox", fieldbackground=[("readonly", FIELD)], foreground=[("readonly", TEXT)],
              background=[("active", BTN_HOVER)], bordercolor=[("focus", ACCENT)], arrowcolor=[("active", TEXT)])
    root.option_add("*TCombobox*Listbox.background", FIELD)
    root.option_add("*TCombobox*Listbox.foreground", TEXT)
    root.option_add("*TCombobox*Listbox.selectBackground", "#27407a")
    root.option_add("*TCombobox*Listbox.selectForeground", "white")
    style.configure("Treeview", background=FIELD, fieldbackground=FIELD, foreground=TEXT, bordercolor=LINE,
                    lightcolor=FIELD, darkcolor=FIELD, rowheight=26, relief="flat")
    style.map("Treeview", background=[("selected", "#27407a")], foreground=[("selected", "white")])
    style.configure("Treeview.Heading", background=PANEL, foreground=DIM, bordercolor=LINE, lightcolor=PANEL,
                    darkcolor=PANEL, relief="flat", padding=(6, 4))
    style.map("Treeview.Heading", background=[("active", BTN_HOVER)])
    style.configure("Vertical.TScrollbar", background=BTN, troughcolor=FIELD, bordercolor=FIELD,
                    arrowcolor=DIM, lightcolor=BTN, darkcolor=BTN, gripcount=0)
    style.map("Vertical.TScrollbar", background=[("active", BTN_HOVER)])
    style.configure("Horizontal.TScale", background=BTN_HOVER, troughcolor=FIELD, bordercolor=LINE,
                    lightcolor=BTN_HOVER, darkcolor=BTN_HOVER)
    style.map("Horizontal.TScale", background=[("active", ACCENT)])


def dark_titlebar(window: tk.Misc) -> None:
    """Ask Windows 10/11 for a dark title bar (silently does nothing elsewhere)."""
    if not sys.platform.startswith("win"):
        return
    try:
        import ctypes
        window.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(window.winfo_id())
        value = ctypes.c_int(1)
        for attribute in (20, 19):          # DWMWA_USE_IMMERSIVE_DARK_MODE (new / old build numbers)
            if ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attribute, ctypes.byref(value), ctypes.sizeof(value)) == 0:
                break
    except Exception:
        pass

