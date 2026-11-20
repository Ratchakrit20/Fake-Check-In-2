import numpy as np
from PIL import Image

from backend.app.core.config import get_settings
from backend.app.services.image_quality_service import UNVERIFIABLE, VERIFIABLE, ImageQualityService


def test_dark_flat_scene_ignores_bright_coordinate_strip():
    pixels = np.full((200, 300, 3), 52, dtype=np.uint8)
    pixels[180:, 170:] = 255
    result = ImageQualityService(get_settings().image_quality).assess(Image.fromarray(pixels))
    assert result.status == UNVERIFIABLE
    assert result.reason == "dark_flat_scene"


def test_dark_scene_with_visible_structure_remains_verifiable():
    pixels = np.full((200, 300, 3), 20, dtype=np.uint8)
    pixels[30:150, 70:180] = 115
    result = ImageQualityService(get_settings().image_quality).assess(Image.fromarray(pixels))
    assert result.status == VERIFIABLE
