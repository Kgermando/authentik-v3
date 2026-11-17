"""Decouverte des scanners eSCL du reseau LOCAL par mDNS (_uscan._tcp et _uscans._tcp).

mDNS ne traverse pas les routeurs : un scanner d'un autre sous-reseau ou d'un autre site
n'apparait pas ici. Pour lui : ajout par adresse ou recherche sur une plage (`network.py`).
"""
from __future__ import annotations

import ipaddress
import time

from .base import ScannerInfo

SERVICE_TYPES = ("_uscan._tcp.local.", "_uscans._tcp.local.")


def escl_url(host: str, port: int, https: bool, root: str) -> str:
    scheme = "https" if https else "http"
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    root = root.strip("/")
    return f"{scheme}://{host}:{port}/{root}" if root else f"{scheme}://{host}:{port}"


def _txt(props: dict, key: str) -> str:
    v = props.get(key.encode()) if props else None
    return v.decode("utf-8", "replace") if isinstance(v, bytes) else ""


def scanner_from_service(service_type: str, name: str, addresses: list[str], port: int,
                         properties: dict) -> ScannerInfo | None:
    """Construit un ScannerInfo a partir d'une annonce mDNS (testable sans reseau)."""
    if not addresses or not port:
        return None
    ipv4 = [a for a in addresses if ipaddress.ip_address(a).version == 4]
    host = (ipv4 or addresses)[0]
    label = name.split("." + service_type)[0] if service_type in name else name.split(".")[0]
    model = _txt(properties, "ty")
    rs = _txt(properties, "rs") if properties and b"rs" in properties else "eSCL"
    url = escl_url(host, port, service_type.startswith("_uscans"), rs)
    return ScannerInfo(model or label, "escl", url, model, "réseau local")


def discover_scanners(timeout: float = 4.0) -> list[ScannerInfo]:
    """Ecoute le reseau local `timeout` secondes. HTTPS prefere quand un scanner annonce les deux."""
    from zeroconf import ServiceBrowser, ServiceStateChange, Zeroconf

    found: dict[tuple[str, str], ScannerInfo] = {}
    zc = Zeroconf()

    def on_change(zeroconf, service_type, name, state_change):
        if state_change is not ServiceStateChange.Added:
            return
        info = zeroconf.get_service_info(service_type, name, timeout=2000)
        if info is None:
            return
        s = scanner_from_service(service_type, name, info.parsed_addresses(), info.port,
                                 info.properties)
        if s is not None:
            host = s.address.split("://", 1)[1].rsplit(":", 1)[0]
            key = (host, s.name)
            if key not in found or s.address.startswith("https"):
                found[key] = s

    try:
        browsers = [ServiceBrowser(zc, t, handlers=[on_change]) for t in SERVICE_TYPES]
        time.sleep(timeout)
        for b in browsers:
            b.cancel()
    finally:
        zc.close()
    return sorted(found.values(), key=lambda s: (s.name.lower(), s.address))
