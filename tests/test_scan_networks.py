"""Scanners d'autres marques et d'autres reseaux.

eSCL : teste contre de FAUX scanners (httpx.MockTransport) ; WIA : non testable sous Linux.
SANE : vrai scan avec le peripherique de test de SANE si `scanimage` est installe.
"""
import subprocess
from pathlib import Path

import httpx
import pytest

from authentik.ingest import load_document
from authentik.scan import ScanError, ScannerInfo, find_scanners, probe, probe_range, scan_to_file
from authentik.scan import sane
from authentik.scan.escl import EsclClient, parse_capabilities
from authentik.scan.network import candidate_urls, parse_range
from authentik.store import AppConfig, load_config, save_config

from test_scan import CAPS, FakeScanner

CAPS_RANGE_ADF_ONLY = b"""<?xml version="1.0"?>
<scan:ScannerCapabilities xmlns:scan="http://schemas.hp.com/imaging/escl/2011/05/03"
                          xmlns:pwg="http://www.pwg.org/schemas/2010/12/sm">
  <pwg:MakeAndModel>Brother ADS-1700W</pwg:MakeAndModel>
  <scan:Adf><scan:AdfSimplexInputCaps>
    <scan:SettingProfiles><scan:SettingProfile>
      <scan:ColorModes><scan:ColorMode>RGB24</scan:ColorMode></scan:ColorModes>
      <scan:DocumentFormats><scan:DocumentFormatExt>image/jpeg</scan:DocumentFormatExt></scan:DocumentFormats>
      <scan:SupportedResolutions><scan:XResolutionRange><scan:Min>100</scan:Min><scan:Max>600</scan:Max>
      </scan:XResolutionRange></scan:SupportedResolutions>
    </scan:SettingProfile></scan:SettingProfiles>
  </scan:AdfSimplexInputCaps></scan:Adf>
</scan:ScannerCapabilities>"""


# -- compatibilite eSCL entre marques ------------------------------------------------------------
def test_resolution_range_and_feeder_only_scanner():
    c = parse_capabilities(CAPS_RANGE_ADF_ONLY)
    assert not c.has_platen and c.has_adf and c.input_source == "Feeder"
    assert c.resolution_ranges == [(100, 600)] and c.supports_dpi(300)
    assert c.problems() == [] and c.best_format() == "image/jpeg"


def test_feeder_used_when_no_platen():
    fake = FakeScanner(CAPS_RANGE_ADF_ONLY, busy=0, pages=[b"jpg"], ctype="image/jpeg")
    with EsclClient("http://10.0.0.5/eSCL", transport=httpx.MockTransport(fake), poll_delay=0) as c:
        c.scan()
    assert b"<pwg:InputSource>Feeder</pwg:InputSource>" in fake.posted


def test_retry_without_format_ext_when_job_refused():
    posts, served = [], []

    def handler(req):
        if req.url.path.endswith("ScannerCapabilities"):
            return httpx.Response(200, content=CAPS)
        if req.method == "POST":
            posts.append(req.content)
            if b"DocumentFormatExt" in req.content:      # modele ancien : refuse l'element
                return httpx.Response(409)
            return httpx.Response(201, headers={"Location": "http://10.0.0.5/eSCL/ScanJobs/7"})
        if req.url.path.endswith("/7/NextDocument") and not served:
            served.append(1)
            return httpx.Response(200, content=b"%PDF", headers={"Content-Type": "application/pdf"})
        return httpx.Response(404)

    with EsclClient("http://10.0.0.5/eSCL", transport=httpx.MockTransport(handler), poll_delay=0) as c:
        pages = c.scan()
    assert len(posts) == 2 and b"DocumentFormatExt" not in posts[1] and pages[0].data == b"%PDF"


# -- autres reseaux : adresse, port, chemin -------------------------------------------------------
def _site_b(path_root="escl", port=8080):
    """Faux scanner d'un autre site : 10.20.0.15, port et chemin non standard."""
    def handler(req):
        if req.url.host == "10.20.0.15" and req.url.port == port \
                and req.url.path == f"/{path_root}/ScannerCapabilities":
            return httpx.Response(200, content=CAPS)
        return httpx.Response(404)
    return httpx.MockTransport(handler)


def test_candidate_urls():
    assert candidate_urls("http://10.0.2.15/eSCL") == ["http://10.0.2.15/eSCL"]
    assert candidate_urls("https://10.0.2.15") == ["https://10.0.2.15/eSCL", "https://10.0.2.15/escl"]
    assert candidate_urls("scanner.site-b.local:8080") == [
        "http://scanner.site-b.local:8080/eSCL", "http://scanner.site-b.local:8080/escl"]
    assert "https://10.0.2.15:443/eSCL" in candidate_urls("10.0.2.15")
    with pytest.raises(ValueError):
        candidate_urls("ftp://x")


def test_probe_finds_scanner_on_other_network_nonstandard_port_and_path():
    s = probe("10.20.0.15", transport=_site_b(), tcp_check=lambda h, p, t: p == 8080)
    assert s == ScannerInfo("HP LaserJet MFP M28w", "escl", "http://10.20.0.15:8080/escl",
                            "HP LaserJet MFP M28w", "ajouté par adresse")


def test_probe_unreachable_returns_none():
    assert probe("10.20.0.99", transport=_site_b(), tcp_check=lambda h, p, t: False) is None


def test_probe_range_finds_scanners_sorted_and_is_limited():
    def handler(req):
        if req.url.host in ("10.30.0.40", "10.30.0.7") and req.url.path == "/eSCL/ScannerCapabilities":
            return httpx.Response(200, content=CAPS)
        return httpx.Response(404)
    found = probe_range("10.30.0.0/24", transport=httpx.MockTransport(handler),
                        tcp_check=lambda h, p, t: h in ("10.30.0.40", "10.30.0.7") and p == 80)
    assert [s.address for s in found] == ["http://10.30.0.7:80/eSCL", "http://10.30.0.40:80/eSCL"]
    assert found[0].origin == "plage 10.30.0.0/24"
    with pytest.raises(ValueError, match="privées"):
        parse_range("8.8.8.0/24")                     # Internet : refuse
    with pytest.raises(ValueError, match="trop grande"):
        parse_range("10.0.0.0/16")
    with pytest.raises(ValueError, match="invalide"):
        parse_range("pas une plage")


# -- liste combinee et memorisation --------------------------------------------------------------
def test_find_scanners_order_dedupe_and_failing_source():
    local = [ScannerInfo("HP", "escl", "http://192.168.1.20:80/eSCL", "", "réseau local")]
    drv = [ScannerInfo("Epson V39", "sane", "epsonscan2:usb:1", "", "pilote")]
    saved = [("Bureau HP", "http://192.168.1.20:80/eSCL/"), ("Site B", "http://10.20.0.15:8080/escl")]
    out = find_scanners(saved, discover=lambda t: local, drivers=lambda: drv)
    assert [(s.name, s.origin) for s in out] == [
        ("Bureau HP", "enregistré"), ("Site B", "enregistré"), ("Epson V39", "pilote")]

    def broken(t):
        raise OSError("pas de reseau")
    assert [s.name for s in find_scanners(saved, discover=broken, drivers=lambda: drv)] == \
        ["Bureau HP", "Site B", "Epson V39"]            # une source en panne n'arrete pas les autres


def test_saved_scanners_roundtrip(tmp_path):
    ini = tmp_path / "authentik.ini"
    cfg = AppConfig(tmp_path / "a.db", tmp_path / "docs", ini,
                    scanners=(("Site B | étage 2", "http://10.20.0.15:8080/escl"),
                              ("Kin%20Nord", "https://10.40.0.2:443/eSCL")))
    save_config(cfg)
    assert load_config(ini).scanners == cfg.scanners   # « | » et « % » dans les noms acceptes


# -- pilotes ---------------------------------------------------------------------------------
SANE_A = """
  Scan Mode:
    --mode Lineart|Gray|24bit Color [Gray]
    --resolution 75|150|300|600dpi [150]
    --source Flatbed|ADF [Flatbed]
"""


def test_sane_parse_devices_excludes_webcams():
    text = ("v4l:/dev/video0|Noname|Integrated Camera|virtual device\n"
            "epsonscan2:Perfection V39:001:usb|EPSON|Perfection V39|flatbed scanner\n"
            "hpaio:/net/officejet?ip=10.0.2.30|HP|OfficeJet 8010|all-in-one\n")
    devs = sane.parse_devices(text)
    assert [d.name for d in devs] == ["EPSON Perfection V39", "HP OfficeJet 8010"]
    assert all(d.backend == "sane" for d in devs)


def test_sane_choose_settings():
    args = sane.choose_settings(sane.parse_options(SANE_A))
    assert args == ["--resolution", "300", "--mode", "24bit Color", "--source", "Flatbed"]
    with pytest.raises(ScanError, match="couleur"):
        sane.choose_settings(sane.parse_options("    --mode Lineart|Gray [Gray]\n"))
    with pytest.raises(ScanError, match="300 DPI"):
        sane.choose_settings(sane.parse_options("    --resolution 75|150|600dpi [150]\n"))
    rng = sane.parse_options("    --resolution 1..1200dpi (in steps of 1) [50]\n")
    assert rng["resolution_ranges"] == [(1, 1200)] and sane.choose_settings(rng)[:2] == ["--resolution", "300"]


@pytest.mark.skipif(not sane.available(), reason="scanimage (SANE) non installe")
def test_real_sane_scan_with_test_device(tmp_path):
    """VRAI scan par le pilote SANE (peripherique de test fourni par SANE)."""
    try:
        subprocess.run(["scanimage", "-d", "test", "-A"], capture_output=True, timeout=30, check=True)
    except (subprocess.SubprocessError, OSError):
        pytest.skip("peripherique de test SANE indisponible")
    path = scan_to_file(ScannerInfo("SANE test", "sane", "test"), tmp_path, lambda s, p: None)
    doc = load_document(path, assumed_dpi=300)
    h, w, c = doc.pages[0].shape
    assert c == 3 and w > 900 and h > 1100              # couleur, ~80 x 100 mm a 300 DPI


def test_wia_not_available_off_windows(tmp_path):
    from authentik.scan import wia
    import sys
    if sys.platform != "win32":
        assert not wia.available() and wia.list_devices() == []
        with pytest.raises(ScanError, match="Windows"):
            wia.scan("x", tmp_path)
