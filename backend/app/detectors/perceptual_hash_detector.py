from dataclasses import dataclass

import imagehash
from PIL import Image, ImageOps


@dataclass(frozen=True, slots=True)
class PerceptualHashResult:
    original: str
    horizontal_flip: str | None


class PerceptualHashDetector:
    ROTATION_ANGLES = (0, 90, 180, 270)

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
    def rotate_clockwise(image: Image.Image, degrees: int) -> Image.Image:
        normalized = ImageOps.exif_transpose(image).convert("RGB")
        transforms = {
            0: None,
            90: Image.Transpose.ROTATE_270,
            180: Image.Transpose.ROTATE_180,
            270: Image.Transpose.ROTATE_90,
        }
        if degrees not in transforms:
            raise ValueError(f"unsupported rotation: {degrees}")
        transform = transforms[degrees]
        return normalized if transform is None else normalized.transpose(transform)

    def calculate_rotations(self, image: Image.Image) -> dict[str, str]:
        """Return canonical clockwise pHashes, after applying EXIF orientation."""
        normalized = ImageOps.exif_transpose(image).convert("RGB")
        transforms = {
            0: None,
            90: Image.Transpose.ROTATE_270,
            180: Image.Transpose.ROTATE_180,
            270: Image.Transpose.ROTATE_90,
        }
        return {
            str(degrees): self.calculate_single(
                normalized if transforms[degrees] is None else normalized.transpose(transforms[degrees])
            )
            for degrees in self.ROTATION_ANGLES
        }

    @staticmethod
    def distance(first: str, second: str) -> int:
        return int(imagehash.hex_to_hash(first) - imagehash.hex_to_hash(second))

    def best_distance(self, first: PerceptualHashResult, second: PerceptualHashResult) -> tuple[int, str]:
        normal = self.distance(first.original, second.original)
        if second.horizontal_flip is None:
            return normal, "original"
        flipped = self.distance(first.original, second.horizontal_flip)
        return (flipped, "horizontal_flip") if flipped < normal else (normal, "original")
