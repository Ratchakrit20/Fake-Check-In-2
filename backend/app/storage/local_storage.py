from pathlib import Path

from ..domain.interfaces import ImageStorage


class LocalImageStorage(ImageStorage):
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def save(self, image_id: str, suffix: str, content: bytes) -> Path:
        safe_suffix = suffix.lower() if suffix.lower() in {".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff", ".bmp"} else ".img"
        target = (self.root / image_id[:2] / f"{image_id}{safe_suffix}").resolve()
        if self.root not in target.parents:
            raise ValueError("invalid storage target")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        return target

    def resolve(self, image_id: str, stored_path: str | Path) -> Path | None:
        """Resolve old absolute paths after the project data folder is moved."""
        original = Path(stored_path)
        if original.is_file():
            return original.resolve()
        folder = (self.root / image_id[:2]).resolve()
        if self.root not in folder.parents:
            return None
        matches = [path.resolve() for path in folder.glob(f"{image_id}.*") if path.is_file()]
        return matches[0] if len(matches) == 1 else None
