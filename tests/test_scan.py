"""Client eSCL teste contre un FAUX scanner (httpx.MockTransport).
Ne prouve pas que le client fonctionne avec l'imprimante du client : a tester sur place."""
import io
import xml.etree.ElementTree as ET

import httpx
import numpy as np
import pytest
from PIL import Image

from authentik.ingest import load_document
from authentik.scan import EsclClient, ScanError, ScannedPage, save_scan
from authentik.scan.discovery import scanner_from_service
from authentik.scan.escl import parse_capabilities

CAPS = b"""<?xml version="1.0" encoding="UTF-8"?>
<scan:ScannerCapabilities xmlns:scan="http://schemas.hp.com/imaging/escl/2011/05/03"
                          xmlns:pwg="http://www.pwg.org/schemas/2010/12/sm">
  <pwg:Version>2.63</pwg:Version>
  <pwg:MakeAndModel>HP LaserJet MFP M28w</pwg:MakeAndModel>
  <scan:Platen><scan:PlatenInputCaps>
    <scan:MaxWidth>2550</scan:MaxWidth><scan:MaxHeight>3508</scan:MaxHeight>
    <scan:SettingProfiles><scan:SettingProfile>
      <scan:ColorModes><scan:ColorMode>Grayscale8</scan:ColorMode><scan:ColorMode>RGB24</scan:ColorMode></scan:ColorModes>
      <scan:DocumentFormats><pwg:DocumentFormat>image/jpeg</pwg:DocumentFormat><pwg:DocumentFormat>application/pdf</pwg:DocumentFormat></scan:DocumentFormats>
      <scan:SupportedResolutions><scan:DiscreteResolutions>
        <scan:DiscreteResolution><scan:XResolution>150</scan:XResolution><scan:YResolution>150</scan:YResolution></scan:DiscreteResolution>
        <scan:DiscreteResolution><scan:XResolution>300</scan:XResolution><scan:YResolution>300</scan:YResolution></scan:DiscreteResolution>
      </scan:DiscreteResolutions></scan:SupportedResolutions>
    </scan:SettingProfile></scan:SettingProfiles>
  </scan:PlatenInputCaps></scan:Platen>
</scan:ScannerCapabilities>"""


def _png(color=(200, 100, 10)):
    buf = io.BytesIO()
    Image.fromarray(np.full((40, 30, 3), color, np.uint8)).save(buf, "PNG")
    return buf.getvalue()


class FakeScanner:
    def __init__(self, caps=CAPS, busy=1, pages=None, ctype="application/pdf"):
        self.caps, self.busy, self.ctype = caps, busy, ctype
        self.pages = list(pages if pages is not None else [b"%PDF-page"])
        self.posted = None

    def __call__(self, req: httpx.Request) -> httpx.Response:
        path = req.url.path
        if req.method == "GET" and path == "/eSCL/ScannerCapabilities":
            return httpx.Response(200, content=self.caps)
        if req.method == "POST" and path == "/eSCL/ScanJobs":
            self.posted = req.content
            return httpx.Response(201, headers={"Location": "/eSCL/ScanJobs/42"})
        if req.method == "GET" and path == "/eSCL/ScanJobs/42/NextDocument":
            if self.busy:
                self.busy -= 1
                return httpx.Response(503)
            if self.pages:
                return httpx.Response(200, content=self.pages.pop(0),
                                      headers={"Content-Type": self.ctype})
            return httpx.Response(404)
        return httpx.Response(500)


def _client(fake):
    return EsclClient("http://10.0.0.5:80/eSCL", transport=httpx.MockTransport(fake), poll_delay=0)


def test_parse_capabilities():
    c = parse_capabilities(CAPS)
    assert c.make_and_model == "HP LaserJet MFP M28w" and c.has_platen
    assert c.resolutions == [150, 300] and "RGB24" in c.color_modes
    assert c.best_format() == "application/pdf"          # PDF prefere au JPEG
    assert c.problems() == []


def test_scan_sends_fixed_settings_and_waits_while_busy():
    fake = FakeScanner()
    with _client(fake) as cl:
        pages = cl.scan()
    assert [p.data for p in pages] == [b"%PDF-page"] and pages[0].extension == ".pdf"
    root = ET.fromstring(fake.posted)
    vals = {e.tag.rsplit("}", 1)[-1]: (e.text or "") for e in root.iter()}
    assert vals["XResolution"] == vals["YResolution"] == "300"
    assert vals["ColorMode"] == "RGB24" and vals["InputSource"] == "Platen"
    assert vals["Width"] == "2480" and vals["Height"] == "3508"         # A4 maximum
    for forbidden in ("Brightness", "Contrast", "Sharpen", "Threshold", "CompressionFactor"):
        assert forbidden not in vals                                    # aucune amelioration


def test_scanner_without_300_dpi_or_color_refused():
    caps = CAPS.replace(b"<scan:XResolution>300</scan:XResolution>", b"<scan:XResolution>600</scan:XResolution>")
    caps = caps.replace(b"<scan:ColorMode>RGB24</scan:ColorMode>", b"")
    with _client(FakeScanner(caps)) as cl, pytest.raises(ScanError) as e:
        cl.scan()
    assert "300 DPI" in str(e.value) and "RGB24" in str(e.value)


def test_no_page_and_unreachable():
    with _client(FakeScanner(pages=[], busy=0)) as cl, pytest.raises(ScanError, match="Aucune page"):
        cl.scan()

    def down(req):
        raise httpx.ConnectError("refused")
    with EsclClient("http://10.0.0.5/eSCL", transport=httpx.MockTransport(down)) as cl, \
            pytest.raises(ScanError, match="injoignable"):
        cl.capabilities()


def test_save_scan_single_and_multi_page_lossless(tmp_path):
    one = save_scan([ScannedPage(_png(), "image/png")], tmp_path)
    assert one.suffix == ".png" and one.read_bytes() == _png()           # octets intacts
    multi = save_scan([ScannedPage(_png(), "image/png"),
                       ScannedPage(_png((1, 2, 3)), "image/png")], tmp_path / "m")
    d = load_document(multi)
    assert multi.suffix == ".tiff" and len(d.pages) == 2
    assert tuple(d.pages[1][0, 0]) == (3, 2, 1)                          # sans perte, BGR
    assert d.dpi == [pytest.approx(300, abs=0.5)] * 2


def test_assumed_dpi_for_scans_without_metadata(tmp_path):
    p = save_scan([ScannedPage(_png(), "image/png")], tmp_path)
    assert load_document(p).dpi == [None]
    d = load_document(p, assumed_dpi=300)
    assert d.dpi == [300.0] and not any("résolution" in w for w in d.warnings)


def test_discovery_record_parsing():
    s = scanner_from_service("_uscans._tcp.local.", "HP M28w._uscans._tcp.local.",
                             ["fe80::1", "192.168.1.20"], 443,
                             {b"rs": b"eSCL", b"ty": b"HP LaserJet MFP M28w"})
    assert s.backend == "escl" and s.address == "https://192.168.1.20:443/eSCL"
    assert s.name == "HP LaserJet MFP M28w" and s.origin == "réseau local"
    s2 = scanner_from_service("_uscan._tcp.local.", "Canon._uscan._tcp.local.", ["10.0.0.9"], 80,
                              {b"rs": b""})
    assert s2.address == "http://10.0.0.9:80" and s2.name == "Canon"
    assert scanner_from_service("_uscan._tcp.local.", "x", [], 80, {}) is None
