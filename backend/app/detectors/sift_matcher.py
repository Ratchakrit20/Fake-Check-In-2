import hashlib
import os
import shutil
import zipfile
from collections import OrderedDict
from concurrent.futures import Future
from pathlib import Path
from threading import Lock, get_ident

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
        cache_dir: Path | None = None,
        disk_cache_max_bytes: int = 5 * 1024**3,
    ) -> None:
        self.ratio_threshold = ratio_threshold
        self.max_dimension = max_dimension
        self.contrast_threshold = contrast_threshold
        self.edge_threshold = edge_threshold
        self.sigma = sigma
        self.cache_size = cache_size
        self.cache_dir = Path(cache_dir) if cache_dir is not None else None
        self.disk_cache_max_bytes = max(0, int(disk_cache_max_bytes))
        self._disk_writes_since_prune = 0
        self._cache: OrderedDict[str, tuple[list, np.ndarray | None, tuple[int, int]]] = OrderedDict()
        self._inflight: dict[str, Future] = {}
        self._cache_lock = Lock()
        if self.cache_dir is not None:
            try:
                self.cache_dir.mkdir(parents=True, exist_ok=True)
            except OSError:
                self.cache_dir = None

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

    def _features_cache_key(self, image: Image.Image, exclusion_mask: np.ndarray | None = None) -> str:
        key_digest = hashlib.sha256()
        key_digest.update(b"sift-features-v2:")
        key_digest.update(self._cache_key(image).encode())
        key_digest.update(
            f"|{cv2.__version__}|{self.max_dimension}|{self.contrast_threshold:.12g}|{self.edge_threshold:.12g}|{self.sigma:.12g}".encode()
        )
        if exclusion_mask is not None:
            key_digest.update(f"|mask:{exclusion_mask.dtype}:{exclusion_mask.shape}".encode())
            key_digest.update(hashlib.sha256(exclusion_mask.tobytes()).digest())
        return key_digest.hexdigest()

    def _features(self, image: Image.Image, exclusion_mask: np.ndarray | None = None) -> tuple[list, np.ndarray | None, tuple[int, int]]:
        key = self._features_cache_key(image, exclusion_mask)
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
            result = self._read_disk_cache(key)
            if result is None:
                gray = self._gray(image)
                sift_mask = None
                if exclusion_mask is not None:
                    sift_mask = cv2.resize(
                        exclusion_mask.astype(np.uint8),
                        (gray.shape[1], gray.shape[0]),
                        interpolation=cv2.INTER_NEAREST,
                    )
                # A detector per uncached image keeps OpenCV work thread-safe.
                detector = cv2.SIFT_create(
                    contrastThreshold=self.contrast_threshold,
                    edgeThreshold=self.edge_threshold,
                    sigma=self.sigma,
                )
                keypoints, descriptors = detector.detectAndCompute(gray, sift_mask)
                result = (keypoints, descriptors, (gray.shape[1], gray.shape[0]))
                self._write_disk_cache(key, result)
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

    def _disk_cache_path(self, key: str) -> Path | None:
        return self.cache_dir / f"{key}.npz" if self.cache_dir is not None else None

    def _read_disk_cache(self, key: str) -> tuple[list, np.ndarray | None, tuple[int, int]] | None:
        cache_path = self._disk_cache_path(key)
        if cache_path is None or not cache_path.is_file():
            return None
        try:
            with np.load(cache_path, allow_pickle=False) as saved:
                data = saved["keypoints"]
                descriptors = saved["descriptors"]
                width, height = (int(value) for value in saved["image_size"])
            keypoints = [
                cv2.KeyPoint(
                    float(row[0]), float(row[1]), float(row[2]), float(row[3]),
                    float(row[4]), int(row[5]), int(row[6]),
                )
                for row in data
            ]
            if descriptors.size == 0:
                descriptors = None
            else:
                descriptors = np.asarray(descriptors, dtype=np.float32)
            try:
                os.utime(cache_path, None)
            except OSError:
                pass
            return keypoints, descriptors, (width, height)
        except (OSError, ValueError, KeyError, EOFError, zipfile.BadZipFile, cv2.error):
            try:
                cache_path.unlink(missing_ok=True)
            except OSError:
                pass
            return None

    def _write_disk_cache(
        self,
        key: str,
        result: tuple[list, np.ndarray | None, tuple[int, int]],
    ) -> None:
        cache_path = self._disk_cache_path(key)
        if cache_path is None or self.disk_cache_max_bytes <= 0:
            return
        keypoints, descriptors, image_size = result
        if descriptors is None:
            descriptor_array = np.empty((0, 128), dtype=np.float32)
        else:
            descriptor_array = np.asarray(descriptors, dtype=np.float32)
        keypoint_array = np.asarray(
            [
                [point.pt[0], point.pt[1], point.size, point.angle, point.response, point.octave, point.class_id]
                for point in keypoints
            ],
            dtype=np.float64,
        ).reshape((-1, 7))
        temp_path = cache_path.with_name(f"{key}.{os.getpid()}.{get_ident()}.tmp")
        try:
            with temp_path.open("wb") as handle:
                np.savez(
                    handle,
                    keypoints=keypoint_array,
                    descriptors=descriptor_array,
                    image_size=np.asarray(image_size, dtype=np.int32),
                )
            if temp_path.stat().st_size <= self.disk_cache_max_bytes:
                try:
                    os.replace(temp_path, cache_path)
                except OSError:
                    # Some Windows sandboxed volumes do not implement rename.
                    # A partial cache is detected and ignored on the next read.
                    shutil.copyfile(temp_path, cache_path)
                self._disk_writes_since_prune += 1
                if self._disk_writes_since_prune >= 32:
                    self._prune_disk_cache()
                    self._disk_writes_since_prune = 0
        except (OSError, ValueError, TypeError):
            # A full or read-only cache must never make image analysis fail.
            pass
        finally:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass

    def _prune_disk_cache(self) -> None:
        if self.cache_dir is None:
            return
        try:
            entries = [(path.stat().st_mtime, path, path.stat().st_size) for path in self.cache_dir.glob("*.npz")]
            total_bytes = sum(size for _, _, size in entries)
            if total_bytes <= self.disk_cache_max_bytes:
                return
            for _, path, size in sorted(entries):
                path.unlink(missing_ok=True)
                total_bytes -= size
                if total_bytes <= int(self.disk_cache_max_bytes * 0.9):
                    break
        except OSError:
            # Cache eviction is best-effort; analysis remains independent of it.
            return

    def match(
        self,
        first: Image.Image,
        second: Image.Image,
        exclusion_mask_a: np.ndarray | None = None,
        exclusion_mask_b: np.ndarray | None = None,
    ) -> SiftResult:
        keypoints_a, descriptors_a, size_a = self._features(first, exclusion_mask_a)
        keypoints_b, descriptors_b, size_b = self._features(second, exclusion_mask_b)
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
