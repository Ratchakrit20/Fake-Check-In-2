from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
from pydantic import BaseModel

from .enums import RelationClassification, RelationshipLevel, ReuseVerdict


@dataclass(slots=True)
class SiftResult:
    keypoint_count_a: int = 0
    keypoint_count_b: int = 0
    raw_match_count: int = 0
    good_match_count: int = 0
    points_a: np.ndarray = field(default_factory=lambda: np.empty((0, 2), dtype=np.float32))
    points_b: np.ndarray = field(default_factory=lambda: np.empty((0, 2), dtype=np.float32))
    image_size_a: tuple[int, int] = (0, 0)
    image_size_b: tuple[int, int] = (0, 0)


@dataclass(slots=True)
class RansacResult:
    homography_found: bool = False
    inlier_count: int = 0
    outlier_count: int = 0
    inlier_ratio: float = 0.0
    transform_matrix: list[list[float]] | None = None
    inlier_mask: list[bool] = field(default_factory=list)
    coverage_a: float = 0.0
    coverage_b: float = 0.0
    min_coverage: float = 0.0


@dataclass(slots=True)
class PairEvidence:
    exact_duplicate: bool = False
    phash_distance: int | None = None
    phash_normal_distance: int | None = None
    phash_flip_distance: int | None = None
    phash_rotation_distances: dict[str, int] = field(default_factory=dict)
    phash_max_distance: int = 64
    embedding_similarity: float | None = None
    sift_good_matches: int = 0
    sift_reference_features: int = 0
    ransac_inliers: int = 0
    ransac_inlier_ratio: float = 0.0
    flip_detected: bool = False
    rotation_degrees: int = 0
    detected_transform: str = "original"
    scene_change_suspected: bool = False
    body_reuse_gate: bool = False
    body_reuse_suspected: bool = False
    similar_person_only: bool = False
    body_part_inliers: dict[str, int] = field(default_factory=dict)
    foreground_ransac_inliers: int = 0
    foreground_ransac_ratio: float = 0.0
    foreground_coverage: float = 0.0
    foreground_source_reuse: bool = False
    repeated_checkin_suspected: bool = False
    background_ransac_inliers: int = 0
    background_ransac_ratio: float = 0.0
    background_coverage: float = 0.0
    same_location_suspected: bool = False
    ransac_coverage: float = 0.0
    recapture_suspected: bool = False
    blur_variance_a: float = 0.0
    blur_variance_b: float = 0.0
    blurred_crop_suspected: bool = False
    whole_image_fallback_used: bool = False
    person_mask_used: bool = False
    person_detected_a: bool = False
    person_detected_b: bool = False


class RelationshipResult(BaseModel):
    score: float
    decision: RelationshipLevel
    classification: RelationClassification
    reuse_verdict: ReuseVerdict
    reasons: list[str]
    evidence: dict[str, Any]
    visualizations: dict[str, str] = {}
