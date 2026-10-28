"""AION 2 Black Cloud Merchant shop decoder.

Pure-Python, no third-party dependencies.  Decodes the shop-list message that the
game server sends over its (unencrypted) server->client TCP stream.

Reverse-engineered from a real capture (black_cloud_merchant_2.pcap):

Stream framing (server -> client, TCP, plaintext)
    frame   = varint(length) + payload
    payload = (length - 4) bytes
    payload[0:2] = opcode

    opcode 00 36 / 03 36  server clock tick (20x per second, 8-byte epoch-ms)
    opcode 93 56          shop request acknowledgement  (request id)
    opcode 91 56          SHOP LIST (this module)

Shop list payload (opcode 91 56)
    u8   opcode_lo = 0x91, u8 opcode_hi = 0x56
    u8   request id            (differs per shop tab / page)
    u8   entry count           (10 in the capture)
    entries (34 bytes each):
        u32  entry_id          shop listing id; entry_id // 10000 = tab (11 Special, 12 Pets, 13 Skins)
        u32  item_id           the item / pet / skin id  (decimal, e.g. 534760049)
        u64  quantity          items delivered per purchase
        u8   discount_tier     0=-10%  1=-20%  2=-30%  3=-50% (observed)
        u8   0x5d              constant marker
        u64  original_price    Kina
        u64  price             Kina after discount
      A one-byte control value (0x55 / 0x05) additionally sits in front of
      entries #1, #5, #9, ... (0-based) - purely framing, carries no item data.
    trailer: u64 server time (epoch ms) + 4 bytes

The packets contain NO item names - only numeric IDs.  Names must come from an
item_id -> name catalog (item_catalog.csv).
"""
from __future__ import annotations

import re
import struct
import time
from dataclasses import dataclass, field
from typing import Iterable

SHOP_OPCODE = b"\x91\x56"
SHOP_ACK_OPCODE = b"\x93\x56"
TICK_OPCODE = b"\x00\x36"

ENTRY_SIZE = 34
ENTRY_MARKER = 0x5D
MAX_FRAME = 1 << 20          # sanity limit for a single frame payload

# Observed discount tier -> percent.  The scanner always shows the percent
# computed from the two prices; this table is only informational.
TIER_PERCENT = {0: 10, 1: 20, 2: 30, 3: 50}

# The tab is encoded in the entry id: entry_id // 10000 == 11 / 12 / 13.
# Inferred from one capture (11xxxx = the tab containing Gravi = "Special",
# 12xxxx = all pets, 13xxxx = skins); edit if more captures show otherwise.
TAB_BY_ENTRY_PREFIX = {11: "Special", 12: "Pets", 13: "Skins"}

# Heartbeat: 0e 00 36 + u64 epoch-ms (upper bytes are 01 00 00 for the next ~500 years)
_HEARTBEAT_RE = re.compile(rb"\x0e\x00\x36.{5}\x01\x00\x00", re.DOTALL)


@dataclass
class ShopOffer:
    index: int               # position inside the page (0-based)
    entry_id: int
    item_id: int
    quantity: int
    discount_tier: int
    original_price: int
    price: int

    @property
    def discount_percent(self) -> int:
        if self.original_price <= 0:
            return 0
        return round((1 - self.price / self.original_price) * 100)


@dataclass
class ShopPage:
    request_id: int
    declared_count: int
    offers: list[ShopOffer] = field(default_factory=list)
    server_time_ms: int | None = None
    complete: bool = True    # False if fewer offers decoded than declared

    @property
    def tab_guess(self) -> str:
        if not self.offers:
            return "?"
        prefix = self.offers[0].entry_id // 10000
        return TAB_BY_ENTRY_PREFIX.get(prefix, f"tab {prefix}")

    def signature(self) -> tuple:
        return (self.request_id, tuple((o.item_id, o.price, o.original_price, o.quantity) for o in self.offers))


# --------------------------------------------------------------------------- #
# Shop message
# --------------------------------------------------------------------------- #
def _try_entry(data: bytes, pos: int) -> tuple[ShopOffer, int] | None:
    if pos + ENTRY_SIZE > len(data):
        return None
    entry_id, item_id, qty, tier, marker, orig, price = struct.unpack_from("<IIQBBQQ", data, pos)
    if marker != ENTRY_MARKER:
        return None
    if not (1 <= qty <= 1_000_000):
        return None
    if not (0 < price <= orig < 10**12):
        return None
    return ShopOffer(0, entry_id, item_id, qty, tier, orig, price), pos + ENTRY_SIZE


def parse_shop_payload(payload: bytes) -> ShopPage | None:
    """Parse one frame payload (opcode included).  Returns None if it is not a shop list."""
    if len(payload) < 4 or payload[:2] != SHOP_OPCODE:
        return None
    request_id = payload[2]
    count = payload[3]
    page = ShopPage(request_id=request_id, declared_count=count)
    pos = 4
    for i in range(count):
        # A control byte precedes entries 1, 5, 9, ...  Be tolerant: try the
        # expected layout first, then the other one.
        orders = (True, False) if i % 4 == 1 else (False, True)
        parsed = None
        for skip in orders:
            parsed = _try_entry(payload, pos + (1 if skip else 0))
            if parsed:
                break
        if not parsed:
            break
        offer, pos = parsed
        offer.index = i
        page.offers.append(offer)
    page.complete = len(page.offers) == count and count > 0
    if pos + 8 <= len(payload):
        ts = struct.unpack_from("<Q", payload, pos)[0]
        if 10**12 < ts < 10**13:            # plausible epoch-ms
            page.server_time_ms = ts
    return page if page.offers else None


# --------------------------------------------------------------------------- #
# Stream framing
# --------------------------------------------------------------------------- #
def _read_varint(buf: bytes | bytearray, pos: int) -> tuple[int, int] | None:
    value = 0
    shift = 0
    for i in range(5):
        if pos + i >= len(buf):
            return None                     # need more bytes
        b = buf[pos + i]
        value |= (b & 0x7F) << shift
        if b < 0x80:
            return value, pos + i + 1
        shift += 7
    return -1, pos                          # malformed


class FrameStream:
    """Reassembles one server->client TCP direction and yields frame payloads.

    * Works when the capture starts in the middle of a connection: it locks on
      to the 20 Hz heartbeat frame (0e 00 36 + timestamp) and parses from there.
    * Survives packets the capture driver dropped: if a TCP hole is not filled
      after a few segments, the hole is skipped and framing is re-established.
      A shop page that was inside the hole is lost (``gaps`` counts these).
    """

    GAP_SECONDS = 1.0         # a hole may wait this long for the missing bytes (a TCP retransmit) before it is skipped
    GAP_BYTES = 1 << 20       # ...unless this much data piles up behind it

    def __init__(self) -> None:
        self.next_seq: int | None = None
        self.pending: dict[int, bytes] = {}
        self.buf = bytearray()
        self.synced = False
        self.ever_synced = False      # found a real heartbeat at least once => this is the game connection
        self.packets = 0
        self.gaps = 0
        self.frames = 0
        self.hole_since: float | None = None      # when the current hole was noticed

    # -- TCP level ---------------------------------------------------------- #
    def _collect(self) -> bytes:
        """Return the contiguous buffered bytes that start at next_seq."""
        out = b""
        while True:
            nxt = self.pending.pop(self.next_seq, None)
            if nxt is None:
                overlap = [s for s in self.pending
                           if 0 < ((self.next_seq - s) & 0xFFFFFFFF) < len(self.pending[s])]
                if not overlap:
                    return out
                s = overlap[0]
                nxt = self.pending.pop(s)[(self.next_seq - s) & 0xFFFFFFFF:]
            out += nxt
            self.next_seq = (self.next_seq + len(nxt)) & 0xFFFFFFFF

    def feed(self, seq: int, payload: bytes, now: float | None = None) -> list[bytes]:
        if not payload:
            return []
        if self.next_seq is None:
            self.next_seq = seq
        diff = (seq - self.next_seq) & 0xFFFFFFFF
        if diff >= 0x80000000:                          # starts before what we have
            skip = (self.next_seq - seq) & 0xFFFFFFFF
            if skip >= len(payload):
                return []                               # pure retransmission
            payload = payload[skip:]
            seq = self.next_seq
            diff = 0
        if diff > 0:                                    # hole / out of order
            now = time.monotonic() if now is None else now
            self.pending[seq] = payload
            if self.hole_since is None:
                self.hole_since = now
            # Wait for the missing bytes (the server resends them within a moment).  In a crowd hundreds of
            # segments arrive meanwhile, so the wait is measured in time, not in segments.
            if (now - self.hole_since < self.GAP_SECONDS
                    and sum(len(p) for p in self.pending.values()) < self.GAP_BYTES):
                return []
            # The missing bytes are not coming: skip the hole and re-sync.
            self.gaps += 1
            self.next_seq = min(self.pending, key=lambda s: (s - self.next_seq) & 0xFFFFFFFF)
            self.buf.clear()
            self.synced = True      # optimistic: segments normally start on a frame boundary
            frames = self._parse(self._collect())
            self.hole_since = now if self.pending else None
            return frames
        self.next_seq = (seq + len(payload)) & 0xFFFFFFFF
        frames = self._parse(payload + self._collect())
        if not self.pending:
            self.hole_since = None
        elif self.hole_since is None:
            self.hole_since = time.monotonic() if now is None else now
        return frames

    # -- frame level -------------------------------------------------------- #
    def _parse(self, data: bytes) -> list[bytes]:
        self.buf += data
        frames: list[bytes] = []
        while True:
            if not self.synced:
                m = _HEARTBEAT_RE.search(self.buf)
                if not m:
                    if len(self.buf) > 64:
                        del self.buf[:-16]
                    return frames
                del self.buf[:m.start()]
                self.synced = True
                self.ever_synced = True
            vr = _read_varint(self.buf, 0)
            if vr is None:
                return frames
            n, hdr = vr
            length = n - 4
            if n < 0 or length < 2 or length > MAX_FRAME:
                self.synced = False                     # garbage: hunt for the next heartbeat
                del self.buf[:1]
                continue
            if len(self.buf) < hdr + length:
                return frames
            frames.append(bytes(self.buf[hdr:hdr + length]))
            self.frames += 1
            del self.buf[:hdr + length]


class ShopDecoder:
    """Feed TCP segments; get ShopPage objects back.  One FrameStream per flow."""

    UNSYNCED_LIMIT = 400       # a flow that shows no game heartbeat in this many data packets is not the game
                               # (generous: in a crowd the server sends hundreds of packets a second)
    MAX_IGNORED = 4096

    def __init__(self) -> None:
        self.streams: dict[tuple, FrameStream] = {}
        self.ignored: set[tuple] = set()
        self.locked_flow: tuple | None = None      # the flow that carries the game's heartbeat
        self.problems: list[str] = []              # shop messages that did not look as expected (game update?)
        self.shop_frames = 0

    def reset(self) -> None:
        self.streams.clear()
        self.ignored.clear()
        self.locked_flow = None
        self.problems.clear()
        self.shop_frames = 0

    def summary(self) -> str:
        """One line for the status bar when traffic is seen but no shop page: what the decoder has made of it."""
        game = self.streams.get(self.locked_flow) if self.locked_flow else None
        if game is None:
            return "game connection not recognised yet"
        return (f"game connection found; {game.frames} messages read, {game.gaps} gaps, "
                f"{self.shop_frames} shop lists seen")

    def feed_tcp(self, flow: tuple, seq: int, payload: bytes, now: float | None = None) -> list[ShopPage]:
        """``now`` = capture time of the segment in seconds (any consistent clock); needed to time out TCP holes."""
        if not payload or flow in self.ignored:
            return []
        stream = self.streams.get(flow)
        if stream is None:
            if len(self.streams) > 512:
                self.streams.clear()
            stream = self.streams[flow] = FrameStream()
        pages = []
        for frame in stream.feed(seq, payload, now):
            if frame[:2] == SHOP_OPCODE:
                self.shop_frames += 1
            page = parse_shop_payload(frame)
            if page:
                pages.append(page)
            elif frame[:2] == SHOP_OPCODE and len(frame) >= 4 and frame[3] > 0:
                self.problems.append(f"a shop list with {frame[3]} items could not be read")
        if stream.ever_synced:
            if self.locked_flow is None:
                self.locked_flow = flow
        else:
            stream.packets += 1
            if stream.packets > self.UNSYNCED_LIMIT:      # other traffic: stop spending any time on it
                del self.streams[flow]
                if len(self.ignored) >= self.MAX_IGNORED:
                    self.ignored.clear()
                self.ignored.add(flow)
        return pages


# --------------------------------------------------------------------------- #
# Helpers shared by GUI / CLI
# --------------------------------------------------------------------------- #
def load_catalog(path: str) -> dict[int, str]:
    import csv
    out: dict[int, str] = {}
    with open(path, "r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        fields = {n.casefold().strip(): n for n in (reader.fieldnames or [])}
        id_col = next((fields[k] for k in ("item_id", "id", "itemid") if k in fields), None)
        name_col = next((fields[k] for k in ("name", "item_name", "itemname") if k in fields), None)
        if not id_col or not name_col:
            raise ValueError("CSV needs the headers item_id,name")
        for row in reader:
            raw = (row.get(id_col) or "").strip()
            name = (row.get(name_col) or "").strip()
            if raw and name:
                try:
                    out[int(raw, 0)] = name
                except ValueError:
                    out[int(raw, 10)] = name
    return out


def _main(argv: list[str]) -> int:
    """CLI:  python shop_decoder.py capture.pcap [names.csv]   (no scapy needed; classic .pcap only)"""
    import os
    import sys
    if len(argv) < 2:
        print(_main.__doc__)
        return 2
    catalog: dict[int, str] = {}
    here = os.path.dirname(os.path.abspath(__file__))
    paths = [argv[2]] if len(argv) > 2 else [os.path.join(here, "aion2_items.csv"), os.path.join(here, "item_catalog.csv")]
    for path in paths:
        if os.path.isfile(path):
            catalog.update(load_catalog(path))
    decoder = ShopDecoder()
    for flow, seq, payload, stamp in iter_pcap_tcp(argv[1], with_time=True):
        for page in decoder.feed_tcp(flow, seq, payload, stamp):
            print(f"\nShop page  request=0x{page.request_id:02x}  tab(guess)={page.tab_guess}  "
                  f"entries={len(page.offers)}/{page.declared_count}")
            print(f"{'#':>2} {'entry':>8} {'item_id':>10} {'qty':>4} {'orig':>9} {'price':>9} {'off':>5}  name")
            for o in page.offers:
                print(f"{o.index + 1:>2} {o.entry_id:>8} {o.item_id:>10} {o.quantity:>4} "
                      f"{o.original_price:>9,} {o.price:>9,} {-o.discount_percent:>4}%  {catalog.get(o.item_id, '')}")
    return 0


def iter_pcap_tcp(path: str, with_time: bool = False) -> Iterable[tuple]:
    """Minimal classic-pcap reader yielding (flow, seq, payload) - or (flow, seq, payload, seconds) with
    ``with_time`` - for IPv4/TCP packets."""
    with open(path, "rb") as fh:
        data = fh.read()
    magic = data[:4]
    if magic in (b"\xd4\xc3\xb2\xa1", b"\x4d\x3c\xb2\xa1"):
        e = "<"
    elif magic in (b"\xa1\xb2\xc3\xd4", b"\xa1\xb2\x3c\x4d"):
        e = ">"
    else:
        raise ValueError("Only classic .pcap files are supported by the CLI (pcapng: open in the GUI)")
    link = struct.unpack(e + "I", data[20:24])[0]
    pos = 24
    while pos + 16 <= len(data):
        _s, _us, caplen, _orig = struct.unpack(e + "IIII", data[pos:pos + 16])
        stamp = _s + _us / 1e6
        pos += 16
        raw = data[pos:pos + caplen]
        pos += caplen
        off = 0
        if link == 1:
            if len(raw) < 14:
                continue
            etype = struct.unpack(">H", raw[12:14])[0]
            off = 14
            if etype == 0x8100:
                etype = struct.unpack(">H", raw[16:18])[0]
                off = 18
            if etype != 0x0800:
                continue
        elif link == 0:
            off = 4
        ip = raw[off:]
        if len(ip) < 20 or ip[0] >> 4 != 4 or ip[9] != 6:
            continue
        ihl = (ip[0] & 15) * 4
        total = struct.unpack(">H", ip[2:4])[0]
        seg = ip[ihl:total] if total >= ihl + 20 else ip[ihl:]
        if len(seg) < 20:
            continue
        sport, dport, seq = struct.unpack(">HHI", seg[:8])
        doff = (seg[12] >> 4) * 4
        payload = seg[doff:]
        if payload:
            flow = (".".join(map(str, ip[12:16])), sport, ".".join(map(str, ip[16:20])), dport)
            yield (flow, seq, payload, stamp) if with_time else (flow, seq, payload)


if __name__ == "__main__":
    import sys
    raise SystemExit(_main(sys.argv))
