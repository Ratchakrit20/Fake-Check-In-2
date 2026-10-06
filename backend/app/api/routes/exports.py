from __future__ import annotations

import io
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from PIL import Image, ImageDraw, ImageFont
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
    customer_ids: list[str] = Field(min_length=1)
    date_from: str
    date_to: str


def image_source(image: ImageRecord) -> tuple[str | None, str | None]:
    reference = parse_source_reference(image.original_filename)
    return image.source_job_number or (reference.job_number if reference else None), image.source_checkin_date or (reference.checkin_date if reference else None)


def image_technician(image: ImageRecord) -> str | None:
    reference = parse_source_reference(image.original_filename)
    return image.source_technician_id or (reference.technician_id if reference else None)


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
        group_customer_ids = sorted({customer_id for image in group if (customer_id := image_source(image)[0])})
        for image in group:
            job_number, checkin_date = image_source(image)
            if (
                not job_number
                or not checkin_date
                or not date_from <= checkin_date <= date_to
                or (search and search not in job_number)
            ):
                continue
            item = by_bbid.setdefault(job_number, {"bbid": job_number, "image_count": 0, "dates": set(), "related_customer_ids": set()})
            item["image_count"] += 1
            item["dates"].add(checkin_date)
            item["related_customer_ids"].update(group_customer_ids)
    return {"items": [{**item, "dates": sorted(item["dates"]), "related_customer_ids": sorted(item["related_customer_ids"]), "exported": item["bbid"] in exported} for item in sorted(by_bbid.values(), key=lambda item: item["bbid"])]}


@router.post("/pdf")
async def create_export_pdf(request: CreateExportRequest, session: AsyncSession = Depends(get_session)) -> dict:
    try:
        from reportlab.lib.colors import HexColor
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.utils import ImageReader
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        from reportlab.pdfgen.canvas import Canvas
    except ImportError as exc:
        raise HTTPException(status_code=503, detail="PDF support is not installed; run python -m pip install -e .") from exc
    selected_customer_ids = set(request.customer_ids)
    selected_groups: list[tuple[str, list[ImageRecord]]] = []
    for index, group in enumerate(await related_groups(session), start=1):
        matches_selected_period = any(
            (job_number := image_source(image)[0]) in selected_customer_ids
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
    report_dates = sorted(
        {
            checkin_date
            for _, group in selected_groups
            for image in group
            if (checkin_date := image_source(image)[1])
        }
    )
    report_date_from = report_dates[0] if report_dates else request.date_from
    report_date_to = report_dates[-1] if report_dates else request.date_to
    settings = get_settings()
    export_dir = Path(settings.storage.root) / "exports"
    export_dir.mkdir(parents=True, exist_ok=True)
    report_id = str(uuid4())
    pdf_path = export_dir / f"export-{report_id}.pdf"
    canvas = Canvas(str(pdf_path), pagesize=A4)
    font_dir = Path(__file__).parents[4] / "font" / "Sarabun"
    thai_font, thai_bold_font = "Sarabun", "Sarabun-Bold"
    pdfmetrics.registerFont(TTFont(thai_font, str(font_dir / "Sarabun-Regular.ttf")))
    pdfmetrics.registerFont(TTFont(thai_bold_font, str(font_dir / "Sarabun-Bold.ttf")))
    width, height = A4
    green, orange, soft_green, muted = HexColor("#12372A"), HexColor("#F59E0B"), HexColor("#F3F8F5"), HexColor("#60756C")
    storage = LocalImageStorage(settings.storage.root)
    logo = Path(__file__).parents[4] / "frontend" / "public" / "AIS-3BB-Fibre3-FullColor-DarkBG.png"
    margin, gap, columns = 36, 8, 4
    card_width = (width - margin * 2 - gap * (columns - 1)) / columns
    card_height = 135

    def format_report_date(value: str) -> str:
        compact = value.replace("-", "")
        return f"{compact[6:8]}-{compact[4:6]}-{compact[0:4]}" if len(compact) == 8 else value

    def draw_thai_text(text: str, x: float, y: float, size: int, color: str) -> None:
        """Render Thai with Pillow's shaping engine, then place it in the PDF."""
        scale = 3
        try:
            font = ImageFont.truetype(
                str(font_dir / "Sarabun-Regular.ttf"), size * scale,
                layout_engine=ImageFont.Layout.RAQM,
            )
        except (AttributeError, OSError, ValueError):
            font = ImageFont.truetype(str(font_dir / "Sarabun-Regular.ttf"), size * scale)
        box = font.getbbox(text)
        image = Image.new("RGBA", (box[2] - box[0] + 6 * scale, box[3] - box[1] + 6 * scale), (255, 255, 255, 0))
        ImageDraw.Draw(image).text((3 * scale - box[0], 3 * scale - box[1]), text, font=font, fill=color)
        content = io.BytesIO()
        image.save(content, format="PNG")
        rendered_width, rendered_height = image.width / scale, image.height / scale
        canvas.drawImage(ImageReader(content), x, y - rendered_height + 2, width=rendered_width, height=rendered_height, mask="auto")

    def draw_header(page_number: int) -> float:
        canvas.setFillColor(green)
        canvas.rect(0, height - 88, width, 88, fill=1, stroke=0)
        if logo.exists():
            canvas.drawImage(
                ImageReader(str(logo)), margin, height - 70,
                width=102, height=48, preserveAspectRatio=True, mask="auto",
            )
        canvas.setFillColor(HexColor("#FFFFFF"))
        canvas.setFont(thai_bold_font, 16)
        canvas.drawString(148, height - 51, "Fake Check In Report")
        period = format_report_date(report_date_from) if report_date_from == report_date_to else f"{format_report_date(report_date_from)} - {format_report_date(report_date_to)}"
        canvas.setFillColor(green)
        canvas.setFont(thai_font, 10)
        canvas.drawString(margin, height - 111, f"Period: {period}")
        canvas.setFont(thai_bold_font, 10)
        canvas.drawString(margin, height - 127, f"Customer ID selected: {len(selected_customer_ids)}")
        canvas.setFont(thai_font, 10)
        canvas.drawString(margin, height - 143, f"Export Date: {datetime.now().strftime('%d-%m-%Y')}")
        canvas.setFillColor(muted)
        canvas.setFont(thai_font, 9)
        canvas.drawRightString(width - margin, 25, f"Page {page_number}")
        return height - 180

    def draw_group_heading(number: int, group: list[ImageRecord], y_position: float) -> float:
        customer_ids = ", ".join(sorted({customer_id for image in group if (customer_id := image_source(image)[0])}))
        technician_ids = ", ".join(sorted({technician_id for image in group if (technician_id := image_technician(image))}))
        canvas.setFillColor(orange)
        canvas.roundRect(margin, y_position - 4, 5, 30, 2, fill=1, stroke=0)
        canvas.setFillColor(green)
        canvas.setFont(thai_bold_font, 13)
        canvas.drawString(margin + 14, y_position + 10, f"Group {number}")
        canvas.setFillColor(muted)
        canvas.setFont(thai_bold_font, 9)
        canvas.drawString(margin + 14, y_position - 3, "Technician ID:")
        canvas.drawString(margin + 14, y_position - 14, "Customer ID:")
        canvas.setFont(thai_font, 9)
        canvas.drawString(margin + 76, y_position - 3, technician_ids[:88] or "-")
        canvas.drawString(margin + 76, y_position - 14, customer_ids[:90])
        draw_thai_text(
            "กลุ่มนี้รวมภาพที่ใช้ซ้ำหรือคล้ายกัน ซึ่งถูกนำไปใช้กับ Customer ID อื่น",
            margin + 14,
            y_position - 21,
            9,
            "#60756C",
        )
        return y_position - 43

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
        canvas.setFont(thai_bold_font, 8)
        canvas.drawString(x + 7, y_position - 105, f"Customer ID: {job_number or '-'}")
        canvas.setFont(thai_font, 8)
        canvas.drawString(x + 7, y_position - 116, f"Date: {checkin_date or '-'}")
        filename = image.original_filename
        canvas.setFillColor(muted)
        canvas.setFont(thai_font, 7)
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
            y -= card_height + 25
        canvas.setStrokeColor(HexColor("#CFE0D5"))
        canvas.setLineWidth(0.7)
        canvas.line(margin, y + 12, width - margin, y + 12)
        y -= 25
    canvas.save()
    report = ExportReport(id=report_id, date_from=report_date_from, date_to=report_date_to, pdf_path=str(pdf_path), created_at=datetime.utcnow())
    session.add(report)
    for image, group_id in report_images.values():
        job_number, checkin_date = image_source(image)
        session.add(ExportReportImage(export_report_id=report_id, image_id=image.id, source_job_number=job_number, source_checkin_date=checkin_date, source_technician_id=image_technician(image), group_id_snapshot=group_id))
    await session.commit()
    return {
        "report_id": report_id,
        "download_url": f"/api/v1/exports/reports/{report_id}",
    }


@router.get("/reports/{report_id}")
async def download_export_pdf(report_id: str, session: AsyncSession = Depends(get_session)) -> FileResponse:
    report = await session.get(ExportReport, report_id)
    if report is None or not Path(report.pdf_path).is_file():
        raise HTTPException(status_code=404, detail="ไม่พบไฟล์รายงาน")
    return FileResponse(
        report.pdf_path,
        media_type="application/pdf",
        filename=f"relationship-report-{report.date_from}-{report.date_to}.pdf",
    )
