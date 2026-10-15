"""Resolve image source metadata from the database with filename fallback."""

from dataclasses import dataclass

from ..db.models import ImageRecord
from .source_filename import parse_source_reference


@dataclass(frozen=True)
class ResolvedImageSource:
    """Source metadata exposed to routes using domain-friendly names."""

    customer_id: str | None
    checkin_date: str | None
    technician_id: str | None


def resolve_image_source(image: ImageRecord) -> ResolvedImageSource:
    """Use persisted metadata first and parse only fields that are missing.

    Persisted values are the source of truth after upload. Parsing is retained
    as a safe fallback for historical images that predate source columns.
    """
    parsed = parse_source_reference(image.original_filename)
    return ResolvedImageSource(
        customer_id=image.source_job_number or (parsed.job_number if parsed else None),
        checkin_date=image.source_checkin_date or (parsed.checkin_date if parsed else None),
        technician_id=image.source_technician_id or (parsed.technician_id if parsed else None),
    )
