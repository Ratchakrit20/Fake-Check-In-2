import re
from dataclasses import dataclass
from pathlib import Path

_SOURCE_REFERENCE_PATTERN = re.compile(
    r"(?:^|_)new_(?P<date>\d{8})(?:_|$).*?(?:home|splitter)_(?P<job_number>\d{10})(?:_|$)",
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
    checkin_date: str

    @property
    def submission_key(self) -> tuple[str, str]:
        return (self.job_number, self.checkin_date)


def parse_source_reference(filename: str) -> SourceReference | None:
    """Parse ``new_YYYYMMDD_*_home|splitter_<10-digit job>`` filenames."""
    match = _SOURCE_REFERENCE_PATTERN.search(Path(filename).name)
    if match is None:
        return None
    return SourceReference(
        job_number=match.group("job_number"),
        checkin_date=match.group("date"),
    )


def declared_source_id(filename: str) -> str | None:
    """Return the 10-digit source encoded after home_/splitter_, if present."""
    reference = parse_source_reference(filename)
    if reference:
        return reference.job_number
    match = _DECLARED_SOURCE_PATTERN.search(Path(filename).name)
    return match.group(1) if match else None
