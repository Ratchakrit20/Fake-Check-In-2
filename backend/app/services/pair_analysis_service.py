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
from ..domain.schemas import PairEvidence, RansacResult, RelationshipResult
from .evidence_visualizer import render_aligned_pair, render_body_masks, render_change_heatmap, render_verified_matches
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
        self.body_parts = BodyPartDetector(settings.body_parts, settings.sift.max_dimension, settings.ransac.reprojection_threshold) if settings.body_parts.enabled else None
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
            first = ImageOps.exif_transpose(opened_a).convert("RGB")
            second = ImageOps.exif_transpose(opened_b).convert("RGB")
        hash_a, hash_b = self.phash.calculate(first), self.phash.calculate(second)
        blur_variance_a = ImageQualityDetector.blur_variance(first)
        blur_variance_b = ImageQualityDetector.blur_variance(second)
        normal_hash_distance = self.phash.distance(hash_a.original, hash_b.original)
        transformed_images = {
            "original": second,
            "rotate_90": second.transpose(Image.Transpose.ROTATE_270),
            "rotate_180": second.transpose(Image.Transpose.ROTATE_180),
            "rotate_270": second.transpose(Image.Transpose.ROTATE_90),
        }
        if self.settings.flip_detection.horizontal:
            transformed_images["horizontal_flip"] = ImageOps.mirror(second)
        transform_distances = {
            name: self.phash.distance(hash_a.original, self.phash.calculate_single(image))
            for name, image in transformed_images.items()
        }
        flip_hash_distance = transform_distances.get("horizontal_flip")
        normal_sift = self.sift.match(first, second)
        normal_ransac = self.ransac.verify(normal_sift)
        best_sift, best_ransac, transform = normal_sift, normal_ransac, "original"
        normal_geometry_passes = (
            normal_ransac.inlier_count >= self.settings.ransac.min_inliers
            and normal_ransac.inlier_ratio >= self.settings.ransac.min_inlier_ratio
        )
        alternatives = sorted(
            ((distance, name) for name, distance in transform_distances.items() if name != "original"),
            key=lambda item: item[0],
        )
        if alternatives:
            candidate_distance, candidate_transform = alternatives[0]
            hash_suggests_transform = (
                candidate_distance <= self.settings.phash.max_hamming_distance
                and candidate_distance + 3 <= normal_hash_distance
            )
            if hash_suggests_transform or not normal_geometry_passes:
                candidate_sift = self.sift.match(first, transformed_images[candidate_transform])
                candidate_ransac = self.ransac.verify(candidate_sift)
                absolute_geometry = (
                    candidate_ransac.inlier_count >= self.settings.ransac.min_inliers
                    and candidate_ransac.inlier_ratio >= self.settings.ransac.min_inlier_ratio
                )
                geometry_improves = (
                    not normal_geometry_passes
                    or candidate_ransac.inlier_ratio >= normal_ransac.inlier_ratio + 0.10
                )
                if absolute_geometry and (hash_suggests_transform or geometry_improves):
                    best_sift, best_ransac, transform = candidate_sift, candidate_ransac, candidate_transform
        distance = transform_distances[transform]
        verification_second = transformed_images[transform]
        rotation_degrees = {"rotate_90": 90, "rotate_180": 180, "rotate_270": 270}.get(transform, 0)
        embedding_similarity = embedding_similarity_override
        if (embedding_similarity is None or rotation_degrees) and self.embedding_provider is not None:
            embed_many = getattr(self.embedding_provider, "embed_many", None)
            if embed_many is not None:
                vector_a, vector_b = embed_many([first, verification_second])
            else:
                vector_a = self.embedding_provider.embed(first)
                vector_b = self.embedding_provider.embed(verification_second)
            embedding_similarity = float(np.dot(vector_a, vector_b) / max(np.linalg.norm(vector_a) * np.linalg.norm(vector_b), 1e-12))
        body_gate, body_suspected, similar_person_only, body_part_inliers = False, False, False, {}
        foreground_ransac, background_ransac = RansacResult(), RansacResult()
        masks_a: dict[str, np.ndarray] = {}
        masks_b: dict[str, np.ndarray] = {}
        heatmap_image: str | None = None
        heatmap_foreground_change: float | None = None
        heatmap_background_change: float | None = None
        heatmap_scene_change_support = False
        geometry_is_credible = (
            best_sift.good_match_count >= self.settings.sift.min_good_matches
            and best_ransac.inlier_count >= 4
        )
        if self.body_parts is not None and geometry_is_credible:
            body_gate, body_suspected, similar_person_only, body_part_inliers, foreground_ransac, background_ransac = self.body_parts.verify_matches(
                first, verification_second, best_sift, best_ransac
            )
            masks_a, masks_b = self.body_parts.segment_many([first, verification_second])
            foreground_mask_a = np.zeros((best_sift.image_size_a[1], best_sift.image_size_a[0]), dtype=bool)
            foreground_mask_b = np.zeros((best_sift.image_size_b[1], best_sift.image_size_b[0]), dtype=bool)
            for label in set(self.settings.body_parts.identity_classes) | set(self.settings.body_parts.reuse_classes):
                organ_mask_a, organ_mask_b = masks_a.get(label), masks_b.get(label)
                if organ_mask_a is not None:
                    foreground_mask_a |= organ_mask_a
                if organ_mask_b is not None:
                    foreground_mask_b |= organ_mask_b
            foreground_alignment_is_reliable = (
                foreground_ransac.homography_found
                and foreground_ransac.inlier_count >= self.settings.ransac.min_inliers
                and foreground_ransac.inlier_ratio >= self.settings.ransac.min_inlier_ratio
            )
            whole_alignment_is_reliable = (
                best_ransac.homography_found
                and best_ransac.inlier_count >= self.settings.ransac.min_inliers
                and best_ransac.inlier_ratio >= self.settings.ransac.min_inlier_ratio
            )
            heatmap_alignment = (
                foreground_ransac
                if foreground_alignment_is_reliable
                else best_ransac if whole_alignment_is_reliable else RansacResult()
            )
            heatmap_image, heatmap_foreground_change, heatmap_background_change = render_change_heatmap(
                first,
                verification_second,
                best_sift,
                heatmap_alignment,
                foreground_mask_a,
                foreground_mask_b,
                include_image=include_visualizations,
            )
            heatmap_scene_change_support = (
                foreground_alignment_is_reliable
                and heatmap_foreground_change is not None
                and heatmap_background_change is not None
                and heatmap_foreground_change <= self.settings.relationship.heatmap_max_foreground_change
                and heatmap_background_change >= self.settings.relationship.heatmap_min_background_change
                and heatmap_background_change - heatmap_foreground_change
                >= self.settings.relationship.heatmap_min_change_gap
                and embedding_similarity is not None
                and embedding_similarity >= self.settings.relationship.background_replaced_min_embedding_similarity
                and (body_gate or body_suspected)
            )
        foreground_verified = (
            body_gate
            and foreground_ransac.inlier_count >= self.settings.body_parts.min_reuse_inliers
            and foreground_ransac.inlier_ratio >= self.settings.ransac.min_inlier_ratio
        )
        background_verified = (
            background_ransac.inlier_count >= self.settings.relationship.partial_reuse_min_inliers
            and background_ransac.inlier_ratio >= self.settings.relationship.partial_reuse_min_inlier_ratio
            and background_ransac.min_coverage >= 0.02
        )
        same_location_suspected = transform == "original" and background_verified
        foreground_source_reuse = (
            foreground_ransac.inlier_count >= self.settings.relationship.foreground_source_min_inliers
            and foreground_ransac.inlier_ratio >= self.settings.relationship.foreground_source_min_inlier_ratio
            and foreground_ransac.min_coverage >= self.settings.relationship.foreground_source_min_coverage
        )
        identity_inliers = sum(body_part_inliers.get(label, 0) for label in self.settings.body_parts.identity_classes)
        reuse_inliers = sum(body_part_inliers.get(label, 0) for label in self.settings.body_parts.reuse_classes)
        repeated_checkin_suspected = (
            transform == "original"
            and background_verified
            and foreground_ransac.inlier_count >= self.settings.relationship.repeated_checkin_min_foreground_inliers
            and foreground_ransac.inlier_ratio >= self.settings.relationship.repeated_checkin_min_foreground_ratio
            and foreground_ransac.min_coverage >= self.settings.relationship.repeated_checkin_min_foreground_coverage
            and identity_inliers >= self.settings.relationship.repeated_checkin_min_identity_inliers
            and reuse_inliers >= self.settings.relationship.repeated_checkin_min_reuse_inliers
        )
        scene_change_suspected = (
            transform == "original"
            and (foreground_verified or foreground_source_reuse or heatmap_scene_change_support)
            and not background_verified
            and normal_hash_distance > self.settings.phash.max_hamming_distance
        )
        recapture_suspected = (
            transform == "original"
            and normal_hash_distance > self.settings.relationship.same_image_phash_max
            and best_ransac.inlier_count >= self.settings.relationship.recapture_min_inliers
            and best_ransac.inlier_ratio >= self.settings.relationship.recapture_min_inlier_ratio
            and best_ransac.min_coverage >= self.settings.relationship.recapture_min_coverage
            and embedding_similarity is not None
            and embedding_similarity >= self.settings.relationship.recapture_min_embedding_similarity
        )
        low_quality_pair = min(blur_variance_a, blur_variance_b) < self.settings.relationship.blur_variance_threshold
        whole_image_fallback = (
            not body_gate
            and low_quality_pair
            and best_ransac.inlier_count >= self.settings.relationship.blurred_whole_min_inliers
            and best_ransac.inlier_ratio >= self.settings.relationship.blurred_whole_min_inlier_ratio
            and best_ransac.min_coverage >= self.settings.relationship.blurred_whole_min_coverage
            and (
                (
                    embedding_similarity is not None
                    and embedding_similarity >= self.settings.relationship.blurred_crop_min_embedding_similarity
                )
                or best_ransac.inlier_ratio >= self.settings.relationship.blurred_whole_strong_inlier_ratio
            )
        )
        blurred_crop_suspected = (
            transform == "original"
            and low_quality_pair
            and (
                whole_image_fallback
                or (
                    best_ransac.inlier_count >= self.settings.relationship.blurred_crop_min_inliers
                    and best_ransac.inlier_ratio >= self.settings.relationship.blurred_crop_min_inlier_ratio
                    and embedding_similarity is not None
                    and embedding_similarity >= self.settings.relationship.blurred_crop_min_embedding_similarity
                    and (
                        body_gate
                        or body_suspected
                        or normal_hash_distance <= self.settings.relationship.blurred_crop_max_phash_distance
                    )
                )
            )
        )
        evidence = PairEvidence(
            exact_duplicate=exact,
            phash_distance=distance,
            phash_normal_distance=normal_hash_distance,
            phash_flip_distance=flip_hash_distance,
            phash_rotation_distances={
                name: transform_distances[name] for name in ("rotate_90", "rotate_180", "rotate_270")
            },
            phash_max_distance=self.settings.phash.hash_size ** 2,
            embedding_similarity=embedding_similarity,
            sift_good_matches=best_sift.good_match_count,
            sift_reference_features=min(best_sift.keypoint_count_a, best_sift.keypoint_count_b),
            ransac_inliers=best_ransac.inlier_count,
            ransac_inlier_ratio=best_ransac.inlier_ratio,
            flip_detected=transform == "horizontal_flip",
            rotation_degrees=rotation_degrees,
            detected_transform=transform,
            scene_change_suspected=scene_change_suspected,
            body_reuse_gate=body_gate,
            body_reuse_suspected=body_suspected,
            similar_person_only=similar_person_only,
            body_part_inliers=body_part_inliers,
            foreground_ransac_inliers=foreground_ransac.inlier_count,
            foreground_ransac_ratio=foreground_ransac.inlier_ratio,
            foreground_coverage=foreground_ransac.min_coverage,
            foreground_source_reuse=foreground_source_reuse,
            repeated_checkin_suspected=repeated_checkin_suspected,
            background_ransac_inliers=background_ransac.inlier_count,
            background_ransac_ratio=background_ransac.inlier_ratio,
            background_coverage=background_ransac.min_coverage,
            same_location_suspected=same_location_suspected,
            ransac_coverage=best_ransac.min_coverage,
            recapture_suspected=recapture_suspected,
            blur_variance_a=round(blur_variance_a, 2),
            blur_variance_b=round(blur_variance_b, 2),
            blurred_crop_suspected=blurred_crop_suspected,
            whole_image_fallback_used=whole_image_fallback,
            heatmap_foreground_change=heatmap_foreground_change,
            heatmap_background_change=heatmap_background_change,
            heatmap_scene_change_support=heatmap_scene_change_support,
            heatmap_used_for_decision=heatmap_scene_change_support,
        )
        result = self.scorer.score(evidence)
        if include_visualizations:
            if transform != "original":
                result.visualizations["aligned_pair"] = render_aligned_pair(
                    first,
                    verification_second,
                )
            match_image = render_verified_matches(
                first,
                verification_second,
                best_sift,
                best_ransac,
            )
            if match_image:
                result.visualizations["sift_ransac"] = match_image
            if self.body_parts is not None and geometry_is_credible:
                mask_image = render_body_masks(first, verification_second, masks_a, masks_b)
                if mask_image:
                    result.visualizations["body_parts"] = mask_image
                if heatmap_image:
                    result.visualizations["change_heatmap"] = heatmap_image
        return result
