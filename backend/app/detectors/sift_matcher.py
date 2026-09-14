import hashlib
from collections import OrderedDict
from concurrent.futures import Future
from threading import Lock

import cv2
import numpy as np
from PIL import Image

from ..domain.schemas import SiftResult


class SIFTMatcher:
    def __init__(
        self,
        ratio_threshold: float,
        max_dimension: int = 1280,
        contrast_threshold: float = 0.02,
        edge_threshold: float = 15,
        sigma: float = 1.2,
        cache_size: int = 128,
    ) -> None:
        self.ratio_threshold = ratio_threshold
        self.max_dimension = max_dimension
        self.contrast_threshold = contrast_threshold
        self.edge_threshold = edge_threshold
        self.sigma = sigma
        self.cache_size = cache_size
        self._cache: OrderedDict[str, tuple[list, np.ndarray | None, tuple[int, int]]] = OrderedDict()
        self._inflight: dict[str, Future] = {}
        self._cache_lock = Lock()

    def _gray(self, image: Image.Image) -> np.ndarray:
        rgb = np.asarray(image.convert("RGB"))
        height, width = rgb.shape[:2]
        scale = min(1.0, self.max_dimension / max(height, width))
        if scale < 1.0:
            rgb = cv2.resize(rgb, (round(width * scale), round(height * scale)), interpolation=cv2.INTER_AREA)
        gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
        return cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(gray)

    @staticmethod
    def _cache_key(image: Image.Image) -> str:
        rgb = image.convert("RGB")
        digest = hashlib.sha256()
        digest.update(f"{rgb.width}x{rgb.height}:RGB".encode())
        digest.update(rgb.tobytes())
        return digest.hexdigest()

    def _features(self, image: Image.Image) -> tuple[list, np.ndarray | None, tuple[int, int]]:
        key = self._cache_key(image)
        with self._cache_lock:
            cached = self._cache.get(key)
            if cached is not None:
                self._cache.move_to_end(key)
                return cached
            future = self._inflight.get(key)
            owner = future is None
            if owner:
                future = Future()
                self._inflight[key] = future
        if not owner:
            return future.result()
        try:
            gray = self._gray(image)
            # A detector per uncached image keeps OpenCV work thread-safe.
            detector = cv2.SIFT_create(
                contrastThreshold=self.contrast_threshold,
                edgeThreshold=self.edge_threshold,
                sigma=self.sigma,
            )
            keypoints, descriptors = detector.detectAndCompute(gray, None)
            result = (keypoints, descriptors, (gray.shape[1], gray.shape[0]))
            with self._cache_lock:
                self._cache[key] = result
                self._cache.move_to_end(key)
                while len(self._cache) > self.cache_size:
                    self._cache.popitem(last=False)
                self._inflight.pop(key, None)
            future.set_result(result)
            return result
        except Exception as exc:
            with self._cache_lock:
                self._inflight.pop(key, None)
            future.set_exception(exc)
            raise

    def match(self, first: Image.Image, second: Image.Image) -> SiftResult:
        keypoints_a, descriptors_a, size_a = self._features(first)
        keypoints_b, descriptors_b, size_b = self._features(second)
        result = SiftResult(
            keypoint_count_a=len(keypoints_a),
            keypoint_count_b=len(keypoints_b),
            image_size_a=size_a,
            image_size_b=size_b,
        )
        if descriptors_a is None or descriptors_b is None or len(descriptors_a) < 2 or len(descriptors_b) < 2:
            return result
        # FLANN's KD-tree avoids the quadratic brute-force cost on detailed
        # images. Reciprocal Lowe matches are both faster downstream and less
        # prone to repeated-pattern false positives.
        matcher = cv2.FlannBasedMatcher({"algorithm": 1, "trees": 5}, {"checks": 64})
        forward_pairs = matcher.knnMatch(descriptors_a, descriptors_b, k=2)
        reverse_pairs = matcher.knnMatch(descriptors_b, descriptors_a, k=2)
        forward = {
            near.queryIdx: near
            for pair in forward_pairs
            if len(pair) == 2
            for near, far in [pair]
            if near.distance < self.ratio_threshold * far.distance
        }
        reverse = {
            near.queryIdx: near.trainIdx
            for pair in reverse_pairs
            if len(pair) == 2
            for near, far in [pair]
            if near.distance < self.ratio_threshold * far.distance
        }
        good = [match for query_index, match in forward.items() if reverse.get(match.trainIdx) == query_index]
        result.raw_match_count = sum(len(pair) == 2 for pair in forward_pairs)
        result.good_match_count = len(good)
        result.points_a = np.float32([keypoints_a[item.queryIdx].pt for item in good])
        result.points_b = np.float32([keypoints_b[item.trainIdx].pt for item in good])
        return result
