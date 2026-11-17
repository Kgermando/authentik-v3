"""Scanners eSCL hors du reseau local : ajout par adresse et recherche sur une plage d'adresses.

mDNS ne traverse pas les routeurs. Pour un scanner d'un autre sous-reseau, d'un autre batiment
ou d'un autre site relie par VPN, il suffit que son adresse soit JOIGNABLE depuis le poste :
- `probe("10.0.2.15")` essaie les ports et chemins eSCL usuels et renvoie le scanner trouve ;
- `probe_range("10.0.2.0/24")` cherche tous les scanners eSCL d'une plage.

Garde-fous : plages PRIVEES uniquement (RFC 1918, etc.), 1024 adresses au plus. Il ne s'agit
pas de balayer Internet, et un scanner ne doit jamais etre expose sur Internet.
"""
from __future__ import annotations

import ipaddress
import socket
from concurrent.futures import ThreadPoolExecutor
from typing import Callable
from urllib.parse import urlsplit

import httpx

from .base import ScannerInfo
from .discovery import escl_url
from .escl import EsclClient, ScanError

# (port, https) dans l'ordre d'essai ; chemins eSCL usuels selon les marques.
PORTS: tuple[tuple[int, bool], ...] = ((443, True), (80, False), (8080, False), (9095, False),
                                       (9096, True))
ROOTS = ("eSCL", "escl")
MAX_HOSTS = 1024

TcpCheck = Callable[[str, int, float], bool]


def tcp_open(host: str, port: int, timeout: float) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def candidate_urls(address: str) -> list[str]:
    """« 10.0.2.15 », « scanner.site.local:8080 » ou une URL complete -> URLs eSCL a essayer."""
    address = address.strip()
    if not address:
        raise ValueError("Adresse vide.")
    if "://" in address:
        parts = urlsplit(address)
        if parts.scheme not in ("http", "https") or not parts.hostname:
            raise ValueError(f"Adresse invalide : {address}")
        if parts.path.strip("/"):
            return [address.rstrip("/")]
        return [address.rstrip("/") + "/" + root for root in ROOTS]
    host, port = address, None
    if address.count(":") == 1:                       # nom:port ou IPv4:port
        host, p = address.split(":")
        if not p.isdigit():
            raise ValueError(f"Port invalide : {address}")
        port = int(p)
    host = host.strip("[]")
    ports = [(port, port in (443, 9096))] if port else list(PORTS)
    return [escl_url(host, pt, https, root) for pt, https in ports for root in ROOTS]


def probe(address: str, timeout: float = 4.0, origin: str = "ajouté par adresse",
          transport: httpx.BaseTransport | None = None,
          tcp_check: TcpCheck | None = tcp_open) -> ScannerInfo | None:
    """Renvoie le scanner eSCL trouve a cette adresse, ou None."""
    tried_ports: dict[tuple[str, int], bool] = {}
    for url in candidate_urls(address):
        parts = urlsplit(url)
        hp = (parts.hostname, parts.port or (443 if parts.scheme == "https" else 80))
        if tcp_check is not None:
            if hp not in tried_ports:
                tried_ports[hp] = tcp_check(hp[0], hp[1], min(timeout, 1.5))
            if not tried_ports[hp]:
                continue
        try:
            with EsclClient(url, timeout=timeout, transport=transport) as c:
                caps = c.capabilities()
        except ScanError:
            continue
        if caps.has_platen or caps.has_adf:
            model = caps.make_and_model
            return ScannerInfo(model or parts.hostname, "escl", url, model, origin)
    return None


def parse_range(cidr: str) -> ipaddress.IPv4Network | ipaddress.IPv6Network:
    try:
        net = ipaddress.ip_network(cidr.strip(), strict=False)
    except ValueError as e:
        raise ValueError(f"Plage invalide : {cidr} (exemple : 10.0.2.0/24)") from e
    if not net.is_private:
        raise ValueError("Seules les plages d'adresses privées (réseaux internes) sont autorisées.")
    if net.num_addresses > MAX_HOSTS:
        raise ValueError(f"Plage trop grande ({net.num_addresses} adresses, maximum {MAX_HOSTS}). "
                         "Utiliser par exemple un /24.")
    return net


def probe_range(cidr: str, timeout: float = 3.0, workers: int = 64,
                transport: httpx.BaseTransport | None = None,
                tcp_check: TcpCheck | None = tcp_open) -> list[ScannerInfo]:
    """Cherche les scanners eSCL d'une plage privee. Resultat trie (ordre fixe)."""
    net = parse_range(cidr)
    hosts = [str(h) for h in (net.hosts() if net.num_addresses > 2 else net)]
    origin = f"plage {net}"

    def one(host: str) -> ScannerInfo | None:
        return probe(host, timeout=timeout, origin=origin, transport=transport, tcp_check=tcp_check)

    with ThreadPoolExecutor(max_workers=max(1, min(workers, len(hosts)))) as ex:
        found = [s for s in ex.map(one, hosts) if s is not None]
    return sorted(found, key=lambda s: (ipaddress.ip_address(urlsplit(s.address).hostname),
                                        s.address))
