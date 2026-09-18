import numpy as np
from PIL import Image

from backend.app.domain.schemas import RansacResult, SiftResult
from backend.app.services.evidence_visualizer import render_body_masks, render_change_heatmap, render_verified_matches


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


def test_change_heatmap_reports_foreground_and_background_without_changing_verdict():
    first = Image.new("RGB", (100, 80), "white")
    second_array = np.full((80, 100, 3), 255, dtype=np.uint8)
    second_array[:, 60:] = 0
    second = Image.fromarray(second_array)
    mask = np.zeros((80, 100), dtype=bool)
    mask[:, :50] = True
    matches = SiftResult(image_size_a=(100, 80), image_size_b=(100, 80))
    alignment = RansacResult(
        homography_found=True,
        transform_matrix=np.eye(3).tolist(),
    )

    result, foreground_change, background_change = render_change_heatmap(
        first, second, matches, alignment, mask, mask
    )

    assert result is not None and result.startswith("data:image/jpeg;base64,")
    assert foreground_change is not None and foreground_change < 0.05
    assert background_change is not None and background_change > 0.5
