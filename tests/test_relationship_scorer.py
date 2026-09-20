from backend.app.core.config import RelationshipConfig
from backend.app.domain.enums import RelationClassification, RelationshipLevel
from backend.app.domain.schemas import PairEvidence
from backend.app.services.relationship_scorer import RelationshipScorer


def scorer():
    return RelationshipScorer(RelationshipConfig.model_validate({
        "exact_duplicate": 1, "very_high_threshold": .9, "high_threshold": .8,
        "possible_threshold": .65, "graph_edge_threshold": .65,
        "partial_reuse_min_inliers": 30, "partial_reuse_min_inlier_ratio": .2,
        "background_replaced_min_embedding_similarity": .45,
        "foreground_source_min_inliers": 30,
        "foreground_source_min_inlier_ratio": .55,
        "foreground_source_min_coverage": .08,
        "repeated_checkin_min_foreground_inliers": 8,
        "repeated_checkin_min_foreground_ratio": .50,
        "repeated_checkin_min_foreground_coverage": .02,
        "repeated_checkin_min_identity_inliers": 6,
        "repeated_checkin_min_reuse_inliers": 4,
        "same_image_phash_max": 4, "same_image_min_inlier_ratio": .5,
        "recapture_min_inliers": 40, "recapture_min_inlier_ratio": .3,
        "recapture_min_coverage": .18, "recapture_min_embedding_similarity": .6,
        "blur_variance_threshold": 80, "blurred_crop_min_inliers": 12,
        "blurred_crop_min_inlier_ratio": .25, "blurred_crop_min_embedding_similarity": .55,
        "blurred_crop_max_phash_distance": 18,
        "blurred_whole_min_inliers": 18,
        "blurred_whole_min_inlier_ratio": .45,
        "blurred_whole_min_coverage": .08,
        "blurred_whole_strong_inlier_ratio": .75,
        "weights": {"phash": .2, "embedding": .3, "sift": .15, "ransac": .35},
    }))


def test_exact_duplicate_short_circuits():
    result = scorer().score(PairEvidence(exact_duplicate=True))
    assert result.score == 1
    assert result.decision == RelationshipLevel.EXACT_DUPLICATE


def test_strong_multisignal_evidence_is_high():
    evidence = PairEvidence(phash_distance=2, embedding_similarity=.95, sift_good_matches=100, sift_reference_features=300, ransac_inliers=80, ransac_inlier_ratio=.8)
    assert scorer().score(evidence).decision in {RelationshipLevel.HIGH_RELATION, RelationshipLevel.VERY_HIGH_RELATION}


def test_weak_flip_does_not_become_an_edited_image():
    evidence = PairEvidence(
        phash_distance=32,
        embedding_similarity=.32,
        sift_good_matches=10,
        sift_reference_features=100,
        ransac_inliers=9,
        ransac_inlier_ratio=.33,
        flip_detected=True,
    )

    result = scorer().score(evidence)

    assert result.score < .65
    assert result.classification == RelationClassification.UNRELATED


def test_high_confidence_flip_is_an_edited_image():
    evidence = PairEvidence(
        phash_distance=2,
        embedding_similarity=.95,
        sift_good_matches=80,
        sift_reference_features=200,
        ransac_inliers=70,
        ransac_inlier_ratio=.75,
        flip_detected=True,
    )

    assert scorer().score(evidence).classification == RelationClassification.EDITED_OR_CROPPED


def test_strong_foreground_source_geometry_survives_head_heavy_edit():
    evidence = PairEvidence(
        phash_distance=32,
        embedding_similarity=.33,
        sift_good_matches=158,
        sift_reference_features=21000,
        ransac_inliers=109,
        ransac_inlier_ratio=.69,
        scene_change_suspected=True,
        foreground_ransac_inliers=86,
        foreground_ransac_ratio=.62,
        foreground_coverage=.40,
        foreground_source_reuse=True,
        similar_person_only=True,
    )

    result = scorer().score(evidence)

    assert result.classification == RelationClassification.BACKGROUND_REPLACED
    assert result.score >= .65


def test_repeated_checkin_is_reviewable_and_can_bridge_groups():
    evidence = PairEvidence(
        phash_distance=26,
        embedding_similarity=.44,
        sift_good_matches=498,
        sift_reference_features=3000,
        ransac_inliers=431,
        ransac_inlier_ratio=.86,
        repeated_checkin_suspected=True,
    )

    result = scorer().score(evidence)

    assert result.classification == RelationClassification.REPEATED_CHECKIN
    assert result.score >= .65


def test_blurred_whole_image_fallback_is_an_edited_source():
    evidence = PairEvidence(
        phash_distance=30,
        embedding_similarity=.62,
        sift_good_matches=28,
        sift_reference_features=900,
        ransac_inliers=20,
        ransac_inlier_ratio=.71,
        ransac_coverage=.16,
        blurred_crop_suspected=True,
        whole_image_fallback_used=True,
    )

    result = scorer().score(evidence)

    assert result.classification == RelationClassification.EDITED_OR_CROPPED
    assert result.score >= .65


def test_verified_same_location_is_grouped_for_review():
    evidence = PairEvidence(
        phash_distance=28,
        embedding_similarity=.40,
        sift_good_matches=80,
        sift_reference_features=1000,
        ransac_inliers=65,
        ransac_inlier_ratio=.81,
        background_ransac_inliers=60,
        background_ransac_ratio=.84,
        background_coverage=.25,
        same_location_suspected=True,
    )

    result = scorer().score(evidence)

    assert result.classification == RelationClassification.SAME_SCENE_NEW_CAPTURE
    assert result.score >= .65


def test_heatmap_strengthens_verified_scene_change_but_not_by_itself():
    supported = PairEvidence(
        phash_distance=30,
        embedding_similarity=.55,
        sift_good_matches=35,
        sift_reference_features=800,
        ransac_inliers=24,
        ransac_inlier_ratio=.48,
        scene_change_suspected=True,
        heatmap_foreground_change=.18,
        heatmap_background_change=.72,
        heatmap_scene_change_support=True,
        heatmap_used_for_decision=True,
    )
    supported_result = scorer().score(supported)
    assert supported_result.classification == RelationClassification.BACKGROUND_REPLACED
    assert supported_result.score >= .76

    heatmap_only = PairEvidence(
        heatmap_foreground_change=.10,
        heatmap_background_change=.90,
        heatmap_scene_change_support=True,
        heatmap_used_for_decision=True,
    )
    heatmap_only_result = scorer().score(heatmap_only)
    assert heatmap_only_result.classification == RelationClassification.UNRELATED
    assert heatmap_only_result.score < .65
