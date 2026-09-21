import io
from pathlib import Path
from uuid import uuid4
from typing import cast
from fastapi import APIRouter, BackgroundTasks, Depends, File, Request, HTTPException, UploadFile
from PIL import Image
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.config import get_settings
from ...db.models import AnalysisJob, AnalysisJobItem, ImageRecord
from ...db.session import get_session
from ...detectors.perceptual_hash_detector import PerceptualHashDetector
from ...detectors.sha256_detector import SHA256Detector
from ...services.batch_analysis_service import run_batch_job
from ...services.image_validation_service import ImageValidationService
from ...storage.local_storage import LocalImageStorage

router = APIRouter(prefix="/batches", tags=["batches"])


async def _ensure_no_active_job(session: AsyncSession) -> None:
    active = await session.scalar(
        select(AnalysisJob.id).where(AnalysisJob.status.not_in(["COMPLETED", "FAILED"]))
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
    for position, file in enumerate(files):
        content = await file.read()
        metadata = validator.validate(content)
        sha256 = SHA256Detector.from_bytes(content)
        # Every upload is evidence. Keep separate records even when the bytes
        # are identical so the relationship graph can show an exact reuse.
        existing_exact = await session.scalar(select(ImageRecord).where(ImageRecord.sha256 == sha256).limit(1))
        image_id = str(uuid4())
        storage_path = storage.save(image_id, metadata.suffix, content)
        if existing_exact is not None and existing_exact.phash:
            phash = existing_exact.phash
        else:
            with Image.open(io.BytesIO(content)) as opened:
                phash = phash_detector.calculate(opened).original
        record = ImageRecord(
            id=image_id,
            original_filename=Path(file.filename or "image").name,
            storage_path=str(storage_path),
            file_size=len(content),
            width=metadata.width,
            height=metadata.height,
            mime_type=metadata.mime_type,
            sha256=sha256,
            phash=phash,
            analysis_status="QUEUED",
        )
        session.add(record)
        await session.flush()
        session.add(AnalysisJobItem(job_id=job.id, image_id=record.id, position=position, status="QUEUED"))
    await session.commit()
    background_tasks.add_task(run_batch_job, job.id)
    return {"job_id": job.id, "status": job.status, "file_count": len(files)}


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
        record.analysis_status = "QUEUED"
        session.add(AnalysisJobItem(job_id=job.id, image_id=record.id, position=position, status="QUEUED"))
    await session.commit()
    background_tasks.add_task(run_batch_job, job.id, True)
    return {"job_id": job.id, "status": job.status, "file_count": len(records)}
