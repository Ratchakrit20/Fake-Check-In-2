from backend.app.core.config import RelationshipConfig
from backend.app.domain.enums import RelationshipLevel
from backend.app.domain.schemas import PairEvidence
from backend.app.services.relationship_scorer import RelationshipScorer


def scorer():
    return RelationshipScorer(RelationshipConfig.model_validate({
        "exact_duplicate": 1, "very_high_threshold": .9, "high_threshold": .8,
        "possible_threshold": .65, "graph_edge_threshold": .65,
        "partial_reuse_min_inliers": 30, "partial_reuse_min_inlier_ratio": .2,
        "background_replaced_min_embedding_similarity": .45,
        "same_image_phash_max": 4, "same_image_min_inlier_ratio": .5,
        "recapture_min_inliers": 40, "recapture_min_inlier_ratio": .3,
        "recapture_min_coverage": .18, "recapture_min_embedding_similarity": .6,
        "blur_variance_threshold": 80, "blurred_crop_min_inliers": 12,
        "blurred_crop_min_inlier_ratio": .25, "blurred_crop_min_embedding_similarity": .55,
        "blurred_crop_max_phash_distance": 18,
        "weights": {"phash": .2, "embedding": .3, "sift": .15, "ransac": .35},
    }))


def test_exact_duplicate_short_circuits():
    result = scorer().score(PairEvidence(exact_duplicate=True))
    assert result.score == 1
    assert result.decision == RelationshipLevel.EXACT_DUPLICATE


def test_strong_multisignal_evidence_is_high():
    evidence = PairEvidence(phash_distance=2, embedding_similarity=.95, sift_good_matches=100, sift_reference_features=300, ransac_inliers=80, ransac_inlier_ratio=.8)
    assert scorer().score(evidence).decision in {RelationshipLevel.HIGH_RELATION, RelationshipLevel.VERY_HIGH_RELATION}
