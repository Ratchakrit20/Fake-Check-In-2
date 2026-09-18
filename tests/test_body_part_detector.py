import numpy as np

from backend.app.detectors.body_part_detector import BodyPartDetector


def test_background_exclusion_adds_margin_without_covering_far_scene():
    foreground = np.zeros((100, 100), dtype=bool)
    foreground[30:70, 30:70] = True

    exclusion = BodyPartDetector._background_exclusion(foreground)

    assert exclusion[50, 50]
    assert exclusion[27, 50]
    assert not exclusion[2, 2]
