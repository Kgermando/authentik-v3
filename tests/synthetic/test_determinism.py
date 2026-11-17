"""Meme document => meme resultat, toujours."""
import cv2
import numpy as np
from synth import make_seal, paste_copy, render, softened

from authentik import __version__
from authentik.analyzers.copy import align_and_compare
from authentik.analyzers.pressure import pressure_features
from authentik.determinism import analysis_key, file_sha256, init_determinism, round_score


def test_copy_analysis_repeatable_even_if_rng_state_changes():
    init_determinism()
    seal = make_seal()
    o = render(seal, 3)
    c = paste_copy(o)
    ref = align_and_compare(c, o)
    for junk in range(10):
        cv2.setRNGSeed(junk * 7919)            # on perturbe l'etat aleatoire d'OpenCV
        np.random.seed(junk)
        assert align_and_compare(c, o) == ref  # identique au bit pres


def test_pressure_repeatable():
    g = softened(render(make_seal(), 4))
    a = pressure_features(g)
    for _ in range(5):
        assert pressure_features(g) == a


def test_rounding_and_keys(tmp_path):
    assert round_score(0.123456789) == 0.1235
    f = tmp_path / "doc.bin"
    f.write_bytes(b"abc")
    sha = file_sha256(f)
    k1 = analysis_key(sha, __version__, {"emb": "h1"}, "p1", {"a": 1})
    assert k1 == analysis_key(sha, __version__, {"emb": "h1"}, "p1", {"a": 1})
    assert k1 != analysis_key(sha, __version__, {"emb": "h2"}, "p1", {"a": 1})   # modele change
    assert k1 != analysis_key(sha, __version__, {"emb": "h1"}, "p2", {"a": 1})   # profils changes
