"""Lean packet capture: talks to Npcap's wpcap.dll directly (ctypes) - no Scapy needed.

Why: Scapy builds a full Python object for every packet it sees; this reads the raw bytes, parses
just the TCP header by hand, and lets the Npcap *driver* throw everything else away:

  1. at first only TCP packets that carry data (and arrive from outside) are captured;
  2. as soon as the game's connection is recognised (it carries a 20 Hz heartbeat) the driver filter is
     narrowed to "TCP from that one server address/port" - everything else, including all other
     network traffic, no longer reaches Python at all;
  3. all other network adapters are closed;
  4. if the game connection goes silent for LOST_SECONDS the wide filter is restored automatically.

Requires Npcap (https://npcap.com).  The API used is the classic libpcap one, so on Linux/macOS it loads
libpcap instead, which is how the logic is tested.
"""
from __future__ import annotations

import ctypes
import ctypes.util
import os
import socket
import struct
import sys
import threading
import time
from ctypes import POINTER, Structure, byref, c_char_p, c_int, c_long, c_uint32, c_ubyte, c_void_p
from typing import Any, Callable

IS_WINDOWS = sys.platform.startswith("win")
LOST_SECONDS = 20.0            # silence on the game connection before capture goes back to the wide filter
TIMEOUT_MS = 100               # how long the driver may hold packets back (also the idle wake-up interval)
SNAPLEN = 65535
KERNEL_BUFFER = 8 * 1024 * 1024   # bytes the driver may hold while this program is busy (the default is 1 MB)
PCAP_D_IN = 1
PCAP_IF_LOOPBACK = 0x1
PCAP_ERRBUF_SIZE = 256

# Wide filter: TCP segments that carry data.  (IPv6 cannot index into the TCP header in BPF, so it is "any TCP".)
FILTER_WIDE = ("(tcp and ip and (ip[2:2] - ((ip[0] & 0xf) << 2) - ((tcp[12] & 0xf0) >> 2)) != 0) or (ip6 and tcp)")
FILTER_FALLBACK = "tcp"


class NpcapError(Exception):
    """Capture cannot work (message is meant for the user)."""


class NpcapMissing(NpcapError):
    """Npcap / libpcap is not installed."""


# --------------------------------------------------------------------------- #
# ctypes layer
# --------------------------------------------------------------------------- #
class _Timeval(Structure):
    _fields_ = [("tv_sec", c_long), ("tv_usec", c_long)]


class _PktHdr(Structure):
    _fields_ = [("ts", _Timeval), ("caplen", c_uint32), ("len", c_uint32)]


class _BpfProgram(Structure):
    _fields_ = [("bf_len", ctypes.c_uint), ("bf_insns", c_void_p)]


class _PcapAddr(Structure):
    pass


_PcapAddr._fields_ = [("next", POINTER(_PcapAddr)), ("addr", c_void_p), ("netmask", c_void_p),
                      ("broadaddr", c_void_p), ("dstaddr", c_void_p)]


class _PcapIf(Structure):
    pass


_PcapIf._fields_ = [("next", POINTER(_PcapIf)), ("name", c_char_p), ("description", c_char_p),
                    ("addresses", POINTER(_PcapAddr)), ("flags", c_uint32)]

_IP_FAMILIES = (socket.AF_INET, getattr(socket, "AF_INET6", 23), 23)      # 23 = AF_INET6 on Windows


class Device:
    def __init__(self, name: str, description: str, loopback: bool, has_ip: bool) -> None:
        self.name, self.description, self.loopback, self.has_ip = name, description, loopback, has_ip

    def __repr__(self) -> str:
        return f"Device({self.description or self.name!r})"


def _load_library() -> ctypes.CDLL:
    if IS_WINDOWS:
        root = os.environ.get("SystemRoot", r"C:\Windows")
        for folder in (os.path.join(root, "System32", "Npcap"), os.path.join(root, "System32")):
            dll = os.path.join(folder, "wpcap.dll")
            if os.path.isfile(dll):
                try:
                    ctypes.windll.kernel32.SetDllDirectoryW(folder)      # so wpcap.dll finds Packet.dll
                    return ctypes.CDLL(dll)          # wpcap exports are cdecl
                except OSError as exc:
                    raise NpcapError(f"Npcap is installed but could not be loaded ({exc})") from exc
        raise NpcapMissing("Npcap is not installed. Install it from https://npcap.com "
                           "(keep \"WinPcap API-compatible mode\" ticked), then start the scan again.")
    name = ctypes.util.find_library("pcap")
    if not name:
        raise NpcapMissing("libpcap is not installed.")
    return ctypes.CDLL(name)


class PcapAPI:
    """The handful of libpcap calls that are needed, with Python-friendly return values."""

    def __init__(self, lib: ctypes.CDLL | None = None) -> None:
        self.lib = lib or _load_library()
        L = self.lib
        try:
            L.pcap_findalldevs.argtypes = [POINTER(POINTER(_PcapIf)), c_char_p]
            L.pcap_findalldevs.restype = c_int
            L.pcap_freealldevs.argtypes = [POINTER(_PcapIf)]
            L.pcap_freealldevs.restype = None
            L.pcap_open_live.argtypes = [c_char_p, c_int, c_int, c_int, c_char_p]
            L.pcap_open_live.restype = c_void_p
            L.pcap_compile.argtypes = [c_void_p, POINTER(_BpfProgram), c_char_p, c_int, c_uint32]
            L.pcap_compile.restype = c_int
            L.pcap_setfilter.argtypes = [c_void_p, POINTER(_BpfProgram)]
            L.pcap_setfilter.restype = c_int
            L.pcap_freecode.argtypes = [POINTER(_BpfProgram)]
            L.pcap_freecode.restype = None
            L.pcap_next_ex.argtypes = [c_void_p, POINTER(POINTER(_PktHdr)), POINTER(POINTER(c_ubyte))]
            L.pcap_next_ex.restype = c_int
            L.pcap_datalink.argtypes = [c_void_p]
            L.pcap_datalink.restype = c_int
            L.pcap_close.argtypes = [c_void_p]
            L.pcap_close.restype = None
            L.pcap_geterr.argtypes = [c_void_p]
            L.pcap_geterr.restype = c_char_p
            L.pcap_setdirection.argtypes = [c_void_p, c_int]
            L.pcap_setdirection.restype = c_int
        except AttributeError as exc:
            raise NpcapError(f"the capture library is missing a function ({exc})") from exc
        try:                                                     # optional: only Npcap / WinPcap have it
            L.pcap_setbuff.argtypes = [c_void_p, c_int]
            L.pcap_setbuff.restype = c_int
        except AttributeError:
            pass

    # -- adapters ----------------------------------------------------------- #
    def devices(self) -> list[Device]:
        err = ctypes.create_string_buffer(PCAP_ERRBUF_SIZE)
        head = POINTER(_PcapIf)()
        if self.lib.pcap_findalldevs(byref(head), err) != 0:
            raise NpcapError(f"could not list the network adapters: {err.value.decode(errors='replace')}")
        out: list[Device] = []
        try:
            node = head
            while node:
                d = node.contents
                has_ip = False
                a = d.addresses
                while a:
                    if a.contents.addr:
                        family = ctypes.cast(a.contents.addr, POINTER(ctypes.c_ushort)).contents.value
                        # Linux sockaddr starts with a 16-bit family; Windows too (BSD has a length byte first)
                        if family in _IP_FAMILIES:
                            has_ip = True
                    a = a.contents.next
                out.append(Device((d.name or b"").decode(errors="replace"),
                                  (d.description or b"").decode(errors="replace"),
                                  bool(d.flags & PCAP_IF_LOOPBACK), has_ip))
                node = d.next
        finally:
            self.lib.pcap_freealldevs(head)
        return out

    # -- one adapter ---------------------------------------------------------- #
    def open(self, name: str) -> int:
        err = ctypes.create_string_buffer(PCAP_ERRBUF_SIZE)
        handle = self.lib.pcap_open_live(name.encode(), SNAPLEN, 0, TIMEOUT_MS, err)     # 0 = not promiscuous
        if not handle:
            raise NpcapError(f"could not open {name}: {err.value.decode(errors='replace') or 'unknown error'}")
        try:
            self.lib.pcap_setdirection(handle, PCAP_D_IN)         # only what arrives (ignored if unsupported)
        except Exception:
            pass
        try:
            self.lib.pcap_setbuff(handle, KERNEL_BUFFER)          # bigger driver buffer: no drops in a crowd (Npcap/WinPcap only)
        except Exception:
            pass
        return handle

    def set_filter(self, handle: int, text: str) -> None:
        prog = _BpfProgram()
        if self.lib.pcap_compile(handle, byref(prog), text.encode(), 1, 0xFFFFFFFF) != 0:
            raise NpcapError(f"bad capture filter: {self.error(handle)}")
        try:
            if self.lib.pcap_setfilter(handle, byref(prog)) != 0:
                raise NpcapError(f"could not apply the capture filter: {self.error(handle)}")
        finally:
            self.lib.pcap_freecode(byref(prog))

    def datalink(self, handle: int) -> int:
        return int(self.lib.pcap_datalink(handle))

    def next(self, handle: int) -> tuple[int, float, bytes]:
        """(status, timestamp, packet): status 1 = packet, 0 = timeout, negative = error / end."""
        hdr_p = POINTER(_PktHdr)()                 # per call: several adapter threads use this at the same time
        data_p = POINTER(c_ubyte)()
        rc = self.lib.pcap_next_ex(handle, byref(hdr_p), byref(data_p))
        if rc != 1:
            return rc, 0.0, b""
        hdr = hdr_p.contents
        return 1, hdr.ts.tv_sec + hdr.ts.tv_usec / 1e6, ctypes.string_at(data_p, hdr.caplen)

    def error(self, handle: int) -> str:
        msg = self.lib.pcap_geterr(handle)
        return msg.decode(errors="replace") if msg else "unknown error"

    def close(self, handle: int) -> None:
        self.lib.pcap_close(handle)


# --------------------------------------------------------------------------- #
# Packet parsing (hand-written, only what is needed)
# --------------------------------------------------------------------------- #
def parse_frame(data: bytes, dlt: int, stamp: float = 0.0) -> dict[str, Any] | None:
    """Link-layer frame -> {payload, src, dst, sport, dport, seq, time} for an IPv4/IPv6 TCP segment, else None."""
    n = len(data)
    if dlt == 1:                                        # Ethernet
        if n < 14:
            return None
        off, et = 14, data[12:14]
        if et == b"\x81\x00" and n >= 18:               # 802.1Q VLAN tag
            off, et = 18, data[16:18]
        version = 4 if et == b"\x08\x00" else 6 if et == b"\x86\xdd" else 0
    elif dlt == 113:                                    # Linux "cooked"
        off, version = 16, 0
    elif dlt in (0, 108):                               # BSD loopback / null
        off, version = 4, 0
    else:                                               # raw IP (12, 101) or anything else: sniff the version
        off, version = 0, 0
    if off >= n:
        return None
    if version == 0:
        version = data[off] >> 4
    if version == 4:
        if n < off + 40:
            return None
        ihl = (data[off] & 0x0F) * 4
        if data[off + 9] != 6 or n < off + ihl + 20:
            return None
        if data[off + 6] & 0x20 or (data[off + 6] & 0x1F) or data[off + 7]:      # fragment
            return None
        total = (data[off + 2] << 8) | data[off + 3]
        end = off + total if ihl + 20 <= total <= n - off else n
        t = off + ihl
        src, dst = socket.inet_ntoa(data[off + 12:off + 16]), socket.inet_ntoa(data[off + 16:off + 20])
    elif version == 6:
        if n < off + 60 or data[off + 6] != 6:          # extension headers are not handled (not used by games)
            return None
        end = min(n, off + 40 + ((data[off + 4] << 8) | data[off + 5]))
        t = off + 40
        src = socket.inet_ntop(socket.AF_INET6, data[off + 8:off + 24])
        dst = socket.inet_ntop(socket.AF_INET6, data[off + 24:off + 40])
    else:
        return None
    sport, dport, seq = struct.unpack_from("!HHI", data, t)
    start = t + ((data[t + 12] >> 4) * 4)
    if start > end or start - t < 20:
        return None
    return {"payload": data[start:end], "src": src, "dst": dst, "sport": sport, "dport": dport,
            "seq": seq, "time": stamp or time.time()}


# --------------------------------------------------------------------------- #
# Capture session
# --------------------------------------------------------------------------- #
class _Session:
    """One pass over all adapters; ends on stop, on 'game connection lost', or when every adapter died."""

    def __init__(self, api: PcapAPI, devices: list[Device], handler: Callable[[dict], str | None],
                 stop: threading.Event) -> None:
        self.api, self.devices, self.handler, self.stop = api, devices, handler, stop
        self.owner: str | None = None
        self.lost = threading.Event()
        self.lock = threading.Lock()
        self.threads: list[threading.Thread] = []
        self.errors: list[str] = []

    def start(self) -> int:
        for dev in self.devices:
            try:
                handle = self.api.open(dev.name)
                try:
                    try:
                        self.api.set_filter(handle, FILTER_WIDE)
                    except NpcapError:
                        self.api.set_filter(handle, FILTER_FALLBACK)
                    dlt = self.api.datalink(handle)
                except Exception:
                    self.api.close(handle)
                    raise
            except NpcapError as exc:
                self.errors.append(str(exc))
                continue
            t = threading.Thread(target=self._loop, args=(dev.name, handle, dlt), daemon=True)
            self.threads.append(t)
            t.start()
        return len(self.threads)

    def _loop(self, name: str, handle: int, dlt: int) -> None:
        api, last = self.api, time.monotonic()
        try:
            while not self.stop.is_set() and not self.lost.is_set():
                if self.owner is not None and self.owner != name:
                    return                                   # the game is on another adapter: stand down
                rc, stamp, data = api.next(handle)
                if rc == 1:
                    last = time.monotonic()
                    fields = parse_frame(data, dlt, stamp)
                    if fields is None:
                        continue
                    narrow = self.handler(fields)
                    if narrow:
                        with self.lock:
                            if self.owner is None:
                                self.owner = name
                        if self.owner == name:
                            try:
                                api.set_filter(handle, narrow)
                            except NpcapError:
                                pass                            # stay on the wide filter, still works
                elif rc == 0:
                    if self.owner == name and time.monotonic() - last > LOST_SECONDS:
                        self.lost.set()                      # game connection silent: go back to the wide filter
                else:
                    self.errors.append(f"{name}: {api.error(handle)}")
                    return
        finally:
            try:
                api.close(handle)
            except Exception:
                pass

    def alive(self) -> bool:
        return any(t.is_alive() for t in self.threads)

    def finish(self) -> None:
        self.lost.set()
        for t in self.threads:
            t.join(timeout=2.0)


class NpcapCapture:
    """Blocking capture loop with automatic recovery.  ``handler(fields)`` may return a narrower BPF filter."""

    def __init__(self, api: PcapAPI, handler: Callable[[dict], str | None], stop: threading.Event,
                 on_restart: Callable[[], None] | None = None) -> None:
        self.api, self.handler, self.stop, self.on_restart = api, handler, stop, on_restart

    def run(self) -> None:
        first = True
        while not self.stop.is_set():
            devices = [d for d in self.api.devices() if d.has_ip and not d.loopback]
            if not devices:
                if first:
                    raise NpcapError("no network adapter with an IP address was found")
                self.stop.wait(3.0)
                continue
            session = _Session(self.api, devices, self.handler, self.stop)
            if not session.start():
                if first:
                    raise NpcapError("could not open any network adapter for capture: "
                                     + "; ".join(session.errors[:2]) + ". Try running the program as administrator.")
                self.stop.wait(3.0)
                continue
            first = False
            while not self.stop.is_set() and not session.lost.is_set() and session.alive():
                self.stop.wait(0.25)
            lost = session.lost.is_set() and not self.stop.is_set()
            session.finish()
            if self.stop.is_set():
                return
            if self.on_restart:
                self.on_restart()                            # forget the old connection, start wide again
            if not lost:
                self.stop.wait(3.0)                          # adapters vanished (sleep / unplug): retry shortly
