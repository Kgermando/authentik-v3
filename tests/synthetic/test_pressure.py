import numpy as np
from synth import make_seal, photocopy, render, softened

from authentik.analyzers.pressure import build_pressure_profile, pressure_features, pressure_signal


def _original(seal, seed):
    return softened(render(seal, seed))


def _reproduction(seal, seed):
    return photocopy(render(seal, seed), seed=seed)


def test_features_separate_cases():
    seal = make_seal()
    o = [pressure_features(_original(seal, s)) for s in range(1, 6)]
    r = [pressure_features(_reproduction(seal, s)) for s in range(1, 6)]
    for k in ("pressure_gradient", "ink_range"):
        assert np.mean([f[k] for f in o]) > 1.5 * np.mean([f[k] for f in r]), k


def test_too_small_ink_returns_none():
    blank = np.full((300, 300), 240, np.uint8)
    assert pressure_features(blank) is None            # ligne masquee
    assert pressure_signal(blank, {}) is None


def test_signal_flags_reproductions_not_originals():
    seal = make_seal()
    profile = build_pressure_profile(
        [pressure_features(_original(seal, s)) for s in range(1, 21)])
    orig_risk = [pressure_signal(_original(seal, s), profile).risk for s in range(21, 41)]
    repr_risk = [pressure_signal(_reproduction(seal, s), profile).risk for s in range(21, 41)]
    assert np.mean(orig_risk) <= 0.1      # tres peu de vrais tampons signales
    assert np.mean(repr_risk) >= 0.9      # presque toutes les reproductions signalees
