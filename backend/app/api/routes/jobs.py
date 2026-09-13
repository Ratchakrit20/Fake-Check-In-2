from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...db.models import AnalysisJob, AnalysisJobItem
from ...db.session import get_session

router = APIRouter(prefix="/jobs", tags=["jobs"])


def _job_response(job: AnalysisJob, items: list[AnalysisJobItem]) -> dict:
    return {
        "id": job.id,
        "status": job.status,
        "total": job.total,
        "processed": job.processed,
        "error": job.error,
        "items": [{"image_id": item.image_id, "position": item.position, "status": item.status} for item in items],
    }


@router.get("/active")
async def active_job(session: AsyncSession = Depends(get_session)) -> dict | None:
    job = await session.scalar(
        select(AnalysisJob)
        .where(AnalysisJob.status.not_in(["COMPLETED", "FAILED"]))
        .order_by(AnalysisJob.created_at.desc())
    )
    if job is None:
        return None
    items = list(await session.scalars(select(AnalysisJobItem).where(AnalysisJobItem.job_id == job.id)))
    return _job_response(job, items)


@router.get("/{job_id}")
async def job_detail(job_id: str, session: AsyncSession = Depends(get_session)) -> dict:
    job = await session.get(AnalysisJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    items = list(await session.scalars(select(AnalysisJobItem).where(AnalysisJobItem.job_id == job_id)))
    return _job_response(job, items)
