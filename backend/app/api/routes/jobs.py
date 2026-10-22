from datetime import UTC, datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.config import get_settings
from ...db.models import AnalysisJob, AnalysisJobItem, ImageEmbedding
from ...db.session import get_session
from ...domain.enums import JobStatus
from ...services.job_dispatch_service import JobDispatchError, dispatch_batch_job

router = APIRouter(prefix="/jobs", tags=["jobs"])


def _job_response(
    job: AnalysisJob,
    embedded: int = 0,
    completed_items: int | None = None,
) -> dict:
    # The job counter is a cached progress value. Reconcile it with the durable
    # per-image checkpoints so a delayed counter update cannot move the UI back.
    processed = max(int(job.processed or 0), int(completed_items or 0))
    if job.total:
        processed = min(processed, job.total)
    return {
        "id": job.id,
        "status": job.status,
        "total": job.total,
        "processed": processed,
        "error": job.error,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
        "duration_seconds": job.duration_seconds,
        "embedded": embedded,
    }


async def _embedded_count(session: AsyncSession, job: AnalysisJob) -> int:
    if job.status != JobStatus.EMBEDDING.value:
        return 0
    settings = get_settings()
    count = await session.scalar(
        select(func.count(func.distinct(ImageEmbedding.image_id)))
        .join(AnalysisJobItem, AnalysisJobItem.image_id == ImageEmbedding.image_id)
        .where(
            AnalysisJobItem.job_id == job.id,
            ImageEmbedding.model_name == settings.embedding.model,
            ImageEmbedding.model_version == settings.embedding.version,
        )
    )
    return int(count or 0)


async def _completed_item_count(session: AsyncSession, job: AnalysisJob) -> int:
    count = await session.scalar(
        select(func.count(AnalysisJobItem.id)).where(
            AnalysisJobItem.job_id == job.id,
            AnalysisJobItem.status == JobStatus.COMPLETED.value,
        )
    )
    return int(count or 0)


@router.get("/active")
async def active_job(session: AsyncSession = Depends(get_session)) -> dict | None:
    job = await session.scalar(
        select(AnalysisJob)
        .where(AnalysisJob.status.not_in(["COMPLETED", "CANCELLED", "INTERRUPTED", "FAILED"]))
        .order_by(AnalysisJob.created_at.desc())
    )
    # After a browser reload there may be no active job even though the latest
    # batch was cancelled or interrupted. Return that resumable job so the UI
    # can offer Resume instead of making the user reselect all uploaded files.
    if job is None:
        job = await session.scalar(
            select(AnalysisJob)
            .where(
                AnalysisJob.status.in_(["CANCELLED", "INTERRUPTED", "FAILED"]),
                AnalysisJob.processed < AnalysisJob.total,
            )
            .order_by(AnalysisJob.created_at.desc())
        )
    if job is None:
        return None
    completed = await _completed_item_count(session, job)
    return _job_response(job, await _embedded_count(session, job), completed)


@router.post("/{job_id}/cancel")
async def cancel_job(job_id: str, session: AsyncSession = Depends(get_session)) -> dict:
    """Request cooperative cancellation of a queued or running batch job."""
    job = await session.get(AnalysisJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    if job.status in {JobStatus.COMPLETED.value, JobStatus.CANCELLED.value, JobStatus.FAILED.value}:
        return _job_response(job)

    now = datetime.now(UTC).replace(tzinfo=None)
    job.status = JobStatus.CANCELLED.value
    job.error = "cancelled by user"
    job.completed_at = now
    started_at = job.started_at or job.created_at
    job.duration_seconds = max(0.0, (now - started_at).total_seconds())
    await session.commit()
    return _job_response(job)


@router.post("/{job_id}/resume", status_code=202)
async def resume_job(job_id: str, background_tasks: BackgroundTasks, session: AsyncSession = Depends(get_session)) -> dict:
    job = await session.get(AnalysisJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    if job.status not in {JobStatus.FAILED.value, JobStatus.INTERRUPTED.value, JobStatus.CANCELLED.value}:
        raise HTTPException(status_code=409, detail="job is already running or completed")
    job.status = JobStatus.QUEUED.value
    job.error = None
    job.completed_at = None
    job.duration_seconds = None
    await session.commit()
    try:
        dispatch_batch_job(background_tasks, job.id)
    except JobDispatchError as exc:
        job.status = JobStatus.FAILED.value
        job.error = str(exc)
        job.completed_at = None
        job.duration_seconds = None
        await session.commit()
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return _job_response(job)


@router.get("/{job_id}")
async def job_detail(job_id: str, session: AsyncSession = Depends(get_session)) -> dict:
    job = await session.get(AnalysisJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    completed = await _completed_item_count(session, job)
    return _job_response(job, await _embedded_count(session, job), completed)
