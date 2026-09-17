import numpy as np
from PIL import Image

from backend.app.domain.schemas import RansacResult, SiftResult
from backend.app.services.evidence_visualizer import render_body_masks, render_person_masks, render_verified_matches


def test_verified_match_visualization_is_a_jpeg_data_url():
    image = Image.new("RGB", (100, 80), "white")
    matches = SiftResult(
        good_match_count=4,
        points_a=np.array([[10, 10], [30, 20], [50, 40], [80, 60]], dtype=np.float32),
        points_b=np.array([[12, 11], [32, 21], [52, 41], [82, 61]], dtype=np.float32),
        image_size_a=(100, 80),
        image_size_b=(100, 80),
    )
    result = render_verified_matches(image, image, matches, RansacResult(inlier_mask=[True] * 4))
    assert result is not None and result.startswith("data:image/jpeg;base64,")


def test_body_mask_visualization_is_a_jpeg_data_url():
    image = Image.new("RGB", (100, 80), "white")
    mask = np.zeros((80, 100), dtype=bool)
    mask[10:40, 20:60] = True
    result = render_body_masks(image, image, {"torso": mask}, {"torso": mask})
    assert result is not None and result.startswith("data:image/jpeg;base64,")


def test_person_mask_visualization_is_a_jpeg_data_url():
    image = Image.new("RGB", (100, 80), "white")
    mask = np.zeros((80, 100), dtype=bool)
    mask[8:72, 30:70] = True
    result = render_person_masks(image, image, mask, mask)
    assert result is not None and result.startswith("data:image/jpeg;base64,")
