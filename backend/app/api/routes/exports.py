from __future__ import annotations

from datetime import datetime
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.config import get_settings
from ...db.models import ExportReport, ExportReportImage, ImageRecord, PairwiseResult
from ...db.session import get_session
from ...services.relationship_graph_service import RelationshipGraphService
from ...services.relationship_group_service import merge_group_indexes_by_bbid
from ...services.source_filename import parse_source_reference
from ...storage.local_storage import LocalImageStorage

router = APIRouter(prefix="/exports", tags=["exports"])

# RELATED_CLASSIFICATIONS = ["exact_file", "same_image", "edited_or_cropped", "background_replaced", "repeated_checkin", "same_scene_new_capture"]
RELATED_CLASSIFICATIONS = ["exact_file", "same_image", "edited_or_cropped"]

class CreateExportRequest(BaseModel):
    bbids: list[str] = Field(min_length=1)
    date_from: str
    date_to: str


def image_source(image: ImageRecord) -> tuple[str | None, str | None]:
    reference = parse_source_reference(image.original_filename)
    return image.source_job_number or (reference.job_number if reference else None), image.source_checkin_date or (reference.checkin_date if reference else None)


async def related_groups(session: AsyncSession) -> list[list[ImageRecord]]:
    """Only components backed by a qualified detected relationship."""
    settings = get_settings()
    images = list(await session.scalars(select(ImageRecord)))
    image_by_id = {image.id: image for image in images}
    pairs = list(await session.scalars(select(PairwiseResult).where(
        PairwiseResult.relationship_level.in_(RELATED_CLASSIFICATIONS),
        PairwiseResult.relationship_score >= settings.relationship.graph_edge_threshold,
    )))
    edges = RelationshipGraphService.qualified_edges(
        [(pair.image_a_id, pair.image_b_id, pair.relationship_score) for pair in pairs],
        settings.relationship.graph_edge_threshold,
    )
    components = [
        [image_by_id[image_id] for image_id in component]
        for component in RelationshipGraphService.connected_components(list(image_by_id), edges)
        if len(component) > 1
    ]
    merged_indexes = merge_group_indexes_by_bbid(
        [{job_number for image in component if (job_number := image_source(image)[0])} for component in components]
    )
    return [
        [image for component_index in indexes for image in components[component_index]]
        for indexes in merged_indexes
    ]


@router.get("/bbids")
async def exportable_bbids(date_from: str, date_to: str, search: str = "", session: AsyncSession = Depends(get_session)) -> dict:
    by_bbid: dict[str, dict] = {}
    exported = {row[0] for row in (await session.execute(select(ExportReportImage.source_job_number))).all() if row[0]}
    for group in await related_groups(session):
        for image in group:
            job_number, checkin_date = image_source(image)
            if (
                not job_number
                or not checkin_date
                or not date_from <= checkin_date <= date_to
                or (search and search not in job_number)
            ):
                continue
            item = by_bbid.setdefault(job_number, {"bbid": job_number, "image_count": 0, "dates": set()})
            item["image_count"] += 1
            item["dates"].add(checkin_date)
    return {"items": [{**item, "dates": sorted(item["dates"]), "exported": item["bbid"] in exported} for item in sorted(by_bbid.values(), key=lambda item: item["bbid"])]}


@router.post("/pdf")
async def create_export_pdf(request: CreateExportRequest, session: AsyncSession = Depends(get_session)) -> FileResponse:
    try:
        from reportlab.lib.colors import HexColor
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.utils import ImageReader
        from reportlab.pdfgen.canvas import Canvas
    except ImportError as exc:
        raise HTTPException(status_code=503, detail="PDF support is not installed; run python -m pip install -e .") from exc
    selected_bbids = set(request.bbids)
    selected_groups: list[tuple[str, list[ImageRecord]]] = []
    for index, group in enumerate(await related_groups(session), start=1):
        matches_selected_period = any(
            (job_number := image_source(image)[0]) in selected_bbids
            and (checkin_date := image_source(image)[1]) is not None
            and request.date_from <= checkin_date <= request.date_to
            for image in group
        )
        if matches_selected_period:
            # The selected BBID only chooses a group. Every image in that
            # group remains in the PDF so the visual relationship is complete.
            selected_groups.append((f"group-{index}", group))
    if not selected_groups:
        raise HTTPException(status_code=422, detail="ไม่พบกลุ่มภาพที่ใช้ซ้ำตาม BBID และช่วงวันที่ที่เลือก")
    settings = get_settings()
    export_dir = Path(settings.storage.root) / "exports"
    export_dir.mkdir(parents=True, exist_ok=True)
    report_id = str(uuid4())
    pdf_path = export_dir / f"export-{report_id}.pdf"
    canvas = Canvas(str(pdf_path), pagesize=A4)
    width, height = A4
    green, orange, soft_green, muted = HexColor("#12372A"), HexColor("#F59E0B"), HexColor("#F3F8F5"), HexColor("#60756C")
    storage = LocalImageStorage(settings.storage.root)
    logo = Path(__file__).parents[4] / "frontend" / "public" / "AIS-3BB-Fibre3-FullColor-LightBG.png"
    margin, gap, columns = 36, 8, 4
    card_width = (width - margin * 2 - gap * (columns - 1)) / columns
    card_height = 135

    def draw_header(page_number: int) -> float:
        canvas.setFillColor(green)
        canvas.rect(0, height - 88, width, 88, fill=1, stroke=0)
        # The source logo is designed for a light background. Give it a white
        # panel in the dark report header and make it prominent but contained.
        canvas.setFillColor(HexColor("#FFFFFF"))
        canvas.roundRect(margin, height - 78, 102, 60, 8, fill=1, stroke=0)
        if logo.exists():
            canvas.drawImage(
                ImageReader(str(logo)), margin + 8, height - 70,
                width=86, height=44, preserveAspectRatio=True, mask="auto",
            )
        canvas.setFillColor(HexColor("#FFFFFF"))
        canvas.setFont("Helvetica-Bold", 16)
        canvas.drawString(152, height - 51, "Image Reuse Report")
        period = request.date_from if request.date_from == request.date_to else f"{request.date_from} - {request.date_to}"
        canvas.setFillColor(green)
        canvas.setFont("Helvetica", 9)
        canvas.drawString(margin, height - 111, f"Period: {period}")
        canvas.setFont("Helvetica-Bold", 9)
        canvas.drawString(margin, height - 127, f"BBIDs selected: {len(request.bbids)}")
        canvas.setFillColor(muted)
        canvas.setFont("Helvetica", 8)
        canvas.drawRightString(width - margin, 25, f"Page {page_number}")
        return height - 180

    def draw_group_heading(number: int, group: list[ImageRecord], y_position: float) -> float:
        bbids = ", ".join(sorted({job for image in group if (job := image_source(image)[0])}))
        canvas.setFillColor(orange)
        canvas.roundRect(margin, y_position - 4, 5, 30, 2, fill=1, stroke=0)
        canvas.setFillColor(green)
        canvas.setFont("Helvetica-Bold", 12)
        canvas.drawString(margin + 14, y_position + 10, f"Group {number}")
        canvas.setFillColor(muted)
        canvas.setFont("Helvetica", 8)
        canvas.drawString(margin + 14, y_position - 3, f"BBIDs in group: {bbids[:104]}")
        return y_position - 25

    def draw_card(image: ImageRecord, x: float, y_position: float) -> None:
        canvas.setFillColor(soft_green)
        canvas.roundRect(x, y_position - card_height, card_width, card_height, 7, fill=1, stroke=0)
        resolved = storage.resolve(image.id, image.storage_path)
        if resolved:
            canvas.drawImage(
                ImageReader(str(resolved)), x + 6, y_position - 92,
                width=card_width - 12, height=78, preserveAspectRatio=True,
                anchor="c", mask="auto",
            )
        job_number, checkin_date = image_source(image)
        canvas.setFillColor(green)
        canvas.setFont("Helvetica-Bold", 7)
        canvas.drawString(x + 7, y_position - 105, f"BBID: {job_number or '-'}")
        canvas.setFont("Helvetica", 7)
        canvas.drawString(x + 7, y_position - 116, f"Date: {checkin_date or '-'}")
        filename = image.original_filename
        canvas.setFillColor(muted)
        canvas.setFont("Helvetica", 6.5)
        canvas.drawString(x + 7, y_position - 127, filename[:28] + ("..." if len(filename) > 28 else ""))

    page_number = 1
    y = draw_header(page_number)
    report_images: dict[str, tuple[ImageRecord, str]] = {}
    for group_number, (group_id, group) in enumerate(selected_groups, start=1):
        if y < margin + card_height + 52:
            canvas.showPage(); page_number += 1; y = draw_header(page_number)
        y = draw_group_heading(group_number, group, y)
        for row_start in range(0, len(group), columns):
            if y - card_height < margin:
                canvas.showPage(); page_number += 1; y = draw_header(page_number)
                y = draw_group_heading(group_number, group, y)
            for column, image in enumerate(group[row_start : row_start + columns]):
                draw_card(image, margin + column * (card_width + gap), y)
                report_images[image.id] = (image, group_id)
            y -= card_height + 10
        y -= 25
    canvas.save()
    report = ExportReport(id=report_id, date_from=request.date_from, date_to=request.date_to, pdf_path=str(pdf_path), created_at=datetime.utcnow())
    session.add(report)
    for image, group_id in report_images.values():
        job_number, checkin_date = image_source(image)
        session.add(ExportReportImage(export_report_id=report_id, image_id=image.id, source_job_number=job_number, source_checkin_date=checkin_date, group_id_snapshot=group_id))
    await session.commit()
    return FileResponse(pdf_path, media_type="application/pdf", filename=f"relationship-report-{request.date_from}-{request.date_to}.pdf")
