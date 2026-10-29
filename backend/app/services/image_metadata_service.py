"""Small, reusable readers for capture metadata embedded in image files."""

from datetime import datetime

from PIL import ExifTags, Image


def extract_capture_datetime(image: Image.Image) -> str | None:
    """Return the camera's original capture time from EXIF when available.

    EXIF times have no timezone in the source image, so this keeps their
    original ``YYYY-MM-DD HH:MM:SS`` value instead of inventing one.
    """
    try:
        exif = image.getexif()
        exif_ifd = exif.get_ifd(ExifTags.IFD.Exif)
        value = (
            exif_ifd.get(ExifTags.Base.DateTimeOriginal)
            or exif.get(ExifTags.Base.DateTimeOriginal)
            or exif.get(ExifTags.Base.DateTime)
        )
    except (AttributeError, KeyError, OSError, TypeError, ValueError):
        return None
    if not isinstance(value, str):
        return None
    try:
        # EXIF has no timezone metadata; retain its wall-clock time as naive.
        return datetime.strptime(value, "%Y:%m:%d %H:%M:%S").strftime("%Y-%m-%d %H:%M:%S")  # noqa: DTZ007
    except ValueError:
        return None
