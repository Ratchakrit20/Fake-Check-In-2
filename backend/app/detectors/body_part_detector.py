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
from .ransac_verifier import RANSACVerifier


class BodyPartDetector:
    """Batched body-part segmentation with bounded in-memory mask caching."""

    def __init__(self, config: BodyPartsConfig, sift_max_dimension: int, reprojection_threshold: float = 5.0) -> None:
        self.config = config
        self.sift_max_dimension = sift_max_dimension
        self._model = None
        self._model_lock = Lock()
        self._inference_lock = Lock()
        self._cache: OrderedDict[str, dict[str, np.ndarray]] = OrderedDict()
        self._cache_lock = Lock()
        self.ransac = RANSACVerifier(reprojection_threshold)

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
            # Ultralytics model instances are not guaranteed to be safe across
            # concurrent requests. Recheck the cache after taking the inference
            # lock so concurrent pairs never segment the same image twice.
            with self._inference_lock:
                with self._cache_lock:
                    still_missing = []
                    for index in missing_indexes:
                        cached = self._cache.get(keys[index])
                        if cached is None:
                            still_missing.append(index)
                        else:
                            output[index] = cached
                            self._cache.move_to_end(keys[index])
                if still_missing:
                    sources = [np.asarray(images[index].convert("RGB")) for index in still_missing]
                    results = model.predict(sources, imgsz=self.config.image_size, conf=self.config.confidence, device=device, verbose=False)
                    for index, result in zip(still_missing, results):
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
    ) -> tuple[bool, bool, bool, dict[str, int], RansacResult, RansacResult]:
        masks_a, masks_b = self.segment_many([first, second])
        labels = set(self.config.identity_classes) | set(self.config.reuse_classes)

        def union_mask(masks: dict[str, np.ndarray], size: tuple[int, int]) -> np.ndarray:
            width, height = size
            union = np.zeros((height, width), dtype=bool)
            for label in labels:
                mask = masks.get(label)
                if mask is not None:
                    union |= mask
            return union

        foreground_a = union_mask(masks_a, matches.image_size_a)
        foreground_b = union_mask(masks_b, matches.image_size_b)

        def inside(mask: np.ndarray, point: np.ndarray) -> bool:
            x, y = np.rint(point).astype(int)
            return 0 <= y < mask.shape[0] and 0 <= x < mask.shape[1] and bool(mask[y, x])

        foreground_indexes, background_indexes = [], []
        for index, (point_a, point_b) in enumerate(zip(matches.points_a, matches.points_b)):
            in_a, in_b = inside(foreground_a, point_a), inside(foreground_b, point_b)
            if in_a and in_b:
                foreground_indexes.append(index)
            elif not in_a and not in_b:
                background_indexes.append(index)

        def subset(indexes: list[int]) -> SiftResult:
            selected = np.asarray(indexes, dtype=int)
            return SiftResult(
                keypoint_count_a=matches.keypoint_count_a,
                keypoint_count_b=matches.keypoint_count_b,
                raw_match_count=len(indexes),
                good_match_count=len(indexes),
                points_a=matches.points_a[selected] if indexes else np.empty((0, 2), dtype=np.float32),
                points_b=matches.points_b[selected] if indexes else np.empty((0, 2), dtype=np.float32),
                image_size_a=matches.image_size_a,
                image_size_b=matches.image_size_b,
            )

        foreground_matches = subset(foreground_indexes)
        background_matches = subset(background_indexes)
        foreground_ransac = self.ransac.verify(foreground_matches)
        background_ransac = self.ransac.verify(background_matches)

        def mask_coverage(points: np.ndarray, flags: list[bool], mask: np.ndarray) -> float:
            selected = points[np.asarray(flags, dtype=bool)] if flags else np.empty((0, 2))
            area = int(mask.sum())
            if len(selected) < 3 or area == 0:
                return 0.0
            return min(1.0, float(cv2.contourArea(cv2.convexHull(selected.astype(np.float32)))) / area)

        foreground_ransac.coverage_a = mask_coverage(foreground_matches.points_a, foreground_ransac.inlier_mask, foreground_a)
        foreground_ransac.coverage_b = mask_coverage(foreground_matches.points_b, foreground_ransac.inlier_mask, foreground_b)
        foreground_ransac.min_coverage = min(foreground_ransac.coverage_a, foreground_ransac.coverage_b)
        background_ransac.coverage_a = mask_coverage(background_matches.points_a, background_ransac.inlier_mask, ~foreground_a)
        background_ransac.coverage_b = mask_coverage(background_matches.points_b, background_ransac.inlier_mask, ~foreground_b)
        background_ransac.min_coverage = min(background_ransac.coverage_a, background_ransac.coverage_b)

        counts: dict[str, int] = {}
        for local_index, is_inlier in enumerate(foreground_ransac.inlier_mask):
            if not is_inlier:
                continue
            index = foreground_indexes[local_index]
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
        return body_gate, body_suspected, similar_person_only, counts, foreground_ransac, background_ransac
