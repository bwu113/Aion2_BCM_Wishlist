"""Tk widgets: the searchable item dropdown and the resizable shop overlay."""
from __future__ import annotations

import sys
import tkinter as tk
from tkinter import ttk
from typing import Callable

import theme
from catalog import FuzzyIndex, PickerEntry, TYPE_LABELS, search_entries
from wishlist import Cell, TabView, card_slots


class SearchDropdown(ttk.Frame):
    """A combo box that lists every item of the item list and can be searched by typing.

    * click the arrow (or the text box) to open the full list, scroll or type to narrow it down
    * Up / Down move through the list, Enter or a click picks the highlighted item
    * ``get_entry()`` returns what the user chose: ("item", PickerEntry), ("keyword", text) or None

    The list is an ordinary widget placed over the window (not a separate popup window), so it
    cannot steal keyboard focus from the text box while the user types.
    """
    MAX_ROWS = 10

    def __init__(self, parent: tk.Misc, entries: list[PickerEntry], on_submit: Callable[[], None] | None = None) -> None:
        super().__init__(parent)
        self.entries = entries
        self.on_submit = on_submit
        self.shown: list[PickerEntry] = []
        self._fuzzy: FuzzyIndex | None = None
        self.similar = False                        # the rows shown are look-alikes for a misspelled search
        self.selected: PickerEntry | None = None
        self._suppress = False
        self._open = False

        self.text = tk.StringVar()
        self.entry = ttk.Entry(self, textvariable=self.text)
        self.entry.pack(side="left", fill="x", expand=True)
        self.arrow = ttk.Button(self, text="\u25bc", width=3, command=self.toggle, takefocus=False)
        self.arrow.pack(side="left", padx=(2, 0))

        top = self.winfo_toplevel()
        self.popup = tk.Frame(top, bd=0, bg=theme.ACCENT, highlightthickness=0, padx=1, pady=1)
        self.listbox = tk.Listbox(self.popup, activestyle="none", exportselection=False, height=self.MAX_ROWS,
                                  selectmode="browse", highlightthickness=0, bd=0, bg=theme.FIELD, fg=theme.TEXT,
                                  selectbackground="#27407a", selectforeground="white", font=theme.FONT)
        bar = ttk.Scrollbar(self.popup, orient="vertical", command=self.listbox.yview)
        self.listbox.configure(yscrollcommand=bar.set)
        bar.pack(side="right", fill="y")
        self.listbox.pack(side="left", fill="both", expand=True)

        self.text.trace_add("write", lambda *_: self._typed())
        self.entry.bind("<Down>", lambda _e: self._move(1) or "break")
        self.entry.bind("<Up>", lambda _e: self._move(-1) or "break")
        self.entry.bind("<Return>", self._return)
        self.entry.bind("<Escape>", lambda _e: self.close())
        self.entry.bind("<Button-1>", lambda _e: self.after_idle(self.open))
        self.listbox.bind("<ButtonRelease-1>", self._clicked)
        top.bind("<Button-1>", self._outside_click, add="+")
        top.bind("<Configure>", lambda e: self._reposition() if e.widget is top else None, add="+")

    # -- list ------------------------------------------------------------- #
    def _filter(self) -> None:
        query = self.text.get()
        self.shown = search_entries(self.entries, query, limit=len(self.entries) + 1)
        self.similar = False
        if not self.shown and query.strip():                 # nothing contains these words: allow for misspellings
            if self._fuzzy is None:
                self._fuzzy = FuzzyIndex(self.entries)
            self.shown = self._fuzzy.search(query)
            self.similar = bool(self.shown)
        self.listbox.delete(0, "end")
        tail = "   (similar)" if self.similar else ""
        for e in self.shown:
            self.listbox.insert("end", f"{e.name}   [{TYPE_LABELS.get(e.kind, e.kind)}]{tail}")
        if self.shown:
            self._highlight(0)
        self.listbox.configure(height=max(1, min(self.MAX_ROWS, len(self.shown))))

    def _highlight(self, index: int) -> None:
        self.listbox.selection_clear(0, "end")
        self.listbox.selection_set(index)
        self.listbox.activate(index)
        self.listbox.see(index)

    def _current_index(self) -> int | None:
        sel = self.listbox.curselection()
        return int(sel[0]) if sel else None

    def _move(self, step: int) -> None:
        if not self._open:
            self.open()
            return
        if not self.shown:
            return
        cur = self._current_index()
        nxt = 0 if cur is None else max(0, min(len(self.shown) - 1, cur + step))
        self._highlight(nxt)

    # -- open / close ------------------------------------------------------ #
    def open(self) -> None:
        self._filter()
        self._open = True
        self._reposition()

    def _reposition(self) -> None:
        if not self._open:
            return
        top = self.winfo_toplevel()
        x = self.winfo_rootx() - top.winfo_rootx()
        y = self.winfo_rooty() - top.winfo_rooty() + self.winfo_height()
        if not self.shown:
            self.popup.place_forget()
            return
        self.popup.place(x=x, y=y, width=self.winfo_width())
        self.popup.lift()

    def close(self) -> None:
        self._open = False
        self.popup.place_forget()

    def toggle(self) -> None:
        if self._open:
            self.close()
        else:
            self.open()
            self.entry.focus_set()

    def _typed(self) -> None:
        if self._suppress:
            return
        self.selected = None
        self.open()

    def _clicked(self, event: tk.Event) -> None:
        index = self.listbox.nearest(event.y)
        if 0 <= index < len(self.shown):
            self._choose(index)

    def _choose(self, index: int) -> None:
        self.selected = self.shown[index]
        self._set_text(self.selected.name)
        self.close()
        self.entry.focus_set()
        self.entry.icursor("end")

    def _return(self, _event: tk.Event | None = None) -> str:
        index = self._current_index()
        if self._open and index is not None and index < len(self.shown):
            self._choose(index)
        elif self.on_submit:
            self.on_submit()
        return "break"

    def _outside_click(self, event: tk.Event) -> None:
        if not self._open:
            return
        w = event.widget
        while w is not None:
            if w is self or w is self.popup:
                return
            w = getattr(w, "master", None)
        self.close()

    # -- result ------------------------------------------------------------ #
    def _set_text(self, text: str) -> None:
        self._suppress = True
        try:
            self.text.set(text)
        finally:
            self._suppress = False

    def clear(self) -> None:
        self.selected = None
        self._set_text("")
        self.close()

    def get_entry(self) -> tuple[str, PickerEntry | str] | None:
        """What the user wants to add: a catalog item, a keyword, or nothing."""
        text = self.text.get().strip()
        if not text:
            return None
        if self.selected and self.selected.name.casefold() == text.casefold():
            return ("item", self.selected)
        matches = search_entries(self.entries, text, limit=len(self.entries) + 1)
        exact = [e for e in matches if e.name.casefold() == text.casefold()]
        if exact:
            return ("item", exact[0])
        if len(matches) == 1:
            return ("item", matches[0])
        return ("keyword", text)

    def focus_entry(self) -> None:
        self.entry.focus_set()


# --------------------------------------------------------------------------- #
# Overlay - mimics the in-game Black Cloud Merchant shop screen
# --------------------------------------------------------------------------- #
# Geometry is in "reference pixels" of a 1920x1080 screenshot of the shop and is scaled to the window.
REF = (404, 0, 1516, 660)               # x0, y0, x1, y1 of the part of the screen that is drawn
CARD_W, CARD_H, CARD_TIP = 160, 250, 20
TAB_X = {"Special": 757, "Pets": 960, "Skins": 1162}
TAB_Y = 34
LINE_H = 1.3                              # line height / font size
# The overlay is never drawn smaller than this scale, because below it the smallest texts (long item names
# at 10 px, prices, badges) stop being readable and would crowd into each other.
MIN_SCALE = 0.58
ASPECT = (REF[2] - REF[0]) / (REF[3] - REF[1])
MIN_HEIGHT = int(round((REF[3] - REF[1]) * MIN_SCALE))
MIN_WIDTH = int(round(MIN_HEIGHT * ASPECT))
NAME_BOX = (24, 140)                      # top and bottom of the item-name area of a card (reference px)
# Card centre x and top y, measured from the screenshot (6 on the top row, 4 on the bottom row).
TOP10 = [(535, 112), (705, 124), (875, 132), (1045, 132), (1215, 124), (1385, 112)]
BOTTOM10 = [(535, 384), (705, 396), (1215, 396), (1385, 384)]

C_BG = "#0b0d12"
C_TEXT = "#d7deee"
C_DIM = "#5d667a"
C_LINE = "#2d3442"
C_HIT = "#14573a"
C_HIT_LINE = "#62e8a5"
C_HIT_GLOW = "#2b9f6c"
C_CARD = "#151a23"
BADGE = {10: "#1f7a43", 20: "#1f5fae", 30: "#a02a2a", 50: "#a02a2a"}
BADGE_DIM = {10: "#1c3a2a", 20: "#1e3250", 30: "#4a2429", 50: "#4a2429"}
ICON = {"pet": ("#1f6f78", "PET"), "skin": ("#5a3d8f", "SKIN"), "godstone": ("#8a5a1d", "STONE"),
        "other": ("#444b59", "ITEM"), "": ("#444b59", "?")}
TYPE_STYLE = {          # kind -> (bright colour for wanted cards, muted colour for the rest, label)
    "pet": ("#1f8f9c", "#1d5560", "PET"),
    "skin": ("#7048c4", "#46327a", "SKIN"),
    "godstone": ("#c47a1d", "#7a5220", "STONE"),
    "other": ("#5b6579", "#3b4352", "ITEM"),
    "": ("#5b6579", "#3b4352", "?"),
}
ICON_DIM = {"pet": "#1b2e33", "skin": "#2a2340", "godstone": "#3a2c1a", "other": "#262b35", "": "#262b35"}


def _geometry(count: int) -> list[tuple[int, int]]:
    """(centre x, top y) in reference pixels for each card in reading order."""
    if count == 10:
        return TOP10 + BOTTOM10
    slots = card_slots(count)
    out: list[tuple[int, int]] = []
    for row in (0, 1):
        n = sum(1 for r, _c in slots if r == row)
        for i in range(n):
            mid = (n - 1) / 2
            u = (i - mid) / mid if mid else 0
            base, depth = (112, 20) if row == 0 else (384, 12)
            out.append((int(960 + (i - mid) * 170), int(base + depth * (1 - u * u))))
    return out


OVERLAY_RATIO = 0.8                          # overlay height as a share of the program window's height
MIN_WINDOW_HEIGHT = int(-(-MIN_HEIGHT // OVERLAY_RATIO))      # shortest window whose overlay is still readable


def overlay_size(window_height: int) -> tuple[int, int]:
    """(width, height) of the overlay that goes with a program window of this height."""
    height = max(int(round(int(window_height) * OVERLAY_RATIO)), MIN_HEIGHT)
    return int(round(height * ASPECT)), height


def monitor_work_area(window: tk.Misc) -> tuple[int, int, int, int]:
    """(left, top, right, bottom) of the usable area of the monitor that holds ``window``.

    Tk's own screen size is only the PRIMARY monitor, so with two monitors it must not be used to decide
    where the overlay goes.  On Windows the real monitor under the window is asked; elsewhere the whole
    virtual desktop is used.
    """
    cx = window.winfo_rootx() + window.winfo_width() // 2
    cy = window.winfo_rooty() + window.winfo_height() // 2
    if sys.platform.startswith("win"):
        try:
            import ctypes
            from ctypes import wintypes

            class MONITORINFO(ctypes.Structure):
                _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                            ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]

            user32 = ctypes.windll.user32
            user32.MonitorFromPoint.restype = wintypes.HANDLE
            user32.MonitorFromPoint.argtypes = [wintypes.POINT, wintypes.DWORD]
            handle = user32.MonitorFromPoint(wintypes.POINT(int(cx), int(cy)), 2)      # MONITOR_DEFAULTTONEAREST
            info = MONITORINFO()
            info.cbSize = ctypes.sizeof(MONITORINFO)
            if handle and user32.GetMonitorInfoW(wintypes.HANDLE(handle), ctypes.byref(info)):
                w = info.rcWork
                return int(w.left), int(w.top), int(w.right), int(w.bottom)
        except Exception:
            pass
    try:
        vx, vy = int(window.winfo_vrootx()), int(window.winfo_vrooty())
        vw, vh = int(window.winfo_vrootwidth()), int(window.winfo_vrootheight())
    except Exception:
        vx = vy = vw = vh = 0
    if vw <= 1 or vh <= 1:
        vx, vy, vw, vh = 0, 0, int(window.winfo_screenwidth()), int(window.winfo_screenheight())
    return vx, vy, vx + vw, vy + vh


def dock_position(rx: int, ry: int, rw: int, rh: int, ow: int, oh: int,
                  monitor: tuple[int, int, int, int]) -> tuple[int, int]:
    """Where the overlay (ow x oh) goes for a program window at rx,ry (size rw x rh).

    Right of the window; if that would leave the window's monitor, left of it; if neither fits, tucked
    against the monitor's right edge.  It never leaves the monitor the program is on.
    """
    left, top, right, bottom = monitor
    x = rx + rw
    if x + ow > right:
        x = rx - ow if rx - ow >= left else max(left, right - ow)
    y = min(max(ry, top), max(top, bottom - oh))
    return x, y


def wrap_words(text: str, max_width: float, measure: Callable[[str], float]) -> list[str]:
    """Greedy word wrap; a single word wider than the box is split."""
    lines: list[str] = []
    cur = ""
    for word in text.split():
        trial = f"{cur} {word}".strip()
        if measure(trial) <= max_width or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = word
        while measure(cur) > max_width and len(cur) > 1:          # very long single word
            cut = len(cur) - 1
            while cut > 1 and measure(cur[:cut]) > max_width:
                cut -= 1
            lines.append(cur[:cut])
            cur = cur[cut:]
    if cur:
        lines.append(cur)
    return lines


def fit_text(text: str, box_w: float, box_h: float, px_max: int, px_min: int,
             measure: Callable[[str, int], float]) -> tuple[int, list[str]]:
    """Largest font (px_max .. px_min) at which ``text`` wraps to fit the box; if even px_min does not
    fit, the text is cut with an ellipsis so it can never run into the next element."""
    px = max(px_min, px_max)
    while True:
        lines = wrap_words(text, box_w, lambda t, p=px: measure(t, p))
        if len(lines) * px * LINE_H <= box_h:
            return px, lines
        if px <= px_min:
            break
        px -= 1
    keep = max(1, int(box_h // (px * LINE_H)))
    lines = lines[:keep]
    last = lines[-1] + "\u2026"
    while len(last) > 1 and measure(last, px) > box_w:
        last = last[:-2] + "\u2026"
    lines[-1] = last
    return px, lines


class OverlayWindow(tk.Toplevel):
    """Replica of the shop screen with your wanted items lit up, docked beside the program window.

    It is owned by the program window: it sits just above it and goes behind other windows (alt+tab to
    another program) together with it - it is not "always on top".

    Cards are in the in-game positions (6 on the top row, 4 on the bottom row).  Click a tab
    to look at another tab; the overlay jumps to the tab you open in the game.
    """

    def __init__(self, parent: tk.Misc, alpha: float = 1.0) -> None:
        super().__init__(parent)
        self.overrideredirect(True)                 # no title bar: it is docked to the program window
        self.configure(bg=C_LINE)
        self._views: list[TabView] = []
        self.selected = "Special"
        self._pending = False
        self._fonts: dict[tuple[int, bool], object] = {}
        self._drawn: tuple | None = None              # what is on the canvas now: skip identical redraws
        self._views_key: tuple = ()
        try:
            self.transient(parent)                    # owned by the program window: it follows that window's stacking
        except tk.TclError:
            pass
        try:
            if alpha < 1.0:                           # a see-through window costs the compositor extra work
                self.attributes("-alpha", alpha)
        except tk.TclError:
            pass
        self.canvas = tk.Canvas(self, bg=C_BG, highlightthickness=0, bd=0)
        self.canvas.pack(fill="both", expand=True, padx=1, pady=1)
        self.canvas.bind("<Configure>", lambda _e: self._schedule())

    # -- public ----------------------------------------------------------- #
    def set_alpha(self, alpha: float) -> None:
        try:
            self.attributes("-alpha", max(0.3, min(1.0, alpha)))
        except tk.TclError:
            pass

    def update_views(self, views: list[TabView]) -> None:
        self._views = views
        self._views_key = tuple(
            (v.tab, v.seen, tuple((c.item_id, c.name, c.kind, c.quantity, c.wanted is not None) for c in v.cells))
            for v in views)
        self._schedule()

    def show_tab(self, tab: str) -> None:
        if tab != self.selected:
            self.selected = tab
            self._schedule()

    def set_geometry(self, x: int, y: int, width: int, height: int) -> None:
        self.geometry(f"{int(width)}x{int(height)}+{int(x)}+{int(y)}")

    def _measure(self, text: str, px: int) -> float:
        """Pixel width of bold text at this font size (real font metrics when Tk provides them)."""
        try:
            from tkinter import font as tkfont
            key = (px, True)
            f = self._fonts.get(key)
            if f is None:
                f = self._fonts[key] = tkfont.Font(family="Segoe UI", size=-px, weight="bold")
            return float(f.measure(text))
        except Exception:
            return len(text) * px * 0.62

    def _schedule(self) -> None:
        """Redraw soon; many requests (window being dragged, several updates) collapse into one redraw."""
        if not self._pending:
            self._pending = True
            self.after(30, self._draw)

    # -- drawing ---------------------------------------------------------- #
    def _draw(self) -> None:
        self._pending = False
        c = self.canvas
        width = max(int(c.winfo_width()), 60)
        height = max(int(c.winfo_height()), 60)
        state = (width, height, self.selected, self._views_key)
        if state == self._drawn:
            return                                    # nothing changed since the last redraw
        self._drawn = state
        c.delete("all")
        if not self._views:
            c.create_text(width / 2, height / 2, text="Waiting for the shop...", fill=C_DIM)
            return
        rx0, ry0, rx1, ry1 = REF
        s = min(width / (rx1 - rx0), height / (ry1 - ry0))
        ox = (width - (rx1 - rx0) * s) / 2 - rx0 * s
        oy = (height - (ry1 - ry0) * s) / 2 - ry0 * s
        self._s, self._ox, self._oy = s, ox, oy

        by_tab = {v.tab: v for v in self._views}
        if self.selected not in by_tab:
            self.selected = next((v.tab for v in self._views if v.seen), self._views[0].tab)
        view = by_tab[self.selected]
        self._draw_tabs(view)
        if not view.seen:
            self._draw_unscanned(view)
            return
        geo = _geometry(len(view.cells))
        for cell, (cx, top) in zip(view.cells, geo):
            self._draw_card(cell, cx, top)
        self._draw_summary(view)

    def _font(self, px: float, bold: bool = False, floor: int = 9) -> tuple:
        size = -max(floor, int(round(px * self._s)))
        return ("Segoe UI", size, "bold") if bold else ("Segoe UI", size)

    def _pt(self, x: float, y: float) -> tuple[float, float]:
        return self._ox + x * self._s, self._oy + y * self._s

    def _draw_tabs(self, current: TabView) -> None:
        c = self.canvas
        for view in self._views:
            cx = TAB_X.get(view.tab, 960)
            hits = len(view.matches)
            x0, y0 = self._pt(cx - 100, TAB_Y - 26)
            x1, y1 = self._pt(cx + 100, TAB_Y + 26)
            tag = f"tab_{view.tab}"
            c.create_rectangle(x0, y0, x1, y1, fill=C_BG, outline=C_BG, tags=(tag,))
            active = view.tab == current.tab
            colour = C_TEXT if active else (C_DIM if not view.seen else "#9aa5bd")
            tx, ty = self._pt(cx, TAB_Y)
            c.create_text(tx, ty, text=view.tab, fill=colour, font=self._font(26, active), tags=(tag,))
            if active:
                ux0, uy = self._pt(cx - 70, TAB_Y + 28)
                ux1, _ = self._pt(cx + 70, TAB_Y + 28)
                c.create_line(ux0, uy, ux1, uy, fill="#5b8cff", width=max(2, int(3 * self._s)), tags=(tag,))
            if hits:
                bx, by = self._pt(cx + 62, TAB_Y - 14)
                r = 13 * self._s
                c.create_oval(bx - r, by - r, bx + r, by + r, fill=C_HIT_GLOW, outline="", tags=(tag,))
                c.create_text(bx, by, text=str(hits), fill="white", font=self._font(16, True), tags=(tag,))
            elif not view.seen:
                bx, by = self._pt(cx + 62, TAB_Y - 14)
                c.create_text(bx, by, text="?", fill=C_DIM, font=self._font(18, True), tags=(tag,))
            c.tag_bind(tag, "<Button-1>", lambda _e, t=view.tab: self.show_tab(t))

    def _draw_unscanned(self, view: TabView) -> None:
        c = self.canvas
        for cx, top in _geometry(10):
            x0, y0 = self._pt(cx - CARD_W / 2, top)
            x1, y1 = self._pt(cx + CARD_W / 2, top + CARD_H)
            c.create_rectangle(x0, y0, x1, y1, outline=C_LINE, dash=(4, 4))
        tx, ty = self._pt(960, 330)
        c.create_text(tx, ty, text=f"{view.tab} not scanned yet\nclick the {view.tab} tab in the game",
                      fill=C_DIM, font=self._font(30, True), justify="center")

    def _draw_card(self, cell: Cell, cx: int, top: int) -> None:
        c, s = self.canvas, self._s
        wanted = cell.wanted is not None
        x0, x1, y1 = cx - CARD_W / 2, cx + CARD_W / 2, top + CARD_H
        body = [x0, top, x1, top, x1, y1 - CARD_TIP, cx, y1, x0, y1 - CARD_TIP]

        def poly(points: list[float], grow: float = 0) -> list[float]:
            out: list[float] = []
            for i in range(0, len(points), 2):
                px, py = points[i], points[i + 1]
                px += grow if px > cx else -grow if px < cx else 0
                py += grow if py >= y1 - 1 else -grow if py <= top + 1 else 0
                out += list(self._pt(px, py))
            return out

        if wanted:
            c.create_polygon(poly(body, 7), fill=C_HIT_GLOW, outline="")
        c.create_polygon(poly(body), fill=C_HIT if wanted else C_CARD, outline=C_HIT_LINE if wanted else C_LINE,
                         width=max(2, int(3 * s)) if wanted else 1)
        # hanger
        hx0, hy0 = self._pt(cx - 14, top - 6)
        hx1, hy1 = self._pt(cx + 14, top + 20)
        c.create_rectangle(hx0, hy0, hx1, hy1, fill=C_BG, outline=C_HIT_LINE if wanted else C_LINE)
        # name (top of the card): the biggest font (never below 10 px) at which the wrapped name fits its box
        n = len(cell.name)
        start = 20 if n <= 16 else 18 if n <= 24 else 16 if n <= 34 else 15
        box_w = (CARD_W - 16) * s
        box_h = (NAME_BOX[1] - NAME_BOX[0]) * s
        px, lines = fit_text(cell.name, box_w, box_h, int(round(start * s)), 10, self._measure)
        nx, ny = self._pt(cx, top + NAME_BOX[0])
        c.create_text(nx, ny, text="\n".join(lines), anchor="n", justify="center",
                      fill="white" if wanted else "#9aa5bd", font=("Segoe UI", -px, "bold"))
        # ITEM TYPE: the centrepiece of the card - big, colourful, readable at a glance
        bright, dim, label = TYPE_STYLE.get(cell.kind, TYPE_STYLE[""])
        tx0, ty0 = self._pt(cx - 60, top + 148)
        tx1, ty1 = self._pt(cx + 60, top + 196)
        c.create_rectangle(tx0, ty0, tx1, ty1, fill=bright if wanted else dim,
                           outline="white" if wanted else bright, width=2 if wanted else 1)
        tx_, ty_ = self._pt(cx, top + 172)
        c.create_text(tx_, ty_, text=label, fill="white", font=self._font(26, True, floor=12))
        # quantity
        qx, qy = self._pt(cx, top + 216)
        c.create_text(qx, qy, text=f"x{cell.quantity}", fill="white" if wanted else "#8793ab",
                      font=self._font(19, True))

    def _draw_summary(self, view: TabView) -> None:
        """Wanted items listed in the empty space where the merchant stands."""
        c = self.canvas
        hits = view.matches
        tx, ty = self._pt(960, 425)
        if not hits:
            c.create_text(tx, ty + 40 * self._s, text="none of your wanted items\nin this tab", fill=C_DIM,
                          font=self._font(22), justify="center")
            return
        c.create_text(tx, ty, text="WANTED HERE", fill=C_HIT_LINE, font=self._font(20, True))
        lines = []
        for cell in hits[:5]:
            lines.append(cell.name)
        if len(hits) > 5:
            lines.append(f"+ {len(hits) - 5} more")
        lx, ly = self._pt(960, 450)
        c.create_text(lx, ly, text="\n".join(lines), anchor="n", justify="center", fill="white",
                      width=300 * self._s, font=self._font(16))
