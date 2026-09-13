import cv2
import numpy as np

from ..domain.schemas import RansacResult, SiftResult


class RANSACVerifier:
    def __init__(self, reprojection_threshold: float) -> None:
        self.reprojection_threshold = reprojection_threshold

    def verify(self, matches: SiftResult) -> RansacResult:
        if matches.good_match_count < 4:
            return RansacResult(outlier_count=matches.good_match_count)
        matrix, mask = cv2.findHomography(
            matches.points_a.reshape(-1, 1, 2),
            matches.points_b.reshape(-1, 1, 2),
            cv2.RANSAC,
            self.reprojection_threshold,
        )
        if matrix is None or mask is None:
            return RansacResult(outlier_count=matches.good_match_count)
        flags = [bool(value) for value in mask.ravel()]
        inliers = sum(flags)
        inlier_mask = np.asarray(flags, dtype=bool)

        def coverage(points: np.ndarray, size: tuple[int, int]) -> float:
            selected = points[inlier_mask]
            width, height = size
            if len(selected) < 3 or width <= 0 or height <= 0:
                return 0.0
            return min(1.0, float(cv2.contourArea(cv2.convexHull(selected))) / float(width * height))

        coverage_a = coverage(matches.points_a, matches.image_size_a)
        coverage_b = coverage(matches.points_b, matches.image_size_b)
        return RansacResult(
            homography_found=True,
            inlier_count=inliers,
            outlier_count=len(flags) - inliers,
            inlier_ratio=inliers / len(flags),
            transform_matrix=matrix.tolist(),
            inlier_mask=flags,
            coverage_a=coverage_a,
            coverage_b=coverage_b,
            min_coverage=min(coverage_a, coverage_b),
        )
