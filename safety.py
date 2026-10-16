"""Safety net: judge every decoded shop page against the item list so a game update can never crash the program.

Two different situations are told apart:

* a few item IDs that are simply not in the item list yet  -> new items: tell the user and learn them;
* the page does not look the way this version of the program expects (unknown shop tab, unreadable entries,
  items of the wrong type for their tab, many unrecognisable IDs)  -> the game was probably updated:
  tell the user to download a new version, and do not guess.

Pure logic, no GUI.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from catalog import Catalog
from shop_decoder import ShopOffer, ShopPage

# What a tab may hold.  The Special tab mixes Theostones, skins and pets, so it is not checked.
TAB_KINDS = {"Pets": {"pet"}, "Skins": {"skin"}}
KNOWN_KINDS = {"pet", "skin", "godstone"}


@dataclass
class NewItem:
    item_id: int
    kind: str                  # pet | skin | godstone | other  (a guess: the shop packet carries no item names)
    tab: str

    @property
    def name(self) -> str:
        return f"Unknown item {self.item_id}"


@dataclass
class Audit:
    verdict: str = "ok"                                    # "ok" | "new_items" | "outdated"
    new_items: list[NewItem] = field(default_factory=list)  # safe to add to the item list
    reasons: list[str] = field(default_factory=list)       # why the page looks wrong (for "outdated")
    unknown_count: int = 0


def guess_kind(offer: ShopOffer, tab: str, catalog: Catalog) -> str:
    kinds = TAB_KINDS.get(tab)
    if kinds and len(kinds) == 1:
        return next(iter(kinds))
    return catalog.kind_by_neighbours(offer.item_id) or "other"


def audit_page(page: ShopPage, catalog: Catalog) -> Audit:
    offers = page.offers
    total = len(offers)
    audit = Audit()
    if total == 0:
        return audit
    tab = page.tab_guess
    structural: list[str] = []
    if tab.startswith("tab "):
        structural.append(f"the shop shows a tab this version does not know ({tab})")
    if not page.complete:
        structural.append(f"only {total} of {page.declared_count} shop entries could be read")

    allowed = TAB_KINDS.get(tab)
    conflicts = 0
    unknown_in_range: list[ShopOffer] = []
    unknown_outside: list[ShopOffer] = []
    for o in offers:
        if catalog.has(o.item_id):
            if allowed and catalog.kind(o.item_id) in KNOWN_KINDS and catalog.kind(o.item_id) not in allowed:
                conflicts += 1
        elif catalog.knows_id_range(o.item_id):
            unknown_in_range.append(o)
        else:
            unknown_outside.append(o)
    unknown = len(unknown_in_range) + len(unknown_outside)
    audit.unknown_count = unknown

    def many(n: int) -> bool:
        return n >= 2 or (total >= 3 and n / total >= 0.3)

    if conflicts and many(conflicts):
        structural.append(f"{conflicts} items are of a different type than their tab says")
    if unknown_outside and many(len(unknown_outside)):
        structural.append(f"{len(unknown_outside)} item IDs are outside every range this version knows")
    heavy = total >= 3 and unknown / total >= 0.6

    if structural:
        audit.verdict, audit.reasons = "outdated", structural          # do not learn anything from a page like this
        return audit
    if heavy:
        audit.verdict = "outdated"
        audit.reasons = [f"{unknown} of the {total} items are not in this version's item list"]
    elif unknown:
        audit.verdict = "new_items"
    audit.new_items = [NewItem(o.item_id, guess_kind(o, tab, catalog), tab) for o in unknown_in_range + unknown_outside]
    return audit
