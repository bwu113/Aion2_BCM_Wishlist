"""Item catalog: item_id -> name/type, plus name-based grouping for the wishlist.

aion2_items.csv   shipped list (pets, skins, Theostones) compiled from aion2hub.com
item_catalog.csv  your own additions / corrections (item_id,name[,type]); wins over the shipped list

Why "name keys"?  The same thing can exist under several IDs: the pet *creature*
"Gravi" (534660051) and the shop *item* "Pet: Gravi" (534760049), or a skin listed as
"Nameless Master (Orb)" and sold as "Nameless Master (Skin: Orb) (Bound)".  The key
strips the decoration so all of those compare equal.
"""
from __future__ import annotations

import csv
import difflib
import os
from collections import Counter
import re
from dataclasses import dataclass, field

TYPE_LABELS = {"pet": "Pet", "skin": "Skin", "godstone": "Theostone", "other": "Other"}
PICKER_TYPES = ("pet", "skin", "godstone")

_WS = re.compile(r"\s+")


def name_key(name: str, kind: str = "") -> str:
    """Normalise an item name so equivalent names compare equal."""
    s = name.replace("’", "'").casefold()
    s = re.sub(r"\(bound\)", "", s)
    s = re.sub(r"^pet:\s*", "", s)
    s = s.replace("(skin: ", "(")
    s = _WS.sub(" ", s).strip()
    return f"{kind}:{s}" if kind else s


def display_name(name: str) -> str:
    """Name as shown to the user: no '(Bound)' suffix."""
    return _WS.sub(" ", re.sub(r"\s*\(Bound\)", "", name)).strip()


@dataclass
class CatalogItem:
    item_id: int
    name: str
    kind: str

    @property
    def key(self) -> str:
        return name_key(self.name, self.kind)


@dataclass
class PickerEntry:
    """One selectable thing in the picker = all catalog items sharing a name key."""
    key: str
    name: str
    kind: str
    item_ids: list[int] = field(default_factory=list)
    _hay: str = field(default="", repr=False, compare=False)

    @property
    def haystack(self) -> str:
        """Lower-case searchable text, computed once (searching runs on every keystroke)."""
        if not self._hay:
            self._hay = " ".join(_tokens(self.name))
        return self._hay


class Catalog:
    def __init__(self) -> None:
        self.items: dict[int, CatalogItem] = {}
        self._prefix_kinds: dict[str, Counter] | None = None

    def __len__(self) -> int:
        return len(self.items)

    def add(self, item_id: int, name: str, kind: str = "") -> None:
        old = self.items.get(item_id)
        if not kind:
            kind = old.kind if old else _guess_kind(name)
        self.items[item_id] = CatalogItem(item_id, name, kind)
        self._prefix_kinds = None

    # -- "have we seen this kind of ID before?" (used by the safety net) ---------- #
    def has(self, item_id: int) -> bool:
        return item_id in self.items

    def _prefixes(self) -> dict[str, Counter]:
        if self._prefix_kinds is None:
            table: dict[str, Counter] = {}
            for it in self.items.values():
                digits = str(it.item_id)
                for n in (5, 4, 3):
                    table.setdefault(digits[:n], Counter())[it.kind] += 1
            self._prefix_kinds = table
        return self._prefix_kinds

    def knows_id_range(self, item_id: int) -> bool:
        """True if some known item starts with the same first three digits (IDs come in families)."""
        return str(item_id)[:3] in self._prefixes()

    def kind_by_neighbours(self, item_id: int) -> str:
        """Best guess of an unknown item's type from known items with the most similar ID, or ""."""
        table = self._prefixes()
        digits = str(item_id)
        for n in (5, 4, 3):
            counts = table.get(digits[:n])
            if counts:
                return counts.most_common(1)[0][0]
        return ""

    def load_csv(self, path: str) -> int:
        n = 0
        with open(path, "r", encoding="utf-8-sig", newline="") as fh:
            reader = csv.DictReader(fh)
            fields = {c.casefold().strip(): c for c in (reader.fieldnames or [])}
            id_col = next((fields[k] for k in ("item_id", "id", "itemid") if k in fields), None)
            name_col = next((fields[k] for k in ("name", "item_name", "itemname") if k in fields), None)
            type_col = fields.get("type")
            if not id_col or not name_col:
                raise ValueError(f"{os.path.basename(path)}: CSV needs the headers item_id,name[,type]")
            for row in reader:
                raw = (row.get(id_col) or "").strip()
                name = (row.get(name_col) or "").strip()
                if not raw or not name:
                    continue
                try:
                    item_id = int(raw, 0)
                except ValueError:
                    continue
                kind = ((row.get(type_col) or "").strip().casefold() if type_col else "")
                self.add(item_id, name, kind)
                n += 1
        return n

    # -- lookups ------------------------------------------------------------- #
    def name(self, item_id: int) -> str:
        it = self.items.get(item_id)
        return display_name(it.name) if it else ""

    def kind(self, item_id: int) -> str:
        it = self.items.get(item_id)
        return it.kind if it else ""

    def key(self, item_id: int) -> str:
        it = self.items.get(item_id)
        return it.key if it else ""

    def picker_entries(self, kinds: tuple[str, ...] = PICKER_TYPES) -> list[PickerEntry]:
        """Unique-by-name entries for the picker, in a stable, name-sorted order."""
        grouped: dict[str, PickerEntry] = {}
        for it in self.items.values():
            if it.kind not in kinds:
                continue
            e = grouped.get(it.key)
            if e is None:
                e = grouped[it.key] = PickerEntry(it.key, display_name(it.name), it.kind)
            e.item_ids.append(it.item_id)
            # prefer the in-game item spelling ("(Skin: X)" / "Pet: X") over the bare listing name
            if ("(Skin:" in it.name or it.name.startswith("Pet:")) and "(Skin:" not in e.name and not e.name.startswith("Pet:"):
                e.name = display_name(it.name)
        out = sorted(grouped.values(), key=lambda e: (e.name.casefold(), e.kind))
        for e in out:
            e.item_ids.sort()
        return out


def append_user_catalog(path: str, rows: list[tuple[int, str, str]]) -> None:
    """Append "item_id,name,type" lines to the user's own item list (created with its header if needed)."""
    need_header = not os.path.isfile(path) or os.path.getsize(path) == 0
    lead_newline = False
    if not need_header:
        with open(path, "rb") as fh:
            fh.seek(-1, os.SEEK_END)
            lead_newline = fh.read(1) not in (b"\n", b"\r")
    with open(path, "a", encoding="utf-8", newline="") as fh:
        if lead_newline:
            fh.write("\n")
        writer = csv.writer(fh, lineterminator="\n")
        if need_header:
            writer.writerow(["item_id", "name", "type"])
        for item_id, name, kind in rows:
            writer.writerow([item_id, name, kind])


def update_user_catalog(path: str, item_id: int, name: str, kind: str) -> None:
    """Set the name/type of one item in the user's own item list (adds the row if it is not there)."""
    rows: list[list[str]] = []
    if os.path.isfile(path):
        with open(path, "r", encoding="utf-8-sig", newline="") as fh:
            rows = [r for r in csv.reader(fh) if r]
    if not rows:
        rows = [["item_id", "name", "type"]]
    found = False
    for row in rows[1:]:
        if row[0].strip() == str(item_id):
            row[:] = [str(item_id), name, kind]
            found = True
    if not found:
        rows.append([str(item_id), name, kind])
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="") as fh:
        csv.writer(fh, lineterminator="\n").writerows(rows)
    os.replace(tmp, path)


def _guess_kind(name: str) -> str:
    n = name.casefold()
    if n.startswith("pet:"):
        return "pet"
    if n.startswith("theostone"):
        return "godstone"
    if "(skin" in n:
        return "skin"
    return "other"


def _tokens(text: str) -> list[str]:
    return re.findall(r"[\w']+", text.replace("\u2019", "'").casefold())


def search_entries(entries: list[PickerEntry], query: str, kind: str = "", limit: int = 800) -> list[PickerEntry]:
    """Case-insensitive AND-search over entry names; punctuation is ignored."""
    words = _tokens(query)
    out = []
    for e in entries:
        if kind and e.kind != kind:
            continue
        hay = e.haystack
        if all(w in hay for w in words):
            out.append(e)
            if len(out) >= limit:
                break
    return out


class FuzzyIndex:
    """Misspelling-tolerant search over the picker entries (used when the normal word search finds nothing).

    Each typed word may be replaced by a similar word that exists in the item names ("warior" -> "warrior",
    "glaciers" -> "glacier's"); an entry matches when every word (or its look-alike) is in its name.  If that
    finds nothing, the whole text is compared with whole item names.
    """
    WORD_RATIO = 0.72           # a typed word counts as a misspelling of a name word at this similarity
    NAME_RATIO = 0.55           # whole-text fallback

    def __init__(self, entries: list[PickerEntry]) -> None:
        self.entries = entries
        self.vocab = sorted({t for e in entries for t in e.haystack.split()})
        self._by_name: dict[str, list[PickerEntry]] = {}
        for e in entries:
            self._by_name.setdefault(name_key(e.name), []).append(e)
        self._names = list(self._by_name)

    def search(self, query: str, limit: int = 60) -> list[PickerEntry]:
        words = _tokens(query)
        if not words:
            return []
        alternatives: list[set[str]] = []
        for w in words:
            alt = {w}
            if len(w) >= 3:
                alt.update(difflib.get_close_matches(w, self.vocab, n=6, cutoff=self.WORD_RATIO))
            alternatives.append(alt)
        found = [e for e in self.entries if all(any(a in e.haystack for a in alt) for alt in alternatives)]
        if not found:
            close = difflib.get_close_matches(name_key(query), self._names, n=10, cutoff=self.NAME_RATIO)
            found = [e for c in close for e in self._by_name[c]]
        target = " ".join(words)
        found.sort(key=lambda e: -difflib.SequenceMatcher(None, target, e.haystack).ratio())
        return found[:limit]
