"""Backfill lat-long and datetime detections for existing image records."""

from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path

from PIL import Image, ImageOps
from sqlalchemy import or_, select

from ..core.config import get_settings
from ..db.models import AnalysisJob, ImageRecord
from ..db.session import SessionFactory
from ..services.ai_image_metadata import serialize_ai_metadata
from ..services.ai_model_service import AIModelService
from ..storage.local_storage import LocalImageStorage

logger = logging.getLogger(__name__)


async def scan_existing_images(batch_size: int = 24) -> None:
    settings = get_settings()
    if not settings.ai_models_lat_long.enabled:
        raise RuntimeError("The lat-long/datetime detector is disabled; enable ai_models_lat_long before scanning.")
    detector = AIModelService(settings.ai_models_lat_long)
    storage = LocalImageStorage(settings.storage.root)
    scanned = 0
    last_id = ""

    async with SessionFactory() as session:
        active = await session.scalar(
            select(AnalysisJob.id).where(
                AnalysisJob.status.not_in(["COMPLETED", "CANCELLED", "INTERRUPTED", "FAILED"])
            ).limit(1)
        )
    if active:
        raise RuntimeError(f"Analysis Job {active} is active; run the SOA scan after it finishes.")

    while True:
        async with SessionFactory() as session:
            records = list(await session.scalars(
                select(ImageRecord)
                .where(
                    or_(
                        ImageRecord.ai_metadata_json.is_(None),
                        ImageRecord.ai_metadata_json.like('%"error"%'),
                        ImageRecord.ai_metadata_json.not_like('%"lat_long"%'),
                    ),
                    ImageRecord.id > last_id,
                )
                .order_by(ImageRecord.id)
                .limit(batch_size)
            ))
            if not records:
                break
            for record in records:
                last_id = record.id
                path: Path | None = storage.resolve(record.id, record.storage_path)
                if path is None:
                    logger.warning("image file missing; skip SOA metadata scan for %s", record.id)
                    continue
                try:
                    with Image.open(path) as opened:
                        image = ImageOps.exif_transpose(opened).convert("RGB")
                        metadata = detector.report_metadata(image)
                        if "error" in metadata:
                            logger.warning("detector could not scan image %s: %s", record.id, metadata["error"])
                            continue
                        record.ai_metadata_json = serialize_ai_metadata(metadata)
                except (OSError, ValueError):
                    logger.exception("unable to scan image metadata for %s", record.id)
                    continue
                scanned += 1
            await session.commit()
        print(f"SOA metadata scanned: {scanned}", flush=True)

    print(f"SOA metadata scan complete. Images scanned: {scanned}", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Scan existing images for lat-long and datetime detections")
    parser.add_argument("--batch-size", type=int, default=24)
    args = parser.parse_args()
    if args.batch_size < 1 or args.batch_size > 256:
        parser.error("--batch-size must be between 1 and 256")
    logging.basicConfig(level=get_settings().logging.level)
    try:
        asyncio.run(scan_existing_images(args.batch_size))
    except RuntimeError as exc:
        parser.exit(2, f"{exc}\n")


if __name__ == "__main__":
    main()
