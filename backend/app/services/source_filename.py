import re
from dataclasses import dataclass
from pathlib import Path

_SOURCE_REFERENCE_PATTERN = re.compile(
    r"(?:^|_)(?:home|splitter)_(?P<job_number>\d{10})(?:_(?P<technician_id>[^_.]+))?(?=$|[_.])",
    re.IGNORECASE,
)
_DATE_PATTERN = re.compile(
    r"(?:^|_)(?:new|ma-mat|ma-new|ma-splice)_(?P<date>\d{8}|null)(?:_|$)",
    re.IGNORECASE,
)
_DECLARED_SOURCE_PATTERN = re.compile(
    r"(?:^|_)(?:home|splitter)_(\d{10})(?:_|$)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class SourceReference:
    """Work metadata encoded in a check-in filename."""

    job_number: str
    checkin_date: str | None
    technician_id: str | None

    @property
    def submission_key(self) -> tuple[str, str | None, str | None]:
        return (self.job_number, self.checkin_date, self.technician_id)


def parse_source_reference(filename: str) -> SourceReference | None:
    """Parse source metadata while tolerating future filename variations."""
    basename = Path(filename).name
    match = _SOURCE_REFERENCE_PATTERN.search(basename)
    if match is None:
        return None
    date_match = _DATE_PATTERN.search(basename)
    checkin_date = date_match.group("date") if date_match else None
    if checkin_date and checkin_date.lower() == "null":
        checkin_date = None
    return SourceReference(
        job_number=match.group("job_number"),
        checkin_date=checkin_date,
        technician_id=match.group("technician_id"),
    )


def declared_source_id(filename: str) -> str | None:
    """Return the 10-digit source encoded after home_/splitter_, if present."""
    reference = parse_source_reference(filename)
    if reference:
        return reference.job_number
    match = _DECLARED_SOURCE_PATTERN.search(Path(filename).name)
    return match.group(1) if match else None
