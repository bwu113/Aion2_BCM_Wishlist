"""Turn a pasted list of item names into wishlist entries (pure logic, no GUI)."""
from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field

from catalog import PickerEntry, name_key, search_entries

# "- item", "* item", "• item", "1. item", "2) item", "[ ] item" -> "item"
_BULLET = re.compile(r"^\s*(?:[-*•‣▪►·>]+|\(?\d{1,3}[.):]|\[[ xX]?\])\s+")
_QUOTES = "\"'`“”‘’"
_SEPARATORS = re.compile(r"[;\t|]|,\s*")


# Words that only describe the kind of item are ignored when matching pasted names: "gravi pet" = "gravi",
# "Reda's Tenacity theostone" = "Reda's Tenacity", "(Bound)" = nothing.  But a word followed by a colon is part of
# the item's real name ("Pet: Gravi", "Theostone: Reda's Tenacity", "(Skin: Mace)") and is kept.
NOISE_WORDS = ("pet", "skin", "godstone", "theostone", "bound", "other")
_NOISE = re.compile(r"\b(?:%s)\b(?!\s*:)" % "|".join(NOISE_WORDS), re.IGNORECASE)


def strip_noise(text: str) -> str:
    out = _NOISE.sub(" ", text)
    out = re.sub(r"\(\s*\)", " ", out)                       # "(Bound)" leaves empty brackets
    out = re.sub(r"\(\s+", "(", re.sub(r"\s+\)", ")", out))
    out = re.sub(r"\s+", " ", out)
    return out.strip(" -,;")


def clean_line(raw: str) -> str:
    line = raw.replace(" ", " ").strip()
    line = _BULLET.sub("", line, count=1)
    if len(line) >= 2 and line[0] in _QUOTES and line[-1] in _QUOTES:
        line = line[1:-1]
    return re.sub(r"\s+", " ", line).strip()


@dataclass
class Resolved:
    line: str                                   # the text as pasted (cleaned)
    status: str                                 # "item" | "ambiguous" | "suggest" | "missing"
    entry: PickerEntry | None = None            # set when status == "item"
    matches: list[PickerEntry] = field(default_factory=list)   # candidates ("ambiguous": exact words, "suggest": closest)
    note: str = ""                              # e.g. 'matched "gravy" to Pet: Gravi' for a typo fixed automatically


class Resolver:
    """Finds the catalog entry a pasted name means."""

    def __init__(self, entries: list[PickerEntry]) -> None:
        self.entries = entries
        self._by_name: dict[str, list[PickerEntry]] = {}
        for e in entries:
            self._by_name.setdefault(self._norm(e.name), []).append(e)
        self._names = list(self._by_name)

    @staticmethod
    def _norm(text: str) -> str:
        return name_key(strip_noise(text))

    def resolve(self, text: str) -> Resolved:
        shown = text
        text = strip_noise(text)                # a bare "pet", "skin", "theostone", "bound", ... is not part of a name
        if not name_key(text).strip(" :"):
            return Resolved(shown, "missing")
        # 1. the same name, ignoring case, punctuation decoration ("Pet: ", "(Skin: ...)", "(Bound)")
        exact = self._by_name.get(name_key(text), [])
        if len(exact) == 1:
            return Resolved(shown, "item", exact[0])
        if len(exact) > 1:
            return Resolved(shown, "ambiguous", matches=list(exact))
        # 2. every word of the text appears in exactly one item name
        found = search_entries(self.entries, text, limit=len(self.entries) + 1)
        if len(found) == 1:
            return Resolved(shown, "item", found[0])
        same = [e for e in found if e.name.casefold() == text.casefold()]
        if len(same) == 1:
            return Resolved(shown, "item", same[0])
        if found:
            return Resolved(shown, "ambiguous", matches=found)
        return self._closest(text, shown)

    # a typo or a slightly different spelling: take the clear winner, otherwise offer the closest names
    AUTO_RATIO = 0.9            # at least this similar ...
    AUTO_MARGIN = 0.05          # ... and clearly better than the runner-up
    SUGGEST_RATIO = 0.6

    def _closest(self, text: str, shown: str) -> Resolved:
        key = name_key(text)
        close = difflib.get_close_matches(key, self._names, n=8, cutoff=self.SUGGEST_RATIO)
        if not close:
            return Resolved(shown, "missing")
        scores = [difflib.SequenceMatcher(None, key, c).ratio() for c in close]
        top = self._by_name[close[0]]
        if scores[0] >= self.AUTO_RATIO and (len(close) == 1 or scores[1] <= scores[0] - self.AUTO_MARGIN) \
                and len(top) == 1:
            return Resolved(shown, "item", top[0], note=f'"{shown}" -> {top[0].name}')
        return Resolved(shown, "suggest", matches=[e for c in close for e in self._by_name[c]])


def parse_list(text: str, resolver: Resolver) -> list[Resolved]:
    """One result per pasted line.  A line that is not one known item but holds commas / semicolons / tabs is
    split into several names (so "Gravi, Krall Warrior" works)."""
    out: list[Resolved] = []
    for raw in text.splitlines():
        line = clean_line(raw)
        if not line or not name_key(strip_noise(line)).strip(" :"):
            continue                              # empty, or only words like "Pet" / "Skin" / "Pet:"
        whole = resolver.resolve(line)
        if whole.status == "item":
            out.append(whole)
            continue
        parts = [clean_line(p) for p in _SEPARATORS.split(line)]
        parts = [p for p in parts if p and name_key(strip_noise(p)).strip(" :")]
        if len(parts) > 1:
            out.extend(resolver.resolve(p) for p in parts)
        else:
            out.append(whole)
    return out
