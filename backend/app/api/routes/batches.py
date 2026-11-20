import io
import json
import logging
from pathlib import Path
from typing import cast
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, UploadFile
from PIL import Image
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from ...core.config import get_settings
from ...db.models import AnalysisJob, AnalysisJobItem, ImageRecord
from ...db.session import get_session
from ...detectors.perceptual_hash_detector import PerceptualHashDetector
from ...detectors.sha256_detector import SHA256Detector
from ...services.image_metadata_service import extract_capture_datetime
from ...services.image_quality_service import QUALITY_VERSION, ImageQualityService
from ...services.image_validation_service import ImageValidationService
from ...services.job_dispatch_service import JobDispatchError, dispatch_batch_job
from ...services.lmr_import_service import LmrImageImportService, LmrImportError
from ...services.source_filename import parse_job_type, parse_source_reference
from ...storage.local_storage import configured_image_storage

router = APIRouter(prefix="/batches", tags=["batches"])
logger = logging.getLogger(__name__)


class LmrImportRequest(BaseModel):
    date: str
    categories: list[str] | None = None


@router.get("/lmr/dates")
async def list_lmr_import_dates(session: AsyncSession = Depends(get_session)) -> dict:
    settings = get_settings()
    service = LmrImageImportService(settings)
    available = settings.lmr_import.enabled and settings.lmr_import.root.is_dir()
    if available:
        try:
            dates = await run_in_threadpool(service.available_dates)
        except OSError:
            logger.exception("Unable to list configured LMR archive")
            dates = []
            available = False
    else:
        dates = []
    grouped_status = await session.execute(
        select(ImageRecord.source_archive_date, ImageRecord.analysis_status, func.count())
        .where(ImageRecord.source_archive_date.is_not(None))
        .group_by(ImageRecord.source_archive_date, ImageRecord.analysis_status)
    )
    counts: dict[str, dict[str, int]] = {}
    for archive_date, status, count in grouped_status:
        values = counts.setdefault(
            archive_date,
            {"imported_count": 0, "analyzed_count": 0, "pending_count": 0},
        )
        values["imported_count"] += count
        values["analyzed_count" if status in {"COMPLETED", "UNVERIFIABLE"} else "pending_count"] += count
    for date_info in dates:
        date_info.update(
            counts.get(str(date_info["date"]), {"imported_count": 0, "analyzed_count": 0, "pending_count": 0})
        )
        date_info["not_imported_count"] = max(0, int(date_info["image_count"]) - int(date_info["imported_count"]))
        date_info["analysis_complete"] = (
            int(date_info["image_count"]) > 0
            and int(date_info["analyzed_count"]) >= int(date_info["image_count"])
        )
    return {"available": available, "dates": dates}


@router.post("/lmr/import", status_code=202)
async def import_lmr_date(
    request: LmrImportRequest,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
) -> dict:
    settings = get_settings()
    if not settings.lmr_import.enabled:
        raise HTTPException(status_code=503, detail="ปิดการนำเข้าคลัง LMR ใน config อยู่")
    if not settings.lmr_import.root.is_dir():
        raise HTTPException(status_code=503, detail="backend เข้าถึงโฟลเดอร์คลัง LMR ที่ตั้งไว้ไม่ได้")

    await _ensure_no_active_job(session)
    importer = LmrImageImportService(settings)
    try:
        day_paths = await run_in_threadpool(
            importer.image_paths_for_selection,
            request.date,
            request.categories,
        )
    except LmrImportError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except OSError as exc:
        logger.exception("Unable to scan configured LMR archive")
        raise HTTPException(status_code=503, detail="อ่านโฟลเดอร์คลัง LMR ไม่ได้ ตรวจสิทธิ์และไดรฟ์ที่ตั้งค่าไว้") from exc
    image_paths = [(day_root, path) for day_root, path in day_paths]
    if not image_paths:
        raise HTTPException(status_code=422, detail="ไม่พบไฟล์ภาพในโฟลเดอร์วันที่เลือก")

    existing_by_path: dict[str, ImageRecord] = {}
    path_strings = [str(path) for _, path in image_paths]
    for offset in range(0, len(path_strings), 500):
        rows = await session.scalars(
            select(ImageRecord).where(
                ImageRecord.storage_path.in_(path_strings[offset : offset + 500])
            )
        )
        existing_by_path.update((row.storage_path, row) for row in rows)

    scheduled_records: list[ImageRecord] = []
    new_records: list[ImageRecord] = []
    new_paths: list[tuple[Path, Path]] = []
    invalid_count = 0
    already_analyzed_count = 0
    pending_retry_count = 0
    for day_root, image_path in image_paths:
        existing = existing_by_path.get(str(image_path))
        if existing is not None:
            if existing.analysis_status in {"COMPLETED", "UNVERIFIABLE"}:
                already_analyzed_count += 1
            else:
                existing.analysis_status = "QUEUED"
                scheduled_records.append(existing)
                pending_retry_count += 1
            continue
        new_paths.append((day_root, image_path))

    potential_job_size = len(scheduled_records) + len(new_paths)
    if potential_job_size > settings.lmr_import.max_images_per_job:
        raise HTTPException(
            status_code=422,
            detail=(
                f"มีภาพที่ยังต้องวิเคราะห์สูงสุด {potential_job_size:,} ภาพ เกินขีดจำกัด "
                f"{settings.lmr_import.max_images_per_job:,} ภาพต่อ Job"
            ),
        )

    for day_root, image_path in new_paths:
        try:
            record = await run_in_threadpool(importer.build_pending_record, image_path, day_root)
        except (OSError, ValueError) as exc:
            invalid_count += 1
            logger.warning("LMR import skipped %s: %s", image_path, exc)
            continue
        scheduled_records.append(record)
        new_records.append(record)

    already_imported_count = len(image_paths) - len(new_records) - invalid_count
    if not scheduled_records:
        return {
            "job_id": None,
            "status": "ALREADY_ANALYZED",
            "found_count": len(image_paths),
            "imported_count": 0,
            "already_imported_count": already_imported_count,
            "already_analyzed_count": already_analyzed_count,
            "pending_retry_count": 0,
            "scheduled_count": 0,
            "invalid_count": invalid_count,
        }

    job = AnalysisJob(status="QUEUED", total=len(scheduled_records), processed=0)
    session.add(job)
    await session.flush()
    session.add_all(new_records)
    await session.flush()
    session.add_all(
        AnalysisJobItem(job_id=job.id, image_id=record.id, position=position, status="QUEUED")
        for position, record in enumerate(scheduled_records)
    )
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
        "found_count": len(image_paths),
        "imported_count": len(new_records),
        "already_imported_count": already_imported_count,
        "already_analyzed_count": already_analyzed_count,
        "pending_retry_count": pending_retry_count,
        "scheduled_count": len(scheduled_records),
        "invalid_count": invalid_count,
    }


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
    storage = configured_image_storage(settings)
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
            rotations = None
            if quality.can_compare:
                if existing_exact is not None and existing_exact.phash_rotations_json:
                    try:
                        saved_rotations = json.loads(existing_exact.phash_rotations_json)
                        if all(str(angle) in saved_rotations for angle in phash_detector.ROTATION_ANGLES):
                            rotations = {str(angle): str(saved_rotations[str(angle)]) for angle in phash_detector.ROTATION_ANGLES}
                    except (TypeError, ValueError):
                        rotations = None
                if rotations is None:
                    rotations = phash_detector.calculate_rotations(opened)
            phash = rotations["0"] if rotations else None
            phash_rotations_json = json.dumps(rotations, separators=(",", ":")) if quality.can_compare else None
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
            phash_rotations_json=phash_rotations_json,
            analysis_status="QUEUED" if quality.can_compare else "UNVERIFIABLE",
            image_quality_status=quality.status,
            image_quality_version=QUALITY_VERSION,
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
