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
from ...services.relationship_group_service import build_reportable_groups, build_reportable_groups_as_of, merge_report_groups_by_customer
from ...services.relationship_policy import REPORTABLE_CLASSIFICATIONS
from ...services.image_source_service import resolve_image_source
from ...storage.local_storage import LocalImageStorage

router = APIRouter(prefix="/exports", tags=["exports"])

class CreateExportRequest(BaseModel):
    customer_ids: list[str] = Field(default_factory=list)
    date_from: str
    date_to: str
    include_technician_summary: bool = False


def technician_customer_counts(selected_groups: list[list[ImageRecord]], all_groups: list[list[ImageRecord]]) -> dict[str, set[str]]:
    """Count customers on qualifying images, without inferring new relationships."""
    technicians = {
        source.technician_id for group in selected_groups for image in group
        if (source := resolve_image_source(image)).technician_id
    }
    result: dict[str, set[str]] = {technician: set() for technician in technicians}
    for group in all_groups:
        for image in group:
            source = resolve_image_source(image)
            if source.technician_id in result and source.customer_id:
                result[source.technician_id].add(source.customer_id)
    return result

async def related_groups(session: AsyncSession, merge_by_customer: bool = True) -> list[list[ImageRecord]]:
    """Only components backed by a qualified detected relationship."""
    settings = get_settings()
    minimum_score = settings.relationship.report_min_relationship_score
    images = list(await session.scalars(select(ImageRecord)))
    pairs = list(await session.scalars(select(PairwiseResult).where(
        PairwiseResult.relationship_level.in_(REPORTABLE_CLASSIFICATIONS),
        PairwiseResult.relationship_score >= minimum_score,
    )))
    return build_reportable_groups(images, pairs, minimum_score, merge_by_customer=merge_by_customer)


@router.get("/bbids")
async def exportable_bbids(date_from: str, date_to: str, search: str = "", session: AsyncSession = Depends(get_session)) -> dict:
    by_bbid: dict[str, dict] = {}
    exported = {row[0] for row in (await session.execute(select(ExportReportImage.source_job_number))).all() if row[0]}
    for group in await related_groups(session):
        group_customer_ids = sorted(
            {
                source.customer_id
                for image in group
                if (source := resolve_image_source(image)).customer_id
            }
        )
        for image in group:
            source = resolve_image_source(image)
            job_number, checkin_date = source.customer_id, source.checkin_date
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
    # Load the graph data once. Keep the all-time graph for technician totals,
    # but select PDF evidence from the graph as of the requested date.
    settings = get_settings()
    minimum_score = settings.relationship.report_min_relationship_score
    images = list(await session.scalars(select(ImageRecord)))
    pairs = list(await session.scalars(select(PairwiseResult).where(
        PairwiseResult.relationship_level.in_(REPORTABLE_CLASSIFICATIONS),
        PairwiseResult.relationship_score >= minimum_score,
    )))
    all_groups = build_reportable_groups(images, pairs, minimum_score, merge_by_customer=False)
    report_groups = build_reportable_groups_as_of(images, pairs, minimum_score, request.date_to)
    matching_groups = []
    for group in report_groups:
        matches_selected_period = any(
            (source := resolve_image_source(image)).checkin_date is not None
            and request.date_from <= source.checkin_date <= request.date_to
            and (not selected_customer_ids or source.customer_id in selected_customer_ids)
            for image in group
        )
        if matches_selected_period:
            # Selection chooses a group; its evidence is limited to the
            # selected date and earlier dates by related_groups_as_of().
            matching_groups.append(group)
    if request.include_technician_summary:
        matching_groups = merge_report_groups_by_customer(matching_groups)
    selected_groups = [(f"group-{index}", group) for index, group in enumerate(matching_groups, start=1)]
    if not selected_groups:
        raise HTTPException(status_code=422, detail="ไม่พบกลุ่มภาพที่ใช้ซ้ำตาม BBID และช่วงวันที่ที่เลือก")
    report_dates = sorted(
        {
            checkin_date
            for _, group in selected_groups
            for image in group
            if (checkin_date := resolve_image_source(image).checkin_date)
        }
    )
    report_date_from = report_dates[0] if report_dates else request.date_from
    report_date_to = report_dates[-1] if report_dates else request.date_to
    report_customer_ids = {
        source.customer_id
        for _, group in selected_groups
        for image in group
        if (source := resolve_image_source(image)).customer_id
    }
    technician_customers = technician_customer_counts([group for _, group in selected_groups], all_groups) if request.include_technician_summary else {}
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
    summary_header_bg = HexColor("#458050")
    summary_text = HexColor("#000000")
    storage = LocalImageStorage(settings.storage.root)
    logo = Path(__file__).parents[4] / "frontend" / "public" / "AIS-3BB-Fibre3-FullColor-DarkBG.png"
    margin, gap, columns = 36, 8, 4
    card_width = (width - margin * 2 - gap * (columns - 1)) / columns
    card_height = 135

    def format_report_date(value: str) -> str:
        compact = value.replace("-", "")
        return f"{compact[6:8]}-{compact[4:6]}-{compact[0:4]}" if len(compact) == 8 else value

    def format_card_date(value: str | None) -> str:
        """Use the Thai-friendly date format beneath each evidence image."""
        if not value:
            return "-"
        compact = value.replace("-", "")
        return f"{compact[6:8]}/{compact[4:6]}/{compact[0:4]}" if len(compact) == 8 else value

    def draw_thai_text(
        text: str,
        x: float,
        y: float,
        size: int,
        color: str,
        align_right: bool = False,
        baseline: bool = False,
    ) -> None:
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
        text_origin_y = 3 * scale - box[1]
        ImageDraw.Draw(image).text((3 * scale - box[0], text_origin_y), text, font=font, fill=color)
        content = io.BytesIO()
        image.save(content, format="PNG")
        rendered_width, rendered_height = image.width / scale, image.height / scale
        draw_x = x - rendered_width if align_right else x
        if baseline:
            ascent, _ = font.getmetrics()
            baseline_from_top = (text_origin_y + ascent) / scale
            draw_y = y - (rendered_height - baseline_from_top)
        else:
            draw_y = y - rendered_height + 2
        canvas.drawImage(ImageReader(content), draw_x, draw_y, width=rendered_width, height=rendered_height, mask="auto")

    def wrap_thai_text(text: str, max_width: float, size: int) -> list[str]:
        scale = 3
        try:
            font = ImageFont.truetype(
                str(font_dir / "Sarabun-Regular.ttf"), size * scale,
                layout_engine=ImageFont.Layout.RAQM,
            )
        except (AttributeError, OSError, ValueError):
            font = ImageFont.truetype(str(font_dir / "Sarabun-Regular.ttf"), size * scale)
        lines: list[str] = []
        line = ""
        for word in text.split():
            candidate = f"{line} {word}".strip()
            if line and font.getlength(candidate) / scale > max_width:
                lines.append(line)
                line = word
            else:
                line = candidate
        if line:
            lines.append(line)
        return lines or [""]

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
        canvas.drawString(margin, height - 127, f"Customer ID in report: {len(report_customer_ids)}")
        canvas.setFont(thai_font, 10)
        canvas.drawString(margin, height - 143, f"Export Date: {datetime.now().strftime('%d-%m-%Y')}")
        canvas.setFillColor(muted)
        canvas.setFont(thai_font, 9)
        canvas.drawRightString(width - margin, 25, f"Page {page_number}")
        return height - 180

    def group_note_for(group: list[ImageRecord]) -> str:
        group_dates = sorted(
            {
                source.checkin_date
                for image in group
                if (source := resolve_image_source(image)).checkin_date
            }
        )
        date_labels = ", ".join(format_card_date(value) for value in group_dates) or "ไม่ระบุวันที่"
        return (
            "กลุ่มนี้รวมภาพที่ใช้ซ้ำหรือคล้ายกัน ซึ่งถูกนำไปใช้กับ Customer ID อื่น "
            f"ในวันที่ {date_labels}"
        )

    def group_note_x(number: int) -> float:
        title = f"Group {number}"
        return margin + 14 + pdfmetrics.stringWidth(title, thai_bold_font, 13) + 4

    def group_heading_height(number: int, group: list[ImageRecord]) -> float:
        note_x = group_note_x(number)
        note_lines = wrap_thai_text(group_note_for(group), width - margin - note_x, 9)
        return 42 + 12 * len(note_lines)

    def draw_group_heading(number: int, group: list[ImageRecord], y_position: float) -> float:
        customer_ids = ", ".join(
            sorted(
                {
                    source.customer_id
                    for image in group
                    if (source := resolve_image_source(image)).customer_id
                }
            )
        )
        technician_ids = ", ".join(
            sorted(
                {
                    source.technician_id
                    for image in group
                    if (source := resolve_image_source(image)).technician_id
                }
            )
        )
        group_note = group_note_for(group)
        note_x = group_note_x(number)
        note_lines = wrap_thai_text(group_note, width - margin - note_x, 9)
        bar_bottom = y_position - 26 - (len(note_lines) - 1) * 11
        bar_height = 42 + (len(note_lines) - 1) * 11
        canvas.setFillColor(orange)
        canvas.roundRect(margin, bar_bottom, 5, bar_height, 2, fill=1, stroke=0)
        canvas.setFillColor(green)
        canvas.setFont(thai_bold_font, 13)
        canvas.drawString(margin + 14, y_position + 10, f"Group {number}")
        for line_index, line in enumerate(note_lines):
            draw_thai_text(
                line,
                note_x,
                y_position + 10 - line_index * 11,
                9,
                "#3F5146",
                baseline=True,
            )
        # Keep the metadata rows clear of the wrapped note on the line above.
        info_y = y_position - 10 - (len(note_lines) - 1) * 11
        canvas.setFillColor(muted)
        canvas.setFont(thai_bold_font, 9)
        canvas.drawString(margin + 14, info_y, "Technician ID:")
        canvas.drawString(margin + 14, info_y - 11, "Customer ID:")
        canvas.setFont(thai_font, 9)
        canvas.drawString(margin + 76, info_y, technician_ids[:88] or "-")
        canvas.drawString(margin + 76, info_y - 11, customer_ids[:90])
        return y_position - (42 + len(note_lines) * 12)

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
        source = resolve_image_source(image)
        job_number, checkin_date = source.customer_id, source.checkin_date
        canvas.setFillColor(green)
        canvas.setFont(thai_bold_font, 8)
        canvas.drawString(x + 7, y_position - 105, f"Customer ID: {job_number or '-'}")
        canvas.setFont(thai_font, 8)
        canvas.drawString(x + 7, y_position - 116, f"Date: {format_card_date(checkin_date)}")
        filename = image.original_filename
        canvas.setFillColor(muted)
        canvas.setFont(thai_font, 7)
        canvas.drawString(x + 7, y_position - 127, filename[:28] + ("..." if len(filename) > 28 else ""))

    page_number = 1
    y = draw_header(page_number)
    # A compact, paginated five-column summary. Each entry represents the
    # technician's distinct customers on qualifying images across all dates.
    entries = sorted(technician_customers.items(), key=lambda item: (-len(item[1]), item[0]))
    def summary_heading(y_position: float) -> float:
        draw_thai_text("รายการช่างที่ตรวจพบการใช้ภาพซ้ำในระบบ", margin, y_position, 11, "#315C46")
        cursor = y_position - 15
        first_description_lines = wrap_thai_text(
            "จำนวน Customer ID ที่เกี่ยวข้องกับภาพที่ระบบตรวจพบว่ามีการใช้งานซ้ำหรือมีความคล้ายคลึงกันสูง",
            width - margin * 2,
            8,
        )
        for line in first_description_lines:
            draw_thai_text(line, margin, cursor, 8, "#60756C")
            cursor -= 10
        cursor -= 3
        second_description_lines = wrap_thai_text(
            "ข้อมูลนี้เป็นผลการตรวจจับเบื้องต้นจากระบบ AI เพื่อใช้ในการคัดกรองและตรวจสอบเพิ่มเติม",
            width - margin * 2,
            8,
        )
        for line in second_description_lines:
            draw_thai_text(line, margin, cursor, 8, "#60756C")
            cursor -= 10
        return cursor - 24

    def summary_columns_heading(y_position: float) -> float:
        column_width = (width - 2 * margin) / 5
        for column in range(5):
            x = margin + column * column_width
            cell_width = column_width - 6
            split_x = x + cell_width * 0.68
            canvas.setFillColor(summary_header_bg)
            canvas.roundRect(x, y_position - 8, cell_width, 18, 3, fill=1, stroke=0)
            canvas.setStrokeColor(HexColor("#D7E4DB"))
            canvas.setLineWidth(0.6)
            canvas.line(split_x, y_position - 8, split_x, y_position + 10)
            canvas.setFillColor(HexColor("#FFFFFF"))
            canvas.setFont(thai_bold_font, 6.5)
            canvas.drawString(x + 4, y_position - 1, "Technician ID")
            canvas.drawRightString(x + cell_width - 4, y_position - 1, "Count ID")
        return y_position - 22

    if request.include_technician_summary:
        # The header's content start leaves a large gap below Export Date;
        # reclaim some of it before the first summary section.
        y += 18
        y = summary_heading(y)
        y = summary_columns_heading(y)
    column_width = (width - 2 * margin) / 5
    for start in range(0, len(entries), 5):
        row = entries[start:start + 5]
        row_height = 19
        if y - row_height < margin:
            canvas.showPage(); page_number += 1
            next_page_y = draw_header(page_number)
            y = summary_columns_heading(summary_heading(next_page_y + 18))
        for column, (technician, customers) in enumerate(row):
            x = margin + column * column_width
            cell_width = column_width - 6
            split_x = x + cell_width * 0.68
            canvas.setFillColor(soft_green)
            canvas.rect(x, y + 14 - row_height, cell_width, row_height, fill=1, stroke=0)
            canvas.setStrokeColor(HexColor("#AFC5B7"))
            canvas.setLineWidth(0.6)
            canvas.rect(x, y + 14 - row_height, cell_width, row_height, fill=0, stroke=1)
            canvas.line(split_x, y + 14 - row_height, split_x, y + 14)
            canvas.setFillColor(summary_text)
            count_label = str(len(customers))
            canvas.setFont(thai_font, 8)
            available = max(1, split_x - (x + 8))
            technician_width = pdfmetrics.stringWidth(technician, thai_font, 8)
            canvas.saveState()
            canvas.translate(x + 4, y + 1)
            if technician_width > available:
                canvas.scale(available / technician_width, 1)
            canvas.drawString(0, 0, technician)
            canvas.restoreState()
            canvas.setFont(thai_font, 8)
            canvas.drawRightString(x + cell_width - 4, y + 1, count_label)
        y -= row_height + 3
    if request.include_technician_summary:
        y -= 20
    report_images: dict[str, tuple[ImageRecord, str]] = {}
    for group_number, (group_id, group) in enumerate(selected_groups, start=1):
        if y - group_heading_height(group_number, group) < margin + card_height + 8:
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
        source = resolve_image_source(image)
        session.add(ExportReportImage(export_report_id=report_id, image_id=image.id, source_job_number=source.customer_id, source_checkin_date=source.checkin_date, source_technician_id=source.technician_id, group_id_snapshot=group_id))
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
        # filename=f"AI-Inspector-Report-{report.date_from}-{report.date_to}.pdf",
        filename=f"AI-Inspector-Report-{report.date_to}.pdf",
    )
