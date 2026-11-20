"""Fast image usability checks that run before perceptual hashing."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from PIL import Image, ImageFilter

from ..core.config import ImageQualityConfig

VERIFIABLE = "VERIFIABLE"
UNVERIFIABLE = "UNVERIFIABLE"
QUALITY_VERSION = 2


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
        # The lower strip commonly contains a bright location/date overlay.
        # Smooth sensor noise before measuring the usable scene's contrast.
        scene = grayscale.crop((0, 0, grayscale.width, max(1, round(grayscale.height * (1 - self.config.flat_scene_bottom_exclusion)))))
        scene_pixels = np.asarray(scene.filter(ImageFilter.GaussianBlur(radius=3)), dtype=np.uint8)
        low, high = np.percentile(scene_pixels, (10, 90))
        if high <= self.config.flat_scene_max_luminance and high - low <= self.config.flat_scene_max_range:
            return ImageQualityAssessment(UNVERIFIABLE, "dark_flat_scene", near_black_ratio)
        return ImageQualityAssessment(VERIFIABLE, None, near_black_ratio)
