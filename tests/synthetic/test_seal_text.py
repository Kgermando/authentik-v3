"""Texte circulaire du sceau. OCR reel si Tesseract (fra) est installe, sinon test saute."""
import pytest
from synth_seal_text import circular_seal

from authentik.analyzers.seal_text import best_match, normalize, seal_text_signal, text_risk
from authentik.ingest.year import configure_tesseract

TEXT = "MINISTERE DE LA FORMATION PROFESSIONNELLE"


def test_matching_and_risk_without_ocr():
    assert normalize("Ministère de la Formation") == "MINISTEREDELAFORMATION"
    assert best_match(TEXT, "TION PROFESSIONNELLE MINISTERE DE LA FORMATION PROFESSIONNELLE") == 1.0
    assert text_risk(1.0) == 0.0 and text_risk(0.85) == 0.0
    assert text_risk(0.5) == 1.0 and 0.4 < text_risk(0.7) < 0.5
    s = seal_text_signal(circular_seal(TEXT), (300, 300, 300), TEXT, ocr=lambda img: TEXT)
    assert s.risk == 0.0
    assert seal_text_signal(circular_seal(TEXT), (300, 300, 300), None) is None      # rien d'attendu
    assert seal_text_signal(circular_seal(TEXT), (300, 300, 300), TEXT,
                            ocr=lambda img: 1 / 0) is None                          # OCR en panne


@pytest.mark.skipif(not configure_tesseract(), reason="Tesseract (fra) non installe")
def test_real_ocr_reads_circular_text_and_flags_wrong_text():
    img = circular_seal(TEXT)
    good = seal_text_signal(img, (300, 300, 300), TEXT)
    assert good.risk == 0.0 and good.evidence["similarity"] >= 0.9
    bad = seal_text_signal(img, (300, 300, 300), "MINISTERE DE LA SANTE PUBLIQUE KINSHASA")
    assert bad.risk >= 0.9                                                          # autre ministere
    other_start = seal_text_signal(circular_seal(TEXT, start_deg=20), (300, 300, 300), TEXT)
    assert other_start.risk == 0.0                                                  # debut du texte quelconque
