"""Interface : test sans ecran (QT_QPA_PLATFORM=offscreen). Verifie l'enchainement des pages."""
import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np                                   # noqa: E402
import pytest                                        # noqa: E402
from PIL import Image                                # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel  # noqa: E402

from authentik import pipeline                       # noqa: E402
from authentik.app.dialogs import details_html       # noqa: E402
from authentik.app.main_window import MainWindow     # noqa: E402
from authentik.app.pages import RowWidget            # noqa: E402
from authentik.store import AppConfig                # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _wait(app, cond, timeout=20.0):
    end = time.monotonic() + timeout
    while not cond():
        if time.monotonic() > end:
            raise AssertionError("delai depasse")
        app.processEvents()
        time.sleep(0.01)


@pytest.fixture
def win(app, tmp_path):
    cfg = AppConfig(tmp_path / "a.db", tmp_path / "docs", tmp_path / "authentik.ini")
    w = MainWindow(cfg)
    yield w
    w.close()


@pytest.fixture
def png(tmp_path):
    p = tmp_path / "certificat.png"
    Image.fromarray(np.full((300, 200, 3), 230, np.uint8)).save(p, dpi=(300, 300))
    return p


def test_import_prepare_analyse_results(app, win, png):
    assert win.stack.currentWidget() is win.home and win.db is not None
    win.load_path(png)                                         # fil d'arriere-plan
    _wait(app, lambda: win.stack.currentWidget() is win.prep)
    assert win.prep.view.scene().items()                       # image affichee
    win.prep.year.setValue(2019)
    assert win.prep.analyse_btn.isEnabled()
    win.prep.analyse_btn.click()
    _wait(app, lambda: win.stack.currentWidget() is win.results)
    assert win.results.verdict.text().startswith("À vérifier")   # page sans sceau : introuvable
    assert win.outcome.stored_path.exists() and win.outcome.details["analysis_id"]
    html = details_html(win.outcome)
    assert "Indications masquées" in html and win.outcome.prepared.sha256 in html


def test_year_required_before_analyse(app, win, png):
    win._prepared(pipeline.prepare(png))
    win.prep.year.setValue(win.prep.NO_YEAR)
    assert not win.prep.analyse_btn.isEnabled()


def test_results_rows_regions_and_highlight(app, win, png):
    p = pipeline.prepare(png)
    out = pipeline.Outcome(
        prepared=p, year=2019, stored_path=png, analysis_key="k", verdict="suspect", score=0.82,
        summary="Sceau copie d'un autre document.",
        rows=[pipeline.RowResult("Sceau", "Copie", "red", "copie d'un document du 12 mars"),
              pipeline.RowResult("Signature", "Conforme", "green")],
        hidden={"Vieillissement": "moins de 30 documents de reference en 2019"},
        regions=[pipeline.Region("Sceau", 0, (10, 10, 50, 50), "red")])
    win._analysed(out)
    assert win.results.verdict.text() == "Suspect — 82 %"
    rows = win.results.findChildren(RowWidget)
    assert [r.name for r in rows] == ["Sceau", "Signature"]    # ligne masquee absente
    assert win.results.view.has_boxes("Sceau")
    rows[0].clicked.emit("Sceau")                              # clic : cadre mis en evidence
    box = win.results.view._boxes["Sceau"][0]
    assert box.pen().width() == 14
    texts = [lab.text() for lab in win.results.findChildren(QLabel)]
    assert "copie d'un document du 12 mars" in texts


def test_errors_are_shown_not_crashing(app, win, tmp_path, monkeypatch):
    shown = []
    monkeypatch.setattr("authentik.app.main_window.QMessageBox.warning",
                        lambda *a: shown.append(a[2]))
    bad = tmp_path / "x.pdf"
    bad.write_bytes(b"pas un pdf")
    win.load_path(bad)
    _wait(app, lambda: shown)
    assert "PDF illisible" in shown[0] and win.stack.currentWidget() is win.home


def test_scan_page_other_network_remember_and_reload(app, win, monkeypatch):
    from authentik.app import main_window as mw
    from authentik.scan import ScannerInfo
    from authentik.store import load_config
    site_b = ScannerInfo("HP Site B", "escl", "http://10.20.0.15:8080/escl", "", "ajouté par adresse")
    monkeypatch.setattr(mw, "find_scanners", lambda saved, **k: [])
    monkeypatch.setattr(mw, "probe", lambda text: site_b if text == "10.20.0.15" else None)
    win.open_scan()
    _wait(app, lambda: win.scan.search_btn.isEnabled())
    assert win.scan.list.count() == 0 and "autre" in win.scan.status.text()
    win.scan.manual.setText("10.20.0.15")
    win.scan.add_btn.click()
    _wait(app, lambda: win.scan.list.count() == 1)
    assert win.scan.current().address == site_b.address and win.scan.remember_btn.isEnabled()
    win.scan.remember_btn.click()
    assert load_config(win.cfg.ini_path).scanners == (("HP Site B", site_b.address),)
    assert win.scan.current().origin == "enregistré" and win.scan.forget_btn.isEnabled()
    win.scan.manual.setText("10.20.0.99")
    win.scan.add_btn.click()
    _wait(app, lambda: "Aucun scanner" in win.scan.status.text())
    assert win.scan.list.count() == 1                       # la liste existante est conservee
    win.scan.forget_btn.click()
    assert load_config(win.cfg.ini_path).scanners == () and win.scan.list.count() == 0


def test_scan_page_rejects_public_range(app, win, monkeypatch):
    from authentik.app import main_window as mw
    monkeypatch.setattr(mw, "find_scanners", lambda saved, **k: [])
    win.open_scan()
    _wait(app, lambda: win.scan.search_btn.isEnabled())
    win.scan.manual.setText("8.8.8.0/24")
    win.scan.add_btn.click()
    _wait(app, lambda: "privées" in win.scan.status.text())


def test_real_sane_scan_reaches_preview(app, win, monkeypatch):
    """De bout en bout : choix d'un scanner pilote -> VRAI scan SANE -> apercu."""
    from authentik.scan import ScannerInfo, sane
    if not sane.available():
        pytest.skip("scanimage (SANE) non installe")
    win.start_scan(ScannerInfo("SANE test", "sane", "test", "", "pilote"))
    _wait(app, lambda: win.stack.currentWidget() is win.prep, timeout=120)
    assert win.prepared.from_scan and win.prepared.doc.dpi == [pytest.approx(300, abs=0.5)]
    assert not any("résolution" in w for w in win.prepared.doc.warnings)
    assert win.prepared.doc.pages[0].shape[2] == 3


# -- references, decision de l'agent, « En savoir plus » -----------------------------------------
def _synthetic_png(tmp_path, name, img):
    p = tmp_path / name
    Image.fromarray(img[..., ::-1]).save(p, dpi=(300, 300))
    return p


def test_references_dialog_add_and_remove(app, win, tmp_path, monkeypatch):
    import sys
    sys.path.insert(0, "tests/synthetic")
    from synth_doc import certificate
    from authentik.app import references_dialog as rd
    files = [str(_synthetic_png(tmp_path, f"ref{s}.png", certificate(s))) for s in (1, 2)]
    monkeypatch.setattr(rd.QFileDialog, "getOpenFileNames", lambda *a, **k: (files, ""))
    monkeypatch.setattr(rd.AddReferencesDialog, "exec", lambda self: (self.year.setValue(2019),
                                                                      self.owner.setText("Directeur"), 1)[2])
    shown = []
    monkeypatch.setattr(rd.QMessageBox, "information", lambda *a: shown.append(a[2]))
    monkeypatch.setattr(rd.QMessageBox, "question", lambda *a: rd.QMessageBox.Yes)
    assert "Aucun document de référence" in win.home.ref_status.text()
    dlg = rd.ReferencesDialog(win)
    dlg.add_btn.click()
    _wait(app, lambda: shown, timeout=120)
    assert "2/2 document(s) ajouté(s)" in shown[0] and "sceau, signature" in shown[0]
    assert dlg.years.rowCount() == 1 and dlg.years.item(0, 1).text() == "2"
    assert dlg.years.item(0, 4).text() == f"2/{rd.SETTINGS.aging_min_docs_per_year} documents"
    assert dlg.docs.item(0, 2).text() == "Directeur" and "provisoire" in dlg.status.text()
    assert {dlg.docs.item(i, 1).text() for i in range(2)} == {"ref1.png", "ref2.png"}   # nom d origine
    dlg.docs.selectRow(0)
    dlg.remove_btn.click()
    assert dlg.docs.rowCount() == 1
    win._update_home()
    assert "1 document(s) de référence" in win.home.ref_status.text()


def test_agent_review_recorded(app, win, png, monkeypatch):
    from authentik.app import main_window as mw
    answers = iter([("Agent Kabila", True), ("vérifié au registre", True)])
    monkeypatch.setattr(mw.QInputDialog, "getText", lambda *a, **k: next(answers))
    win.load_path(png)
    _wait(app, lambda: win.stack.currentWidget() is win.prep)
    win.prep.year.setValue(2019)
    win.prep.analyse_btn.click()
    _wait(app, lambda: win.stack.currentWidget() is win.results)
    assert all(b.isEnabled() for b in win.results.review_btns.values())
    win.results.review_btns["faux"].click()
    assert "Faux" in win.results.review_label.text() and "Agent Kabila" in win.results.review_label.text()
    saved = win.db.find_analysis(win.outcome.analysis_key)
    assert saved["reviews"][0]["decision"] == "faux" and saved["verdict"] == win.outcome.verdict


def test_details_dialog_images_and_pdf(app, win, tmp_path, monkeypatch):
    import sys
    sys.path.insert(0, "tests/synthetic")
    from synth_doc import certificate
    from authentik.app import dialogs
    p = _synthetic_png(tmp_path, "doc.png", certificate(5))
    out = pipeline.run_analysis(pipeline.prepare(p), 2019, win.cfg, win.db)
    target = tmp_path / "rapport.pdf"
    monkeypatch.setattr(dialogs.QFileDialog, "getSaveFileName", lambda *a, **k: (str(target), ""))
    monkeypatch.setattr(dialogs.QMessageBox, "information", lambda *a: None)
    dlg = dialogs.DetailsDialog(out, win.cfg.crops_dir, win)
    html = dlg.findChild(dialogs.QTextBrowser).toHtml()
    assert "img://0/doc" in html and "img://0/ref" not in html   # rien a comparer : pas d'image vide
    assert "Aucun élément de comparaison" in html
    dlg.pdf_btn.click()
    assert target.read_bytes().startswith(b"%PDF")
