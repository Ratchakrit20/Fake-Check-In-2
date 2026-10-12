"""Shared policy for relationships that can be presented and exported.

Classification decides whether a detected pair is eligible.  The configurable
minimum score is an optional second safety gate; it defaults to 0.0 so it does
not currently exclude any eligible classification.
"""

REPORTABLE_CLASSIFICATIONS = frozenset(
    {
        "exact_file",
        "same_image",
        "edited_or_cropped",
    }
)
