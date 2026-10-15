"""Shared policy for relationships that can be presented and exported.

Classification decides whether a detected pair is eligible.  The configurable
minimum score is an optional second safety gate; it defaults to 0.0 so it does
not currently exclude any eligible classification.
"""

GROUP_CLASSIFICATIONS = frozenset(
    {
        "exact_file",
        "same_image",
        "edited_or_cropped",
        "background_replaced", 
        "repeated_checkin",
        "same_scene_new_capture",
        "similar_person"
    }
)
REPORTABLE_CLASSIFICATIONS = frozenset(
    {
        "exact_file",
        "same_image",
        "edited_or_cropped",
    }
)
