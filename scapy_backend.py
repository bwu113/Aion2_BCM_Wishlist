"""Packet capture through Npcap + Scapy."""
from __future__ import annotations

import os
import sys
import threading
import time
from typing import Any, Callable

try:
    from scapy.all import IP, IPv6, TCP, Raw, conf, get_if_list, sniff  # type: ignore
    try:
        from scapy.arch.windows import get_windows_if_list  # type: ignore
    except Exception:
        get_windows_if_list = None
    AVAILABLE = True
    ERROR = ""
except Exception as exc:        # scapy not installed / no Npcap
    AVAILABLE = False
    ERROR = str(exc)


NPCAP_URL = "https://npcap.com"


def npcap_installed() -> bool:
    """True if the Npcap (or WinPcap) runtime is present - always True away from Windows."""
    if not sys.platform.startswith("win"):
        return True
    root = os.environ.get("SystemRoot", r"C:\Windows")
    return any(os.path.isfile(os.path.join(root, "System32", *p))
               for p in (("Npcap", "wpcap.dll"), ("wpcap.dll",)))


def problem() -> str:
    """Why capture cannot start (shown to the user), or "" if it can."""
    if not AVAILABLE:
        return f"the capture library could not be loaded ({ERROR})"
    if not npcap_installed():
        return f"Npcap is not installed. Install it from {NPCAP_URL} (keep \"WinPcap API-compatible mode\" ticked), then start the scan again"
    return ""


def interfaces() -> list[str]:
    conf.use_pcap = True
    names: list[str] = []
    if get_windows_if_list is not None:
        try:
            for item in get_windows_if_list():
                name = str(item.get("name") or item.get("guid") or "").strip()
                ips = item.get("ips") or []
                ips = [ips] if isinstance(ips, str) else [str(ip) for ip in ips if str(ip).strip()]
                if name and ips and "loopback" not in f"{item.get('description', '')} {name}".casefold():
                    names.append(name)
        except Exception:
            names = []
    if not names:
        names = [n for n in get_if_list() if "loopback" not in str(n).casefold() and str(n) != "lo"]
    return names


def _fields(packet: Any) -> dict[str, Any] | None:
    try:
        if TCP not in packet:
            return None
        if IP in packet:
            src, dst = packet[IP].src, packet[IP].dst
        elif IPv6 in packet:
            src, dst = packet[IPv6].src, packet[IPv6].dst
        else:
            return None
        tcp = packet[TCP]
        payload = bytes(packet[Raw].load) if Raw in packet else b""
        return {"payload": payload, "proto": "TCP", "src": src, "dst": dst, "sport": int(tcp.sport),
                "dport": int(tcp.dport), "seq": int(tcp.seq), "time": float(getattr(packet, "time", time.time()))}
    except Exception:
        return None


def run(callback: Callable[[dict[str, Any]], None], stop: threading.Event) -> None:
    names = interfaces()
    if not names:
        raise RuntimeError("no capture adapters found")
    iface: Any = names[0] if len(names) == 1 else names

    def on_packet(packet: Any) -> None:
        fields = _fields(packet)
        if fields is not None:
            callback(fields)

    conf.use_pcap = True
    while not stop.is_set():
        sniff(iface=iface, filter="tcp", prn=on_packet, store=False, timeout=1)
