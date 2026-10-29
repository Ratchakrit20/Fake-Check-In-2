import io

from PIL import ExifTags, Image

from backend.app.services.image_metadata_service import extract_capture_datetime


def test_extract_capture_datetime_from_exif_original_timestamp():
    image = Image.new("RGB", (8, 8))
    exif = Image.Exif()
    exif[ExifTags.Base.DateTimeOriginal] = "2026:10:26 10:20:30"
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", exif=exif)
    buffer.seek(0)

    with Image.open(buffer) as decoded:
        assert extract_capture_datetime(decoded) == "2026-10-26 10:20:30"


def test_extract_capture_datetime_returns_none_when_exif_is_missing():
    with Image.new("RGB", (8, 8)) as image:
        assert extract_capture_datetime(image) is None
