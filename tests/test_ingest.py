from datetime import date

import numpy as np
import pymupdf
import pytest
from PIL import Image

from authentik.ingest import IngestError, find_year, load_document

TODAY = date(2026, 11, 17)


def _color_page(h=120, w=90):
    img = np.zeros((h, w, 3), np.uint8)
    img[..., 0] = 10    # B
    img[..., 1] = 100   # G
    img[..., 2] = 200   # R
    return img


def test_png_loaded_as_bgr_with_dpi(tmp_path):
    p = tmp_path / "scan.png"
    Image.fromarray(_color_page()[..., ::-1]).save(p, dpi=(300, 300))
    d = load_document(p)
    assert d.kind == "image" and len(d.pages) == 1
    assert d.pages[0].shape == (120, 90, 3)
    assert tuple(d.pages[0][0, 0]) == (10, 100, 200)          # ordre BGR conserve
    assert d.dpi == [pytest.approx(300, abs=0.5)] and d.warnings == []


def test_wrong_dpi_and_jpeg_warn(tmp_path):
    p = tmp_path / "scan.jpg"
    Image.fromarray(_color_page()).save(p, dpi=(150, 150), quality=95)
    w = load_document(p).warnings
    assert any("150 DPI" in m for m in w) and any("JPEG" in m for m in w)


def test_multipage_tiff(tmp_path):
    p = tmp_path / "scan.tiff"
    frames = [Image.fromarray(_color_page()), Image.fromarray(_color_page(60, 40))]
    frames[0].save(p, save_all=True, append_images=frames[1:], dpi=(300, 300))
    d = load_document(p)
    assert [pg.shape[:2] for pg in d.pages] == [(120, 90), (60, 40)]


def test_pdf_rasterized_at_300_dpi_in_color(tmp_path):
    p = tmp_path / "cert.pdf"
    pdf = pymupdf.open()
    page = pdf.new_page(width=72, height=144)                   # 1 x 2 pouces
    page.draw_rect(page.rect, color=(1, 0, 0), fill=(1, 0, 0))  # rouge
    pdf.save(p)
    d = load_document(p)
    assert d.kind == "pdf" and d.pages[0].shape == (600, 300, 3)
    b, g, r = d.pages[0][300, 150]
    assert r > 200 and g < 50 and b < 50


def test_pdf_same_pixels_twice(tmp_path):
    p = tmp_path / "cert.pdf"
    pdf = pymupdf.open()
    pdf.new_page(width=200, height=200).insert_text((20, 100), "Certificat 12/03/2019")
    pdf.save(p)
    assert np.array_equal(load_document(p).pages[0], load_document(p).pages[0])


def test_rejects_bad_files(tmp_path):
    with pytest.raises(IngestError, match="introuvable"):
        load_document(tmp_path / "absent.pdf")
    (tmp_path / "a.docx").write_bytes(b"x")
    with pytest.raises(IngestError, match="non pris en charge"):
        load_document(tmp_path / "a.docx")
    (tmp_path / "b.pdf").write_bytes(b"pas un pdf")
    with pytest.raises(IngestError):
        load_document(tmp_path / "b.pdf")
    (tmp_path / "c.png").write_bytes(b"pas une image")
    with pytest.raises(IngestError, match="illisible"):
        load_document(tmp_path / "c.png")


@pytest.mark.parametrize("text, year", [
    ("Fait a Kinshasa, le 12/03/2019", 2019),
    ("Fait a Kinshasa, le 1er mars 2018", 2018),
    ("delivre le 5 Décembre 2021", 2021),
    ("Annee academique : 2017\nFait le 02-07-2018", 2018),      # date complete prioritaire
    ("Annee academique : 2017", 2017),
    ("Naissance 14/05/1990 ... fait le 20/06/2015", 2015),      # date de delivrance (la plus recente)
])
def test_find_year(text, year):
    assert find_year(text, TODAY).year == year


def test_find_year_rejects_implausible_and_flags_bare():
    assert find_year("Arrete n 2045 du ministere", TODAY).year is None   # futur : ignore
    assert find_year("reference 1234-5678", TODAY).year is None
    r = find_year("Certificat 2016", TODAY)
    assert r.year == 2016 and "vérifier" in r.message
    assert find_year("", TODAY).message
