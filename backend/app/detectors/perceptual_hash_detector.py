from dataclasses import dataclass

import imagehash
from PIL import Image, ImageOps


@dataclass(frozen=True, slots=True)
class PerceptualHashResult:
    original: str
    horizontal_flip: str | None


class PerceptualHashDetector:
    def __init__(self, hash_size: int = 8, compare_horizontal_flip: bool = True) -> None:
        self.hash_size = hash_size
        self.compare_horizontal_flip = compare_horizontal_flip

    def calculate(self, image: Image.Image) -> PerceptualHashResult:
        rgb = image.convert("RGB")
        original = self.calculate_single(rgb)
        flipped = self.calculate_single(ImageOps.mirror(rgb)) if self.compare_horizontal_flip else None
        return PerceptualHashResult(original, flipped)

    def calculate_single(self, image: Image.Image) -> str:
        return str(imagehash.phash(image.convert("RGB"), hash_size=self.hash_size))

    @staticmethod
    def distance(first: str, second: str) -> int:
        return int(imagehash.hex_to_hash(first) - imagehash.hex_to_hash(second))

    def best_distance(self, first: PerceptualHashResult, second: PerceptualHashResult) -> tuple[int, str]:
        normal = self.distance(first.original, second.original)
        if second.horizontal_flip is None:
            return normal, "original"
        flipped = self.distance(first.original, second.horizontal_flip)
        return (flipped, "horizontal_flip") if flipped < normal else (normal, "original")
