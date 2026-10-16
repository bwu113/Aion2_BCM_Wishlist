"""The "Paste list" window: a big text area to paste many item names at once."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Callable

import theme


def _wrap_to(event: tk.Event, frame: tk.Misc, *labels: tk.Misc) -> None:
    """Keep wrapping labels inside their frame (14 px padding on each side, plus a little slack for the label)."""
    if event.widget is frame:
        for label in labels:
            label.configure(wraplength=max(160, event.width - 42))


class PasteListDialog(tk.Toplevel):
    """on_add(text) -> (leftover_text, message, finished).  Lines it could not use stay in the box."""

    def __init__(self, master: tk.Misc, on_add: Callable[[str], tuple[str, str, bool]], limit: int) -> None:
        super().__init__(master)
        self._on_add = on_add
        self.title("Paste a list of items")
        self.configure(bg=theme.BG)
        self.transient(master)
        self.minsize(420, 360)
        self.geometry(self._centered(master, 460, 440))
        try:
            theme.dark_titlebar(self)
        except Exception:
            pass

        outer = ttk.Frame(self, padding=14)
        outer.pack(fill="both", expand=True)
        ttk.Label(outer, text="Paste your list", style="Title.TLabel").pack(anchor="w")
        self.hint_label = ttk.Label(outer, style="Dim.TLabel", wraplength=390, justify="left",
                  text=f"One item per line (commas also work). Bullets and numbers are ignored. "
                       f"Names are matched to the item list as closely as possible; if a name fits several items "
                       f"you will be asked which one(s) you mean. The wishlist holds up to {limit} items.")
        self.hint_label.pack(anchor="w", pady=(6, 8))

        box = ttk.Frame(outer)
        box.pack(fill="both", expand=True)
        self.text = tk.Text(box, wrap="word", undo=True, height=10, bg=theme.FIELD, fg=theme.TEXT,
                            insertbackground=theme.TEXT, selectbackground="#27407a", selectforeground="white",
                            relief="flat", borderwidth=0, highlightthickness=1, highlightbackground=theme.LINE,
                            highlightcolor=theme.ACCENT, padx=8, pady=6, font=theme.FONT)
        bar = ttk.Scrollbar(box, orient="vertical", command=self.text.yview)
        self.text.configure(yscrollcommand=bar.set)
        self.text.pack(side="left", fill="both", expand=True)
        bar.pack(side="right", fill="y")

        self.message = tk.StringVar(value="")
        self.message_label = ttk.Label(outer, textvariable=self.message, justify="left", wraplength=390)
        self.message_label.pack(fill="x", pady=(8, 0))
        outer.bind("<Configure>", lambda e: _wrap_to(e, outer, self.hint_label, self.message_label))

        row = ttk.Frame(outer)
        row.pack(fill="x", pady=(10, 0))
        ttk.Button(row, text="Paste from clipboard", command=self.paste_clipboard).pack(side="left")
        ttk.Button(row, text="Add to wishlist", style="Accent.TButton", command=self.submit).pack(side="right")
        ttk.Button(row, text="Close", command=self.destroy).pack(side="right", padx=(0, 8))

        self.bind("<Escape>", lambda _e: self.destroy())
        self.text.focus_set()

    @staticmethod
    def _centered(master: tk.Misc, width: int, height: int) -> str:
        try:
            x = master.winfo_rootx() + max(0, (master.winfo_width() - width) // 2)
            y = master.winfo_rooty() + max(0, (master.winfo_height() - height) // 3)
        except tk.TclError:
            x, y = 100, 100
        return f"{width}x{height}+{x}+{y}"

    def paste_clipboard(self) -> None:
        try:
            clip = self.clipboard_get()
        except tk.TclError:
            self.message.set("The clipboard is empty (or does not hold text).")
            return
        self.text.insert("end", clip if clip.endswith("\n") else clip + "\n")

    def submit(self) -> None:
        raw = self.text.get("1.0", "end")
        if not raw.strip():
            self.message.set("Paste or type some item names first.")
            return
        leftover, message, finished = self._on_add(raw)
        if finished:
            self.destroy()
            return
        self.text.delete("1.0", "end")
        self.text.insert("1.0", leftover)
        self.message.set(message)


class ResolveDialog(tk.Toplevel):
    """Asks which item(s) a pasted name means.  After it closes, .result is one of:
        ("items", [PickerEntry, ...])   add these items
        ("cancel", None)                stop; this line and the rest stay in the paste box
    """

    def __init__(self, master: tk.Misc, line: str, candidates: list, index: int, total: int, exact: bool) -> None:
        super().__init__(master)
        from catalog import TYPE_LABELS
        self.result: tuple[str, object] = ("cancel", None)
        self._candidates = candidates
        self.title(f"Choose the item ({index} of {total})")
        self.configure(bg=theme.BG)
        self.transient(master)
        self.minsize(400, 340)
        self.geometry(PasteListDialog._centered(master, 440, 420))
        try:
            theme.dark_titlebar(self)
        except Exception:
            pass
        self.protocol("WM_DELETE_WINDOW", lambda: self._finish("cancel"))

        outer = ttk.Frame(self, padding=14)
        outer.pack(fill="both", expand=True)
        title_label = ttk.Label(outer, text=f'You pasted: "{line}"', style="Title.TLabel", wraplength=396, justify="left")
        title_label.pack(anchor="w")
        if exact:
            hint = f"{len(candidates)} items contain these words. Pick the one(s) you want (Ctrl/Shift-click for several):"
        else:
            hint = "No item has exactly that name. The closest items are below - pick the one(s) you mean:"
        hint_label = ttk.Label(outer, text=hint, style="Dim.TLabel", wraplength=396, justify="left")
        hint_label.pack(anchor="w", pady=(6, 8))
        outer.bind("<Configure>", lambda e: _wrap_to(e, outer, title_label, hint_label))

        box = ttk.Frame(outer)
        box.pack(fill="both", expand=True)
        self.listbox = tk.Listbox(box, selectmode="extended", exportselection=False, activestyle="none",
                                  bg=theme.FIELD, fg=theme.TEXT, selectbackground="#27407a", selectforeground="white",
                                  relief="flat", borderwidth=0, highlightthickness=1, highlightbackground=theme.LINE,
                                  highlightcolor=theme.ACCENT, font=theme.FONT)
        bar = ttk.Scrollbar(box, orient="vertical", command=self.listbox.yview)
        self.listbox.configure(yscrollcommand=bar.set)
        self.listbox.pack(side="left", fill="both", expand=True)
        bar.pack(side="right", fill="y")
        for e in candidates:
            self.listbox.insert("end", f"{e.name}   ({TYPE_LABELS.get(e.kind, e.kind)})")
        if len(candidates) == 1:
            self.listbox.selection_set(0)
        self.listbox.bind("<Double-Button-1>", lambda _e: self._add_selected())
        self.listbox.bind("<Return>", lambda _e: self._add_selected())

        self.message = tk.StringVar(value="")
        ttk.Label(outer, textvariable=self.message, foreground=theme.DIM).pack(anchor="w", pady=(6, 0))

        row = ttk.Frame(outer)
        row.pack(fill="x", pady=(10, 0))
        ttk.Button(row, text="Add selected", style="Accent.TButton", command=self._add_selected).pack(side="left")
        ttk.Button(row, text="Cancel rest", command=lambda: self._finish("cancel")).pack(side="right")

        self.bind("<Escape>", lambda _e: self._finish("cancel"))
        try:
            self.wait_visibility()
            self.grab_set()
        except Exception:
            pass
        self.listbox.focus_set()

    def _add_selected(self) -> None:
        chosen = [self._candidates[int(i)] for i in self.listbox.curselection()]
        if not chosen:
            self.message.set("Select at least one item, or choose Cancel rest.")
            return
        self.result = ("items", chosen)
        self.destroy()

    def _finish(self, kind: str) -> None:
        self.result = (kind, None)
        self.destroy()


class NoticeDialog(tk.Toplevel):
    """A plain notice with a read-only list and a single OK button (the window's X closes it too)."""

    def __init__(self, master: tk.Misc, title: str, message: str, names: list[str], modal: bool = True) -> None:
        super().__init__(master)
        self.title(title)
        self.configure(bg=theme.BG)
        self.transient(master)
        self.minsize(360, 300)
        self.geometry(PasteListDialog._centered(master, 420, 380))
        try:
            theme.dark_titlebar(self)
        except Exception:
            pass

        outer = ttk.Frame(self, padding=14)
        outer.pack(fill="both", expand=True)
        label = ttk.Label(outer, text=message, wraplength=380, justify="left")
        label.pack(anchor="w", pady=(0, 8))
        outer.bind("<Configure>", lambda e: _wrap_to(e, outer, label))

        box = ttk.Frame(outer)
        box.pack(fill="both", expand=True)
        self.listbox = tk.Listbox(box, selectmode="browse", exportselection=False, activestyle="none",
                                  bg=theme.FIELD, fg=theme.TEXT, selectbackground=theme.FIELD,
                                  selectforeground=theme.TEXT, relief="flat", borderwidth=0, highlightthickness=1,
                                  highlightbackground=theme.LINE, highlightcolor=theme.LINE, font=theme.FONT)
        bar = ttk.Scrollbar(box, orient="vertical", command=self.listbox.yview)
        self.listbox.configure(yscrollcommand=bar.set)
        self.listbox.pack(side="left", fill="both", expand=True)
        bar.pack(side="right", fill="y")
        for name in names:
            self.listbox.insert("end", name)

        ok = ttk.Button(outer, text="OK", style="Accent.TButton", width=10, command=self.destroy)
        ok.pack(side="right", pady=(10, 0))
        self.bind("<Return>", lambda _e: self.destroy())
        self.bind("<Escape>", lambda _e: self.destroy())
        if modal:
            try:
                self.wait_visibility()
                self.grab_set()
            except Exception:
                pass
            ok.focus_set()


ITEM_TYPES = (("Pet", "pet"), ("Skin", "skin"), ("Theostone", "godstone"), ("Other", "other"))


def decorate_name(name: str, kind: str) -> str:
    """Use the item list's own spelling: pets are "Pet: Name", Theostones "Theostone: Name"."""
    name = " ".join(name.split())
    if kind == "pet" and not name.casefold().startswith("pet:"):
        return f"Pet: {name}"
    if kind == "godstone" and not name.casefold().startswith("theostone:"):
        return f"Theostone: {name}"
    return name


class NameItemDialog(tk.Toplevel):
    """Asks for the name and type of an item that is in the shop but not in the item list.

    on_done(result) is called exactly once with ("save", name, kind), ("skip",) or ("skip_all",).
    The window does not block the program or grab the keyboard.
    """

    def __init__(self, master: tk.Misc, item_id: int, tab: str, guessed_kind: str, index: int, total: int,
                 on_done: Callable[[tuple], None]) -> None:
        super().__init__(master)
        self.item_id = item_id
        self._on_done = on_done
        self._finished = False
        self.title("New item found" + (f" ({index} of {total})" if total > 1 else ""))
        self.configure(bg=theme.BG)
        self.transient(master)
        self.minsize(380, 330)
        self.geometry(PasteListDialog._centered(master, 440, 340))
        try:
            theme.dark_titlebar(self)
        except Exception:
            pass
        self.protocol("WM_DELETE_WINDOW", lambda: self._finish(("skip",)))

        outer = ttk.Frame(self, padding=14)
        outer.pack(fill="both", expand=True)
        ttk.Label(outer, text="New item in the shop", style="Title.TLabel").pack(anchor="w")
        info = ttk.Label(outer, style="Dim.TLabel", justify="left", wraplength=380,
                         text=f"Item ID {item_id} ({tab} tab) is not in this program's item list, and the game does not "
                              f"send item names. Type its name and pick its type. You can look the ID up at "
                              f"aion2hub.com/database/items/{item_id}")
        info.pack(anchor="w", pady=(6, 10))
        outer.bind("<Configure>", lambda e: _wrap_to(e, outer, info))

        ttk.Label(outer, text="Name").pack(anchor="w")
        self.name_var = tk.StringVar()
        self.entry = ttk.Entry(outer, textvariable=self.name_var)
        self.entry.pack(fill="x", pady=(2, 8))
        ttk.Label(outer, text="Type").pack(anchor="w")
        self.type_var = tk.StringVar()
        labels = [label for label, _kind in ITEM_TYPES]
        self.combo = ttk.Combobox(outer, textvariable=self.type_var, values=labels, state="readonly")
        guessed = next((label for label, kind in ITEM_TYPES if kind == guessed_kind), "Other")
        self.type_var.set(guessed)
        self.combo.pack(fill="x", pady=(2, 0))

        self.message = tk.StringVar(value="")
        ttk.Label(outer, textvariable=self.message, foreground=theme.DIM).pack(anchor="w", pady=(8, 0))

        row = ttk.Frame(outer)
        row.pack(fill="x", side="bottom", pady=(10, 0))
        ttk.Button(row, text="Save", style="Accent.TButton", command=self.save).pack(side="left")
        ttk.Button(row, text="Skip", command=lambda: self._finish(("skip",))).pack(side="left", padx=(8, 0))
        if total > index:
            ttk.Button(row, text="Skip all", command=lambda: self._finish(("skip_all",))).pack(side="right")

        self.entry.bind("<Return>", lambda _e: self.save())
        self.bind("<Escape>", lambda _e: self._finish(("skip",)))
        self.entry.focus_set()

    def save(self) -> None:
        name = " ".join(self.name_var.get().split())
        if not name:
            self.message.set("Type the item's name, or choose Skip.")
            return
        kind = dict(ITEM_TYPES).get(self.type_var.get(), "other")
        self._finish(("save", decorate_name(name, kind), kind))

    def _finish(self, result: tuple) -> None:
        if self._finished:
            return
        self._finished = True
        try:
            self.destroy()
        except tk.TclError:
            pass
        self._on_done(result)
