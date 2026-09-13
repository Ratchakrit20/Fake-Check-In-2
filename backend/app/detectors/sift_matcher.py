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
    ) -> None:
        self.ratio_threshold = ratio_threshold
        self.max_dimension = max_dimension
        self.contrast_threshold = contrast_threshold
        self.edge_threshold = edge_threshold
        self.sigma = sigma

    def _gray(self, image: Image.Image) -> np.ndarray:
        rgb = np.asarray(image.convert("RGB"))
        height, width = rgb.shape[:2]
        scale = min(1.0, self.max_dimension / max(height, width))
        if scale < 1.0:
            rgb = cv2.resize(rgb, (round(width * scale), round(height * scale)), interpolation=cv2.INTER_AREA)
        gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
        return cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(gray)

    def match(self, first: Image.Image, second: Image.Image) -> SiftResult:
        # One detector per call makes concurrent CPU verification thread-safe.
        detector = cv2.SIFT_create(
            contrastThreshold=self.contrast_threshold,
            edgeThreshold=self.edge_threshold,
            sigma=self.sigma,
        )
        gray_a, gray_b = self._gray(first), self._gray(second)
        keypoints_a, descriptors_a = detector.detectAndCompute(gray_a, None)
        keypoints_b, descriptors_b = detector.detectAndCompute(gray_b, None)
        result = SiftResult(
            keypoint_count_a=len(keypoints_a),
            keypoint_count_b=len(keypoints_b),
            image_size_a=(gray_a.shape[1], gray_a.shape[0]),
            image_size_b=(gray_b.shape[1], gray_b.shape[0]),
        )
        if descriptors_a is None or descriptors_b is None or len(descriptors_a) < 2 or len(descriptors_b) < 2:
            return result
        pairs = cv2.BFMatcher(cv2.NORM_L2).knnMatch(descriptors_a, descriptors_b, k=2)
        valid_pairs = [pair for pair in pairs if len(pair) == 2]
        good = [near for near, far in valid_pairs if near.distance < self.ratio_threshold * far.distance]
        result.raw_match_count = len(valid_pairs)
        result.good_match_count = len(good)
        result.points_a = np.float32([keypoints_a[item.queryIdx].pt for item in good])
        result.points_b = np.float32([keypoints_b[item.trainIdx].pt for item in good])
        return result
