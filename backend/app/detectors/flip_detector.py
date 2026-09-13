from dataclasses import dataclass

from PIL import Image, ImageOps

from .ransac_verifier import RANSACVerifier
from .sift_matcher import SIFTMatcher


@dataclass(frozen=True, slots=True)
class FlipResult:
    detected_transform: str
    normal_score: float
    horizontal_flip_score: float


class FlipDetector:
    def __init__(self, matcher: SIFTMatcher, verifier: RANSACVerifier) -> None:
        self.matcher = matcher
        self.verifier = verifier

    def detect(self, first: Image.Image, second: Image.Image) -> FlipResult:
        normal = self.verifier.verify(self.matcher.match(first, second)).inlier_ratio
        flipped = self.verifier.verify(self.matcher.match(first, ImageOps.mirror(second))).inlier_ratio
        transform = "horizontal_flip" if flipped > normal + 0.05 else "original"
        return FlipResult(transform, normal, flipped)

