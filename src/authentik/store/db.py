"""Acces a la base SQLite (remplace PostgreSQL).

- Une connexion par operation : utilisable depuis le fil d'analyse (QThreadPool) et l'interface.
- Mode journal par defaut (DELETE), pas WAL : WAL ne fonctionne pas sur un dossier reseau.
- Memoisation (AGENTS.md 0 bis) : `find_analysis(analysis_key)` avant d'analyser ;
  `save_analysis` est idempotent (meme cle => rien n'est ecrit deux fois).
- Ajout seulement : analyses, signaux et revues ne sont jamais modifies (triggers SQL).
- Les listes de comparaison sont renvoyees dans un ordre fixe (ORDER BY id).
Bibliotheque standard uniquement.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator

from .migrations import migrate

DECISIONS = ("authentique", "faux", "indetermine")


def to_signed64(u: int) -> int:
    """Empreinte perceptuelle 64 bits non signee -> entier signe (SQLite INTEGER = int64 signe)."""
    if not 0 <= u < 1 << 64:
        raise ValueError(f"empreinte hors 64 bits : {u}")
    return u - (1 << 64) if u >= 1 << 63 else u


def to_unsigned64(s: int) -> int:
    return s + (1 << 64) if s < 0 else s


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _json_default(o: Any):
    if hasattr(o, "tolist"):          # tableaux et scalaires numpy
        return o.tolist()
    if isinstance(o, (set, frozenset)):
        return sorted(o)
    if isinstance(o, Path):
        return str(o)
    raise TypeError(f"Non serialisable en JSON : {type(o).__name__}")


def dumps(obj: Any) -> str:
    """JSON stable : cles triees, pas de NaN (refuse plutot que d'enregistrer une valeur invalide)."""
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, allow_nan=False,
                      default=_json_default)


@dataclass(frozen=True)
class AnalysisRecord:
    analysis_key: str
    file_sha256: str
    file_name: str
    stored_path: str
    year: int | None
    score: float
    verdict: str
    software_version: str
    result: dict


class Database:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            migrate(conn)

    # -- connexion ---------------------------------------------------------------------------
    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        try:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")
            yield conn
        finally:
            conn.close()

    @contextmanager
    def _tx(self) -> Iterator[sqlite3.Connection]:
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                yield conn
                conn.execute("COMMIT")
            except BaseException:
                conn.execute("ROLLBACK")
                raise

    # -- analyses ----------------------------------------------------------------------------
    def find_analysis(self, analysis_key: str) -> dict | None:
        """Resultat memorise pour cette cle, ou None (il faut alors analyser)."""
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM analyses WHERE analysis_key = ?",
                               (analysis_key,)).fetchone()
            return self._full(conn, row) if row else None

    def save_analysis(self, rec: AnalysisRecord, signals: dict[str, Any],
                      fingerprints: Iterable[tuple[str, int, str]] = ()) -> tuple[int, bool]:
        """Enregistre en une transaction : analyse + signaux + empreintes.

        `signals` : nom -> objet avec risk, confidence, evidence (Signal) ; None = masque, ignore.
        `fingerprints` : (kind, phash 64 bits non signe, crop_path).
        Renvoie (id, cree). Si la cle existe deja : (id existant, False), rien n'est ecrit.
        """
        if rec.verdict not in ("conforme", "a_verifier", "suspect"):
            raise ValueError(f"verdict inconnu : {rec.verdict}")
        with self._tx() as conn:
            old = conn.execute("SELECT id FROM analyses WHERE analysis_key = ?",
                               (rec.analysis_key,)).fetchone()
            if old:
                return old["id"], False
            cur = conn.execute(
                "INSERT INTO analyses (analysis_key, file_sha256, file_name, stored_path, year,"
                " score, verdict, software_version, result_json, created_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?)",
                (rec.analysis_key, rec.file_sha256, rec.file_name, rec.stored_path, rec.year,
                 float(rec.score), rec.verdict, rec.software_version, dumps(rec.result), _now()))
            aid = cur.lastrowid
            for name in sorted(signals):
                s = signals[name]
                if s is None:
                    continue
                conn.execute("INSERT INTO signals VALUES (?,?,?,?,?)",
                             (aid, name, float(s.risk), float(s.confidence), dumps(s.evidence)))
            for kind, phash, crop in fingerprints:
                conn.execute("INSERT INTO fingerprints (analysis_id, kind, phash, crop_path)"
                             " VALUES (?,?,?,?)", (aid, kind, to_signed64(int(phash)), str(crop)))
            return aid, True

    def analyses_for_file(self, file_sha256: str) -> list[dict]:
        """Historique d'un document (plusieurs lignes si le logiciel ou un profil a change)."""
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM analyses WHERE file_sha256 = ? ORDER BY id",
                                (file_sha256,)).fetchall()
            return [self._full(conn, r) for r in rows]

    def recent_analyses(self, limit: int = 100) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute("SELECT id, file_name, year, score, verdict, created_at"
                                " FROM analyses ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
            return [dict(r) for r in rows]

    @staticmethod
    def _full(conn: sqlite3.Connection, row: sqlite3.Row) -> dict:
        d = dict(row)
        d["result"] = json.loads(d.pop("result_json"))
        d["signals"] = {
            r["name"]: {"risk": r["risk"], "confidence": r["confidence"],
                        "evidence": json.loads(r["evidence"])}
            for r in conn.execute("SELECT * FROM signals WHERE analysis_id = ? ORDER BY name",
                                  (d["id"],))}
        d["reviews"] = [dict(r) for r in conn.execute(
            "SELECT reviewed_by, decision, review_note, created_at FROM reviews"
            " WHERE analysis_id = ? ORDER BY id", (d["id"],))]
        return d

    # -- revue humaine -----------------------------------------------------------------------
    def add_review(self, analysis_id: int, reviewed_by: str, decision: str,
                   note: str | None = None) -> int:
        if decision not in DECISIONS:
            raise ValueError(f"decision inconnue : {decision}")
        if not reviewed_by.strip():
            raise ValueError("nom de l'agent obligatoire")
        with self._tx() as conn:
            cur = conn.execute("INSERT INTO reviews (analysis_id, reviewed_by, decision,"
                               " review_note, created_at) VALUES (?,?,?,?,?)",
                               (analysis_id, reviewed_by.strip(), decision, note, _now()))
            return cur.lastrowid

    # -- detection de copie ------------------------------------------------------------------
    def known_fingerprints(self, kind: str, exclude_file_sha256: str | None = None) -> list[dict]:
        """Sceaux ou signatures deja vus, ORDRE FIXE (id croissant).

        Les analyses precedentes du MEME fichier sont exclues : sinon une nouvelle analyse
        (apres mise a jour du logiciel) trouverait le document « copie de lui-meme ».
        """
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT f.id, f.phash, f.crop_path, a.file_name, a.file_sha256, a.created_at"
                " FROM fingerprints f JOIN analyses a ON a.id = f.analysis_id"
                " WHERE f.kind = ? AND a.file_sha256 IS NOT ?"
                " ORDER BY f.id", (kind, exclude_file_sha256)).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["phash"] = to_unsigned64(d["phash"])
            out.append(d)
        return out

    # -- specimens et documents de reference -----------------------------------------------------
    def add_specimen(self, kind: str, owner_name: str, year: int, image_path: str,
                     embedding: bytes | None = None, expected_text: str | None = None,
                     source_sha256: str | None = None, features: dict | None = None) -> int:
        with self._tx() as conn:
            return conn.execute(
                "INSERT INTO specimens (kind, owner_name, year, image_path, embedding,"
                " expected_text, source_sha256, features) VALUES (?,?,?,?,?,?,?,?)",
                (kind, owner_name, year, image_path, embedding, expected_text, source_sha256,
                 dumps(features) if features is not None else None)).lastrowid

    def specimens(self, kind: str, year: int | None = None) -> list[dict]:
        """Ordre fixe. `embedding` : bytes float32 (numpy.frombuffer(..., '<f4') cote appelant)."""
        q, args = "SELECT * FROM specimens WHERE kind = ?", [kind]
        if year is not None:
            q, args = q + " AND year = ?", args + [year]
        with self._connect() as conn:
            rows = [dict(r) for r in conn.execute(q + " ORDER BY id", args)]
        for r in rows:
            r["features"] = json.loads(r["features"]) if r.get("features") else None
        return rows

    def add_reference(self, year: int, sha256: str, stored_path: str, owner_name: str | None,
                      measures: dict | None, specimens: list[dict], scanner: str | None = None,
                      file_name: str | None = None) -> int:
        """Document authentique de reference + ses specimens (sceau, signature), en une transaction.
        `measures` None : mesures de vieillissement indisponibles (document garde pour les specimens).
        Leve ValueError si ce document est deja enregistre."""
        with self._tx() as conn:
            if conn.execute("SELECT 1 FROM reference_docs WHERE source_sha256 = ?",
                            (sha256,)).fetchone():
                raise ValueError("Ce document est déjà enregistré comme référence.")
            rid = conn.execute(
                "INSERT INTO reference_docs (year, scanner, measures, added_at, source_sha256,"
                " stored_path, owner_name, file_name) VALUES (?,?,?,?,?,?,?,?)",
                (year, scanner, dumps(measures or {}), _now(), sha256, stored_path,
                 owner_name, file_name or Path(stored_path).name)).lastrowid
            for sp in specimens:
                conn.execute(
                    "INSERT INTO specimens (kind, owner_name, year, image_path, embedding,"
                    " expected_text, source_sha256, features) VALUES (?,?,?,?,?,?,?,?)",
                    (sp["kind"], owner_name or "", year, str(sp["image_path"]),
                     sp.get("embedding"), sp.get("expected_text"), sha256,
                     dumps(sp["features"]) if sp.get("features") is not None else None))
            return rid

    def remove_reference(self, sha256: str) -> int:
        """Retire un document de reference (ajoute par erreur) et ses specimens."""
        with self._tx() as conn:
            conn.execute("DELETE FROM specimens WHERE source_sha256 = ?", (sha256,))
            return conn.execute("DELETE FROM reference_docs WHERE source_sha256 = ?",
                                (sha256,)).rowcount

    def reference_documents(self, year: int | None = None) -> list[dict]:
        q, args = "SELECT * FROM reference_docs", []
        if year is not None:
            q, args = q + " WHERE year = ?", [year]
        with self._connect() as conn:
            rows = [dict(r) for r in conn.execute(q + " ORDER BY year, id", args)]
        for r in rows:
            r["measures"] = json.loads(r["measures"])
        return rows

    def reference_summary(self) -> list[dict]:
        """Par annee : documents de reference, mesures valides, specimens de sceau et de signature."""
        with self._connect() as conn:
            years = sorted({r[0] for r in conn.execute(
                "SELECT year FROM reference_docs UNION SELECT year FROM specimens")})
            out = []
            for y in years:
                docs = conn.execute("SELECT measures FROM reference_docs WHERE year = ?", (y,)).fetchall()
                out.append({
                    "year": y, "documents": len(docs),
                    "with_measures": sum(1 for (m,) in docs if json.loads(m)),
                    "seals": conn.execute("SELECT COUNT(*) FROM specimens WHERE year = ? AND kind = 'seal'",
                                          (y,)).fetchone()[0],
                    "signatures": conn.execute("SELECT COUNT(*) FROM specimens WHERE year = ?"
                                               " AND kind = 'signature'", (y,)).fetchone()[0]})
        return out

    def reviewed_analyses(self) -> list[dict]:
        """Analyses avec la DERNIERE decision d'un agent (sert a entrainer la decision)."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT a.*, r.decision FROM analyses a JOIN reviews r ON r.analysis_id = a.id"
                " WHERE r.id = (SELECT MAX(id) FROM reviews WHERE analysis_id = a.id)"
                " ORDER BY a.id").fetchall()
            return [self._full(conn, r) | {"decision": r["decision"]} for r in rows]

    # -- vieillissement ----------------------------------------------------------------------
    def add_reference_doc(self, year: int, measures: dict, scanner: str | None = None) -> int:
        with self._tx() as conn:
            return conn.execute("INSERT INTO reference_docs (year, scanner, measures, added_at)"
                                " VALUES (?,?,?,?)",
                                (year, scanner, dumps(measures), _now())).lastrowid

    def reference_measures(self, year: int) -> list[dict]:
        """Mesures de vieillissement valides (non vides) de l'annee, ordre fixe."""
        with self._connect() as conn:
            ms = [json.loads(r[0]) for r in conn.execute(
                "SELECT measures FROM reference_docs WHERE year = ? ORDER BY id", (year,))]
        return [m for m in ms if m]

    def count_reference_docs(self, year: int) -> int:
        """Documents de reference de l'annee AVEC des mesures de vieillissement valides."""
        return len(self.reference_measures(year))

    def set_year_profile(self, year: int, profile: dict[str, tuple[float, float, int]]) -> None:
        """Remplace la plage normale d'une annee : mesure -> (mediane, MAD, n)."""
        with self._tx() as conn:
            conn.execute("DELETE FROM year_profiles WHERE year = ?", (year,))
            for measure in sorted(profile):
                med, mad, n = profile[measure]
                conn.execute("INSERT INTO year_profiles VALUES (?,?,?,?,?)",
                             (year, measure, float(med), float(mad), int(n)))

    def year_profile(self, year: int) -> dict[str, tuple[float, float, int]]:
        with self._connect() as conn:
            return {r["measure"]: (r["median"], r["mad"], r["n"]) for r in conn.execute(
                "SELECT * FROM year_profiles WHERE year = ? ORDER BY measure", (year,))}

    def profile_version(self) -> str:
        """Empreinte de tous les profils de vieillissement : entre dans `analysis_key`.
        Si un profil change, la cle change et le document est re-analyse (AGENTS.md 0 bis)."""
        h = hashlib.sha256()
        with self._connect() as conn:
            for r in conn.execute("SELECT year, measure, median, mad, n FROM year_profiles"
                                  " ORDER BY year, measure"):
                h.update(dumps(list(r)).encode())
        return h.hexdigest()

    def schema_version(self) -> int:
        with self._connect() as conn:
            return conn.execute("PRAGMA user_version").fetchone()[0]
