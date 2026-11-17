"""Extraction des zones : sceau, signature, papier, texte."""
from .regions import Box, Element, PageRegions, crop_color, crop_gray, element_mask, find_regions, ink_gray, paper_text_masks

__all__ = ["Box", "Element", "PageRegions", "crop_color", "crop_gray", "element_mask",
           "find_regions", "ink_gray", "paper_text_masks"]
