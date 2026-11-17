"""Evaluation officielle (AGENTS.md 9) : `python -m authentik.eval DOSSIER`.

Le DOSSIER contient les documents et un fichier `labels.csv` (separateur « ; » ou « , ») :

    fichier;label;annee;groupe;type
    vrais/c001.pdf;authentique;2019;c001;
    faux/c001_colle.png;faux;2019;c001;sceau_colle

- label  : « authentique » ou « faux » (ou 0 / 1) ;
- groupe : certificat source. Un groupe n'apparait que dans UN lot (faux derives compris) ;
- type   : type de faux (sceau_colle, signature_deplacee, texte_modifie, imprime_rescanne,
           jpeg_basse_qualite...), vide pour un authentique.

Deroulement : chaque document est analyse avec les references de la base configuree (copie
temporaire : la vraie base n'est pas modifiee) ; lots 60/20/20 par groupe (GroupShuffleSplit,
graine fixe) ; decision entrainee sur le lot d'entrainement ; seuil de revue choisi sur la
validation ; mesure UNIQUE sur le test. Rapport : rappel et faux rejets avec intervalle de
Wilson, rappel par type de faux, part envoyee en revue, courbe ROC, matrice de confusion.
"""
from __future__ import annotations

import csv
import json
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import numpy as np
from sklearn.metrics import roc_auc_score, roc_curve
from sklearn.model_selection import GroupShuffleSplit

from .. import __version__, pipeline
from ..analyzers.base import Signal
from ..config import SETTINGS
from ..fusion import Fusion, review_threshold_from_roc
from ..store import AppConfig, Database, sha256_of
from .metrics import recall_and_false_reject, wilson

SEED = 20240601
MIN_TEST_PER_CLASS = 200          # AGENTS.md 9 : en dessous, l'objectif n'est pas etabli
Progress = Callable[[str, int], None]


@dataclass
class Item:
    path: Path
    label: int
    year: int
    group: str
    kind: str


def read_labels(folder: Path) -> list[Item]:
    f = folder / "labels.csv"
    if not f.exists():
        raise FileNotFoundError(f"{f} introuvable (voir l'aide : python -m authentik.eval --help)")
    text = f.read_text(encoding="utf-8-sig")
    dialect = csv.Sniffer().sniff(text.splitlines()[0], delimiters=";,")
    items = []
    for i, row in enumerate(csv.DictReader(text.splitlines(), dialect=dialect), 2):
        row = {k.strip().lower(): (v or "").strip() for k, v in row.items()}
        lab = row["label"].lower()
        if lab not in ("faux", "authentique", "1", "0"):
            raise ValueError(f"labels.csv ligne {i} : label inconnu « {row['label']} »")
        p = folder / row["fichier"]
        if not p.exists():
            raise FileNotFoundError(f"labels.csv ligne {i} : fichier introuvable {p}")
        items.append(Item(p, 1 if lab in ("faux", "1") else 0, int(row["annee"]),
                          row.get("groupe") or row["fichier"], row.get("type") or ""))
    return sorted(items, key=lambda it: str(it.path))         # ordre fixe


def split(items: list[Item]) -> tuple[list[int], list[int], list[int]]:
    """60 / 20 / 20 par groupe, graine fixe."""
    idx = np.arange(len(items))
    groups = np.array([it.group for it in items])
    rest, test = next(GroupShuffleSplit(1, test_size=0.2, random_state=SEED).split(idx, groups=groups))
    tr, va = next(GroupShuffleSplit(1, test_size=0.25, random_state=SEED)
                  .split(rest, groups=groups[rest]))
    return sorted(rest[tr].tolist()), sorted(rest[va].tolist()), sorted(test.tolist())


def analyse_all(items: list[Item], base: AppConfig, work: Path,
                progress: Progress) -> tuple[list[dict[str, Signal]], list[str]]:
    """Analyse dans une copie temporaire de la base (references incluses)."""
    cfg = AppConfig(work / "eval.db", work / "documents", work / "eval.ini")
    if base.database.exists():
        shutil.copyfile(base.database, cfg.database)
    if (base.documents_dir / "references").exists():
        shutil.copytree(base.documents_dir / "references", cfg.documents_dir / "references")
        _rebase_paths(cfg.database, str(base.documents_dir), str(cfg.documents_dir))
    db = Database(cfg.database)
    ref_shas = {r["source_sha256"] for r in db.reference_documents()}
    signals, notes = [], []
    for i, it in enumerate(items):
        progress(f"Analyse {i + 1}/{len(items)} : {it.path.name}", int(100 * i / len(items)))
        if sha256_of(it.path) in ref_shas:
            notes.append(f"{it.path.name} est aussi un document de référence : exclu des références "
                         "pendant son analyse (il ne peut pas être « copie de lui-même »).")
        out = pipeline.run_analysis(pipeline.prepare(it.path), it.year, cfg, db)
        signals.append({k: Signal(v["risk"], v["confidence"], v["evidence"])
                        for k, v in out.details["signals"].items()})
    return signals, notes


def _rebase_paths(db_path: Path, old: str, new: str) -> None:
    import sqlite3
    conn = sqlite3.connect(db_path)
    conn.execute("UPDATE specimens SET image_path = replace(image_path, ?, ?)", (old, new))
    conn.commit()
    conn.close()


def evaluate(folder: str | Path, base: AppConfig, out_dir: str | Path,
             progress: Progress = lambda s, p: None) -> dict:
    folder, out_dir = Path(folder), Path(out_dir)
    items = read_labels(folder)
    n_fake = sum(it.label for it in items)
    if n_fake < 5 or len(items) - n_fake < 5:
        raise ValueError("Il faut au moins 5 faux et 5 authentiques (viser 200 de chaque).")
    with tempfile.TemporaryDirectory(prefix="authentik_eval_") as tmp:
        signals, notes = analyse_all(items, base, Path(tmp), progress)
    tr, va, te = split(items)
    y = np.array([it.label for it in items])
    if len(set(y[tr])) < 2 or len(set(y[va])) < 2 or len(set(y[te])) < 2:
        raise ValueError("Un des lots ne contient qu'une seule classe : ajouter des documents.")

    fusion = Fusion()
    fusion.fit([signals[i] for i in tr], [int(y[i]) for i in tr])
    p_val = [fusion.decide(signals[i])[0] for i in va]
    thr = review_threshold_from_roc(y[va], p_val)
    review = SETTINGS.review_threshold if thr is None else round(float(min(thr, 1.0)), 4)
    fusion.review, fusion.suspect = review, max(review, SETTINGS.suspect_threshold)

    decisions = [fusion.decide(signals[i]) for i in te]          # mesure UNIQUE sur le test
    p_te = np.array([d[0] for d in decisions])
    verdicts = [d[1] for d in decisions]
    y_te = y[te]
    m = recall_and_false_reject(list(y_te), verdicts)
    by_type = {}
    for kind in sorted({items[i].kind for i in te if items[i].label == 1}):
        sel = [k for k, i in enumerate(te) if items[i].label == 1 and items[i].kind == kind]
        k_ok = sum(verdicts[k] != "conforme" for k in sel)
        by_type[kind or "non précisé"] = {"n": len(sel), "recall": k_ok / len(sel),
                                          "ci95": wilson(k_ok, len(sel)),
                                          "limite": k_ok / len(sel) < 0.80}
    flagged = np.array([v != "conforme" for v in verdicts])
    fpr, tpr, thr_roc = roc_curve(y_te, p_te)
    report = {
        "version": __version__, "n_documents": len(items),
        "lots": {"entrainement": len(tr), "validation": len(va), "test": len(te)},
        "seuil_revue": review, "seuil_trouve_sur_validation": thr is not None,
        "test": {"n_faux": int(y_te.sum()), "n_authentiques": int((1 - y_te).sum()),
                 "rappel": m.get("recall"), "rappel_ic95": m.get("recall_ci95"),
                 "faux_rejets": m.get("false_reject"), "faux_rejets_ic95": m.get("false_reject_ci95"),
                 "part_en_revue": float(np.mean([v == "a_verifier" for v in verdicts])),
                 "auc": float(roc_auc_score(y_te, p_te)) if len(set(y_te)) > 1 else None,
                 "matrice_confusion": {
                     "faux_signales": int((flagged & (y_te == 1)).sum()),
                     "faux_manques": int((~flagged & (y_te == 1)).sum()),
                     "vrais_signales_a_tort": int((flagged & (y_te == 0)).sum()),
                     "vrais_conformes": int((~flagged & (y_te == 0)).sum())}},
        "rappel_par_type": by_type,
        # None = non etabli : lot de test trop petit pour conclure (AGENTS.md 0 et 9)
        "objectif_atteint": (None if y_te.sum() < MIN_TEST_PER_CLASS
                             or (1 - y_te).sum() < MIN_TEST_PER_CLASS else
                             bool(m.get("recall", 0) >= 0.90 and m.get("false_reject", 1) <= 0.05)),
        "notes": notes,
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "evaluation.json").write_text(json.dumps(report, indent=2, ensure_ascii=False),
                                             encoding="utf-8")
    with open(out_dir / "roc.csv", "w", encoding="utf-8") as f:
        f.write("taux_faux_positifs;taux_vrais_positifs;seuil\n")
        for a, b, c in zip(fpr, tpr, thr_roc):
            f.write(f"{a:.4f};{b:.4f};{min(c, 1.0):.4f}\n")
    (out_dir / "evaluation.md").write_text(markdown(report), encoding="utf-8")
    progress("Terminé", 100)
    return report


def _pct(x, ci=None) -> str:
    if x is None:
        return "—"
    return f"{x:.1%}" + (f" (IC 95 % : {ci[0]:.1%} – {ci[1]:.1%})" if ci else "")


def _objective(ok: bool | None, t: dict) -> str:
    if ok is None:
        return (f"**non établi** (lot de test trop petit : {t['n_faux']} faux et "
                f"{t['n_authentiques']} authentiques ; {MIN_TEST_PER_CLASS} de chaque requis)")
    return "**oui**" if ok else "**non**"


def markdown(r: dict) -> str:
    t = r["test"]
    cm = t["matrice_confusion"]
    lines = [f"# Évaluation Authentik {r['version']}", "",
             f"Documents : {r['n_documents']} — lots : {r['lots']['entrainement']} entraînement, "
             f"{r['lots']['validation']} validation, {r['lots']['test']} test (mesure unique).", "",
             f"Seuil de revue : {r['seuil_revue']:.2f}"
             + ("" if r["seuil_trouve_sur_validation"] else
                " (objectif hors de portée sur la validation : seuil provisoire conservé)"), "",
             "## Résultats sur le lot de test", "",
             f"- Faux détectés (rappel) : **{_pct(t['rappel'], t['rappel_ic95'])}** — objectif ≥ 90 %",
             f"- Vrais signalés à tort : **{_pct(t['faux_rejets'], t['faux_rejets_ic95'])}** — objectif ≤ 5 %",
             f"- Part envoyée en revue manuelle : {_pct(t['part_en_revue'])}",
             f"- Aire sous la courbe ROC : {t['auc']:.3f}" if t["auc"] is not None else "- AUC : —",
             "- Objectif atteint : " + _objective(r["objectif_atteint"], t), "",
             "| | signalé | non signalé |", "|---|---|---|",
             f"| faux | {cm['faux_signales']} | {cm['faux_manques']} |",
             f"| authentique | {cm['vrais_signales_a_tort']} | {cm['vrais_conformes']} |", "",
             "## Rappel par type de faux", "", "| type | n | rappel | limite (< 80 %) |",
             "|---|---|---|---|"]
    for k, v in r["rappel_par_type"].items():
        lines.append(f"| {k} | {v['n']} | {_pct(v['recall'], v['ci95'])} | {'OUI' if v['limite'] else 'non'} |")
    if t["n_faux"] < 200 or t["n_authentiques"] < 200:
        lines += ["", f"**Attention** : lot de test de {t['n_faux']} faux et {t['n_authentiques']} "
                  "authentiques. AGENTS.md demande au moins 200 de chaque : l'intervalle de "
                  "confiance est large."]
    if r["notes"]:
        lines += ["", "## Notes", ""] + [f"- {n}" for n in r["notes"]]
    lines += ["", "Limites : aucun système ne garantit 100 % ; un agent habilité décide."]
    return "\n".join(lines) + "\n"
