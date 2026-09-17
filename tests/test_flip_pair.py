import io

import numpy as np
from PIL import Image, ImageDraw, ImageOps

from backend.app.core.config import get_settings
from backend.app.services.pair_analysis_service import PairAnalysisService


def _jpeg(image: Image.Image, quality: int) -> bytes:
    output = io.BytesIO()
    image.save(output, format="JPEG", quality=quality)
    return output.getvalue()


def test_mirrored_recompressed_image_is_detected():
    rng = np.random.default_rng(42)
    image = Image.fromarray(rng.integers(0, 256, (360, 240, 3), dtype=np.uint8))
    draw = ImageDraw.Draw(image)
    draw.rectangle((15, 30, 85, 155), fill="red")
    draw.ellipse((130, 190, 220, 310), fill="blue")
    settings = get_settings().model_copy(deep=True)
    settings.body_parts.enabled = False
    result = PairAnalysisService(settings).analyze_bytes(
        _jpeg(image, 92),
        _jpeg(ImageOps.mirror(image), 76),
        include_visualizations=True,
    )

    assert result.evidence["flip_detected"] is True
    assert result.reuse_verdict.value == "reused"
    assert result.visualizations["aligned_pair"].startswith("data:image/jpeg;base64,")


def test_rotated_recompressed_images_are_detected():
    rng = np.random.default_rng(84)
    image = Image.fromarray(rng.integers(0, 256, (360, 240, 3), dtype=np.uint8))
    draw = ImageDraw.Draw(image)
    draw.rectangle((18, 35, 90, 165), fill="orange")
    draw.ellipse((135, 195, 225, 315), fill="green")
    settings = get_settings().model_copy(deep=True)
    settings.body_parts.enabled = False

    rotations = (
        Image.Transpose.ROTATE_270,
        Image.Transpose.ROTATE_180,
        Image.Transpose.ROTATE_90,
    )
    for rotation in rotations:
        rotated = image.transpose(rotation)
        result = PairAnalysisService(settings).analyze_bytes(_jpeg(image, 92), _jpeg(rotated, 76))

        assert result.evidence["rotation_degrees"] in {90, 180, 270}
        assert result.evidence["ransac_inliers"] >= settings.ransac.min_inliers
        assert result.reuse_verdict.value == "reused"
