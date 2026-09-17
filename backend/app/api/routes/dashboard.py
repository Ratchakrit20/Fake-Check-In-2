from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...db.models import AnalysisJob, PairwiseResult
from ...db.session import get_session
from ...services.dashboard_report_service import build_dashboard_summary, create_excel_report

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("")
async def dashboard(session: AsyncSession = Depends(get_session)) -> dict:
    summary = await build_dashboard_summary(session)
    total = summary["images_in_system"]
    allowed = ["exact_file", "same_image", "edited_or_cropped", "background_replaced"]
    related = await session.scalar(select(func.count()).select_from(PairwiseResult).where(PairwiseResult.relationship_level.in_(allowed))) or 0
    pending = await session.scalar(select(func.count()).select_from(AnalysisJob).where(AnalysisJob.status.not_in(["COMPLETED", "FAILED"]))) or 0
    failed = await session.scalar(select(func.count()).select_from(AnalysisJob).where(AnalysisJob.status == "FAILED")) or 0
    return {
        "total_images": total,
        "related_pairs": related,
        "pending_jobs": pending,
        "failed_jobs": failed,
        **summary,
    }


@router.get("/report.xlsx")
async def dashboard_report(
    total_images: int | None = Query(default=None, ge=0),
    session: AsyncSession = Depends(get_session),
) -> Response:
    summary = await build_dashboard_summary(session)
    content = create_excel_report(summary, total_images)
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="image-analysis-report.xlsx"'},
    )
