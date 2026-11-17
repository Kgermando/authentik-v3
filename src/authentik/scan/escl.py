"""Client eSCL (AirScan) : capacites, travail de scan, recuperation des pages.

Reglages FIXES (AGENTS.md 2 et 0 bis) : 300 DPI, couleur RGB24, vitre (Platen), page entiere,
AUCUN reglage d'amelioration envoye (luminosite, contraste, nettete... restent ceux du scanner).
Format prefere : sans perte (PNG, TIFF), puis PDF, puis JPEG en dernier recours.
Compatibilite entre marques : resolutions discretes OU par plage, vitre ou (a defaut) chargeur
de feuilles, second essai sans `DocumentFormatExt` si le travail est refuse (400/409/415).

ATTENTION : protocole NON VERIFIE sur une imprimante reelle. A tester sur celle du client.
"""
from __future__ import annotations

import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from urllib.parse import urljoin

import httpx

from ..config import SETTINGS

NS_SCAN = "http://schemas.hp.com/imaging/escl/2011/05/03"
NS_PWG = "http://www.pwg.org/schemas/2010/12/sm"
FORMAT_PREFERENCE = ("image/png", "image/tiff", "application/pdf", "image/jpeg")
EXTENSIONS = {"image/png": ".png", "image/tiff": ".tiff", "application/pdf": ".pdf",
              "image/jpeg": ".jpg"}
A4_300THS = (2480, 3508)          # 210 x 297 mm en 1/300 de pouce


class ScanError(Exception):
    """Erreur de scan (message affiche tel quel)."""


@dataclass
class Capabilities:
    make_and_model: str = ""
    formats: list[str] = field(default_factory=list)
    color_modes: list[str] = field(default_factory=list)
    resolutions: list[int] = field(default_factory=list)
    resolution_ranges: list[tuple[int, int]] = field(default_factory=list)
    max_width: int = A4_300THS[0]
    max_height: int = A4_300THS[1]
    has_platen: bool = False
    has_adf: bool = False

    @property
    def input_source(self) -> str:
        """Vitre de preference ; chargeur de feuilles seulement si l'appareil n'a pas de vitre."""
        return "Platen" if self.has_platen else "Feeder"

    def supports_dpi(self, dpi: int) -> bool:
        if not self.resolutions and not self.resolution_ranges:
            return True                       # non annonce : on laisse le scanner trancher
        return dpi in self.resolutions or any(lo <= dpi <= hi for lo, hi in self.resolution_ranges)

    def problems(self, dpi: int = SETTINGS.scan_dpi) -> list[str]:
        """Ce qui empeche un scan aux reglages imposes (liste vide = OK)."""
        out = []
        if not self.has_platen and not self.has_adf:
            out.append("ni vitre d'exposition ni chargeur de feuilles annoncés")
        if not self.supports_dpi(dpi):
            ranges = [f"{lo}-{hi}" for lo, hi in self.resolution_ranges]
            out.append(f"{dpi} DPI non proposé (résolutions : {self.resolutions + ranges})")
        if self.color_modes and "RGB24" not in self.color_modes:
            out.append("mode couleur RGB24 non proposé")
        if not any(f in self.formats for f in FORMAT_PREFERENCE):
            out.append(f"aucun format utilisable ({self.formats})")
        return out

    def best_format(self) -> str:
        for f in FORMAT_PREFERENCE:
            if f in self.formats:
                return f
        raise ScanError(f"Aucun format de fichier utilisable : {self.formats}")


@dataclass
class ScannedPage:
    data: bytes
    content_type: str

    @property
    def extension(self) -> str:
        return EXTENSIONS.get(self.content_type, ".bin")


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _texts(root: ET.Element, name: str) -> list[str]:
    return [e.text.strip() for e in root.iter() if _local(e.tag) == name and e.text]


def parse_capabilities(xml: bytes) -> Capabilities:
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as e:
        raise ScanError(f"Réponse du scanner illisible : {e}") from e
    caps = Capabilities()
    caps.make_and_model = next(iter(_texts(root, "MakeAndModel")), "")
    platen = next((e for e in root.iter() if _local(e.tag) == "PlatenInputCaps"), None)
    adf = next((e for e in root.iter() if _local(e.tag) in ("AdfSimplexInputCaps", "AdfDuplexInputCaps")), None)
    caps.has_platen, caps.has_adf = platen is not None, adf is not None
    platen = platen if platen is not None else adf
    if platen is None:
        return caps
    for rng in (e for e in platen.iter() if _local(e.tag) == "XResolutionRange"):
        lo, hi = _texts(rng, "Min"), _texts(rng, "Max")
        if lo and hi and lo[0].isdigit() and hi[0].isdigit():
            caps.resolution_ranges.append((int(lo[0]), int(hi[0])))
    caps.formats = sorted(set(_texts(platen, "DocumentFormat") + _texts(platen, "DocumentFormatExt")))
    caps.color_modes = sorted(set(_texts(platen, "ColorMode")))
    caps.resolutions = sorted({int(x) for x in _texts(platen, "XResolution") if x.isdigit()})
    w, h = _texts(platen, "MaxWidth"), _texts(platen, "MaxHeight")
    if w and w[0].isdigit():
        caps.max_width = int(w[0])
    if h and h[0].isdigit():
        caps.max_height = int(h[0])
    return caps


def scan_settings_xml(fmt: str, width: int, height: int, dpi: int = SETTINGS.scan_dpi,
                      source: str = "Platen", format_ext: bool = True) -> bytes:
    """XML ScanSettings : page entiere, couleur, resolution fixe, sans amelioration."""
    ET.register_namespace("scan", NS_SCAN)
    ET.register_namespace("pwg", NS_PWG)
    s, p = f"{{{NS_SCAN}}}", f"{{{NS_PWG}}}"
    root = ET.Element(s + "ScanSettings")
    ET.SubElement(root, p + "Version").text = "2.0"
    region = ET.SubElement(ET.SubElement(root, p + "ScanRegions"), p + "ScanRegion")
    for tag, val in (("XOffset", 0), ("YOffset", 0), ("Width", width), ("Height", height)):
        ET.SubElement(region, p + tag).text = str(val)
    ET.SubElement(region, p + "ContentRegionUnits").text = "escl:ThreeHundredthsOfInches"
    ET.SubElement(root, p + "InputSource").text = source
    ET.SubElement(root, s + "ColorMode").text = "RGB24"
    ET.SubElement(root, s + "XResolution").text = str(dpi)
    ET.SubElement(root, s + "YResolution").text = str(dpi)
    ET.SubElement(root, p + "DocumentFormat").text = fmt
    if format_ext:            # certains modeles anciens refusent cet element : voir EsclClient.scan
        ET.SubElement(root, s + "DocumentFormatExt").text = fmt
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


class EsclClient:
    def __init__(self, base_url: str, timeout: float = 120.0,
                 transport: httpx.BaseTransport | None = None, poll_delay: float = 2.0):
        """`base_url` : par ex. http://192.168.1.20:80/eSCL (sans / final).

        Certificat HTTPS non verifie : les imprimantes du reseau local utilisent presque toujours
        un certificat auto-signe. Le document ne quitte pas le reseau local.
        """
        self.base = base_url.rstrip("/") + "/"
        self.poll_delay = poll_delay
        self.http = httpx.Client(timeout=timeout, verify=False, transport=transport,
                                 follow_redirects=True)

    def close(self) -> None:
        self.http.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def _get(self, url: str) -> httpx.Response:
        try:
            return self.http.get(url)
        except httpx.HTTPError as e:
            raise ScanError(f"Scanner injoignable : {e}") from e

    def capabilities(self) -> Capabilities:
        r = self._get(urljoin(self.base, "ScannerCapabilities"))
        if r.status_code != 200:
            raise ScanError(f"Le scanner a refusé la demande de capacités (HTTP {r.status_code}).")
        return parse_capabilities(r.content)

    def scan(self, max_pages: int = 20, max_busy_wait: float = 120.0) -> list[ScannedPage]:
        caps = self.capabilities()
        problems = caps.problems()
        if problems:
            raise ScanError("Ce scanner ne permet pas les réglages imposés : " + "; ".join(problems))
        fmt = caps.best_format()
        size = (min(caps.max_width, A4_300THS[0]), min(caps.max_height, A4_300THS[1]))
        r = None
        for format_ext in (True, False):      # 2e essai sans DocumentFormatExt (modeles anciens)
            body = scan_settings_xml(fmt, *size, source=caps.input_source, format_ext=format_ext)
            try:
                r = self.http.post(urljoin(self.base, "ScanJobs"), content=body,
                                   headers={"Content-Type": "text/xml"})
            except httpx.HTTPError as e:
                raise ScanError(f"Scanner injoignable : {e}") from e
            if r.status_code not in (400, 409, 415):
                break
        if r.status_code == 503:
            raise ScanError("Scanner occupé. Réessayer dans un instant.")
        if r.status_code not in (200, 201) or "Location" not in r.headers:
            raise ScanError(f"Le scanner a refusé le travail de scan (HTTP {r.status_code}).")
        job = urljoin(self.base, r.headers["Location"]).rstrip("/") + "/"

        pages: list[ScannedPage] = []
        waited = 0.0
        while len(pages) < max_pages:
            r = self._get(urljoin(job, "NextDocument"))
            if r.status_code == 200:
                ctype = r.headers.get("Content-Type", fmt).split(";")[0].strip() or fmt
                pages.append(ScannedPage(r.content, ctype))
                waited = 0.0
            elif r.status_code == 404:          # plus de page
                break
            elif r.status_code == 503:          # numerisation en cours
                if waited >= max_busy_wait:
                    raise ScanError("Le scanner ne répond plus (délai dépassé).")
                time.sleep(self.poll_delay)
                waited += self.poll_delay
            else:
                raise ScanError(f"Erreur pendant la récupération de la page (HTTP {r.status_code}).")
        if not pages:
            where = "sur la vitre" if caps.has_platen else "dans le chargeur"
            raise ScanError(f"Aucune page reçue. Le document est-il posé {where} ?")
        return pages
