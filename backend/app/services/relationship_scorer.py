from dataclasses import asdict

from ..core.config import RelationshipConfig
from ..domain.enums import RelationClassification, RelationshipLevel, ReuseVerdict
from ..domain.schemas import PairEvidence, RelationshipResult


class RelationshipScorer:
    def __init__(self, config: RelationshipConfig) -> None:
        self.config = config

    def score(self, evidence: PairEvidence) -> RelationshipResult:
        if evidence.exact_duplicate:
            return RelationshipResult(
                score=1.0,
                decision=RelationshipLevel.EXACT_DUPLICATE,
                classification=RelationClassification.EXACT_FILE,
                reuse_verdict=ReuseVerdict.REUSED,
                reasons=["SHA-256 hashes are identical"],
                evidence=asdict(evidence),
            )
        weights = self.config.weights
        values: list[tuple[float, float]] = []
        reasons: list[str] = []
        if evidence.phash_distance is not None:
            phash_score = max(0.0, 1 - evidence.phash_distance / max(1, evidence.phash_max_distance))
            values.append((phash_score, weights.phash))
            if phash_score >= 0.80:
                reasons.append(f"Close perceptual hashes (distance {evidence.phash_distance})")
        if evidence.embedding_similarity is not None:
            embedding_score = max(0.0, min(1.0, evidence.embedding_similarity))
            values.append((embedding_score, weights.embedding))
            if embedding_score >= 0.80:
                reasons.append(f"High SSCD copy similarity ({embedding_score:.3f})")
        if evidence.sift_reference_features:
            sift_score = min(1.0, evidence.sift_good_matches / max(12, evidence.sift_reference_features * 0.15))
            values.append((sift_score, weights.sift))
            if evidence.sift_good_matches >= 12:
                reasons.append(f"Local feature correspondence ({evidence.sift_good_matches} SIFT matches)")
        if evidence.sift_good_matches:
            ransac_score = evidence.ransac_inlier_ratio if evidence.ransac_inliers >= 4 else 0.0
            values.append((ransac_score, weights.ransac))
            if evidence.ransac_inliers >= 8:
                reasons.append(f"Geometrically consistent overlap ({evidence.ransac_inliers} RANSAC inliers)")
        if evidence.flip_detected:
            reasons.append("Horizontal mirror transformation detected")
        if evidence.body_reuse_gate:
            reasons.append("Matching features are verified across reusable body regions")
        elif evidence.foreground_source_reuse:
            reasons.append("Strong geometry across the segmented foreground verifies source reuse")
        elif evidence.body_reuse_suspected:
            reasons.append("One reusable body region has strong matching evidence")
        elif evidence.similar_person_only:
            reasons.append("Head or neck features are similar, but body reuse is not verified")
        denominator = sum(weight for _, weight in values)
        score = sum(value * weight for value, weight in values) / denominator if denominator else 0.0
        if evidence.scene_change_suspected:
            score = max(score, 0.72)
            reasons.append("Strong geometrically verified partial reuse")
        elif evidence.repeated_checkin_suspected:
            score = max(score, 0.68)
            reasons.append("The same location and person regions recur across check-ins")
        elif evidence.recapture_suspected:
            score = max(score, 0.80)
            reasons.append("Wide geometrically consistent coverage indicates a recaptured source image")
        elif evidence.blurred_crop_suspected:
            score = max(score, 0.70)
            if evidence.whole_image_fallback_used:
                reasons.append("Body regions were incomplete, but strong whole-image geometry verifies the blurred source")
            else:
                reasons.append("A blurred or cropped image retains geometrically verified source regions")
        elif evidence.same_location_suspected:
            score = max(score, 0.67)
            reasons.append("The background verifies that the same work location appears across submissions")
        elif evidence.similar_person_only and not evidence.same_location_suspected:
            score = min(score, 0.64)
        if score >= self.config.very_high_threshold:
            decision = RelationshipLevel.VERY_HIGH_RELATION
        elif score >= self.config.high_threshold:
            decision = RelationshipLevel.HIGH_RELATION
        elif score >= self.config.possible_threshold:
            decision = RelationshipLevel.POSSIBLY_RELATED
        elif score >= 0.35:
            decision = RelationshipLevel.LOW_RELATION
        else:
            decision = RelationshipLevel.UNRELATED
        strong_geometry = evidence.ransac_inliers >= self.config.partial_reuse_min_inliers and evidence.ransac_inlier_ratio >= self.config.partial_reuse_min_inlier_ratio
        verified_flip = evidence.flip_detected and score >= self.config.possible_threshold
        if verified_flip or evidence.recapture_suspected or evidence.blurred_crop_suspected:
            classification = RelationClassification.EDITED_OR_CROPPED
        elif evidence.scene_change_suspected:
            classification = RelationClassification.BACKGROUND_REPLACED
        elif evidence.repeated_checkin_suspected:
            classification = RelationClassification.REPEATED_CHECKIN
        elif (
            evidence.phash_distance is not None
            and evidence.phash_distance <= self.config.same_image_phash_max
            and evidence.ransac_inlier_ratio >= self.config.same_image_min_inlier_ratio
        ):
            classification = RelationClassification.SAME_IMAGE
        elif evidence.body_reuse_gate and strong_geometry:
            classification = RelationClassification.EDITED_OR_CROPPED
        elif evidence.same_location_suspected:
            classification = RelationClassification.SAME_SCENE_NEW_CAPTURE
        elif evidence.similar_person_only:
            classification = RelationClassification.SIMILAR_PERSON
        elif strong_geometry:
            classification = RelationClassification.SAME_SCENE_NEW_CAPTURE
        else:
            classification = RelationClassification.UNRELATED
        if classification in {
            RelationClassification.EXACT_FILE,
            RelationClassification.SAME_IMAGE,
            RelationClassification.EDITED_OR_CROPPED,
        }:
            reuse_verdict = ReuseVerdict.REUSED
        elif classification in {
            RelationClassification.BACKGROUND_REPLACED,
            RelationClassification.REPEATED_CHECKIN,
            RelationClassification.SAME_SCENE_NEW_CAPTURE,
        }:
            reuse_verdict = ReuseVerdict.REVIEW
        else:
            reuse_verdict = ReuseVerdict.NOT_REUSED
        return RelationshipResult(
            score=round(score, 4),
            decision=decision,
            classification=classification,
            reuse_verdict=reuse_verdict,
            reasons=reasons or ["No strong relationship evidence was found"],
            evidence=asdict(evidence),
        )
