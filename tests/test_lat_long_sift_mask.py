from types import SimpleNamespace

import numpy as np
from PIL import Image

from backend.app.core.config import get_settings
from backend.app.detectors.sift_matcher import SIFTMatcher
from backend.app.services.ai_model_service import AIModelService
from backend.app.services.pair_analysis_service import PairAnalysisService


def test_lat_long_detection_masks_only_high_confidence_coordinate_boxes():
    settings = get_settings().ai_models_lat_long.model_copy(deep=True)
    settings.datetime_enabled = False
    settings.datetime_confidence = 0.95
    settings.datetime_report_confidence = 0.95
    service = AIModelService(settings)

    class Tensor:
        def __init__(self, values):
            self.values = np.asarray(values)

        def cpu(self):
            return self

        def numpy(self):
            return self.values

    class Model:
        def __init__(self):
            self.names = {0: "lat-long", 1: "datetime"}

        def predict(self, **_kwargs):
            return [SimpleNamespace(boxes=SimpleNamespace(
                xyxy=Tensor([[20, 20, 60, 40], [70, 20, 90, 40], [15, 50, 40, 70], [40, 50, 60, 70]]),
                conf=Tensor([0.95, 0.99, 0.89, 0.94]),
                cls=Tensor([0, 1, 0, 1]),
            ))]

    service._model = Model()
    image = Image.new("RGB", (100, 80))
    mask, is_soa = service.analyze_image(image)

    assert mask is not None
    assert is_soa is False  # datetime class is independently disabled by default
    assert mask[30, 40] == 0
    assert mask[30, 80] == 255
    assert mask[60, 25] == 255
    assert mask[70, 40] == 255
    report = service.report_metadata(image)
    assert len(report["datetime"]) == 1

    service.config.datetime_enabled = True
    service.config.datetime_confidence = 0.25
    service._box_cache.clear()
    mask, is_soa = service.analyze_image(image)
    assert mask is not None
    assert is_soa is True
    assert mask[30, 80] == 0  # enabled high-confidence datetime region is excluded
    assert mask[60, 50] == 0  # lower SIFT threshold is independent from report confidence
    assert len(service.report_metadata(image)["datetime"]) == 1  # the report still requires 0.95


def test_sift_does_not_extract_keypoints_inside_exclusion_mask():
    rng = np.random.default_rng(101)
    image = Image.fromarray(rng.integers(0, 256, (160, 160, 3), dtype=np.uint8))
    mask = np.full((160, 160), 255, dtype=np.uint8)
    mask[:, :80] = 0
    matcher = SIFTMatcher(0.75, max_dimension=320)

    keypoints, descriptors, _size = matcher._features(image, mask)

    assert descriptors is not None
    assert keypoints
    assert min(point.pt[0] for point in keypoints) >= 80


def test_rotation_transforms_coordinate_exclusion_mask_with_image():
    mask = np.full((3, 5), 255, dtype=np.uint8)
    mask[0, 0] = 0

    rotated = PairAnalysisService._transform_mask(mask, Image.Transpose.ROTATE_270)

    assert rotated.shape == (5, 3)
    assert rotated[0, 2] == 0
