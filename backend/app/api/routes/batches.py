import io
from pathlib import Path
from typing import cast
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, UploadFile
from PIL import Image
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.config import get_settings
from ...db.models import AnalysisJob, AnalysisJobItem, ImageRecord
from ...db.session import get_session
from ...detectors.perceptual_hash_detector import PerceptualHashDetector
from ...detectors.sha256_detector import SHA256Detector
from ...services.image_metadata_service import extract_capture_datetime
from ...services.image_quality_service import ImageQualityService
from ...services.image_validation_service import ImageValidationService
from ...services.job_dispatch_service import JobDispatchError, dispatch_batch_job
from ...services.source_filename import parse_job_type, parse_source_reference
from ...storage.local_storage import LocalImageStorage

router = APIRouter(prefix="/batches", tags=["batches"])


async def _ensure_no_active_job(session: AsyncSession) -> None:
    active = await session.scalar(
        select(AnalysisJob.id).where(AnalysisJob.status.not_in(["COMPLETED", "CANCELLED", "INTERRUPTED", "FAILED"]))
    )
    if active:
        raise HTTPException(status_code=409, detail="มีงานวิเคราะห์กำลังทำงานอยู่ กรุณารอให้งานเดิมเสร็จก่อน")


@router.post("", status_code=202)
async def create_batch(
    background_tasks: BackgroundTasks,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> dict:
    settings = get_settings()

    form = await request.form(max_files=settings.app.max_upload_files)
    files = cast(list[UploadFile], form.getlist("files"))

    await _ensure_no_active_job(session)

    if not files or len(files) > settings.app.max_upload_files:
        raise HTTPException(
            status_code=422,
            detail=f"upload between 1 and {settings.app.max_upload_files} images",
        )
    job = AnalysisJob(status="QUEUED", total=len(files), processed=0)
    session.add(job)
    await session.flush()
    validator = ImageValidationService(settings.app)
    storage = LocalImageStorage(settings.storage.root)
    phash_detector = PerceptualHashDetector(settings.phash.hash_size, settings.flip_detection.horizontal)
    quality_service = ImageQualityService(settings.image_quality)
    unverifiable_count = 0
    job_items: list[AnalysisJobItem] = []
    for position, file in enumerate(files):
        content = await file.read()
        metadata = validator.validate(content)
        sha256 = SHA256Detector.from_bytes(content)
        # Every upload is evidence. Keep separate records even when the bytes
        # are identical so the relationship graph can show an exact reuse.
        existing_exact = await session.scalar(select(ImageRecord).where(ImageRecord.sha256 == sha256).limit(1))
        image_id = str(uuid4())
        storage_path = storage.save(image_id, metadata.suffix, content)
        with Image.open(io.BytesIO(content)) as opened:
            quality = quality_service.assess(opened)
            if not quality.can_compare:
                unverifiable_count += 1
            captured_at = extract_capture_datetime(opened)
            if not quality.can_compare:
                phash = None
            elif existing_exact is not None and existing_exact.phash:
                phash = existing_exact.phash
            else:
                phash = phash_detector.calculate(opened).original
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
            analysis_status="QUEUED" if quality.can_compare else "UNVERIFIABLE",
            image_quality_status=quality.status,
            image_quality_reason=quality.reason,
            near_black_ratio=quality.near_black_ratio,
        )
        session.add(record)
        job_items.append(AnalysisJobItem(job_id=job.id, image_id=record.id, position=position, status="QUEUED"))
    # Persist all image rows before creating rows that reference them. The
    # duplicate lookup inside the loop can autoflush pending images, so defer
    # AnalysisJobItem rows until the image inserts are complete.
    await session.flush()
    session.add_all(job_items)
    await session.commit()
    try:
        dispatch_batch_job(background_tasks, job.id)
    except JobDispatchError as exc:
        job.status = "FAILED"
        job.error = str(exc)
        await session.commit()
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {
        "job_id": job.id,
        "status": job.status,
        "file_count": len(files),
        "unverifiable_count": unverifiable_count,
    }


@router.post("/reanalyze", status_code=202)
async def reanalyze_library(background_tasks: BackgroundTasks, session: AsyncSession = Depends(get_session)) -> dict:
    await _ensure_no_active_job(session)
    records = list(await session.scalars(select(ImageRecord).order_by(ImageRecord.created_at)))
    if not records:
        raise HTTPException(status_code=422, detail="ยังไม่มีภาพในคลังสำหรับวิเคราะห์ใหม่")
    job = AnalysisJob(status="QUEUED", total=len(records), processed=0)
    session.add(job)
    await session.flush()
    for position, record in enumerate(records):
        reference = parse_source_reference(record.original_filename)
        if reference is not None:
            record.source_technician_id = reference.technician_id
            record.source_job_number = reference.job_number
            record.source_checkin_date = reference.checkin_date
            record.source_job_type = reference.job_type
        elif record.source_job_type is None:
            record.source_job_type = parse_job_type(record.original_filename)
        record.analysis_status = "QUEUED"
        session.add(AnalysisJobItem(job_id=job.id, image_id=record.id, position=position, status="QUEUED"))
    await session.commit()
    try:
        dispatch_batch_job(background_tasks, job.id, True)
    except JobDispatchError as exc:
        job.status = "FAILED"
        job.error = str(exc)
        await session.commit()
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"job_id": job.id, "status": job.status, "file_count": len(records)}
