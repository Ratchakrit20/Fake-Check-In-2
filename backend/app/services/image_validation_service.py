import io
from dataclasses import dataclass
from typing import ClassVar

from PIL import Image, UnidentifiedImageError

from ..core.config import AppConfig
from ..core.exceptions import InvalidImageError


@dataclass(frozen=True, slots=True)
class ValidatedImage:
    width: int
    height: int
    mime_type: str
    suffix: str


class ImageValidationService:
    FORMAT_MAP: ClassVar[dict[str, tuple[str, str]]] = {"JPEG": ("image/jpeg", ".jpg"), "PNG": ("image/png", ".png"), "WEBP": ("image/webp", ".webp"), "TIFF": ("image/tiff", ".tiff"), "BMP": ("image/bmp", ".bmp")}

    def __init__(self, config: AppConfig) -> None:
        self.config = config

    def validate(self, content: bytes) -> ValidatedImage:
        if len(content) > self.config.max_file_size_mb * 1024 * 1024:
            raise InvalidImageError("image exceeds configured file-size limit")
        try:
            with Image.open(io.BytesIO(content)) as image:
                image.verify()
            with Image.open(io.BytesIO(content)) as image:
                width, height, image_format = image.width, image.height, image.format
        except (UnidentifiedImageError, OSError) as exc:
            raise InvalidImageError("file is not a decodable image") from exc
        if width * height > self.config.max_image_pixels:
            raise InvalidImageError("image dimensions exceed configured pixel limit")
        if image_format not in self.FORMAT_MAP:
            raise InvalidImageError(f"unsupported image format: {image_format}")
        mime, suffix = self.FORMAT_MAP[image_format]
        if mime not in self.config.allowed_mime_types:
            raise InvalidImageError(f"image MIME type is disabled: {mime}")
        return ValidatedImage(width, height, mime, suffix)
