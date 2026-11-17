"""Entrainement de la decision a partir des verdicts d'agents (donnees de SYNTHESE)."""
import json

import numpy as np

from authentik.analyzers.base import Signal
from authentik.decision import decide, load_fusion, model_path
from authentik.fusion import FEATURES
from authentik.store import AnalysisRecord, AppConfig, Database
from authentik.training import reset_model, train_from_reviews


def _cfg(tmp_path):
    return AppConfig(tmp_path / "a.db", tmp_path / "docs", tmp_path / "a.ini")


def _fill(db, n, seed=0, sep=0.55):
    rng = np.random.default_rng(seed)
    for i in range(n):
        fake = i % 2
        sig = {k: Signal(float(np.clip(rng.normal(0.15 + sep * fake, 0.15), 0, 1)), 0.8)
               for k in FEATURES if not k.endswith("copy")}
        aid, _ = db.save_analysis(AnalysisRecord(f"k{i}", f"s{i}", "f.png", "p", 2019, 0.5,
                                                 "a_verifier", "0.1.0", {}), sig)
        db.add_review(aid, "Agent", "faux" if fake else "authentique")


def test_not_enough_examples(tmp_path):
    cfg, db = _cfg(tmp_path), Database(tmp_path / "a.db")
    _fill(db, 8)
    r = train_from_reviews(cfg, db)
    assert not r.trained and "Pas assez" in r.message and not model_path(cfg).exists()


def test_train_save_load_and_decide(tmp_path):
    cfg, db = _cfg(tmp_path), Database(tmp_path / "a.db")
    _fill(db, 80)
    r = train_from_reviews(cfg, db)
    assert r.trained and r.cv_recall >= 0.9 and r.review_threshold is not None
    info = json.loads(model_path(cfg).with_suffix(".json").read_text(encoding="utf-8"))
    assert info["n_fake"] == 40 and "trained_at" in info
    f = load_fusion(cfg)
    clean = {k: Signal(0.05, 0.8) for k in FEATURES if not k.endswith("copy")}
    bad = {k: Signal(0.9, 0.8) for k in FEATURES if not k.endswith("copy")}
    assert decide(clean, f).verdict == "conforme" and decide(clean, f).calibrated
    assert decide(bad, f).verdict == "suspect"
    assert decide({"seal_copy": Signal(1.0, 1.0)}, f).verdict == "suspect"   # regle dure conservee
    assert train_from_reviews(cfg, db).review_threshold == r.review_threshold  # deterministe
    reset_model(cfg)
    assert load_fusion(cfg) is None and decide(clean, None).verdict == "a_verifier"


def test_unreachable_objective_keeps_provisional_threshold(tmp_path):
    cfg, db = _cfg(tmp_path), Database(tmp_path / "a.db")
    _fill(db, 60, sep=0.0)                                   # signaux sans pouvoir separateur
    r = train_from_reviews(cfg, db)
    assert r.trained and "hors de portée" in r.message


def test_indetermine_reviews_ignored(tmp_path):
    cfg, db = _cfg(tmp_path), Database(tmp_path / "a.db")
    aid, _ = db.save_analysis(AnalysisRecord("x", "x", "f", "p", 2019, 0.5, "a_verifier", "0.1.0", {}), {})
    db.add_review(aid, "Agent", "indetermine")
    r = train_from_reviews(cfg, db)
    assert (r.n_fake, r.n_genuine) == (0, 0)


def test_reduced_reliability_aging_never_suspect_alone():
    weak = {"aging": Signal(1.0, 0.05, {"reduced_reliability": True, "flagged": ["paper_L"]})}
    assert decide(weak, None).verdict == "a_verifier"
    full = {"aging": Signal(1.0, 0.5, {"reduced_reliability": False, "flagged": ["paper_L"]})}
    assert decide(full, None).verdict == "suspect"
