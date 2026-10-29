"""Lazy, cached access to auxiliary AI models used by image analysis."""

from __future__ import annotations

import hashlib
import logging
from collections import OrderedDict
from threading import Lock
from time import perf_counter

import numpy as np
from PIL import Image

from ..core.config import LatLongModelConfig

logger = logging.getLogger(__name__)


class AIModelService:
    """Detect metadata regions that should not contribute SIFT keypoints."""

    def __init__(self, config: LatLongModelConfig) -> None:
        self.config = config
        self._model = None
        self._model_lock = Lock()
        self._inference_lock = Lock()
        self._cache_lock = Lock()
        self._box_cache: OrderedDict[str, tuple[tuple[str, int, int, int, int, float], ...]] = OrderedDict()

    def _get_model(self):
        if self._model is not None:
            return self._model
        with self._model_lock:
            if self._model is None:
                started = perf_counter()
                from ultralytics import YOLO

                self._model = YOLO(str(self.config.model_path))
                logger.info("lat-long detector loaded in %.3fs: %s", perf_counter() - started, self.config.model_path)
        return self._model

    @staticmethod
    def _normalized_label(name: object) -> str:
        return str(name).lower().replace("_", "").replace("-", "").replace(" ", "")

    @classmethod
    def _class_confidence_threshold(cls, name: object, config: LatLongModelConfig) -> float | None:
        normalized = cls._normalized_label(name)
        if normalized in {"latlong", "latitudeandlongitude", "coordinates", "coordinate"}:
            return config.lat_long_confidence
        if normalized in {"datetime", "dateandtime", "timestamp"}:
            return config.datetime_confidence
        return None

    def _detected_boxes(self, rgb: Image.Image, key: str) -> tuple[tuple[str, int, int, int, int, float], ...] | None:
        with self._cache_lock:
            if key in self._box_cache:
                self._box_cache.move_to_end(key)
                return self._box_cache[key]
        try:
            model = self._get_model()
            thresholds = [
                self.config.lat_long_confidence,
                self.config.datetime_confidence,
                self.config.datetime_report_confidence,
            ]
            with self._inference_lock:
                results = model.predict(
                    source=np.asarray(rgb),
                    imgsz=self.config.image_size,
                    conf=min(thresholds),
                    device=None if self.config.device == "auto" else self.config.device,
                    verbose=False,
                )
            detected_boxes = []
            names = getattr(model, "names", {})
            for result in results:
                boxes = getattr(result, "boxes", None)
                if boxes is None:
                    continue
                coordinates = boxes.xyxy.cpu().numpy()
                confidences = boxes.conf.cpu().numpy()
                classes = boxes.cls.cpu().numpy().astype(int)
                for box, confidence, class_id in zip(coordinates, confidences, classes, strict=False):
                    label = names.get(int(class_id), str(class_id)) if isinstance(names, dict) else names[int(class_id)]
                    threshold = self._class_confidence_threshold(label, self.config)
                    if threshold is None or confidence < min(thresholds):
                        continue
                    x1, y1, x2, y2 = (round(float(value)) for value in box)
                    pad_x = max(2, int((x2 - x1) * 0.04))
                    pad_y = max(2, int((y2 - y1) * 0.10))
                    x1, y1 = max(0, x1 - pad_x), max(0, y1 - pad_y)
                    x2, y2 = min(rgb.width, x2 + pad_x), min(rgb.height, y2 + pad_y)
                    if x2 > x1 and y2 > y1:
                        detected_boxes.append((self._normalized_label(label), x1, y1, x2, y2, float(confidence)))
            boxes = tuple(detected_boxes)
            with self._cache_lock:
                self._box_cache[key] = boxes
                self._box_cache.move_to_end(key)
                while len(self._box_cache) > self.config.cache_size:
                    self._box_cache.popitem(last=False)
            return boxes
        except Exception:
            logger.exception("lat-long detection failed; continuing without SIFT exclusion")
            return None

    def analyze_image(self, image: Image.Image) -> tuple[np.ndarray | None, bool]:
        """Return SIFT exclusion mask and SOA source hint for the LMR dataset."""
        if not self.config.enabled:
            return None, False
        rgb = image.convert("RGB")
        key = hashlib.sha256(f"{rgb.width}x{rgb.height}:".encode() + rgb.tobytes()).hexdigest()
        boxes = self._detected_boxes(rgb, key)
        if boxes is None or not boxes:
            return None, False
        mask = np.full((rgb.height, rgb.width), 255, dtype=np.uint8)
        datetime_detected = False
        for label, x1, y1, x2, y2, confidence in boxes:
            threshold = self._class_confidence_threshold(label, self.config)
            if threshold is None or confidence < threshold:
                continue
            is_datetime = label in {"datetime", "dateandtime", "timestamp"}
            if not is_datetime or self.config.datetime_enabled:
                mask[y1:y2, x1:x2] = 0
            datetime_detected |= (
                is_datetime
                and self.config.datetime_enabled
                and confidence >= self.config.datetime_report_confidence
            )
        mask.setflags(write=False)
        # In the user's LMR data, a detected datetime overlay is an agreed
        # indicator that the image came from SOA; it is metadata, not a match gate.
        return mask, datetime_detected

    def report_metadata(self, image: Image.Image) -> dict[str, object]:
        """Metadata for SOA reporting, independent of whether datetime is used by SIFT."""
        if not self.config.enabled:
            return {"model": "lat-long/v1", "datetime": [], "error": "detector_disabled"}
        rgb = image.convert("RGB")
        key = hashlib.sha256(f"{rgb.width}x{rgb.height}:".encode() + rgb.tobytes()).hexdigest()
        boxes = self._detected_boxes(rgb, key)
        if boxes is None:
            return {"model": "lat-long/v1", "datetime": [], "error": "detection_failed"}
        datetime_boxes = []
        lat_long_boxes = []
        for label, x1, y1, x2, y2, confidence in boxes or ():
            threshold = self._class_confidence_threshold(label, self.config)
            if threshold is None:
                continue
            detection = {"bbox": [x1, y1, x2, y2], "confidence": round(confidence, 5)}
            if label in {"datetime", "dateandtime", "timestamp"} and confidence >= self.config.datetime_report_confidence:
                datetime_boxes.append(detection)
            elif label in {"latlong", "latitudeandlongitude", "coordinates", "coordinate"} and confidence >= self.config.lat_long_confidence:
                lat_long_boxes.append(detection)
        return {
            "model": "lat-long/v1",
            "metadata_version": 2,
            "lat_long": lat_long_boxes,
            "datetime": datetime_boxes,
        }

    def sift_exclusion_mask(self, image: Image.Image) -> np.ndarray | None:
        """Return an 8-bit SIFT mask (255=keep, 0=exclude), or None on fallback."""
        mask, _datetime_detected = self.analyze_image(image)
        return mask
