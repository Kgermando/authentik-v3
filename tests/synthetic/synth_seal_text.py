"""Sceau de synthese avec texte CIRCULAIRE (comme un vrai tampon). Ne prouve rien sur de vrais sceaux."""
import cv2
import numpy as np


def circular_seal(text, size=600, radius=245, font_scale=1.5, thickness=4, start_deg=-170):
    img = np.full((size, size), 255, np.uint8)
    c = size // 2
    cv2.circle(img, (c, c), radius + 40, 0, 10)
    cv2.circle(img, (c, c), radius - 45, 0, 6)
    n = len(text)
    span = 340
    for i, ch in enumerate(text):
        ang = np.deg2rad(start_deg + span * i / n)
        tile = np.full((80, 80), 255, np.uint8)
        (w, h), _ = cv2.getTextSize(ch, cv2.FONT_HERSHEY_SIMPLEX, font_scale, thickness)
        cv2.putText(tile, ch, ((80 - w) // 2, (80 + h) // 2), cv2.FONT_HERSHEY_SIMPLEX,
                    font_scale, 0, thickness, cv2.LINE_AA)
        rot = cv2.getRotationMatrix2D((40, 40), -np.rad2deg(ang) - 90, 1.0)
        tile = cv2.warpAffine(tile, rot, (80, 80), borderValue=255)
        x, y = int(c + radius * np.cos(ang)) - 40, int(c + radius * np.sin(ang)) - 40
        img[y:y + 80, x:x + 80] = np.minimum(img[y:y + 80, x:x + 80], tile)
    return img
