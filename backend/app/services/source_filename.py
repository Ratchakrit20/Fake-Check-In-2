import re
from pathlib import Path

_DECLARED_SOURCE_PATTERN = re.compile(
    r"(?:^|_)(?:home|splitter)_(\d{10})(?:_|$)",
    re.IGNORECASE,
)


def declared_source_id(filename: str) -> str | None:
    """Return the 10-digit source encoded after home_/splitter_, if present."""
    match = _DECLARED_SOURCE_PATTERN.search(Path(filename).name)
    return match.group(1) if match else None
