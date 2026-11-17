from synth import make_seal, paste_copy, render

from authentik.analyzers.copy import align_and_compare, copy_signal
from authentik.determinism import init_determinism


def test_copy_vs_restamp_separate():
    init_determinism()
    seal = make_seal()
    for seed in range(1, 6):
        original = render(seal, seed)
        copy = paste_copy(original)
        restamp = render(seal, seed + 100, jitter=True)
        ci, cr = align_and_compare(copy, original)
        ri, rr = align_and_compare(restamp, original)
        assert ci >= 30 and cr < 0.5, (seed, ci, cr)     # copie numerique
        assert rr > 0.8, (seed, ri, rr)                  # tampon reapose


def test_copy_signal_rules():
    init_determinism()
    seal = make_seal()
    original = render(seal, 1)
    assert copy_signal(original, []) is None                       # rien a comparer : ligne masquee
    s = copy_signal(paste_copy(original), [("doc-1", original)])
    assert s.risk == 1.0 and s.evidence["copy_of"]["document"] == "doc-1"
    s = copy_signal(render(seal, 101, jitter=True), [("doc-1", original)])
    assert s.risk == 0.0
