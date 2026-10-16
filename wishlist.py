"""Wishlist model (add / edit / delete / persist), offer matching and overlay layout.

No GUI code here, so it can be tested without Tk.
"""
from __future__ import annotations

import json
import shutil
import os
from dataclasses import dataclass, field

from catalog import Catalog, PickerEntry, name_key
from shop_decoder import ShopOffer, ShopPage

TABS = ("Special", "Pets", "Skins")
MAX_WISHLIST = 100                      # most items the wishlist can hold


class WishlistFull(Exception):
    """Raised when adding to a wishlist that already has MAX_WISHLIST items."""


@dataclass
class WishEntry:
    """Something the user is looking for.

    kind "item"    : exact thing picked from the catalog (matched by item id or name key)
    kind "keyword" : any shop item whose name contains the text (case-insensitive)
    """
    kind: str                                   # "item" | "keyword"
    name: str                                   # display name or keyword text
    key: str = ""                               # normalised name key (item entries)
    item_type: str = ""                         # pet | skin | godstone
    item_ids: list[int] = field(default_factory=list)

    @classmethod
    def from_picker(cls, e: PickerEntry) -> "WishEntry":
        return cls("item", e.name, e.key, e.kind, list(e.item_ids))

    @classmethod
    def keyword(cls, text: str) -> "WishEntry":
        return cls("keyword", text.strip())

    def label(self) -> str:
        if self.kind == "keyword":
            return f'any item containing "{self.name}"'
        return self.name

    def to_json(self) -> dict:
        return {"kind": self.kind, "name": self.name, "key": self.key,
                "type": self.item_type, "item_ids": self.item_ids}

    @classmethod
    def from_json(cls, d: dict) -> "WishEntry":
        return cls(str(d.get("kind", "item")), str(d.get("name", "")), str(d.get("key", "")),
                   str(d.get("type", "")), [int(x) for x in d.get("item_ids", [])])


class Wishlist:
    def __init__(self, path: str | None = None) -> None:
        self.path = path
        self.entries: list[WishEntry] = []
        self.last_save_error: OSError | None = None
        self.load_problem = ""
        self.settings: dict = {}                # small program settings kept in the same file (e.g. chime volume)

    # -- editing ------------------------------------------------------------- #
    def add(self, entry: WishEntry) -> bool:
        """Add unless an identical entry already exists.  Returns True if added; raises WishlistFull at the limit."""
        if any(self._same(e, entry) for e in self.entries):
            return False
        if len(self.entries) >= MAX_WISHLIST:
            raise WishlistFull(f"the wishlist is limited to {MAX_WISHLIST} items")
        self.entries.append(entry)
        self.save()
        return True

    def add_many(self, entries: list[WishEntry]) -> tuple[list[WishEntry], list[WishEntry], list[WishEntry]]:
        """Add several entries with one save.  Returns (added, already_on_list, over_the_limit)."""
        added: list[WishEntry] = []
        dupes: list[WishEntry] = []
        overflow: list[WishEntry] = []
        for entry in entries:
            if any(self._same(e, entry) for e in self.entries):
                dupes.append(entry)
            elif len(self.entries) >= MAX_WISHLIST:
                overflow.append(entry)
            else:
                self.entries.append(entry)
                added.append(entry)
        self.last_save_error = None
        if added:
            try:
                self.save()
            except OSError as exc:                  # the entries stay in memory; the caller reports the problem
                self.last_save_error = exc
        return added, dupes, overflow

    def edit(self, index: int, entry: WishEntry) -> None:
        self.entries[index] = entry
        self.save()

    def clear(self) -> int:
        """Remove every entry (the chime volume and other settings stay).  Returns how many were removed."""
        count = len(self.entries)
        self.entries = []
        self.save()
        return count

    def delete(self, index: int) -> None:
        del self.entries[index]
        self.save()

    @staticmethod
    def _same(a: WishEntry, b: WishEntry) -> bool:
        if a.kind != b.kind:
            return False
        return a.name.casefold() == b.name.casefold() if a.kind == "keyword" else a.key == b.key

    # -- persistence --------------------------------------------------------- #
    def save(self) -> None:
        if not self.path:
            return
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump({"version": 1, "settings": self.settings, "entries": [e.to_json() for e in self.entries]},
                      fh, indent=2, ensure_ascii=False)
        os.replace(tmp, self.path)

    def load(self) -> str:
        """Read the file.  Never raises for bad content: unreadable entries are skipped and an unreadable file is
        copied to wishlist.json.bad before anything can overwrite it.  Returns a problem description or ""."""
        self.load_problem = ""
        if not self.path or not os.path.isfile(self.path):
            return ""
        try:
            with open(self.path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            if not isinstance(data, dict):
                raise ValueError("the file does not hold a wishlist")
        except (OSError, ValueError) as exc:
            self.load_problem = f"{os.path.basename(self.path)} could not be read ({exc})."
            self._keep_copy()
            return self.load_problem
        entries: list[WishEntry] = []
        bad = 0
        for d in data.get("entries", []) if isinstance(data.get("entries", []), list) else []:
            try:
                entries.append(WishEntry.from_json(d))
            except Exception:
                bad += 1
        self.entries = entries[:MAX_WISHLIST]
        settings = data.get("settings", {})
        self.settings = settings if isinstance(settings, dict) else {}
        if bad:
            self.load_problem = f"{bad} entr{'y' if bad == 1 else 'ies'} in {os.path.basename(self.path)} could not be read and were skipped."
            self._keep_copy()
        return self.load_problem

    def _keep_copy(self) -> None:
        try:
            shutil.copy2(self.path, self.path + ".bad")
            self.load_problem += f" A copy was kept as {os.path.basename(self.path)}.bad."
        except OSError:
            pass

    # -- matching ------------------------------------------------------------ #
    def match(self, offer: ShopOffer, catalog: Catalog) -> WishEntry | None:
        key = catalog.key(offer.item_id)
        lname = catalog.name(offer.item_id).casefold()
        for e in self.entries:
            if e.kind == "keyword":
                if e.name and e.name.casefold() in lname:
                    return e
            elif offer.item_id in e.item_ids or (key and key == e.key):
                return e
        return None


# --------------------------------------------------------------------------- #
# Overlay / matches model
# --------------------------------------------------------------------------- #
def ordinal(n: int) -> str:
    return f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


def card_slots(count: int) -> list[tuple[int, int]]:
    """(row, column-in-row) for each card in reading order.

    The in-game shop shows 10 cards as 6 on the top row and 4 on the bottom row
    (with the merchant standing in the gap in the middle of the bottom row).
    """
    top = 6 if count == 10 else max(1, round(count * 0.6))
    return [(0, i) for i in range(min(top, count))] + [(1, i) for i in range(max(0, count - top))]


@dataclass
class Cell:
    tab: str
    index: int               # 0-based position in the in-game (reading) order
    row: int                 # 0 = top row, 1 = bottom row
    col: int                 # index within the row, from the left
    item_id: int
    entry_id: int
    name: str
    kind: str                # pet | skin | godstone | other | ""
    price: int
    original_price: int
    discount: int
    quantity: int
    wanted: WishEntry | None

    @property
    def position_text(self) -> str:
        return f"#{self.index + 1} ({'top' if self.row == 0 else 'bottom'} row, {ordinal(self.col + 1)} from left)"


@dataclass
class TabView:
    tab: str
    seen: bool
    cells: list[Cell] = field(default_factory=list)
    seen_at: str = ""

    @property
    def matches(self) -> list[Cell]:
        return [c for c in self.cells if c.wanted]


def _view(tab: str, page: ShopPage, wishlist: Wishlist, catalog: Catalog, seen_at: str, sort_by_entry: bool) -> TabView:
    # The server sends the entries in an arbitrary order; the game shows them sorted by
    # entry id (Theostones, then skins, then pets in the Special tab).
    offers = sorted(page.offers, key=lambda o: o.entry_id) if sort_by_entry else list(page.offers)
    slots = card_slots(len(offers))
    cells = []
    for i, o in enumerate(offers):
        row, col = slots[i]
        cells.append(Cell(
            tab, i, row, col, o.item_id, o.entry_id,
            catalog.name(o.item_id) or f"Unknown item {o.item_id}", catalog.kind(o.item_id),
            o.price, o.original_price, o.discount_percent, o.quantity, wishlist.match(o, catalog),
        ))
    return TabView(tab, True, cells, seen_at)


def build_views(pages: dict[str, ShopPage], wishlist: Wishlist, catalog: Catalog,
                seen_at: dict[str, str] | None = None, sort_by_entry: bool = True) -> list[TabView]:
    """One TabView per shop tab (Special, Pets, Skins), cards in in-game order."""
    seen_at = seen_at or {}
    views = [_view(t, pages[t], wishlist, catalog, seen_at.get(t, ""), sort_by_entry) if t in pages else TabView(t, False)
             for t in TABS]
    for tab in sorted(t for t in pages if t not in TABS):
        views.append(_view(tab, pages[tab], wishlist, catalog, seen_at.get(tab, ""), sort_by_entry))
    return views
