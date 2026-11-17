"""Stockage SQLite, configuration et documents. Bibliotheque standard uniquement."""
import sqlite3
from dataclasses import dataclass, field

import pytest

from authentik.store import (AnalysisRecord, Database, load_config, save_config,
                             sha256_of, store_document, verify_document)
from authentik.store.db import to_signed64, to_unsigned64
from authentik.store.documents import DocumentAltered


@dataclass
class Sig:                       # meme forme que analyzers.base.Signal
    risk: float
    confidence: float
    evidence: dict = field(default_factory=dict)


def _rec(key="k1", sha="a" * 64, verdict="conforme"):
    return AnalysisRecord(key, sha, "cert.pdf", "/docs/2019/x.pdf", 2019, 0.12, verdict,
                          "0.1.0", {"summary": "ok", "hidden": {"aging": "moins de 30"}})


def test_schema_created_and_reopen_is_noop(tmp_path):
    from authentik.store.migrations import MIGRATIONS
    db = Database(tmp_path / "a.db")
    assert db.schema_version() == len(MIGRATIONS)
    assert Database(tmp_path / "a.db").schema_version() == len(MIGRATIONS)


def test_upgrade_from_v1_keeps_results(tmp_path):
    """Une base creee par la version precedente est migree sans perte."""
    from authentik.store.migrations import MIGRATIONS, _split
    conn = sqlite3.connect(tmp_path / "old.db", isolation_level=None)
    for stmt in _split(MIGRATIONS[0]):
        conn.execute(stmt)
    conn.execute("PRAGMA user_version = 1")
    conn.execute("INSERT INTO analyses (analysis_key, file_sha256, file_name, stored_path, score,"
                 " verdict, software_version, result_json, created_at) VALUES"
                 " ('k', 's', 'f', 'p', 0.1, 'conforme', '0.1.0', '{}', 'now')")
    conn.close()
    db = Database(tmp_path / "old.db")
    assert db.schema_version() == len(MIGRATIONS) and db.find_analysis("k")["verdict"] == "conforme"


def test_reference_documents_and_specimens(tmp_path):
    db = Database(tmp_path / "a.db")
    sp = [{"kind": "seal", "image_path": "s.png", "expected_text": "MINISTERE",
           "features": {"pressure_gradient": 0.03}},
          {"kind": "signature", "image_path": "g.png"}]
    db.add_reference(2019, "sha1", "/d/1.pdf", "Directeur", {"paper_L": 200.0}, sp)
    db.add_reference(2019, "sha2", "/d/2.pdf", "Directeur", None, sp[:1])   # sans mesures
    with pytest.raises(ValueError, match="déjà"):
        db.add_reference(2019, "sha1", "/d/1.pdf", "Directeur", {}, [])
    assert db.count_reference_docs(2019) == 1                    # seules les mesures valides
    assert db.reference_summary() == [{"year": 2019, "documents": 2, "with_measures": 1,
                                       "seals": 2, "signatures": 1}]
    seal = db.specimens("seal")[0]
    assert seal["expected_text"] == "MINISTERE" and seal["features"] == {"pressure_gradient": 0.03}
    assert db.remove_reference("sha1") == 1
    assert db.reference_summary()[0]["documents"] == 1 and len(db.specimens("signature")) == 0


def test_reviewed_analyses_uses_last_decision(tmp_path):
    db = Database(tmp_path / "a.db")
    aid, _ = db.save_analysis(_rec(), {"aging": Sig(0.1, 1.0)})
    db.save_analysis(_rec("k2"), {})
    db.add_review(aid, "Agent A", "authentique")
    db.add_review(aid, "Agent B", "faux", "sceau colle")
    rows = db.reviewed_analyses()
    assert len(rows) == 1 and rows[0]["decision"] == "faux" and "aging" in rows[0]["signals"]


def test_save_find_and_idempotent(tmp_path):
    db = Database(tmp_path / "a.db")
    assert db.find_analysis("k1") is None
    sigs = {"seal_copy": Sig(0.0, 0.8, {"closest": None}), "aging": None}
    aid, created = db.save_analysis(_rec(), sigs, [("seal", 2**63 + 5, "crops/s.png")])
    assert created
    again, created2 = db.save_analysis(_rec(), sigs)
    assert (again, created2) == (aid, False)                   # aucun doublon
    got = db.find_analysis("k1")
    assert got["verdict"] == "conforme" and got["result"]["hidden"]["aging"] == "moins de 30"
    assert list(got["signals"]) == ["seal_copy"]               # signal masque non enregistre
    assert got["signals"]["seal_copy"]["evidence"] == {"closest": None}


def test_results_are_append_only(tmp_path):
    db = Database(tmp_path / "a.db")
    aid, _ = db.save_analysis(_rec(), {"aging": Sig(0.1, 1.0)})
    conn = sqlite3.connect(tmp_path / "a.db")
    for sql in ("UPDATE analyses SET verdict = 'suspect'", "DELETE FROM analyses",
                "UPDATE signals SET risk = 1", "DELETE FROM signals"):
        with pytest.raises(sqlite3.DatabaseError):
            conn.execute(sql)
    conn.close()
    db.add_review(aid, "Agent A", "authentique", "verifie au registre papier")
    got = db.find_analysis("k1")
    assert got["verdict"] == "conforme"                        # resultat machine intact
    assert got["reviews"][0]["decision"] == "authentique"
    with pytest.raises(ValueError):
        db.add_review(aid, "Agent A", "peut-etre")


def test_failed_transaction_leaves_nothing(tmp_path):
    db = Database(tmp_path / "a.db")
    with pytest.raises(ValueError):                            # NaN refuse dans le JSON
        db.save_analysis(_rec(), {"aging": Sig(0.1, 1.0, {"z": float("nan")})})
    assert db.find_analysis("k1") is None


def test_new_version_adds_row_and_history(tmp_path):
    db = Database(tmp_path / "a.db")
    db.save_analysis(_rec("k1"), {})
    db.save_analysis(_rec("k2", verdict="a_verifier"), {})     # logiciel ou profil change
    hist = db.analyses_for_file("a" * 64)
    assert [h["analysis_key"] for h in hist] == ["k1", "k2"]


def test_fingerprints_fixed_order_and_exclude_same_file(tmp_path):
    db = Database(tmp_path / "a.db")
    db.save_analysis(_rec("k1", "a" * 64), {}, [("seal", 1, "c1.png"), ("signature", 2, "c2.png")])
    db.save_analysis(_rec("k2", "b" * 64), {}, [("seal", 2**64 - 1, "c3.png")])
    seals = db.known_fingerprints("seal")
    assert [s["crop_path"] for s in seals] == ["c1.png", "c3.png"]
    assert seals[1]["phash"] == 2**64 - 1                      # 64 bits restitues
    assert [s["crop_path"] for s in db.known_fingerprints("seal", "b" * 64)] == ["c1.png"]


def test_phash_conversion():
    for u in (0, 1, 2**63 - 1, 2**63, 2**64 - 1):
        assert to_unsigned64(to_signed64(u)) == u
    with pytest.raises(ValueError):
        to_signed64(2**64)


def test_reference_docs_profiles_and_version(tmp_path):
    db = Database(tmp_path / "a.db")
    for i in range(3):
        db.add_reference_doc(2019, {"paper_L": 200 + i})
    assert db.count_reference_docs(2019) == 3 and db.count_reference_docs(2020) == 0
    assert [m["paper_L"] for m in db.reference_measures(2019)] == [200, 201, 202]
    v0 = db.profile_version()
    db.set_year_profile(2019, {"paper_L": (201.0, 1.0, 3)})
    v1 = db.profile_version()
    assert v1 != v0 and db.year_profile(2019) == {"paper_L": (201.0, 1.0, 3)}
    db.set_year_profile(2019, {"paper_L": (201.0, 1.0, 3)})
    assert db.profile_version() == v1                          # meme profil => meme version


def test_specimens_fixed_order(tmp_path):
    db = Database(tmp_path / "a.db")
    db.add_specimen("seal", "Directeur", 2019, "s2.png", b"\x00" * 1024)
    db.add_specimen("seal", "Directeur", 2020, "s1.png")
    assert [s["image_path"] for s in db.specimens("seal")] == ["s2.png", "s1.png"]
    assert len(db.specimens("seal", 2019)[0]["embedding"]) == 1024


def test_store_document_copies_without_modifying(tmp_path):
    src = tmp_path / "Scan Original.PDF"
    src.write_bytes(b"%PDF-1.4 contenu")
    before = sha256_of(src)
    sha, dest = store_document(src, tmp_path / "docs", 2019)
    assert sha == before and dest == tmp_path / "docs" / "2019" / f"{sha}.pdf"
    assert src.read_bytes() == b"%PDF-1.4 contenu"             # original intact
    assert store_document(src, tmp_path / "docs", 2019) == (sha, dest)   # idempotent
    assert verify_document(dest, sha)
    dest.write_bytes(b"falsifie")
    assert not verify_document(dest, sha)                      # alerte d'integrite
    with pytest.raises(DocumentAltered):                       # copie alteree jamais ecrasee
        store_document(src, tmp_path / "docs", 2019)
    assert dest.read_bytes() == b"falsifie"                    # conservee comme preuve
    _, d2 = store_document(src, tmp_path / "docs", None)
    assert d2.parent.name == "annee_inconnue"


def test_config_created_read_and_invalid(tmp_path):
    ini = tmp_path / "cfg" / "authentik.ini"
    cfg = load_config(ini)
    assert ini.exists() and cfg.warning is None and cfg.database.name == "authentik.db"
    save_config(type(cfg)(tmp_path / "x.db", tmp_path / "docs", ini))
    cfg2 = load_config(ini)
    assert cfg2.database == tmp_path / "x.db" and cfg2.crops_dir == tmp_path / "docs" / "crops"
    ini.write_text("[storage\nnimporte quoi", encoding="utf-8")
    bad = load_config(ini)
    assert bad.warning and "invalide" in bad.warning           # demarre quand meme
    ini.write_text("[storage]\ndatabase = \n", encoding="utf-8")
    assert load_config(ini).database.name == "authentik.db"    # valeur vide => defaut
