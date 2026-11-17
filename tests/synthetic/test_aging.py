import numpy as np

from authentik.analyzers.aging import MEASURES, aging_signal, build_profile, robust_z


def _refs(n, rng):
    base = {"paper_L": 200, "paper_b": 135, "paper_grain": 2.0,
            "text_contrast": 120, "seal_contrast": 100, "seal_text_gap": 20}
    return [{k: v + rng.normal(0, 1.5) for k, v in base.items()} for _ in range(n)]


def _profiles(refs):
    return {k: build_profile([r[k] for r in refs]) for k in MEASURES}


def test_mad_floor_catches_too_dark_seal():
    # references quasi identiques : MAD = 0 sans plancher
    p = build_profile([100.0] * 40)
    assert p[1] >= 1.0
    assert abs(robust_z(130.0, *p)) > 3.5         # sceau trop fonce : signale


def test_normal_doc_passes_abnormal_flagged():
    rng = np.random.default_rng(0)
    refs = _refs(60, rng)
    prof = _profiles(refs)
    normal = _refs(1, rng)[0]
    s = aging_signal(normal, prof, 60)
    assert s.risk <= 0.2
    bad = dict(normal, paper_L=normal["paper_L"] + 40, seal_contrast=normal["seal_contrast"] + 60)
    s = aging_signal(bad, prof, 60)
    assert s.risk >= 0.3 and "paper_L" in s.evidence["flagged"]


def test_not_enough_references_masks_row():
    rng = np.random.default_rng(0)
    refs = _refs(4, rng)
    assert aging_signal(refs[0], _profiles(refs), 4) is None          # moins de 5 : ligne masquee
    assert aging_signal(None, _profiles(refs), 60) is None


def test_active_from_5_references_with_reduced_reliability():
    """Decision de l'utilisateur : actif des 5 documents, tolerance elargie jusqu'a 30."""
    rng = np.random.default_rng(1)
    refs = _refs(5, rng)
    prof = _profiles(refs)
    normal = [aging_signal(r, prof, 5) for r in _refs(200, rng)]
    assert all(s is not None and s.evidence["reduced_reliability"] for s in normal)
    false_alarms = np.mean([s.risk > 0 for s in normal])
    assert false_alarms <= 0.05, false_alarms                         # authentiques peu signales
    bad = dict(_refs(1, rng)[0])
    bad["paper_L"] += 40                                              # papier nettement anormal
    s = aging_signal(bad, prof, 5)
    assert "paper_L" in s.evidence["flagged"] and s.evidence["z_limit"] > 3.5


def test_full_reliability_from_30_references():
    rng = np.random.default_rng(2)
    refs = _refs(30, rng)
    s = aging_signal(_refs(1, rng)[0], _profiles(refs), 30)
    assert not s.evidence["reduced_reliability"] and s.evidence["z_limit"] == 3.5
