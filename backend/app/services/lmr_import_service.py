from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from uuid import uuid4

from ..core.config import Settings
from ..db.models import ImageRecord
from .source_filename import parse_job_type, parse_source_reference

_DATE_FOLDER = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff", ".bmp"}
_ROOT_CATEGORY = "__date_root__"


class LmrImportError(ValueError):
    """An import request points outside the configured LMR date folders."""


class LmrImageImportService:
    """Index images from the configured archive without copying image bytes."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.root = settings.lmr_import.root.resolve()

    def available_dates(self) -> list[dict[str, object]]:
        if not self.settings.lmr_import.enabled or not self.root.is_dir():
            return []

        dates: list[dict[str, object]] = []
        for day_root in self._date_directories():
            try:
                image_paths = self._image_paths(day_root)
                category_names = {
                    path.relative_to(day_root).parts[0]
                    for path in image_paths
                    if len(path.relative_to(day_root).parts) > 1
                }
                if any(path.parent == day_root for path in image_paths):
                    category_names.add(_ROOT_CATEGORY)
            except OSError:
                continue
            dates.append({
                "date": day_root.name,
                "categories": sorted(category_names, key=lambda name: (name != _ROOT_CATEGORY, name.casefold())),
                "image_count": len(image_paths),
            })
        return sorted(dates, key=lambda item: str(item["date"]), reverse=True)

    def image_paths_for_selection(
        self,
        selection: str,
        categories: list[str] | None = None,
    ) -> list[tuple[Path, Path]]:
        if selection.casefold() == "all":
            day_roots = self._date_directories()
        else:
            day_roots = [self._date_directory(selection)]

        selected_categories = set(categories or [])
        day_images_by_root = [(day_root, self._image_paths(day_root)) for day_root in day_roots]
        available_categories: set[str] = set()
        for day_root, day_images in day_images_by_root:
            for image_path in day_images:
                relative = image_path.relative_to(day_root)
                available_categories.add(relative.parts[0] if len(relative.parts) > 1 else _ROOT_CATEGORY)
        unknown_categories = selected_categories - available_categories
        if unknown_categories:
            raise LmrImportError("หมวดหมู่ที่เลือกไม่พบในคลังวันที่เลือก กรุณารีเฟรชรายการ")

        selected: list[tuple[Path, Path]] = []
        for day_root, day_images in day_images_by_root:
            for image_path in day_images:
                relative = image_path.relative_to(day_root)
                category = relative.parts[0] if len(relative.parts) > 1 else _ROOT_CATEGORY
                if selected_categories and category not in selected_categories:
                    continue
                selected.append((day_root, image_path))
        return selected

    def build_pending_record(self, image_path: Path, day_root: Path) -> ImageRecord:
        """Create a light DB row; worker computes image hashes and quality asynchronously."""
        resolved = image_path.resolve(strict=True)
        resolved.relative_to(day_root)
        if len(resolved.name) > 255:
            raise ValueError("filename exceeds the 255-character database limit")
        file_size = resolved.stat().st_size
        source = parse_source_reference(resolved.name)
        relative_parent = resolved.relative_to(day_root).parent
        category = relative_parent.parts[0] if relative_parent.parts else None
        folder_date = date.fromisoformat(day_root.name).strftime("%Y%m%d")
        checkin_date = source.checkin_date if source and source.checkin_date else folder_date
        suffix = resolved.suffix.lower()
        mime_type = {
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".webp": "image/webp",
            ".tif": "image/tiff",
            ".tiff": "image/tiff",
            ".bmp": "image/bmp",
        }[suffix]

        return ImageRecord(
            id=str(uuid4()),
            original_filename=resolved.name,
            source_technician_id=source.technician_id if source else None,
            source_job_number=source.job_number if source else None,
            source_checkin_date=checkin_date,
            source_job_type=(source.job_type if source and source.job_type else parse_job_type(resolved.name)),
            source_category=category[:255] if category else None,
            source_archive_date=day_root.name,
            storage_path=str(resolved),
            file_size=file_size,
            width=0,
            height=0,
            mime_type=mime_type,
            sha256="",
            phash=None,
            phash_rotations_json=None,
            analysis_status="QUEUED",
        )

    def _date_directories(self) -> list[Path]:
        if not self.root.is_dir():
            return []
        directories: list[Path] = []
        for directory in self.root.iterdir():
            if directory.is_symlink() or not directory.is_dir() or not _DATE_FOLDER.fullmatch(directory.name):
                continue
            try:
                date.fromisoformat(directory.name)
                resolved = directory.resolve(strict=True)
                if resolved.parent == self.root:
                    directories.append(resolved)
            except (OSError, ValueError):
                continue
        return sorted(directories, key=lambda item: item.name)

    def _date_directory(self, date_folder: str) -> Path:
        if not _DATE_FOLDER.fullmatch(date_folder):
            raise LmrImportError("รูปแบบวันที่ต้องเป็น YYYY-MM-DD หรือเลือกทุกวัน")
        configured_day = self.root / date_folder
        if configured_day.is_symlink():
            raise LmrImportError("ไม่รองรับโฟลเดอร์วันที่ที่เป็น symbolic link")
        try:
            date.fromisoformat(date_folder)
            day_root = configured_day.resolve(strict=True)
            day_root.relative_to(self.root)
        except (OSError, ValueError) as exc:
            raise LmrImportError("ไม่พบโฟลเดอร์วันที่ในคลัง LMR") from exc
        if day_root.parent != self.root or not day_root.is_dir():
            raise LmrImportError("วันที่ที่เลือกไม่ใช่โฟลเดอร์รายวันในคลัง LMR")
        return day_root

    @staticmethod
    def _image_paths(day_root: Path) -> list[Path]:
        paths: list[Path] = []
        seen: set[Path] = set()
        for candidate in day_root.rglob("*"):
            if candidate.suffix.lower() not in _IMAGE_SUFFIXES or not candidate.is_file():
                continue
            try:
                resolved = candidate.resolve(strict=True)
                resolved.relative_to(day_root)
            except (OSError, ValueError):
                # Do not follow links outside the selected date folder.
                continue
            if resolved not in seen:
                seen.add(resolved)
                paths.append(resolved)
        return sorted(paths, key=lambda item: str(item).casefold())
