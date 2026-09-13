from __future__ import annotations

import hashlib
import os
from collections import OrderedDict
from pathlib import Path
from threading import Lock

import cv2
import numpy as np
from PIL import Image

from ..core.config import BodyPartsConfig
from ..core.exceptions import FeatureMatchingError
from ..domain.schemas import RansacResult, SiftResult


class BodyPartDetector:
    """Batched body-part segmentation with bounded in-memory mask caching."""

    def __init__(self, config: BodyPartsConfig, sift_max_dimension: int) -> None:
        self.config = config
        self.sift_max_dimension = sift_max_dimension
        self._model = None
        self._model_lock = Lock()
        self._inference_lock = Lock()
        self._cache: OrderedDict[str, dict[str, np.ndarray]] = OrderedDict()
        self._cache_lock = Lock()

    def _load(self):
        if self._model is not None:
            return self._model
        with self._model_lock:
            if self._model is None:
                try:
                    config_dir = Path(self.config.config_dir).resolve()
                    config_dir.mkdir(parents=True, exist_ok=True)
                    os.environ["YOLO_CONFIG_DIR"] = str(config_dir)
                    from ultralytics import YOLO

                    model_path = Path(self.config.model_path).resolve()
                    if not model_path.is_file():
                        raise FeatureMatchingError(f"body-part model not found: {model_path}")
                    self._model = YOLO(str(model_path))
                except FeatureMatchingError:
                    raise
                except Exception as exc:
                    raise FeatureMatchingError(f"unable to load body-part model: {exc}") from exc
        return self._model

    @staticmethod
    def _key(image: Image.Image) -> str:
        return hashlib.sha256(image.tobytes()).hexdigest()

    def _target_shape(self, image: Image.Image) -> tuple[int, int]:
        width, height = image.size
        scale = min(1.0, self.sift_max_dimension / max(height, width))
        return round(height * scale), round(width * scale)

    def segment_many(self, images: list[Image.Image]) -> list[dict[str, np.ndarray]]:
        keys = [self._key(image) for image in images]
        output: list[dict[str, np.ndarray] | None] = []
        missing_indexes: list[int] = []
        with self._cache_lock:
            for index, key in enumerate(keys):
                cached = self._cache.get(key)
                output.append(cached)
                if cached is None:
                    missing_indexes.append(index)
                else:
                    self._cache.move_to_end(key)
        if missing_indexes:
            model = self._load()
            if self.config.device == "auto":
                import torch

                device = 0 if torch.cuda.is_available() else "cpu"
            else:
                device = self.config.device
            sources = [np.asarray(images[index].convert("RGB")) for index in missing_indexes]
            # Ultralytics model instances are not guaranteed to be safe across
            # concurrent requests. CPU feature matching can remain parallel.
            with self._inference_lock:
                results = model.predict(sources, imgsz=self.config.image_size, conf=self.config.confidence, device=device, verbose=False)
            for index, result in zip(missing_indexes, results):
                height, width = self._target_shape(images[index])
                masks: dict[str, np.ndarray] = {}
                if result.masks is not None and result.boxes is not None:
                    names = result.names
                    for raw_mask, raw_class in zip(result.masks.data.cpu().numpy(), result.boxes.cls.int().cpu().tolist()):
                        label = str(names[int(raw_class)])
                        resized = cv2.resize(raw_mask, (width, height), interpolation=cv2.INTER_NEAREST) >= 0.5
                        masks[label] = resized if label not in masks else masks[label] | resized
                output[index] = masks
                with self._cache_lock:
                    self._cache[keys[index]] = masks
                    while len(self._cache) > self.config.cache_size:
                        self._cache.popitem(last=False)
        return [item or {} for item in output]

    def verify_matches(
        self,
        first: Image.Image,
        second: Image.Image,
        matches: SiftResult,
        ransac: RansacResult,
    ) -> tuple[bool, bool, bool, dict[str, int]]:
        if not ransac.inlier_mask:
            return False, False, False, {}
        masks_a, masks_b = self.segment_many([first, second])
        counts: dict[str, int] = {}
        for index, is_inlier in enumerate(ransac.inlier_mask):
            if not is_inlier:
                continue
            ax, ay = np.rint(matches.points_a[index]).astype(int)
            bx, by = np.rint(matches.points_b[index]).astype(int)
            for label in set(masks_a) & set(masks_b):
                mask_a, mask_b = masks_a[label], masks_b[label]
                inside = (
                    0 <= ay < mask_a.shape[0]
                    and 0 <= ax < mask_a.shape[1]
                    and 0 <= by < mask_b.shape[0]
                    and 0 <= bx < mask_b.shape[1]
                )
                if inside and mask_a[ay, ax] and mask_b[by, bx]:
                    counts[label] = counts.get(label, 0) + 1
        reuse_classes = [label for label in self.config.reuse_classes if counts.get(label, 0) > 0]
        reuse_inliers = sum(counts.get(label, 0) for label in self.config.reuse_classes)
        major_inliers = sum(counts.get(label, 0) for label in self.config.major_classes)
        body_gate = (
            len(reuse_classes) >= self.config.min_reuse_classes
            and reuse_inliers >= self.config.min_reuse_inliers
            and major_inliers >= self.config.min_major_inliers
        )
        identity_inliers = sum(counts.get(label, 0) for label in self.config.identity_classes)
        strongest_reuse_part = max((counts.get(label, 0) for label in self.config.reuse_classes), default=0)
        body_suspected = not body_gate and strongest_reuse_part >= self.config.single_part_suspect_min_inliers
        similar_person_only = identity_inliers >= self.config.identity_min_inliers and not body_gate and not body_suspected
        return body_gate, body_suspected, similar_person_only, counts
