from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...db.models import AnalysisJob, ImageRecord, PairwiseResult
from ...db.session import get_session

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("")
async def dashboard(session: AsyncSession = Depends(get_session)) -> dict:
    total = await session.scalar(select(func.count()).select_from(ImageRecord)) or 0
    allowed = ["exact_file", "same_image", "edited_or_cropped", "background_replaced"]
    related = await session.scalar(select(func.count()).select_from(PairwiseResult).where(PairwiseResult.relationship_level.in_(allowed))) or 0
    pending = await session.scalar(select(func.count()).select_from(AnalysisJob).where(AnalysisJob.status.not_in(["COMPLETED", "FAILED"]))) or 0
    failed = await session.scalar(select(func.count()).select_from(AnalysisJob).where(AnalysisJob.status == "FAILED")) or 0
    return {"total_images": total, "related_pairs": related, "pending_jobs": pending, "failed_jobs": failed}
