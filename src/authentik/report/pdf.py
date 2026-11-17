"""Rapport PDF d'une analyse (reportlab) : verdict, indications, preuves visuelles, limites."""
from __future__ import annotations

import io
from pathlib import Path

import cv2
import numpy as np
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (Image, KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table,
                                TableStyle)

from .. import __version__

VERDICT_FR = {"conforme": "Conforme", "a_verifier": "À vérifier", "suspect": "Suspect"}
COLOR = {"green": colors.HexColor("#2e7d32"), "orange": colors.HexColor("#ef6c00"),
         "red": colors.HexColor("#c62828")}
BGR = {"green": (50, 125, 46), "orange": (0, 108, 239), "red": (40, 40, 198)}
SIGNAL_FR = {"seal_text": "Texte du sceau", "seal_reference": "Sceau : ressemblance aux spécimens",
             "seal_copy": "Sceau : copie d'un autre document", "seal_integrity": "Sceau : papier autour",
             "sig_reference": "Signature : ressemblance aux spécimens",
             "sig_copy": "Signature : copie d'un autre document",
             "sig_integrity": "Signature : papier autour", "seal_pressure": "Pression (sceau)",
             "sig_pressure": "Pression (signature)", "aging": "Vieillissement",
             "unreadable": "Élément attendu introuvable"}
LIMITS = ("Aucun système ne garantit 100 % sur des scans. Le logiciel donne un score et des "
          "preuves ; un agent habilité décide. Un faux imprimé sur du papier d'époque de la même "
          "année passe le contrôle de vieillissement. La pression de l'encre est mesurée sur l'encre, "
          "pas sur le relief. Les seuils restent provisoires tant qu'ils n'ont pas été calibrés et "
          "mesurés sur un lot de documents réels.")


def _png(img: np.ndarray, max_side: int) -> io.BytesIO:
    h, w = img.shape[:2]
    f = min(1.0, max_side / max(h, w))
    if f < 1:
        img = cv2.resize(img, (int(w * f), int(h * f)), interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".png", img)
    return io.BytesIO(buf.tobytes())


def _flowable_image(img: np.ndarray, width_cm: float, max_side: int = 1400) -> Image:
    h, w = img.shape[:2]
    return Image(_png(img, max_side), width=width_cm * cm, height=width_cm * cm * h / w)


def _page_with_boxes(outcome) -> np.ndarray:
    page = outcome.prepared.doc.pages[0].copy()
    for r in outcome.regions:
        if r.page == 0:
            x, y, w, h = r.rect
            cv2.rectangle(page, (x, y), (x + w, y + h), BGR.get(r.color, (0, 0, 0)), 12)
    return page


def _read(path: str | None) -> np.ndarray | None:
    if not path or not Path(path).exists():
        return None
    return cv2.imdecode(np.fromfile(path, np.uint8), cv2.IMREAD_COLOR)


def evidence_images(outcome, crops_dir: Path) -> list[tuple[str, np.ndarray, str, np.ndarray | None]]:
    """[(titre, recadrage du document, libelle de comparaison, image de comparaison)]."""
    out = []
    sigs = outcome.details.get("signals", {})
    for kind, prefix, title in (("seal", "seal", "Sceau"), ("signature", "sig", "Signature")):
        crop = _read(str(crops_dir / f"{outcome.prepared.sha256}_{kind}.png"))
        if crop is None:
            continue
        ev = (sigs.get(f"{prefix}_copy") or {}).get("evidence", {})
        match = ev.get("copy_of") or ev.get("closest")
        ref_ev = (sigs.get(f"{prefix}_reference") or {}).get("evidence", {})
        if match:
            label = ("COPIE de : " if ev.get("copy_of") else "Le plus proche : ") + match["document"]
            other = _read(match.get("image"))
        elif ref_ev.get("nearest_image"):
            label, other = "Spécimen le plus proche : " + ref_ev["nearest_specimen"], _read(ref_ev["nearest_image"])
        else:
            label, other = "Aucun élément de comparaison", None
        out.append((title, crop, label, other))
    return out


def write_report(outcome, path: str | Path, crops_dir: Path) -> Path:
    path = Path(path)
    st = getSampleStyleSheet()
    small = ParagraphStyle("small", parent=st["Normal"], fontSize=8, leading=10)
    p = outcome.prepared
    verdict = VERDICT_FR.get(outcome.verdict, "Pas de verdict")
    vcolor = {"conforme": "green", "a_verifier": "orange", "suspect": "red"}.get(outcome.verdict)
    story = [Paragraph("Authentik — Rapport d'analyse", st["Title"]),
             Paragraph("Ministère de la Formation Professionnelle (MFP), République Démocratique du Congo",
                       st["Normal"]), Spacer(1, 0.4 * cm)]
    score = f" — {round(outcome.score * 100)} %" if outcome.score is not None else ""
    story.append(Paragraph(f'<font color="{COLOR[vcolor].hexval() if vcolor else "#616161"}">'
                           f"<b>{verdict}{score}</b></font>", st["Heading1"]))
    story.append(Paragraph(outcome.summary, st["Normal"]))
    if not outcome.details.get("calibrated", False):
        story.append(Paragraph("<i>Décision provisoire : le modèle de décision n'est pas encore "
                               "entraîné sur des documents vérifiés.</i>", small))
    if not outcome.integrity_ok:
        story.append(Paragraph('<font color="#c62828"><b>Alerte d\'intégrité : la copie enregistrée '
                               "du document a été modifiée.</b></font>", st["Normal"]))
    story.append(Spacer(1, 0.3 * cm))

    rows = [["Indication", "Constat", "Motif"]]
    for r in outcome.rows:
        rows.append([r.name, Paragraph(f'<font color="{COLOR[r.color].hexval()}"><b>{r.word}</b></font>',
                                       st["Normal"]), Paragraph(r.reason or "", small)])
    for name, why in outcome.hidden.items():
        rows.append([name, Paragraph("<i>non affichée</i>", small), Paragraph(why, small)])
    t = Table(rows, colWidths=[4 * cm, 4 * cm, 9 * cm])
    t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
                           ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eeeeee")),
                           ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    story += [t, Spacer(1, 0.4 * cm)]
    story.append(KeepTogether([Paragraph("Document analysé", st["Heading2"]),
                               _flowable_image(_page_with_boxes(outcome), 9)]))
    for title, crop, label, other in evidence_images(outcome, crops_dir):
        cells = [[_flowable_image(crop, 7, 800),
                  _flowable_image(other, 7, 800) if other is not None else Paragraph("—", st["Normal"])],
                 [Paragraph(f"{title} du document", small), Paragraph(label, small)]]
        story += [Paragraph(title, st["Heading2"]), Table(cells, colWidths=[8.5 * cm, 8.5 * cm])]

    sig_rows = [["Contrôle", "Risque", "Confiance"]]
    for k, s in sorted(outcome.details.get("signals", {}).items()):
        sig_rows.append([SIGNAL_FR.get(k, k), f"{s['risk']:.2f}", f"{s['confidence']:.2f}"])
    if len(sig_rows) > 1:
        t2 = Table(sig_rows, colWidths=[9 * cm, 3 * cm, 3 * cm])
        t2.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
                                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eeeeee"))]))
        story += [Paragraph("Contrôles", st["Heading2"]), t2]
    reviews = outcome.details.get("reviews") or []
    if reviews:
        story.append(Paragraph("Décisions des agents", st["Heading2"]))
        for rv in reviews:
            story.append(Paragraph(f"{rv['created_at'][:16]} — {rv['reviewed_by']} : "
                                   f"<b>{rv['decision']}</b> {rv.get('review_note') or ''}", small))
    story += [Paragraph("Identification", st["Heading2"]),
              Paragraph(f"Fichier : {p.source.name} — année retenue : {outcome.year}<br/>"
                        f"SHA-256 : {p.sha256}<br/>Clé d'analyse : {outcome.analysis_key}<br/>"
                        f"Copie enregistrée : {outcome.stored_path}<br/>Authentik {__version__}", small),
              Paragraph("Limites", st["Heading2"]), Paragraph(LIMITS, small)]
    doc = SimpleDocTemplate(str(path), pagesize=A4, leftMargin=2 * cm, rightMargin=2 * cm,
                            topMargin=1.5 * cm, bottomMargin=1.5 * cm, title="Rapport Authentik",
                            author="Authentik — MFP")
    doc.build(story)
    return path
