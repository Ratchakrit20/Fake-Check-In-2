from __future__ import annotations

import io

import numpy as np
from PIL import Image, ImageOps

from ..core.config import Settings
from ..detectors.body_part_detector import BodyPartDetector
from ..detectors.flip_detector import FlipDetector
from ..detectors.image_quality_detector import ImageQualityDetector
from ..detectors.perceptual_hash_detector import PerceptualHashDetector
from ..detectors.ransac_verifier import RANSACVerifier
from ..detectors.sha256_detector import SHA256Detector
from ..detectors.sift_matcher import SIFTMatcher
from ..domain.interfaces import EmbeddingProvider
from ..domain.schemas import PairEvidence, RelationshipResult
from .evidence_visualizer import render_body_masks, render_verified_matches
from .relationship_scorer import RelationshipScorer


class PairAnalysisService:
    def __init__(self, settings: Settings, embedding_provider: EmbeddingProvider | None = None) -> None:
        self.settings = settings
        self.embedding_provider = embedding_provider
        self.phash = PerceptualHashDetector(settings.phash.hash_size, settings.flip_detection.horizontal)
        self.sift = SIFTMatcher(
            settings.sift.ratio_threshold,
            settings.sift.max_dimension,
            settings.sift.contrast_threshold,
            settings.sift.edge_threshold,
            settings.sift.sigma,
        )
        self.ransac = RANSACVerifier(settings.ransac.reprojection_threshold)
        self.flip = FlipDetector(self.sift, self.ransac)
        self.body_parts = BodyPartDetector(settings.body_parts, settings.sift.max_dimension) if settings.body_parts.enabled else None
        self.scorer = RelationshipScorer(settings.relationship)

    def analyze_bytes(
        self,
        first_content: bytes,
        second_content: bytes,
        embedding_similarity_override: float | None = None,
        include_visualizations: bool = False,
    ) -> RelationshipResult:
        exact = SHA256Detector.from_bytes(first_content) == SHA256Detector.from_bytes(second_content)
        if exact:
            return self.scorer.score(PairEvidence(exact_duplicate=True))
        with Image.open(io.BytesIO(first_content)) as opened_a, Image.open(io.BytesIO(second_content)) as opened_b:
            first, second = opened_a.convert("RGB"), opened_b.convert("RGB")
        hash_a, hash_b = self.phash.calculate(first), self.phash.calculate(second)
        blur_variance_a = ImageQualityDetector.blur_variance(first)
        blur_variance_b = ImageQualityDetector.blur_variance(second)
        normal_hash_distance = self.phash.distance(hash_a.original, hash_b.original)
        flip_hash_distance = (
            self.phash.distance(hash_a.original, hash_b.horizontal_flip) if hash_b.horizontal_flip is not None else None
        )
        embedding_similarity = embedding_similarity_override
        if embedding_similarity is None and self.embedding_provider is not None:
            embed_many = getattr(self.embedding_provider, "embed_many", None)
            if embed_many is not None:
                vector_a, vector_b = embed_many([first, second])
            else:
                vector_a, vector_b = self.embedding_provider.embed(first), self.embedding_provider.embed(second)
            embedding_similarity = float(np.dot(vector_a, vector_b) / max(np.linalg.norm(vector_a) * np.linalg.norm(vector_b), 1e-12))
        normal_sift = self.sift.match(first, second)
        normal_ransac = self.ransac.verify(normal_sift)
        best_sift, best_ransac, transform = normal_sift, normal_ransac, "original"
        if self.settings.flip_detection.horizontal:
            flipped_sift = self.sift.match(first, ImageOps.mirror(second))
            flipped_ransac = self.ransac.verify(flipped_sift)
            hash_confirms_flip = (
                flip_hash_distance is not None
                and flip_hash_distance <= self.settings.phash.max_hamming_distance
                and flip_hash_distance + 3 <= normal_hash_distance
            )
            geometry_confirms_flip = (
                flipped_ransac.inlier_count >= self.settings.ransac.min_inliers
                and flipped_ransac.inlier_ratio >= self.settings.ransac.min_inlier_ratio
                and flipped_ransac.inlier_ratio >= normal_ransac.inlier_ratio + 0.10
            )
            absolute_flip_geometry = (
                flipped_ransac.inlier_count >= self.settings.ransac.min_inliers
                and flipped_ransac.inlier_ratio >= self.settings.ransac.min_inlier_ratio
            )
            if geometry_confirms_flip or (hash_confirms_flip and absolute_flip_geometry):
                best_sift, best_ransac, transform = flipped_sift, flipped_ransac, "horizontal_flip"
        distance = flip_hash_distance if transform == "horizontal_flip" and flip_hash_distance is not None else normal_hash_distance
        body_gate, body_suspected, similar_person_only, body_part_inliers = False, False, False, {}
        if self.body_parts is not None:
            verification_second = ImageOps.mirror(second) if transform == "horizontal_flip" else second
            body_gate, body_suspected, similar_person_only, body_part_inliers = self.body_parts.verify_matches(
                first, verification_second, best_sift, best_ransac
            )
        scene_change_suspected = (
            transform == "original"
            and (body_gate or body_suspected)
            and best_ransac.inlier_count >= self.settings.relationship.partial_reuse_min_inliers
            and best_ransac.inlier_ratio >= self.settings.relationship.partial_reuse_min_inlier_ratio
            and normal_hash_distance > self.settings.phash.max_hamming_distance
            and (
                body_gate
                or (
                    embedding_similarity is not None
                    and embedding_similarity >= self.settings.relationship.background_replaced_min_embedding_similarity
                )
            )
        )
        recapture_suspected = (
            transform == "original"
            and best_ransac.inlier_count >= self.settings.relationship.recapture_min_inliers
            and best_ransac.inlier_ratio >= self.settings.relationship.recapture_min_inlier_ratio
            and best_ransac.min_coverage >= self.settings.relationship.recapture_min_coverage
            and embedding_similarity is not None
            and embedding_similarity >= self.settings.relationship.recapture_min_embedding_similarity
        )
        low_quality_pair = min(blur_variance_a, blur_variance_b) < self.settings.relationship.blur_variance_threshold
        blurred_crop_suspected = (
            transform == "original"
            and low_quality_pair
            and best_ransac.inlier_count >= self.settings.relationship.blurred_crop_min_inliers
            and best_ransac.inlier_ratio >= self.settings.relationship.blurred_crop_min_inlier_ratio
            and embedding_similarity is not None
            and embedding_similarity >= self.settings.relationship.blurred_crop_min_embedding_similarity
            and (
                body_gate
                or body_suspected
                or normal_hash_distance <= self.settings.relationship.blurred_crop_max_phash_distance
            )
        )
        evidence = PairEvidence(
            exact_duplicate=exact,
            phash_distance=distance,
            phash_normal_distance=normal_hash_distance,
            phash_flip_distance=flip_hash_distance,
            phash_max_distance=self.settings.phash.hash_size ** 2,
            embedding_similarity=embedding_similarity,
            sift_good_matches=best_sift.good_match_count,
            sift_reference_features=min(best_sift.keypoint_count_a, best_sift.keypoint_count_b),
            ransac_inliers=best_ransac.inlier_count,
            ransac_inlier_ratio=best_ransac.inlier_ratio,
            flip_detected=transform == "horizontal_flip",
            detected_transform=transform,
            scene_change_suspected=scene_change_suspected,
            body_reuse_gate=body_gate,
            body_reuse_suspected=body_suspected,
            similar_person_only=similar_person_only,
            body_part_inliers=body_part_inliers,
            ransac_coverage=best_ransac.min_coverage,
            recapture_suspected=recapture_suspected,
            blur_variance_a=round(blur_variance_a, 2),
            blur_variance_b=round(blur_variance_b, 2),
            blurred_crop_suspected=blurred_crop_suspected,
        )
        result = self.scorer.score(evidence)
        if include_visualizations:
            match_image = render_verified_matches(first, verification_second if self.body_parts is not None else second, best_sift, best_ransac)
            if match_image:
                result.visualizations["sift_ransac"] = match_image
            if self.body_parts is not None:
                masks_a, masks_b = self.body_parts.segment_many([first, verification_second])
                mask_image = render_body_masks(first, verification_second, masks_a, masks_b)
                if mask_image:
                    result.visualizations["body_parts"] = mask_image
        return result
