from types import SimpleNamespace

import numpy as np
from PIL import Image

from backend.app.detectors.body_part_detector import BodyPartDetector
from backend.app.domain.schemas import RansacResult, SiftResult


def test_person_mask_can_split_foreground_when_organ_masks_are_empty(monkeypatch):
    config = SimpleNamespace(
        identity_classes=["head", "neck"],
        reuse_classes=["torso", "uarm"],
        major_classes=["torso", "uarm"],
        min_reuse_classes=2,
        min_reuse_inliers=18,
        min_major_inliers=10,
        identity_min_inliers=50,
        single_part_suspect_min_inliers=18,
    )
    detector = BodyPartDetector(config, sift_max_dimension=100)
    monkeypatch.setattr(detector, "segment_many", lambda images: [{}, {}])
    monkeypatch.setattr(
        detector.ransac,
        "verify",
        lambda matches: RansacResult(
            homography_found=matches.good_match_count >= 4,
            inlier_count=matches.good_match_count,
            inlier_ratio=1.0 if matches.good_match_count else 0.0,
            inlier_mask=[True] * matches.good_match_count,
        ),
    )
    points = np.array([[20, 20], [30, 20], [20, 30], [30, 30]], dtype=np.float32)
    matches = SiftResult(
        good_match_count=4,
        points_a=points,
        points_b=points.copy(),
        image_size_a=(100, 100),
        image_size_b=(100, 100),
    )
    person_mask = np.zeros((100, 100), dtype=bool)
    person_mask[10:50, 10:50] = True

    body_gate, _, _, counts, foreground, background = detector.verify_matches(
        Image.new("RGB", (100, 100)),
        Image.new("RGB", (100, 100)),
        matches,
        RansacResult(),
        (person_mask, person_mask),
    )

    assert foreground.inlier_count == 4
    assert background.inlier_count == 0
    assert body_gate is False
    assert counts == {}
