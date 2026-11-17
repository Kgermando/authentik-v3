"""Scenario complet sur certificats de SYNTHESE : references -> analyse -> verdict.
Ne prouve rien sur de vrais documents (AGENTS.md 0)."""
from pathlib import Path

import numpy as np
import pytest
from PIL import Image
from synth_doc import SEAL_POS, certificate, crop, paste, reproduced_seal_gray

from authentik import pipeline
from authentik.analysis import page_facts
from authentik.extract import find_regions
from authentik.references import add_reference_documents, remove_reference_document
from authentik.store import AppConfig, Database


def _save(img, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(img[..., ::-1]).save(path, dpi=(300, 300))
    return path


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    t = tmp_path_factory.mktemp("e2e")
    cfg = AppConfig(t / "a.db", t / "docs", t / "a.ini")
    db = Database(cfg.database)
    refs = [_save(certificate(s), t / "refs" / f"ref_{s}.png") for s in range(1, 7)]
    reports = add_reference_documents(refs, 2019, "Directeur", None, cfg, db)
    return t, cfg, db, reports


def _analyse(world, img, name):
    t, cfg, db, _ = world
    return pipeline.run_analysis(pipeline.prepare(_save(img, t / "in" / name)), 2019, cfg, db)


def test_extraction_finds_seal_and_signature():
    for seed in range(3):
        r = find_regions(certificate(seed))
        cx, cy, rad = r.seal.circle
        assert abs(cx - (SEAL_POS[0] + 250)) < 15 and abs(cy - (SEAL_POS[1] + 250)) < 15
        assert 215 <= rad <= 245
        b = r.signature.box
        assert 1350 <= b.x <= 1500 and b.w >= 400
    blank = find_regions(certificate(0, with_seal=False, with_sig=False))
    assert blank.seal is None and blank.signature is None


def test_references_registered(world):
    _, _, db, reports = world
    assert all(r.error is None and r.seal_found and r.signature_found and r.aging_measured
               for r in reports)
    assert db.reference_summary() == [{"year": 2019, "documents": 6, "with_measures": 6,
                                       "seals": 6, "signatures": 6}]
    assert set(db.year_profile(2019)) == {"paper_L", "paper_b", "paper_grain", "text_contrast",
                                          "seal_contrast", "seal_text_gap"}


def test_genuine_new_stamp_not_flagged_but_never_conforme_uncalibrated(world):
    o = _analyse(world, certificate(50), "authentique.png")
    assert o.verdict == "a_verifier" and "provisoire" in o.summary          # jamais « conforme » seul
    rows = {r.name: r for r in o.rows}
    assert rows["Sceau"].color == "green" and rows["Pression de l'encre"].color == "green"
    aging = rows["Vieillissement"]                                         # actif des 5 references
    assert aging.color == "green" and "fiabilité réduite" in aging.reason
    assert {r.row for r in o.regions} == {"Sceau", "Signature"}


def test_pasted_seal_from_reference_is_suspect(world):
    x, y = SEAL_POS
    src = certificate(1)                                                   # = reference ref_1
    fake = paste(certificate(51, with_seal=False), crop(src, x - 20, y - 20, 540, 540), x - 20, y - 20)
    o = _analyse(world, fake, "faux_colle.png")
    assert o.verdict == "suspect" and o.score == 1.0
    sceau = next(r for r in o.rows if r.name == "Sceau")
    assert sceau.word == "Copie" and "référence 2019" in sceau.reason


def test_seal_copied_from_previously_analysed_document_is_suspect(world):
    """Un sceau colle depuis un document deja ANALYSE (pas une reference) est aussi detecte."""
    x, y = SEAL_POS
    victim = certificate(60)
    _analyse(world, victim, "victime.png")
    fake = paste(certificate(61, with_seal=False), crop(victim, x - 20, y - 20, 540, 540), x - 20, y - 20)
    o = _analyse(world, fake, "faux_colle_2.png")
    sceau = next(r for r in o.rows if r.name == "Sceau")
    assert o.verdict == "suspect" and sceau.word == "Copie" and "victime.png" in sceau.reason


def test_photocopied_seal_flagged_by_pressure(world):
    o = _analyse(world, certificate(52, seal_gray=reproduced_seal_gray(52)), "faux_photocopie.png")
    rows = {r.name: r for r in o.rows}
    assert rows["Pression de l'encre"].color == "red" and o.verdict == "suspect"


def test_missing_seal_is_introuvable(world):
    o = _analyse(world, certificate(53, with_seal=False), "sans_sceau.png")
    sceau = next(r for r in o.rows if r.name == "Sceau")
    assert sceau.word == "Introuvable" and o.verdict == "a_verifier"


def test_patch_from_other_paper_flagged_by_integrity(world):
    x, y = SEAL_POS
    other = certificate(70, tone=(200, 228, 238))                          # papier jauni
    fake = paste(certificate(71, with_seal=False), crop(other, x - 30, y - 30, 560, 560), x - 30, y - 30)
    o = _analyse(world, fake, "faux_autre_papier.png")
    ev = o.details["signals"]["seal_integrity"]["evidence"]
    assert "delta_e" in ev["flagged"]
    assert next(r for r in o.rows if r.name == "Sceau").color in ("orange", "red")


def test_same_file_same_result_and_memoized(world):
    t, cfg, db, _ = world
    p = _save(certificate(80), t / "in" / "rep.png")
    a = pipeline.run_analysis(pipeline.prepare(p), 2019, cfg, db)
    b = pipeline.run_analysis(pipeline.prepare(p), 2019, cfg, db)
    assert b.memoized and (a.verdict, a.score, a.analysis_key) == (b.verdict, b.score, b.analysis_key)
    assert [r.__dict__ for r in a.rows] == [r.__dict__ for r in b.rows]


def test_recompute_identical_without_memo(world):
    """Sans memoisation, deux calculs complets donnent exactement les memes signaux."""
    from authentik.analysis import analyze_page
    _, _, db, _ = world
    page = certificate(81)
    a = analyze_page(page, 2019, db, "x")
    b = analyze_page(page, 2019, db, "x")
    sa = {k: (s.risk, s.confidence, s.evidence) for k, s in a.signals.items() if s}
    sb = {k: (s.risk, s.confidence, s.evidence) for k, s in b.signals.items() if s}
    assert sa == sb and a.rows == b.rows


def test_adding_reference_changes_key_and_removal_restores(world):
    t, cfg, db, _ = world
    p = _save(certificate(90), t / "in" / "cle.png")
    prep = pipeline.prepare(p)
    k1 = pipeline.make_key(prep, 2019, db, cfg)
    extra = add_reference_documents([_save(certificate(7), t / "refs" / "ref_7.png")],
                                    2019, "Directeur", None, cfg, db)[0]
    assert extra.error is None
    k2 = pipeline.make_key(prep, 2019, db, cfg)
    assert k1 != k2                                       # references changees => recalcul
    sha = db.reference_documents(2019)[-1]["source_sha256"]
    remove_reference_document(sha, 2019, db)
    assert db.reference_summary()[0]["documents"] == 6


def test_duplicate_reference_reported_not_added(world):
    t, cfg, db, _ = world
    rep = add_reference_documents([t / "refs" / "ref_1.png"], 2019, "Directeur", None, cfg, db)[0]
    assert rep.error and "déjà" in rep.error


def test_page_facts_deterministic():
    a, b = page_facts(certificate(5)), page_facts(certificate(5))
    for k in a.elements:
        assert a.elements[k].phash == b.elements[k].phash
        assert np.array_equal(a.elements[k].embedding, b.elements[k].embedding)
        assert a.elements[k].pressure == b.elements[k].pressure


def test_pdf_report(world, tmp_path):
    from authentik.report import evidence_images, write_report
    t, cfg, db, _ = world
    x, y = SEAL_POS
    fake = paste(certificate(95, with_seal=False), crop(certificate(2), x - 20, y - 20, 540, 540),
                 x - 20, y - 20)
    o = _analyse(world, fake, "rapport.png")
    imgs = evidence_images(o, cfg.crops_dir)
    assert imgs and imgs[0][0] == "Sceau" and imgs[0][2].startswith("COPIE de")
    assert imgs[0][3] is not None                                # image du document d'origine
    out = write_report(o, tmp_path / "r.pdf", cfg.crops_dir)
    data = out.read_bytes()
    assert data.startswith(b"%PDF") and len(data) > 20_000


def test_review_then_train_uses_real_analyses(world):
    from authentik.training import examples
    _, _, db, _ = world
    rows = db.recent_analyses()
    db.add_review(rows[0]["id"], "Agent A", "faux")
    X, y = examples(db)
    assert len(X) >= 1 and y[-1] in (0, 1) and all(isinstance(k, str) for k in X[0])


def test_evaluation_protocol_on_synthetic_dataset(world, tmp_path):
    """Protocole complet sur un PETIT jeu de synthese : verifie le mecanisme, pas la fiabilite."""
    from authentik.eval.runner import evaluate
    t, cfg, _, _ = world
    ds = tmp_path / "ds"
    lines = ["fichier;label;annee;groupe;type"]
    x, y = SEAL_POS
    for i in range(12):
        g = f"c{i:02d}"
        _save(certificate(200 + i), ds / "vrais" / f"{g}.png")
        lines.append(f"vrais/{g}.png;authentique;2019;{g};")
        if i % 2:
            src = certificate(1 + i % 6)                         # sceau d'une reference
            f = paste(certificate(300 + i, with_seal=False), crop(src, x - 20, y - 20, 540, 540), x - 20, y - 20)
            kind = "sceau_colle"
        else:
            f = certificate(300 + i, seal_gray=reproduced_seal_gray(300 + i))
            kind = "imprime_rescanne"
        _save(f, ds / "faux" / f"{g}_f.png")
        lines.append(f"faux/{g}_f.png;faux;2019;{g};{kind}")
    (ds / "labels.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")
    rep = evaluate(ds, cfg, tmp_path / "out")
    assert rep["lots"]["test"] > 0 and rep["test"]["rappel"] is not None
    assert set(rep["rappel_par_type"]) <= {"sceau_colle", "imprime_rescanne"}
    md = (tmp_path / "out" / "evaluation.md").read_text(encoding="utf-8")
    assert "Attention" in md                                   # lot < 200 : averti
    assert rep["objectif_atteint"] is None and "non établi" in md   # jamais « oui » sur un petit lot
    assert (tmp_path / "out" / "roc.csv").exists()
    assert db_untouched(cfg)


def db_untouched(cfg):
    """L'evaluation travaille sur une copie : la vraie base n'a pas recu les analyses du jeu."""
    names = {a["file_name"] for a in Database(cfg.database).recent_analyses(1000)}
    return not any(n.startswith("c0") or n.startswith("c1") for n in names)
