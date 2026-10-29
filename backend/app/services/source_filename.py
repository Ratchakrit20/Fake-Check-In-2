import re
from dataclasses import dataclass
from pathlib import Path

_SOURCE_REFERENCE_PATTERN = re.compile(
    r"(?:^|_)(?:home|splitter)_(?P<job_number>\d{10})(?:_(?P<technician_id>[^_.]+))?(?=$|[_.])",
    re.IGNORECASE,
)
_DATE_PATTERN = re.compile(
    r"(?:^|_)(?P<job_type>new|ma-mat|ma-new|ma-splice)_(?P<date>\d{8}|null)(?:_|$)",
    re.IGNORECASE,
)
@dataclass(frozen=True)
class SourceReference:
    """Work metadata encoded in a check-in filename."""

    job_number: str
    checkin_date: str | None
    technician_id: str | None
    job_type: str | None = None

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
    job_type = date_match.group("job_type").lower() if date_match else None
    if checkin_date and checkin_date.lower() == "null":
        checkin_date = None
    return SourceReference(
        job_number=match.group("job_number"),
        checkin_date=checkin_date,
        technician_id=match.group("technician_id"),
        job_type=job_type,
    )


def parse_job_type(filename: str) -> str | None:
    """Read the job type token even when a filename has no Customer ID token."""
    match = _DATE_PATTERN.search(Path(filename).name)
    return match.group("job_type").lower() if match else None
