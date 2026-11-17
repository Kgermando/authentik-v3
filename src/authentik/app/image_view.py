"""Colonne 1 : l'image entiere, avec des cadres de couleur sur le sceau et la signature."""
from __future__ import annotations

import numpy as np
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QGraphicsPixmapItem, QGraphicsRectItem, QGraphicsScene, QGraphicsView

COLORS = {"green": "#2e7d32", "orange": "#ef6c00", "red": "#c62828"}


def bgr_to_qimage(img: np.ndarray) -> QImage:
    img = np.ascontiguousarray(img)
    h, w = img.shape[:2]
    if img.ndim == 2:
        return QImage(img.data, w, h, img.strides[0], QImage.Format_Grayscale8).copy()
    return QImage(img.data, w, h, img.strides[0], QImage.Format_BGR888).copy()


class ImageView(QGraphicsView):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setScene(QGraphicsScene(self))
        self.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setBackgroundBrush(QColor("#e0e0e0"))
        self._pixmap: QGraphicsPixmapItem | None = None
        self._boxes: dict[str, list[QGraphicsRectItem]] = {}

    def set_image(self, img: np.ndarray) -> None:
        self.scene().clear()
        self._boxes.clear()
        self._pixmap = self.scene().addPixmap(QPixmap.fromImage(bgr_to_qimage(img)))
        self.scene().setSceneRect(self._pixmap.boundingRect())
        self.fit()

    def set_regions(self, regions) -> None:
        """`regions` : objets avec row, rect (x, y, l, h), color."""
        for items in self._boxes.values():
            for it in items:
                self.scene().removeItem(it)
        self._boxes.clear()
        for r in regions:
            x, y, w, h = r.rect
            item = self.scene().addRect(QRectF(x, y, w, h), self._pen(r.color, 6))
            item.setData(0, r.color)
            self._boxes.setdefault(r.row, []).append(item)

    def highlight(self, row: str | None) -> None:
        """Met en evidence le(s) cadre(s) de la ligne cliquee et centre la vue dessus."""
        for name, items in self._boxes.items():
            for it in items:
                on = name == row
                it.setPen(self._pen(it.data(0), 14 if on else 6))
                fill = QColor(COLORS.get(it.data(0), "#000"))
                fill.setAlpha(40)                   # transparent : le sceau reste visible
                it.setBrush(QBrush(fill) if on else Qt.NoBrush)
                it.setOpacity(1.0 if on or row is None else 0.6)
                if on:
                    self.centerOn(it)

    def has_boxes(self, row: str) -> bool:
        return bool(self._boxes.get(row))

    @staticmethod
    def _pen(color: str, width: int) -> QPen:
        pen = QPen(QColor(COLORS.get(color, "#000000")), width)
        pen.setCosmetic(False)
        return pen

    def fit(self) -> None:
        if self._pixmap is not None:
            self.fitInView(self._pixmap, Qt.KeepAspectRatio)

    def wheelEvent(self, event):
        f = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        self.scale(f, f)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._pixmap is not None and self.transform().m11() < 1.0:
            self.fit()
