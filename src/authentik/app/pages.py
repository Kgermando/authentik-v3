"""Pages de la fenetre principale : accueil, scan, apercu + annee, chargement, resultats."""
from __future__ import annotations

from datetime import date

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QProgressBar, QPushButton, QSpinBox, QSplitter,
                               QVBoxLayout, QWidget)

from ..ingest.year import MIN_YEAR
from .image_view import COLORS, ImageView

VERDICTS = {"conforme": ("Conforme", "green"), "a_verifier": ("À vérifier", "orange"),
            "suspect": ("Suspect", "red")}
GREY = "#616161"


def _image_first(split: QSplitter) -> None:
    """Colonne image prioritaire : elle prend toute la place restante."""
    split.widget(0).setMinimumWidth(420)
    split.setChildrenCollapsible(False)
    split.setStretchFactor(0, 1)
    split.setStretchFactor(1, 0)
    split.setSizes([900, 380])


def _big_button(text: str) -> QPushButton:
    b = QPushButton(text)
    b.setMinimumSize(260, 120)
    f = b.font()
    f.setPointSize(16)
    f.setBold(True)
    b.setFont(f)
    return b


def _title(text: str, size: int = 15) -> QLabel:
    lab = QLabel(text)
    f = lab.font()
    f.setPointSize(size)
    f.setBold(True)
    lab.setFont(f)
    lab.setWordWrap(True)
    return lab


def _wrap(text: str = "", style: str = "") -> QLabel:
    lab = QLabel(text)
    lab.setWordWrap(True)
    lab.setTextInteractionFlags(Qt.TextSelectableByMouse)
    if style:
        lab.setStyleSheet(style)
    return lab


class HomePage(QWidget):
    scan_clicked = Signal()
    import_clicked = Signal()
    references_clicked = Signal()

    def __init__(self):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.addStretch()
        t = _title("Authentik : contrôle des certificats administratifs", 18)
        t.setAlignment(Qt.AlignCenter)
        lay.addWidget(t)
        sub = QLabel("Ministère de la Formation Professionnelle (MFP)")
        sub.setAlignment(Qt.AlignCenter)
        lay.addWidget(sub)
        lay.addSpacing(30)
        row = QHBoxLayout()
        row.addStretch()
        self.scan_btn = _big_button("Scanner")
        self.import_btn = _big_button("Importer un fichier")
        self.scan_btn.clicked.connect(self.scan_clicked)
        self.import_btn.clicked.connect(self.import_clicked)
        row.addWidget(self.scan_btn)
        row.addSpacing(30)
        row.addWidget(self.import_btn)
        row.addStretch()
        lay.addLayout(row)
        lay.addSpacing(20)
        ref_row = QHBoxLayout()
        ref_row.addStretch()
        self.ref_btn = QPushButton("Références : documents authentiques de comparaison")
        self.ref_btn.setMinimumHeight(40)
        self.ref_btn.clicked.connect(self.references_clicked)
        ref_row.addWidget(self.ref_btn)
        ref_row.addStretch()
        lay.addLayout(ref_row)
        self.ref_status = QLabel()
        self.ref_status.setAlignment(Qt.AlignCenter)
        self.ref_status.setStyleSheet(f"color:{GREY}")
        lay.addWidget(self.ref_status)
        lay.addStretch()


class ScanPage(QWidget):
    """Choix du scanner : reseau local, scanners enregistres, pilotes du poste, autre reseau."""
    search_clicked = Signal()
    scan_clicked = Signal(object)        # ScannerInfo
    add_clicked = Signal(str)            # adresse IP, nom, URL ou plage (ex. 10.0.2.0/24)
    remember_clicked = Signal(object)    # ScannerInfo a memoriser
    forget_clicked = Signal(object)      # ScannerInfo a oublier
    back_clicked = Signal()

    def __init__(self):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.addWidget(_title("Scanner un document"))
        lay.addWidget(_wrap("Réglages imposés : 300 DPI, couleur, sans amélioration automatique. "
                            "Poser le certificat sur la vitre."))
        self.list = QListWidget()
        lay.addWidget(self.list, 1)
        self.status = _wrap()
        lay.addWidget(self.status)

        other = QHBoxLayout()
        other.addWidget(QLabel("Autre réseau :"))
        self.manual = QLineEdit()
        self.manual.setPlaceholderText("adresse du scanner (10.0.2.15, nom ou URL) "
                                       "ou plage d'adresses (10.0.2.0/24)")
        other.addWidget(self.manual, 1)
        self.add_btn = QPushButton("Ajouter / Rechercher")
        other.addWidget(self.add_btn)
        lay.addLayout(other)

        btns = QHBoxLayout()
        self.back_btn = QPushButton("Retour")
        self.search_btn = QPushButton("Actualiser la liste")
        self.remember_btn = QPushButton("Mémoriser")
        self.forget_btn = QPushButton("Oublier")
        self.scan_btn = QPushButton("Numériser")
        self.scan_btn.setDefault(True)
        btns.addWidget(self.back_btn)
        btns.addStretch()
        for b in (self.search_btn, self.remember_btn, self.forget_btn, self.scan_btn):
            btns.addWidget(b)
        lay.addLayout(btns)

        self.back_btn.clicked.connect(self.back_clicked)
        self.search_btn.clicked.connect(self.search_clicked)
        self.scan_btn.clicked.connect(self._scan)
        self.add_btn.clicked.connect(self._add)
        self.manual.returnPressed.connect(self._add)
        self.remember_btn.clicked.connect(lambda: self._emit_current(self.remember_clicked))
        self.forget_btn.clicked.connect(lambda: self._emit_current(self.forget_clicked))
        self.list.itemDoubleClicked.connect(lambda _: self._scan())
        self.list.currentItemChanged.connect(lambda *_: self._update_buttons())
        self._busy = False
        self._update_buttons()

    def current(self):
        it = self.list.currentItem()
        return it.data(Qt.UserRole) if it is not None else None

    def set_busy(self, busy: bool, message: str = "") -> None:
        self._busy = busy
        for w in (self.search_btn, self.back_btn, self.list, self.manual, self.add_btn):
            w.setEnabled(not busy)
        self._update_buttons()
        self.status.setText(message)

    def _update_buttons(self) -> None:
        s = self.current()
        self.scan_btn.setEnabled(not self._busy and s is not None)
        self.remember_btn.setEnabled(not self._busy and s is not None and s.backend == "escl"
                                     and s.origin != "enregistré")
        self.forget_btn.setEnabled(not self._busy and s is not None and s.origin == "enregistré")

    def set_scanners(self, scanners, message: str | None = None) -> None:
        keep = self.current()
        self.list.clear()
        for s in scanners:
            it = QListWidgetItem(s.label)
            it.setData(Qt.UserRole, s)
            self.list.addItem(it)
            if keep is not None and s.key == keep.key:
                self.list.setCurrentItem(it)
        if self.list.currentItem() is None and scanners:
            self.list.setCurrentRow(0)
        if message is not None:
            self.status.setText(message)
        elif scanners:
            self.status.setText(f"{len(scanners)} scanner(s) disponible(s).")
        else:
            self.status.setText("Aucun scanner trouvé sur ce réseau. Pour un scanner d'un autre "
                                "réseau, saisir son adresse ou une plage d'adresses ci-dessous ; "
                                "sinon, importer un fichier déjà scanné.")
        self._update_buttons()

    def scanners(self) -> list:
        return [self.list.item(i).data(Qt.UserRole) for i in range(self.list.count())]

    def _emit_current(self, signal) -> None:
        if self.current() is not None:
            signal.emit(self.current())

    def _scan(self) -> None:
        if self.current() is None:
            self.status.setText("Choisir un scanner dans la liste.")
            return
        self.scan_clicked.emit(self.current())

    def _add(self) -> None:
        text = self.manual.text().strip()
        if not text:
            self.status.setText("Saisir l'adresse du scanner ou une plage d'adresses.")
            return
        self.add_clicked.emit(text)


class PreparePage(QWidget):
    """Aperçu du document et confirmation de l'année avant l'analyse."""
    analyse_clicked = Signal(int)
    cancel_clicked = Signal()

    NO_YEAR = MIN_YEAR - 1

    def __init__(self):
        super().__init__()
        split = QSplitter(Qt.Horizontal)
        self.view = ImageView()
        split.addWidget(self.view)
        panel = QWidget()
        p = QVBoxLayout(panel)
        p.addWidget(_title("Vérifier avant l'analyse"))
        self.file_label = _wrap()
        p.addWidget(self.file_label)
        p.addSpacing(10)
        p.addWidget(QLabel("Année du document :"))
        self.year = QSpinBox()
        self.year.setRange(self.NO_YEAR, date.today().year)
        self.year.setSpecialValueText("À saisir")
        self.year.valueChanged.connect(self._check)
        f = self.year.font()
        f.setPointSize(14)
        self.year.setFont(f)
        p.addWidget(self.year)
        self.year_source = _wrap(style=f"color:{GREY}")
        p.addWidget(self.year_source)
        self.warnings = _wrap(style=f"color:{COLORS['orange']}")
        p.addWidget(self.warnings)
        p.addStretch()
        btns = QHBoxLayout()
        self.cancel_btn = QPushButton("Annuler")
        self.analyse_btn = QPushButton("Analyser")
        self.analyse_btn.setDefault(True)
        btns.addWidget(self.cancel_btn)
        btns.addStretch()
        btns.addWidget(self.analyse_btn)
        p.addLayout(btns)
        panel.setMaximumWidth(480)
        split.addWidget(panel)
        _image_first(split)
        lay = QVBoxLayout(self)
        lay.addWidget(split)
        self.cancel_btn.clicked.connect(self.cancel_clicked)
        self.analyse_btn.clicked.connect(lambda: self.analyse_clicked.emit(self.year.value()))

    def show_prepared(self, prepared) -> None:
        self.view.set_image(prepared.doc.pages[0])
        n = len(prepared.doc.pages)
        self.file_label.setText(f"<b>{prepared.source.name}</b><br>{n} page(s)"
                                + (" — seule la première est analysée." if n > 1 else ""))
        r = prepared.year_reading
        self.year.setValue(r.year or self.NO_YEAR)
        src = f"Lu sur le document : « {r.source} »" if r.year else ""
        self.year_source.setText("<br>".join(x for x in (src, r.message or "") if x))
        self.warnings.setText("<br>".join(prepared.doc.warnings))
        self._check()

    def _check(self) -> None:
        self.analyse_btn.setEnabled(self.year.value() != self.NO_YEAR)


class ProgressPage(QWidget):
    def __init__(self):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.addStretch()
        self.step = _title("")
        self.step.setAlignment(Qt.AlignCenter)
        lay.addWidget(self.step)
        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setMinimumWidth(420)
        row = QHBoxLayout()
        row.addStretch()
        row.addWidget(self.bar)
        row.addStretch()
        lay.addLayout(row)
        lay.addStretch()

    def update(self, step: str, pct: int) -> None:      # noqa: A003 - nom explicite
        self.step.setText(step + "…")
        self.bar.setValue(pct)


class RowWidget(QFrame):
    """Une ligne d'indication : nom, mot en couleur, courte raison. Cliquable."""
    clicked = Signal(str)

    def __init__(self, row):
        super().__init__()
        self.name = row.name
        self.setFrameShape(QFrame.StyledPanel)
        self.setCursor(Qt.PointingHandCursor)
        color = COLORS.get(row.color, GREY)
        self.setStyleSheet(f"RowWidget {{ border-left: 6px solid {color}; }}")
        lay = QVBoxLayout(self)
        top = QHBoxLayout()
        name = QLabel(row.name)
        f = name.font()
        f.setPointSize(12)
        name.setFont(f)
        word = QLabel(row.word)
        word.setStyleSheet(f"color:{color}; font-weight:bold; font-size:12pt")
        top.addWidget(name)
        top.addStretch()
        top.addWidget(word)
        lay.addLayout(top)
        if row.reason:
            lay.addWidget(_wrap(row.reason, f"color:{GREY}"))

    def mousePressEvent(self, event):
        self.clicked.emit(self.name)
        super().mousePressEvent(event)


class ResultsPage(QWidget):
    details_clicked = Signal()
    new_clicked = Signal()
    review_clicked = Signal(str)          # authentique | faux | indetermine

    def __init__(self):
        super().__init__()
        split = QSplitter(Qt.Horizontal)
        self.view = ImageView()
        split.addWidget(self.view)
        panel = QWidget()
        self.panel = QVBoxLayout(panel)
        self.verdict = _title("", 22)
        self.panel.addWidget(self.verdict)
        self.summary = _wrap()
        self.panel.addWidget(self.summary)
        self.alert = _wrap(style=f"color:{COLORS['red']}; font-weight:bold")
        self.panel.addWidget(self.alert)
        self.rows_box = QVBoxLayout()
        self.panel.addLayout(self.rows_box)
        self.panel.addStretch()
        self.panel.addWidget(QLabel("<b>Décision de l'agent</b>"))
        rv = QHBoxLayout()
        self.review_btns = {}
        for key, text in (("authentique", "Authentique"), ("faux", "Faux"),
                          ("indetermine", "Indéterminé")):
            b = QPushButton(text)
            b.clicked.connect(lambda _=False, k=key: self.review_clicked.emit(k))
            rv.addWidget(b)
            self.review_btns[key] = b
        self.panel.addLayout(rv)
        self.review_label = _wrap(style=f"color:{GREY}")
        self.panel.addWidget(self.review_label)
        btns = QHBoxLayout()
        self.new_btn = QPushButton("Nouveau document")
        self.details_btn = QPushButton("En savoir plus")
        btns.addWidget(self.new_btn)
        btns.addStretch()
        btns.addWidget(self.details_btn)
        self.panel.addLayout(btns)
        panel.setMaximumWidth(560)
        split.addWidget(panel)
        _image_first(split)
        lay = QVBoxLayout(self)
        lay.addWidget(split)
        self.details_btn.clicked.connect(self.details_clicked)
        self.new_btn.clicked.connect(self.new_clicked)

    def show_outcome(self, outcome) -> None:
        self.view.set_image(outcome.prepared.doc.pages[0])
        self.view.set_regions([r for r in outcome.regions if r.page == 0])
        if outcome.verdict in VERDICTS:
            word, color = VERDICTS[outcome.verdict]
            pct = f" — {round(outcome.score * 100)} %" if outcome.score is not None else ""
            self.verdict.setText(word + pct)
            self.verdict.setStyleSheet(f"color:{COLORS[color]}")
        else:
            self.verdict.setText("Pas de verdict")
            self.verdict.setStyleSheet(f"color:{GREY}")
        extra = " (résultat déjà enregistré, non recalculé)" if outcome.memoized else ""
        self.summary.setText(outcome.summary + extra)
        self.alert.setText("" if outcome.integrity_ok else
                           "Alerte d'intégrité : la copie enregistrée du document a été modifiée "
                           "ou a disparu depuis l'analyse.")
        while self.rows_box.count():
            w = self.rows_box.takeAt(0).widget()
            if w is not None:
                w.hide()
                w.setParent(None)
                w.deleteLater()
        for row in outcome.rows:                         # lignes masquees : non affichees
            rw = RowWidget(row)
            rw.clicked.connect(self.view.highlight)
            self.rows_box.addWidget(rw)
        if not outcome.rows:
            self.rows_box.addWidget(_wrap("Aucune indication disponible. Le détail est dans "
                                          "« En savoir plus ».", f"color:{GREY}"))
        can_review = bool(outcome.details.get("analysis_id"))
        for b in self.review_btns.values():
            b.setEnabled(can_review)
        self.show_reviews(outcome.details.get("reviews") or [])

    def show_reviews(self, reviews: list[dict]) -> None:
        names = {"authentique": "Authentique", "faux": "Faux", "indetermine": "Indéterminé"}
        if not reviews:
            self.review_label.setText("Aucune décision enregistrée. Elle sert aussi à entraîner "
                                      "la décision automatique.")
            return
        last = reviews[-1]
        self.review_label.setText(f"Dernière décision : <b>{names.get(last['decision'], last['decision'])}</b>"
                                  f" — {last['reviewed_by']}, {str(last['created_at'])[:16].replace('T', ' ')}"
                                  + (f" ({len(reviews)} au total)" if len(reviews) > 1 else ""))
