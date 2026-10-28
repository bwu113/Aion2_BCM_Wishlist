"""BCM Wishlist (AION 2).

Passive packet capture (Npcap, read directly - see npcap_native.py) that decodes the Black Cloud Merchant shop, checks it
against YOUR wishlist and shows where the wanted items are in an overlay docked to the right
of the window.  Npcap (https://npcap.com) must be installed on the PC.

It does not inject packets, modify game memory, or automate gameplay.

Files next to the program (or in %APPDATA%\\BCMWishlist if that folder is read-only):
    wishlist.json     your wishlist (created automatically, at most 100 items)
    item_catalog.csv  your own names / corrections (optional)
The item list aion2_items.csv is built into the exe.
"""
from __future__ import annotations

import datetime as dt
import os
import queue
import sys
import threading
import time
import traceback
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Any

import npcap_native
import theme
from catalog import TYPE_LABELS, Catalog, append_user_catalog, update_user_catalog
import safety
from shop_decoder import ShopDecoder, ShopPage
import chime
from bulk_add import Resolver, parse_list
from paste_dialog import NameItemDialog, NoticeDialog, PasteListDialog, ResolveDialog
from ui_widgets import MIN_WINDOW_HEIGHT, OverlayWindow, SearchDropdown, dock_position, monitor_work_area, overlay_size
from wishlist import MAX_WISHLIST, TABS, WishEntry, Wishlist, WishlistFull, build_views

APP_TITLE = "BCM Wishlist"
CHIME_FILE = "found_chime.wav"
ITEMS_FILE = "aion2_items.csv"
USER_CATALOG_FILE = "item_catalog.csv"
WISHLIST_FILE = "wishlist.json"
DEBUG_FILE = "bcm_debug.txt"
LOG_FILE = "bcm_log.txt"
LOG_MAX_BYTES = 300_000
MIN_WIDTH = 400
DEFAULT_WIDTH = 460
DEFAULT_HEIGHT = 486                    # overlay about 658 x 389 (80 % of the window height)


def app_dir() -> str:
    """Folder of the .exe (frozen) or of this script."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def resource_dir() -> str:
    """Folder with files bundled into the .exe (PyInstaller) or the script folder."""
    return getattr(sys, "_MEIPASS", None) or app_dir()


def data_dir() -> str:
    """Where wishlist.json lives: next to the program, or %APPDATA% when that folder is read-only."""
    here = app_dir()
    if os.access(here, os.W_OK):
        return here
    base = os.environ.get("APPDATA") or os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~")
    path = os.path.join(base, "BCMWishlist")
    try:
        os.makedirs(path, exist_ok=True)
    except OSError:
        return here
    return path


def lower_priority() -> None:
    """Run below normal priority so the game always gets the CPU first (Windows only)."""
    if not sys.platform.startswith("win"):
        return
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        kernel32.SetPriorityClass(kernel32.GetCurrentProcess(), 0x4000)       # BELOW_NORMAL_PRIORITY_CLASS
    except Exception:
        pass


def format_timestamp(value: float | int | None) -> str:
    try:
        stamp = dt.datetime.fromtimestamp(float(value)) if value is not None else dt.datetime.now()
        return stamp.strftime("%H:%M:%S")
    except Exception:
        return dt.datetime.now().strftime("%H:%M:%S")


class BlackCloudWatcher:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title(APP_TITLE)
        self._set_icon()

        self.packet_queue: queue.Queue[tuple[str, Any]] = queue.Queue(maxsize=2000)
        self.stop_event = threading.Event()
        self.worker: threading.Thread | None = None
        self.running = False
        self.packet_count = 0
        self.queue_drops = 0
        self.capture_started_monotonic: float | None = None
        self._waiting_notice_sent = False
        self._had_error = False

        self.decoder = ShopDecoder()          # used by the capture thread only
        self._narrow_sent = False
        self._polling = False
        self.pages: dict[str, ShopPage] = {}
        self.page_time: dict[str, str] = {}
        self.catalog = Catalog()
        self.wishlist = Wishlist(os.path.join(data_dir(), WISHLIST_FILE))
        self._picker_entries: list | None = None
        self.last_error = ""                    # details of the last unexpected error (the program keeps running)
        self._format_problems = 0               # shop messages that did not look as expected, this scan
        self._format_details: list[str] = []
        self._diag_time = 0.0                   # last refresh of the live diagnostic numbers
        self._debug_clock = 0.0
        self._log_bytes = 0
        self._debug_written = 0                 # how many unreadable big messages are already in bcm_debug.txt
        self._auto_stopped = False              # the scan ended by itself because all 3 tabs were scanned
        self._outdated_notified = False         # the "download a new version" notice is shown once per scan
        self._notice_window = None
        self._naming_queue: list = []           # unknown shop items waiting for the user to name them
        self._naming_dialog = None
        self._naming_done = 0
        self.root.report_callback_exception = self._on_callback_error
        self.overlay: OverlayWindow | None = None
        self._user_hid_overlay = False          # the user clicked Hide: do not pop it up again by itself
        self._auto_show_pending = False         # show the overlay on the first shop page of a scan
        self.current_tab = ""
        self._sync_pending = False
        self._overlay_geometry: tuple | None = None
        self._window_placement: tuple | None = None
        self.views: list = []
        self.status_var = tk.StringVar(value="Add the items you want, then click Start Scan.")

        theme.apply_theme(self.root)
        self._load_catalogs()
        try:
            problem = self.wishlist.load()
        except Exception as exc:                                    # (load() handles bad content itself)
            problem = f"Could not read {WISHLIST_FILE}: {exc}"
        if problem:
            messagebox.showwarning("Wishlist", problem)

        self.chime = chime.Chime(os.path.join(resource_dir(), CHIME_FILE))
        self.volume_var = tk.IntVar(value=chime.clamp_volume(self.wishlist.settings.get("chime_volume", chime.DEFAULT_VOLUME)))
        self.volume_text = tk.StringVar(value=f"{self.volume_var.get()}%")

        self._build_ui()
        self._place_window()
        theme.dark_titlebar(self.root)
        self.refresh_all()
        self.root.bind("<Configure>", self._on_root_configure)
        self.root.bind("<Unmap>", self._on_root_unmap)
        self.root.bind("<Map>", self._on_root_map)
        self.root.after(250, self._drain_queue)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ------------------------------------------------------------------ #
    # Catalog
    # ------------------------------------------------------------------ #
    def _load_catalogs(self) -> None:
        self.catalog = Catalog()
        self._picker_entries = None
        shipped = next((p for p in (os.path.join(app_dir(), ITEMS_FILE), os.path.join(resource_dir(), ITEMS_FILE))
                        if os.path.isfile(p)), "")
        if shipped:
            try:
                self.catalog.load_csv(shipped)
            except Exception as exc:
                messagebox.showerror("Item list", f"Could not read {ITEMS_FILE}:\n{exc}")
        else:
            messagebox.showwarning("Item list", f"{ITEMS_FILE} was not found.\n"
                                                "The item dropdown will be empty until it is restored.")
        for folder in dict.fromkeys((app_dir(), data_dir())):
            user = os.path.join(folder, USER_CATALOG_FILE)
            if os.path.isfile(user):
                try:
                    self.catalog.load_csv(user)
                except Exception as exc:
                    messagebox.showerror("Item list", f"Could not read {USER_CATALOG_FILE}:\n{exc}")

    def picker_entries(self) -> list:
        if self._picker_entries is None:
            self._picker_entries = self.catalog.picker_entries()
        return self._picker_entries

    # ------------------------------------------------------------------ #
    # UI
    # ------------------------------------------------------------------ #
    def _build_ui(self) -> None:
        outer = ttk.Frame(self.root, padding=14)
        outer.pack(fill="both", expand=True)
        ttk.Label(outer, text=APP_TITLE, style="Title.TLabel").pack(anchor="w")

        ttk.Label(outer, text="Add an item - open the list or start typing to search:", style="Dim.TLabel").pack(
            anchor="w", pady=(12, 4))
        add_row = ttk.Frame(outer)
        add_row.pack(fill="x")
        self.dropdown = SearchDropdown(add_row, self.picker_entries(), on_submit=self.add_item)
        self.dropdown.pack(side="left", fill="x", expand=True)
        ttk.Button(add_row, text="Add", width=7, command=self.add_item, style="Accent.TButton").pack(
            side="left", padx=(8, 0))
        ttk.Button(add_row, text="Paste list", command=self.open_paste_dialog).pack(side="left", padx=(8, 0))

        self.count_var = tk.StringVar()
        head_row = ttk.Frame(outer)
        head_row.pack(fill="x", pady=(10, 4))
        ttk.Label(head_row, textvariable=self.count_var, style="Dim.TLabel").pack(side="left")
        ttk.Button(head_row, text="Clear all", command=self.clear_all, padding=(10, 2)).pack(side="right")
        # Bottom rows are packed first so that, when the window is short, the item list gives way and
        # the buttons and the status text stay fully visible.
        self.status_label = ttk.Label(outer, textvariable=self.status_var, wraplength=400, justify="left")
        self.status_label.pack(side="bottom", fill="x", pady=(12, 0))
        outer.bind("<Configure>", lambda e: self.status_label.configure(wraplength=max(160, e.width - 42))
                   if e.widget is outer else None)

        scan_row = ttk.Frame(outer)
        scan_row.pack(side="bottom", fill="x", pady=(14, 0))
        self.start_button = ttk.Button(scan_row, text="Start Scan", command=self.start_live_capture,
                                       style="Accent.TButton")
        self.start_button.pack(side="left")
        self.stop_button = ttk.Button(scan_row, text="Stop Scan", command=self.stop_capture, state="disabled")
        self.stop_button.pack(side="left", padx=(8, 0))
        self.overlay_button = ttk.Button(scan_row, text="Show Overlay", command=self.toggle_overlay)
        self.overlay_button.pack(side="right")

        tools_row = ttk.Frame(outer)
        tools_row.pack(side="bottom", fill="x", pady=(10, 0))
        ttk.Button(tools_row, text="Delete selected", command=self.delete_item).pack(side="left")
        ttk.Button(tools_row, text="Test", width=5, command=self.test_chime).pack(side="right")
        ttk.Label(tools_row, textvariable=self.volume_text, width=5, anchor="e").pack(side="right", padx=(6, 8))
        self.volume_scale = ttk.Scale(tools_row, from_=0, to=100, orient="horizontal", length=110,
                                      variable=self.volume_var, command=self._on_volume_drag)
        self.volume_scale.pack(side="right")
        self.volume_scale.bind("<ButtonRelease-1>", lambda _e: self._save_volume())
        for key in ("Left", "Right", "Up", "Down", "Home", "End"):
            self.volume_scale.bind(f"<KeyRelease-{key}>", lambda _e: self._save_volume())
        ttk.Label(tools_row, text="Chime volume", style="Dim.TLabel").pack(side="right", padx=(0, 8))

        list_row = ttk.Frame(outer)
        list_row.pack(fill="both", expand=True)
        self.wish_tree = ttk.Treeview(list_row, columns=("name", "where"), show="headings", selectmode="extended", height=4)
        self.wish_tree.heading("name", text="Item")
        self.wish_tree.heading("where", text="In the shop right now")
        self.wish_tree.column("name", width=210, minwidth=120, anchor="w")
        self.wish_tree.column("where", width=190, minwidth=100, anchor="w")
        self.wish_tree.tag_configure("found", background=theme.HIT, foreground=theme.HIT_TEXT)
        bar = ttk.Scrollbar(list_row, orient="vertical", command=self.wish_tree.yview)
        self.wish_tree.configure(yscrollcommand=bar.set)
        self.wish_tree.pack(side="left", fill="both", expand=True)
        bar.pack(side="right", fill="y")
        self.wish_tree.bind("<Delete>", lambda _e: self.delete_item())

    def _set_icon(self) -> None:
        """Window / taskbar icon (bcm_icon.ico is also embedded in the exe by the build)."""
        folder = resource_dir()
        try:
            if sys.platform.startswith("win"):
                self.root.iconbitmap(os.path.join(folder, "bcm_icon.ico"))
            else:
                self._icon_image = tk.PhotoImage(file=os.path.join(folder, "bcm_icon.png"))
                self.root.iconphoto(True, self._icon_image)
        except Exception:
            pass                                            # a missing icon must never stop the program

    def _place_window(self) -> None:
        """Start centred with room for the overlay on the right; the smallest size is set by the overlay."""
        self.root.update_idletasks()
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        need_w, need_h = self.root.winfo_reqwidth(), self.root.winfo_reqheight()
        min_w = max(MIN_WIDTH, need_w)                     # never narrower than the controls need
        self.root.minsize(min_w, max(MIN_WINDOW_HEIGHT, need_h))
        height = max(MIN_WINDOW_HEIGHT, need_h, min(DEFAULT_HEIGHT, sh - 140))
        width = max(DEFAULT_WIDTH, min_w)
        while width + overlay_size(height)[0] > sw - 40 and height > MIN_WINDOW_HEIGHT:
            height -= 10
        height = max(height, MIN_WINDOW_HEIGHT)
        total = width + overlay_size(height)[0]
        x = max(10, (sw - total) // 2)
        y = max(10, (sh - height) // 2 - 20)
        self.root.geometry(f"{width}x{height}+{x}+{y}")

    def _set_status(self, message: str) -> None:
        self.status_var.set(message)

    # ------------------------------------------------------------------ #
    # Wishlist actions
    # ------------------------------------------------------------------ #
    def add_item(self) -> None:
        got = self.dropdown.get_entry()
        if got is None:
            self._set_status("Pick an item from the dropdown (or type part of its name) first.")
            return
        kind, value = got
        if len(self.wishlist.entries) >= MAX_WISHLIST:
            self._set_status(f"Your list is full ({MAX_WISHLIST} items). Delete something to add more.")
            return
        entries: list[WishEntry] = []
        note = ""
        if kind == "item":
            entries.append(WishEntry.from_picker(value))      # type: ignore[arg-type]
        else:
            text = str(value)
            guess = Resolver(self.picker_entries()).resolve(text)      # misspelling? find the closest item(s)
            if guess.status == "item":
                entries.append(WishEntry.from_picker(guess.entry))     # type: ignore[arg-type]
                note = f' (matched "{text}" to the closest item)'
            elif guess.status == "suggest":
                choice, payload = self.resolve_choice(guess, 1, 1)
                if choice == "items":
                    entries.extend(WishEntry.from_picker(e) for e in payload)   # type: ignore[union-attr]
                else:
                    self._set_status("Nothing added. Check the spelling or pick an item from the dropdown.")
                    return
            else:
                if not messagebox.askyesno(
                        "Add as keyword?",
                        f'"{text}" is not an item in the list.\n\nAdd it as a keyword that matches any shop item '
                        "whose name contains this text?"):
                    return
                entries.append(WishEntry.keyword(text))
        if len(entries) == 1:
            entry = entries[0]
            try:
                added = self._wish_call(self.wishlist.add, entry)
            except WishlistFull:
                self._set_status(f"Your list is full ({MAX_WISHLIST} items). Delete something to add more.")
                return
            if added:
                self._set_status(f"Added: {entry.label()}{note}")
            else:
                self._set_status(f"Already on your list: {entry.label()}")
        else:
            added_list, dupes, overflow = self.wishlist.add_many(entries)
            if self.wishlist.last_save_error is not None:
                messagebox.showerror("Wishlist", f"Could not save {WISHLIST_FILE} in {data_dir()}:\n"
                                                 f"{self.wishlist.last_save_error}")
            message = f"Added {len(added_list)} item(s)."
            if dupes:
                message += f" {len(dupes)} already on your list."
            if overflow:
                message += f" Your list is full ({MAX_WISHLIST} items): {len(overflow)} not added."
            self._set_status(message)
        self.dropdown.clear()
        self.refresh_all()
        self.dropdown.focus_entry()

    def open_paste_dialog(self) -> None:
        if getattr(self, "_paste_dialog", None) is not None:
            try:
                self._paste_dialog.lift()
                self._paste_dialog.focus_set()
                return
            except tk.TclError:
                self._paste_dialog = None
        self._paste_dialog = PasteListDialog(self.root, self.add_pasted, MAX_WISHLIST)

    def _dialog_parent(self):
        """The Paste list window if it is open (pop-ups go on top of it), otherwise the main window."""
        dialog = getattr(self, "_paste_dialog", None)
        if dialog is not None:
            try:
                if dialog.winfo_exists():
                    return dialog
            except tk.TclError:
                pass
            self._paste_dialog = None
        return self.root

    def resolve_choice(self, r, index: int, total: int) -> tuple[str, object]:
        """Pop-up for one name that fits several items (or only roughly one): the user decides."""
        dialog = ResolveDialog(self._dialog_parent(), r.line, r.matches, index, total, exact=(r.status == "ambiguous"))
        self.root.wait_window(dialog)
        return dialog.result

    def add_pasted(self, text: str) -> tuple[str, str, bool]:
        """Add every name in a pasted list.  Returns (lines left over, message, everything was handled).
        Whatever does not fit under the wishlist limit is cut off (and shown to the user in a notice)."""
        results = parse_list(text, Resolver(self.picker_entries()))
        total = sum(1 for r in results if r.status in ("ambiguous", "suggest"))
        entries: list[WishEntry] = []
        left: list = []                                     # lines that stay in the box
        cut: list[str] = []                                 # names that did not fit under the limit
        matched_notes: list[str] = []
        room = MAX_WISHLIST - len(self.wishlist.entries)

        def take(entry: WishEntry) -> None:
            nonlocal room
            if any(self.wishlist._same(e, entry) for e in self.wishlist.entries) or \
                    any(self.wishlist._same(e, entry) for e in entries):
                entries.append(entry)                       # already there: add_many counts it as a duplicate
            elif room > 0:
                room -= 1
                entries.append(entry)
            else:
                cut.append(entry.label())

        asked = 0
        cancelled = False
        for r in results:
            if r.status == "item":
                take(WishEntry.from_picker(r.entry))
                if r.note:
                    matched_notes.append(r.note)
            elif room <= 0:
                cut.append(r.line)                          # the list is full: no point asking about this one
            elif r.status == "missing" or cancelled:
                left.append(r)
            else:                                           # several matches / only close ones: ask the user
                asked += 1
                kind, payload = self.resolve_choice(r, asked, total)
                if kind == "items":
                    for e in payload:                       # type: ignore[union-attr]
                        take(WishEntry.from_picker(e))
                else:
                    cancelled = True
                    left.append(r)
        added, dupes, overflow = self.wishlist.add_many(entries)
        cut.extend(e.label() for e in overflow)             # (safety net: add_many enforces the limit too)
        if self.wishlist.last_save_error is not None:
            messagebox.showerror("Wishlist", f"Could not save {WISHLIST_FILE} in {data_dir()}:\n"
                                             f"{self.wishlist.last_save_error}")
        self.refresh_all()

        parts = [f"Added {len(added)} item(s)."]
        if dupes:
            parts.append(f"{len(dupes)} already on your list.")
        if cut:
            parts.append(f"{len(cut)} cut off (limit {MAX_WISHLIST}).")
        notes: list[str] = []
        if matched_notes:
            shown = matched_notes[:3] + ([f"... and {len(matched_notes) - 3} more"] if len(matched_notes) > 3 else [])
            notes.append("Matched to the closest item: " + "; ".join(shown))
        missing = [r for r in left if r.status == "missing"]
        if missing:
            names = ", ".join(f'"{r.line}"' for r in missing[:4]) + (", ..." if len(missing) > 4 else "")
            notes.append(f"Not in the item list: {names}")
        if cancelled:
            notes.append("Stopped early - the unresolved lines are still in the box.")
        message = " ".join(parts) + ("\n" + "\n".join(notes) if notes else "")

        leftover_lines = [r.line for r in left]
        finished = not leftover_lines
        if finished:
            self._set_status(" ".join(parts) + (" " + notes[0] if matched_notes else ""))
        else:
            self._set_status(f"Added {len(added)} item(s). {len(leftover_lines)} line(s) were not added - "
                             "see the Paste list window.")
        if cut:
            self.show_cut_off(cut)
        return "\n".join(leftover_lines), message, finished

    def show_cut_off(self, names: list[str]) -> None:
        """Tell the user which pasted items did not fit under the wishlist limit."""
        dialog = NoticeDialog(self._dialog_parent(), "List limit reached",
                              f"Your wishlist holds at most {MAX_WISHLIST} items, so only the first ones were "
                              f"added. These {len(names)} item(s) were cut off:", names)
        self.root.wait_window(dialog)

    def clear_all(self) -> None:
        count = len(self.wishlist.entries)
        if count == 0:
            self._set_status("Your list is already empty.")
            return
        if not messagebox.askyesno(
                "Clear the whole list?",
                f"This removes all {count} item(s) from your wishlist and cannot be undone.\n\nClear the list?",
                icon="warning", default="no"):
            return
        self._wish_call(self.wishlist.clear)
        self._set_status(f"Cleared your list ({count} item(s) removed).")
        self.refresh_all()

    def delete_item(self) -> None:
        indices = sorted((int(i) for i in self.wish_tree.selection()), reverse=True)
        if not indices:
            self._set_status("Select one or more items in the list, then click Delete.")
            return
        for i in indices:
            self._wish_call(self.wishlist.delete, i)
        self._set_status(f"Removed {len(indices)} item(s).")
        self.refresh_all()

    def _wish_call(self, fn, *args):
        try:
            return fn(*args)
        except OSError as exc:
            messagebox.showerror("Wishlist", f"Could not save {WISHLIST_FILE} in {data_dir()}:\n{exc}")
            return False

    # ------------------------------------------------------------------ #
    # Views
    # ------------------------------------------------------------------ #
    def refresh_all(self) -> None:
        self.refresh_views()

    def refresh_views(self) -> None:
        previous = {(c.tab, c.item_id) for v in self.views for c in v.matches}
        self.views = build_views(self.pages, self.wishlist, self.catalog, self.page_time)
        found: dict[int, list[str]] = {}
        fresh: list = []
        for view in self.views:
            for cell in view.matches:
                found.setdefault(id(cell.wanted), []).append(f"{view.tab} {cell.position_text}")
                if (cell.tab, cell.item_id) not in previous:
                    fresh.append(cell)
        self.count_var.set(f"Items I'm looking for ({len(self.wishlist.entries)} / {MAX_WISHLIST}):")
        for iid in self.wish_tree.get_children():
            self.wish_tree.delete(iid)
        for i, entry in enumerate(self.wishlist.entries):
            where = "; ".join(found.get(id(entry), []))
            self.wish_tree.insert("", "end", iid=str(i), tags=(("found",) if where else ()),
                                  values=(entry.label(), where))
        if self.overlay is not None:
            try:
                self.overlay.update_views(self.views)
            except Exception as exc:                                # a drawing problem must never stop the program
                self._on_callback_error(type(exc), exc, exc.__traceback__)
        self._announce(fresh)

    def _announce(self, fresh: list) -> None:
        if not fresh:
            return
        first = fresh[0]
        more = f" (+{len(fresh) - 1} more)" if len(fresh) > 1 else ""
        self._set_status(f"FOUND: {first.name} - {first.tab} tab, {first.position_text}, {first.price:,} Kina{more}")
        self._play_chime()

    def _play_chime(self) -> None:
        """Shop-door bell chime at the chosen volume; falls back to the system beep if it cannot be played."""
        if self.chime.play(self.volume_var.get()) != "unavailable":
            return
        try:
            self.root.bell()
        except tk.TclError:
            pass

    def _on_volume_drag(self, value: str) -> None:
        self.volume_var.set(chime.clamp_volume(value))
        self.volume_text.set(f"{self.volume_var.get()}%")

    def _save_volume(self) -> None:
        volume = chime.clamp_volume(self.volume_var.get())
        self.wishlist.settings["chime_volume"] = volume
        try:
            self.wishlist.save()
        except OSError:
            pass                                            # the volume still applies for this session
        self.test_chime()

    def test_chime(self) -> None:
        self._play_chime()

    # ------------------------------------------------------------------ #
    # Overlay: docked to the right of the window, as tall as the window
    # ------------------------------------------------------------------ #
    def toggle_overlay(self) -> None:
        if self.overlay is None:
            self._user_hid_overlay = False
            self.show_overlay()
        else:
            self._user_hid_overlay = True
            self.hide_overlay()

    def show_overlay(self) -> None:
        if self.overlay is None:
            self.overlay = OverlayWindow(self.root)
            self._overlay_geometry = None
            self._window_placement = None
        seen = [v.tab for v in self.views if v.seen]
        self.overlay.selected = self.current_tab if self.current_tab in seen else (seen[0] if seen else "Special")
        self.overlay.update_views(self.views)
        self._sync_overlay()
        self._update_overlay_button()
        if not self._polling:
            self._polling = True
            self.root.after(500, self._poll_overlay)

    def hide_overlay(self) -> None:
        if self.overlay is not None:
            self.overlay.destroy()
            self.overlay = None
        self._update_overlay_button()

    def _update_overlay_button(self) -> None:
        """The button always says what a click will do, based on whether the overlay is really showing."""
        self.overlay_button.configure(text="Hide Overlay" if self.overlay is not None else "Show Overlay")

    def _sync_overlay(self) -> None:
        """Dock the overlay against the window: same top, same height, on the window's own monitor."""
        self._sync_pending = False
        ov = self.overlay
        if ov is None:
            return
        r = self.root
        placed = (r.winfo_rootx(), r.winfo_rooty(), r.winfo_width(), r.winfo_height())
        if placed == self._window_placement and self._overlay_geometry is not None:
            return                                         # the window has not moved or resized
        self._window_placement = placed
        width, height = overlay_size(placed[3])
        x, y = dock_position(placed[0], placed[1], placed[2], placed[3], width, height, monitor_work_area(r))
        geometry = (x, y, width, height)
        if geometry != self._overlay_geometry:
            self._overlay_geometry = geometry
            ov.set_geometry(x, y, width, height)

    def _poll_overlay(self) -> None:
        """Safety net: re-dock twice a second in case a window move did not send an event (only while shown)."""
        if self.overlay is None:
            self._polling = False
            return
        self._sync_overlay()
        self.root.after(500, self._poll_overlay)

    def _on_root_configure(self, event: tk.Event) -> None:
        if event.widget is self.root and self.overlay is not None and not self._sync_pending:
            self._sync_pending = True
            self.root.after_idle(self._sync_overlay)

    def _on_root_unmap(self, event: tk.Event) -> None:
        if event.widget is self.root and self.overlay is not None:
            self.overlay.withdraw()

    def _on_root_map(self, event: tk.Event) -> None:
        if event.widget is self.root and self.overlay is not None:
            self.overlay.deiconify()
            self._sync_overlay()

    # ------------------------------------------------------------------ #
    # Capture
    # ------------------------------------------------------------------ #
    def start_live_capture(self) -> None:
        if self.running:
            return
        self.packet_count = 0
        self.queue_drops = 0
        self.pages.clear()
        self.page_time.clear()
        self.current_tab = ""
        self.refresh_views()
        self.stop_event.clear()
        self.capture_started_monotonic = time.monotonic()
        self._waiting_notice_sent = False
        self._had_error = False
        self._format_problems = 0
        self._format_details = []
        self._outdated_notified = False
        self._auto_stopped = False
        self._debug_written = 0
        self._log_bytes = 0
        self._remove_debug_file()
        self.running = True
        self._set_controls_running(True)
        self._set_status("Scanning. In the game open the Black Cloud Merchant and click each tab "
                         "(Special, Pets, Skins).")
        self._auto_show_pending = True                      # the overlay appears with the first shop page
        self.worker =  threading.Thread(target=self._live_worker, daemon=True)
        self.worker.start()

    def _live_worker(self) -> None:
        """Capture thread: reads packets, decodes the shop, and hands only finished shop pages to the window."""
        decoder = self.decoder
        decoder.reset()
        self._narrow_sent = False

        log_clock = [time.monotonic()]

        def on_fields(fields: dict):
            self.packet_count += 1
            flow = (fields["src"], fields["sport"], fields["dst"], fields["dport"])
            try:
                pages = decoder.feed_tcp(flow, fields["seq"], fields["payload"], fields["time"])
            except Exception as exc:                        # a decoder bug must never kill the capture
                self._safe_queue_put(("format", f"the shop data caused an error ({type(exc).__name__}: {exc})"))
                return None
            if decoder.problems:                            # shop messages it could not read (game update?)
                for detail in decoder.problems[:5]:
                    self._safe_queue_put(("format", detail))
                decoder.problems.clear()
            for page in pages:
                self._safe_queue_put(("page", (page, fields["time"])))
            if time.monotonic() - log_clock[0] >= 1.0:       # hand the connection's event notes to the window once a second
                log_clock[0] = time.monotonic()
                lines = decoder.take_log()
                if lines:
                    self._safe_queue_put(("log", lines))
            if decoder.locked_flow is not None and not self._narrow_sent:
                self._narrow_sent = True                    # found the game connection: listen to it alone
                src, sport = decoder.locked_flow[0], decoder.locked_flow[1]
                return f"tcp and src host {src} and src port {sport}"
            return None

        def on_restart() -> None:                           # game connection lost: start wide again
            decoder.reset()
            self._narrow_sent = False

        try:
            try:
                api = npcap_native.PcapAPI()
                npcap_native.NpcapCapture(api, on_fields, self.stop_event, on_restart).run()
            except npcap_native.NpcapMissing:
                raise
            except npcap_native.NpcapError as exc:
                if self.stop_event.is_set():
                    return
                raise RuntimeError(str(exc)) from exc
        except Exception as exc:
            self._safe_queue_put(("error", f"Live capture failed: {exc}"))
        finally:
            try:
                lines = decoder.take_log()                  # the last second of notes, so the log is complete
                if lines:
                    self.packet_queue.put(("log", lines), timeout=0.5)
            except Exception:
                pass
            self._safe_queue_put(("finished", "live"))

    def stop_capture(self) -> None:
        if not self.running:
            return
        self.stop_event.set()
        self.stop_button.configure(state="disabled")
        self._set_status("Stopping scan...")

    def _safe_queue_put(self, item: tuple[str, Any]) -> None:
        try:
            self.packet_queue.put_nowait(item)
        except queue.Full:
            if item[0] == "packet":
                self.queue_drops += 1

    def _set_controls_running(self, is_running: bool) -> None:
        self.start_button.configure(state="disabled" if is_running else "normal")
        self.stop_button.configure(state="normal" if is_running else "disabled")

    def _drain_queue(self) -> None:
        processed = 0
        while processed < 200:
            try:
                kind, value = self.packet_queue.get_nowait()
            except queue.Empty:
                break
            processed += 1
            try:
                if kind == "page":
                    self._handle_page(*value)
                elif kind == "log":
                    self._append_log(value)
                elif kind == "format":
                    self._note_format_problem(str(value))
                elif kind == "warning":
                    self._set_status(str(value))
                elif kind == "error":
                    self._had_error = True
                    self._set_status(str(value))
                elif kind == "finished":
                    self.running = False
                    self._set_controls_running(False)
                    if self._auto_stopped and not self._had_error:
                        found = sum(len(v.matches) for v in self.views)
                        self._set_status("All 3 tabs scanned - scan stopped automatically. "
                                         + (f"{found} of your items found." if found else "None of your items are in the shop."))
                    elif not self._had_error:
                        self._set_status("Scan stopped.")
            except Exception as exc:                        # one bad message must never stop the program
                self._on_callback_error(type(exc), exc, exc.__traceback__)
        self._check_auto_stop()
        if self.running and time.monotonic() - self._debug_clock >= 2.0:
            self._debug_clock = time.monotonic()
            self._write_debug_file()                          # samples of the server messages the program could not read
        if self.running and self.capture_started_monotonic is not None and not self._waiting_notice_sent:
            elapsed = time.monotonic() - self.capture_started_monotonic
            if self.packet_count == 0 and elapsed >= 8:
                self._set_status("No game traffic seen yet. Is the game running and connected? "
                                 "If it stays empty, try running the program as administrator.")
                self._waiting_notice_sent = True
            elif self.packet_count > 0 and not self.pages and elapsed >= 15:
                self._set_status("Scanning. Now open the Black Cloud Merchant in the game and click each tab. "
                                 f"({self.decoder.summary()})")
                self._waiting_notice_sent = True
        elif (self.running and not self.pages and self._waiting_notice_sent
              and time.monotonic() - self._diag_time >= 2.0
              and self.status_var.get().startswith("Scanning. Now open")):
            self._diag_time = time.monotonic()               # keep the numbers live until the first shop page arrives
            self._write_debug_file()
            note = f" Details: {DEBUG_FILE}." if self._debug_written else ""
            self._set_status("Scanning. Now open the Black Cloud Merchant in the game and click each tab. "
                             f"({self.decoder.summary()}).{note}")
        self.root.after(150 if self.running else 600, self._drain_queue)

    def _remove_debug_file(self) -> None:
        for name in (DEBUG_FILE, LOG_FILE):
            try:
                os.remove(os.path.join(data_dir(), name))
            except OSError:
                pass

    def _append_log(self, lines: list) -> None:
        """bcm_log.txt: what happened to the game connection (lost packets, lost framing, shop messages)."""
        try:
            if self._log_bytes > LOG_MAX_BYTES:
                return
            text = "\n".join(str(x) for x in lines) + "\n"
            with open(os.path.join(data_dir(), LOG_FILE), "a", encoding="utf-8") as fh:
                fh.write(text)
            self._log_bytes += len(text)
        except Exception:
            pass                                               # diagnostics must never get in the way

    def _write_debug_file(self) -> None:
        """While no shop page has been read: keep the big messages the server sent in a text file (hex), so that a
        scan that finds nothing can be looked at afterwards.  Only appends; stops after DEBUG_FRAMES messages."""
        try:
            frames = list(self.decoder.debug_frames)
            if len(frames) <= self._debug_written:
                return
            with open(os.path.join(data_dir(), DEBUG_FILE), "a", encoding="utf-8") as fh:
                for i in range(self._debug_written, len(frames)):
                    fh.write(f"{i} len={len(frames[i])} {frames[i].hex()}\n")
            self._debug_written = len(frames)
        except Exception:
            pass                                               # diagnostics must never get in the way

    def _handle_page(self, page: ShopPage, stamp: float) -> None:
        self.pages[page.tab_guess] = page
        self.page_time[page.tab_guess] = format_timestamp(stamp)
        self.current_tab = page.tab_guess
        self._append_log([f"{time.strftime('%H:%M:%S')} window got the {page.tab_guess} list "
                          f"({len(self.pages)}/3 tabs filled: {', '.join(sorted(self.pages))})"])
        noted = False
        try:
            noted = self._check_page(page)
        except Exception as exc:                            # the safety net itself must never be a problem
            self._on_callback_error(type(exc), exc, exc.__traceback__)
        self.refresh_views()
        if self._auto_show_pending:
            self._auto_show_pending = False
            if self.overlay is None and not self._user_hid_overlay:
                self.show_overlay()
        if self.overlay is not None:
            self.overlay.show_tab(page.tab_guess)          # follow the tab being opened in the game
        if not noted and not any(v.matches for v in self.views):
            self._set_status(f"Scanned the {page.tab_guess} tab - none of your items. "
                             f"({len(self.pages)}/3 tabs scanned)")
        self._check_auto_stop()

    def _check_auto_stop(self) -> None:
        """End the scan as soon as the overlay has all three tabs filled in (Special, Pets, Skins)."""
        if not self.running or self._auto_stopped:
            return
        filled = {v.tab for v in self.views if v.seen and v.cells}
        if all(tab in filled for tab in TABS):
            self._auto_stopped = True
            self.stop_capture()

    # ------------------------------------------------------------------ #
    # Safety net: game updates / unknown items must never crash the program
    # ------------------------------------------------------------------ #
    def _on_callback_error(self, exc_type, exc, tb) -> None:
        """Any unexpected error ends up here: remember it, tell the user quietly, keep running."""
        try:
            self.last_error = "".join(traceback.format_exception(exc_type, exc, tb))
            self._set_status(f"Something unexpected happened ({exc_type.__name__}: {exc}). The program keeps running.")
        except Exception:
            pass

    def _check_page(self, page: ShopPage) -> bool:
        """Compare a decoded shop page with the item list: learn new items, or warn that the game was updated.
        Returns True if it put a message in the status line."""
        audit = safety.audit_page(page, self.catalog)
        if audit.verdict != "ok":
            self._append_log([f"{time.strftime('%H:%M:%S')} check of the {page.tab_guess} list: {audit.verdict} "
                              f"({'; '.join(audit.reasons)[:200]})"])
        if audit.verdict == "ok":
            return False
        if audit.new_items:
            self._learn_items(audit.new_items, page.tab_guess)
        if audit.verdict == "outdated":
            self._warn_outdated(audit.reasons)
        return True

    def _learn_items(self, items: list, tab: str) -> None:
        """Items that are in the shop but not in the item list: remember them by ID right away (so nothing is lost
        and the overlay can show them), then ask the user, one at a time, for their name and type."""
        for it in items:
            self.catalog.add(it.item_id, it.name, it.kind)
        self._refresh_picker()
        path = os.path.join(data_dir(), USER_CATALOG_FILE)
        unsaved = ""
        try:
            append_user_catalog(path, [(it.item_id, it.name, it.kind) for it in items])
        except OSError as exc:
            unsaved = f" (could not be saved to {USER_CATALOG_FILE}: {exc})"
        ids = ", ".join(str(it.item_id) for it in items[:3]) + (", ..." if len(items) > 3 else "")
        self._set_status(f"New item(s) in the shop that were not in the item list: {ids}. Please name them.{unsaved}")
        self._naming_queue.extend((it, tab) for it in items)
        self._next_naming()

    def _refresh_picker(self) -> None:
        self._picker_entries = None
        self.dropdown.entries = self.picker_entries()
        self.dropdown._fuzzy = None

    def _next_naming(self) -> None:
        if self._naming_dialog is not None or not self._naming_queue:
            return
        it, tab = self._naming_queue.pop(0)
        index = self._naming_done + 1
        total = index + len(self._naming_queue)
        try:
            self._naming_dialog = NameItemDialog(self.root, it.item_id, tab, it.kind, index, total,
                                                 lambda result, item=it: self._naming_finished(item, result))
        except Exception as exc:                            # even a failing pop-up must not matter
            self._naming_dialog = None
            self._on_callback_error(type(exc), exc, exc.__traceback__)

    def _naming_finished(self, item, result: tuple) -> None:
        self._naming_dialog = None
        self._naming_done += 1
        if result[0] == "save":
            _, name, kind = result
            self.catalog.add(item.item_id, name, kind)
            self._refresh_picker()
            try:
                update_user_catalog(os.path.join(data_dir(), USER_CATALOG_FILE), item.item_id, name, kind)
                self._set_status(f"Saved: {name} ({TYPE_LABELS.get(kind, kind)}).")
            except OSError as exc:
                self._set_status(f"Named it {name}, but could not save it to {USER_CATALOG_FILE} ({exc}).")
            self.refresh_views()
        elif result[0] == "skip_all":
            self._naming_queue.clear()
        if not self._naming_queue:
            self._naming_done = 0
        self.root.after_idle(self._next_naming)

    def _note_format_problem(self, detail: str) -> None:
        self._append_log([f"{time.strftime('%H:%M:%S')} problem: {detail[:200]}"])
        self._format_problems += 1
        self._format_details.append(detail)
        if self._format_problems >= 2:
            self._warn_outdated(list(dict.fromkeys(self._format_details))[:5])

    def _warn_outdated(self, reasons: list[str]) -> None:
        self._set_status("The game may have been updated - please download a new version of BCM Wishlist.")
        if self._outdated_notified:
            return
        self._outdated_notified = True
        self._notice(
            "Please download a new version",
            "The game seems to have changed (it was probably updated), and this version of BCM Wishlist may no longer "
            "read the shop correctly. Please download the newest version of the program from wherever you got this one.\n\n"
            "What looked wrong:",
            [r[:1].upper() + r[1:] for r in reasons])

    def _notice(self, title: str, message: str, lines: list[str]) -> None:
        """A small window with an OK button.  It does not block the program or grab the keyboard."""
        try:
            if self._notice_window is not None:
                self._notice_window.destroy()
        except Exception:
            pass
        self._notice_window = None
        try:
            self._notice_window = NoticeDialog(self.root, title, message, lines, modal=False)
        except Exception as exc:                            # even a failing pop-up must not matter
            self._on_callback_error(type(exc), exc, exc.__traceback__)

    def _on_close(self) -> None:
        self.stop_event.set()
        self.root.destroy()


def main() -> None:
    lower_priority()
    root = tk.Tk()
    try:
        BlackCloudWatcher(root)
    except Exception as exc:                                # explain instead of vanishing
        try:
            messagebox.showerror(APP_TITLE, f"The program could not start:\n{type(exc).__name__}: {exc}")
        except Exception:
            pass
        root.destroy()
        return
    root.mainloop()


if __name__ == "__main__":
    main()
