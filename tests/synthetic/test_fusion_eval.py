import numpy as np
import pytest

from authentik.analyzers.base import Signal
from authentik.eval.metrics import recall_and_false_reject, wilson
from authentik.fusion import FEATURES, Fusion, review_threshold_from_roc


def _sig(rng, fake):
    s = {}
    for k in FEATURES:
        if k.endswith("copy"):
            s[k] = Signal(0.0, 0.8)
        else:
            s[k] = Signal(float(np.clip(rng.normal(0.7 if fake else 0.15, 0.15), 0, 1)), 0.9)
    return s


def _data(n, seed):
    rng = np.random.default_rng(seed)
    y = [i % 2 for i in range(n)]
    return [_sig(rng, bool(v)) for v in y], y


def test_copy_rule_overrides_model():
    f = Fusion()
    sig = {"seal_copy": Signal(1.0, 1.0)}
    assert f.decide(sig) == (1.0, "suspect")          # sans meme avoir entraine le modele


def test_unfitted_model_raises():
    with pytest.raises(RuntimeError):
        Fusion().decide({"aging": Signal(0.1, 1.0)})


def test_same_input_same_output_and_roundtrip(tmp_path):
    X, y = _data(200, 1)
    f = Fusion()
    f.fit(X, y)
    a = f.decide(X[3])
    assert a == f.decide(X[3])
    f.save(str(tmp_path / "f.joblib"))
    assert Fusion.load(str(tmp_path / "f.joblib")).decide(X[3]) == a


def test_threshold_and_metrics():
    X, y = _data(400, 2)
    f = Fusion()
    f.fit(X[:200], y[:200])
    p_val = [f.decide(s)[0] for s in X[200:]]
    thr = review_threshold_from_roc(y[200:], p_val)
    assert thr is not None
    verdicts = [f.decide(s)[1] for s in X[200:]]
    m = recall_and_false_reject(y[200:], verdicts)
    assert m["recall"] >= 0.9 and m["false_reject"] <= 0.1


def test_wilson_matches_documented_widths():
    lo, hi = wilson(184, 200)                         # rappel 92 % sur 200 faux
    assert abs((hi - lo) / 2 - 0.038) < 0.005
    lo, hi = wilson(46, 50)
    assert abs((hi - lo) / 2 - 0.078) < 0.01
