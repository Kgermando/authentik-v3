import numpy as np
import pytest
from PIL import Image

from authentik import pipeline
from authentik.store import AnalysisRecord, AppConfig, Database, sha256_of


@pytest.fixture
def env(tmp_path):
    cfg = AppConfig(tmp_path / "a.db", tmp_path / "docs", tmp_path / "authentik.ini")
    src = tmp_path / "in" / "certificat.png"
    src.parent.mkdir()
    img = np.full((200, 150, 3), 235, np.uint8)
    img[50:80, 30:120] = (40, 40, 200)
    Image.fromarray(img[..., ::-1]).save(src, dpi=(300, 300))
    return cfg, Database(cfg.database), src


def test_prepare_reads_file_and_hash(env):
    _, _, src = env
    p = pipeline.prepare(src)
    assert p.sha256 == sha256_of(src) and p.doc.pages[0].shape == (200, 150, 3)
    assert p.year_reading.year is None or p.year_reading.year >= 1960


def test_without_references_document_is_stored_and_sent_to_review(env):
    cfg, db, src = env
    steps = []
    out = pipeline.run_analysis(pipeline.prepare(src), 2019, cfg, db,
                                progress=lambda s, p: steps.append(p))
    assert out.verdict == "a_verifier"                                    # jamais « conforme » seul
    assert next(r for r in out.rows if r.name == "Sceau").word == "Introuvable"
    assert out.stored_path == cfg.documents_dir / "2019" / f"{sha256_of(src)}.png"
    assert out.stored_path.read_bytes() == src.read_bytes() and out.integrity_ok
    assert steps == sorted(steps) and steps[-1] == 100
    assert len(db.recent_analyses()) == 1                                  # resultat enregistre


def test_key_depends_on_year_profiles_and_settings(env):
    cfg, db, src = env
    p = pipeline.prepare(src)
    cfg = env[0]
    k = pipeline.make_key(p, 2019, db, cfg)
    assert k == pipeline.make_key(pipeline.prepare(src), 2019, db, cfg)     # stable
    assert k != pipeline.make_key(p, 2018, db, cfg)                         # autre annee
    db.set_year_profile(2019, {"paper_L": (200.0, 1.0, 40)})
    assert k != pipeline.make_key(p, 2019, db, cfg)                         # profil change
    k2 = pipeline.make_key(p, 2019, db, cfg)
    from authentik.decision import model_path
    model_path(cfg).parent.mkdir(parents=True, exist_ok=True)
    model_path(cfg).write_bytes(b"modele")
    assert k2 != pipeline.make_key(p, 2019, db, cfg)                        # modele de decision change


def test_saved_result_is_returned_without_recompute(env):
    cfg, db, src = env
    p = pipeline.prepare(src)
    key = pipeline.make_key(p, 2019, db, cfg)
    stored = cfg.documents_dir / "2019" / f"{p.sha256}.png"
    result = {"summary": "Copie d'un document du 12 mars",
              "rows": [{"name": "Sceau", "word": "Copie", "color": "red",
                        "reason": "copie d'un document du 12 mars"}],
              "regions": [{"row": "Sceau", "page": 0, "rect": [10, 20, 30, 40], "color": "red"}],
              "hidden": {"Vieillissement": "moins de 30 documents de reference en 2019"}}
    pipeline.store_document(src, cfg.documents_dir, 2019)
    db.save_analysis(AnalysisRecord(key, p.sha256, src.name, str(stored), 2019, 1.0, "suspect",
                                    "0.1.0", result), {})
    out = pipeline.run_analysis(p, 2019, cfg, db)
    assert out.memoized and out.verdict == "suspect" and out.score == 1.0
    assert out.rows[0].word == "Copie" and out.regions[0].rect == (10, 20, 30, 40)
    assert out.hidden["Vieillissement"].startswith("moins de 30")
    assert out.integrity_ok
    stored.write_bytes(b"altere")
    assert not pipeline.run_analysis(p, 2019, cfg, db).integrity_ok        # alerte d'integrite


def test_selfcheck_runs_without_touching_real_storage(env, monkeypatch, tmp_path):
    import io
    from authentik.selfcheck import run
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    _, _, src = env
    buf = io.StringIO()
    assert run(str(src), out=buf) == 0, buf.getvalue()
    assert "Lecture du document : 1 page(s), 150 x 200 pixels" in buf.getvalue()
    assert not (tmp_path / "data" / "authentik" / "documents").exists()   # vraie base intacte
    buf = io.StringIO()
    assert run(str(tmp_path / "absent.pdf"), out=buf) == 1 and "ÉCHEC" in buf.getvalue()
