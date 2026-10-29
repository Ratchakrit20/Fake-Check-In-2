"""Fast image usability checks that run before perceptual hashing."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from PIL import Image

from ..core.config import ImageQualityConfig

VERIFIABLE = "VERIFIABLE"
UNVERIFIABLE = "UNVERIFIABLE"


@dataclass(frozen=True, slots=True)
class ImageQualityAssessment:
    status: str
    reason: str | None
    near_black_ratio: float

    @property
    def can_compare(self) -> bool:
        return self.status == VERIFIABLE


class ImageQualityService:
    """Flag images whose near-black area leaves too little visual evidence."""

    def __init__(self, config: ImageQualityConfig) -> None:
        self.config = config

    def assess(self, image: Image.Image) -> ImageQualityAssessment:
        grayscale = image.convert("L")
        grayscale.thumbnail(
            (self.config.sample_max_dimension, self.config.sample_max_dimension),
            Image.Resampling.BOX,
        )
        pixels = np.asarray(grayscale, dtype=np.uint8)
        if pixels.size == 0:
            return ImageQualityAssessment(UNVERIFIABLE, "empty_image", 1.0)

        near_black_ratio = float(np.count_nonzero(pixels <= self.config.near_black_luminance_max) / pixels.size)
        if near_black_ratio >= self.config.unverifiable_near_black_ratio:
            return ImageQualityAssessment(UNVERIFIABLE, "near_black_dominant", near_black_ratio)
        return ImageQualityAssessment(VERIFIABLE, None, near_black_ratio)
