import io
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import FileResponse
from PIL import Image
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.config import get_settings
from ...db.models import ImageRecord
from ...db.session import get_session
from ...detectors.perceptual_hash_detector import PerceptualHashDetector
from ...detectors.sha256_detector import SHA256Detector
from ...services.image_metadata_service import extract_capture_datetime
from ...services.image_quality_service import ImageQualityService
from ...services.image_validation_service import ImageValidationService
from ...services.source_filename import parse_job_type, parse_source_reference
from ...storage.local_storage import LocalImageStorage

router = APIRouter(prefix="/images", tags=["images"])


@router.post("")
async def upload_image(file: UploadFile = File(...), session: AsyncSession = Depends(get_session)) -> dict:
    settings = get_settings()
    content = await file.read()
    metadata = ImageValidationService(settings.app).validate(content)
    sha256 = SHA256Detector.from_bytes(content)
    quality_service = ImageQualityService(settings.image_quality)
    with Image.open(io.BytesIO(content)) as image:
        quality = quality_service.assess(image)
        captured_at = extract_capture_datetime(image)
    existing = await session.scalar(select(ImageRecord).where(ImageRecord.sha256 == sha256))
    if existing:
        storage = LocalImageStorage(settings.storage.root)
        restored_path = storage.ensure_available(existing.id, existing.storage_path, metadata.suffix, content)
        existing.storage_path = str(restored_path)
        existing.image_quality_status = quality.status
        existing.image_quality_reason = quality.reason
        existing.near_black_ratio = quality.near_black_ratio
        if not quality.can_compare:
            existing.phash = None
            existing.analysis_status = "UNVERIFIABLE"
        await session.commit()
        return {
            "id": existing.id,
            "status": "EXACT_DUPLICATE" if quality.can_compare else "UNVERIFIABLE",
            "sha256": sha256,
            "image_quality_status": quality.status,
            "near_black_ratio": quality.near_black_ratio,
        }
    image_id = str(uuid4())
    storage_path = LocalImageStorage(settings.storage.root).save(image_id, metadata.suffix, content)
    with Image.open(io.BytesIO(content)) as image:
        phash = (
            PerceptualHashDetector(settings.phash.hash_size, settings.flip_detection.horizontal).calculate(image).original
            if quality.can_compare
            else None
        )
    original_filename = Path(file.filename or "image").name
    source_reference = parse_source_reference(original_filename)
    record = ImageRecord(
        id=image_id,
        original_filename=original_filename,
        source_technician_id=source_reference.technician_id if source_reference else None,
        source_job_number=source_reference.job_number if source_reference else None,
        source_checkin_date=source_reference.checkin_date if source_reference else None,
        source_job_type=parse_job_type(original_filename),
        source_captured_at=captured_at,
        storage_path=str(storage_path),
        file_size=len(content),
        width=metadata.width,
        height=metadata.height,
        mime_type=metadata.mime_type,
        sha256=sha256,
        phash=phash,
        analysis_status="HASHED" if quality.can_compare else "UNVERIFIABLE",
        image_quality_status=quality.status,
        image_quality_reason=quality.reason,
        near_black_ratio=quality.near_black_ratio,
    )
    session.add(record)
    await session.commit()
    return {
        "id": image_id,
        "status": record.analysis_status,
        "sha256": sha256,
        "phash": phash,
        "image_quality_status": quality.status,
        "near_black_ratio": quality.near_black_ratio,
    }


@router.get("/{image_id}")
async def image_detail(image_id: str, session: AsyncSession = Depends(get_session)) -> dict:
    record = await session.get(ImageRecord, image_id)
    if record is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="image not found")
    return {column.name: getattr(record, column.name) for column in record.__table__.columns if column.name != "storage_path"}


@router.get("/{image_id}/content", response_class=FileResponse)
async def image_content(image_id: str, session: AsyncSession = Depends(get_session)) -> FileResponse:
    record = await session.get(ImageRecord, image_id)
    settings = get_settings()
    resolved = LocalImageStorage(settings.storage.root).resolve(record.id, record.storage_path) if record else None
    if record is None or resolved is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="image not found")
    return FileResponse(resolved, media_type=record.mime_type, filename=record.original_filename)
