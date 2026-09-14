from enum import StrEnum


class RelationshipLevel(StrEnum):
    EXACT_DUPLICATE = "EXACT_DUPLICATE"
    VERY_HIGH_RELATION = "VERY_HIGH_RELATION"
    HIGH_RELATION = "HIGH_RELATION"
    POSSIBLY_RELATED = "POSSIBLY_RELATED"
    LOW_RELATION = "LOW_RELATION"
    UNRELATED = "UNRELATED"


class RelationClassification(StrEnum):
    EXACT_FILE = "exact_file"
    SAME_IMAGE = "same_image"
    EDITED_OR_CROPPED = "edited_or_cropped"
    BACKGROUND_REPLACED = "background_replaced"
    SIMILAR_PERSON = "similar_person"
    SAME_SCENE_NEW_CAPTURE = "same_scene_new_capture"
    REPEATED_CHECKIN = "repeated_checkin"
    UNRELATED = "unrelated"


class ReuseVerdict(StrEnum):
    REUSED = "reused"
    REVIEW = "review"
    NOT_REUSED = "not_reused"


class JobStatus(StrEnum):
    QUEUED = "QUEUED"
    VALIDATING = "VALIDATING"
    HASHING = "HASHING"
    EMBEDDING = "EMBEDDING"
    SEARCHING = "SEARCHING"
    VERIFYING = "VERIFYING"
    GROUPING = "GROUPING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
