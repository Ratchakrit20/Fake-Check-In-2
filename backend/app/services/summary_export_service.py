"""Reusable, configurable Excel summary generation for detection reports."""

from __future__ import annotations

import io
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import xlsxwriter
from PIL import Image, ImageOps


@dataclass(frozen=True)
class SummaryColumn:
    """A display column mapped to a key in a summary row."""

    key: str
    title: str
    width: int = 22
    is_datetime: bool = False
    is_image: bool = False


DETECTION_SUMMARY_COLUMNS: tuple[SummaryColumn, ...] = (
    SummaryColumn("checked_at", "วัน-เวลา ที่ตรวจ", 22, True),
    SummaryColumn("detect_category", "Detect Category (หมวดตรวจ)", 26),
    SummaryColumn("detect_sub_category", "Detect Sub Category (ประเภทความสัมพันธ์)", 38),
    SummaryColumn("image_a_technician_id", "ภาพ A - Technician ID", 20),
    SummaryColumn("image_b_technician_id", "ภาพ B - Technician ID", 20),
    SummaryColumn("image_a_customer_id", "ภาพ A - Customer ID", 20),
    SummaryColumn("image_b_customer_id", "ภาพ B - Customer ID", 20),
    SummaryColumn("image_a_filename", "ภาพ A - ชื่อไฟล์", 38),
    SummaryColumn("image_a_captured_at", "ภาพ A - วันเวลาถ่าย", 22, True),
    SummaryColumn("image_a_job_type", "ภาพ A - Job type", 16),
    SummaryColumn("image_b_filename", "ภาพ B - ชื่อไฟล์", 38),
    SummaryColumn("image_b_captured_at", "ภาพ B - วันเวลาถ่าย", 22, True),
    SummaryColumn("image_b_job_type", "ภาพ B - Job type", 16),
)

DETECTION_SUMMARY_DESCRIPTION = (
    "แถวหมวดภาพซ้ำระบุภาพ A และภาพ B ที่นำมาเปรียบเทียบ โดย A/B เป็นเพียงลำดับ ไม่ได้สรุปว่าภาพใดเป็นต้นฉบับ; "
    "แถวหมวดถ่ายภาพซ้อนจอระบุภาพ SOA ในช่องภาพ A และเว้นช่องภาพ B; Detect Sub Category แสดงประเภทความสัมพันธ์ "
    "หรือรายละเอียดที่ตรวจพบ; วันเวลาถ่ายอ่านจาก EXIF หากไม่มีจะแสดงวันที่จากชื่อไฟล์"
)


def _excel_datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    if isinstance(value, str):
        for format_string in ("%Y-%m-%d %H:%M:%S", "%Y:%m:%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
            try:
                # Excel datetimes are stored without timezone information.
                return datetime.strptime(value[:19], format_string)  # noqa: DTZ007
            except ValueError:
                continue
    return None


def make_excel_thumbnail(image_path: Path | None) -> bytes | None:
    """Create a small embedded JPEG preview suitable for an Excel table cell."""
    if image_path is None:
        return None
    try:
        with Image.open(image_path) as source:
            preview = ImageOps.exif_transpose(source).convert("RGB")
            preview.thumbnail((140, 100), Image.Resampling.LANCZOS)
            output = io.BytesIO()
            preview.save(output, format="JPEG", quality=68, optimize=True)
            return output.getvalue()
    except (OSError, ValueError):
        return None


def create_summary_workbook(
    rows: Iterable[Mapping[str, object]],
    *,
    columns: Sequence[SummaryColumn] = DETECTION_SUMMARY_COLUMNS,
    sheet_name: str = "Summary",
    description: str = DETECTION_SUMMARY_DESCRIPTION,
) -> bytes:
    """Build an XLSX sheet from reusable column definitions and row mappings."""
    output = io.BytesIO()
    workbook = xlsxwriter.Workbook(output, {"in_memory": True})
    workbook.set_properties({"title": "AI-Inspector Summary"})
    sheet = workbook.add_worksheet(sheet_name[:31])
    sheet.freeze_panes(2, min(3, len(columns)))
    sheet.hide_gridlines(2)

    header = workbook.add_format({
        "bold": True,
        "font_color": "#FFFFFF",
        "bg_color": "#176B4A",
        "border": 1,
        "border_color": "#D5E3DA",
        "text_wrap": True,
        "valign": "vcenter",
    })
    text_cell = workbook.add_format({"border": 1, "border_color": "#D5E3DA", "valign": "top"})
    datetime_cell = workbook.add_format({
        "border": 1,
        "border_color": "#D5E3DA",
        "num_format": "dd/mm/yyyy hh:mm:ss",
        "valign": "top",
    })
    description_format = workbook.add_format({
        "font_color": "#52665B",
        "bg_color": "#F3F8F5",
        "text_wrap": True,
        "valign": "vcenter",
    })

    if columns:
        sheet.merge_range(0, 0, 0, len(columns) - 1, description, description_format)
    sheet.set_row(0, 38)

    for index, column in enumerate(columns):
        sheet.set_column(index, index, column.width)
        sheet.write(1, index, column.title, header)
    sheet.set_row(1, 42)

    row_count = 0
    for row_count, row in enumerate(rows, start=2):
        sheet.set_row(row_count, 80 if any(column.is_image for column in columns) else 20)
        for column_index, column in enumerate(columns):
            value = row.get(column.key)
            if column.is_image and isinstance(value, bytes):
                sheet.insert_image(
                    row_count,
                    column_index,
                    f"preview-{row_count}-{column_index}.jpg",
                    {
                        "image_data": io.BytesIO(value),
                        "x_offset": 4,
                        "y_offset": 4,
                        "object_position": 1,
                        "description": str(row.get(f"{column.key}_description") or column.title),
                    },
                )
            elif value is None:
                sheet.write_blank(row_count, column_index, None, datetime_cell if column.is_datetime else text_cell)
            elif column.is_datetime and (parsed := _excel_datetime(value)) is not None:
                sheet.write_datetime(row_count, column_index, parsed, datetime_cell)
            else:
                # Write IDs and categories as text to preserve leading zeros and
                # prevent values beginning with '=' from becoming formulas.
                sheet.write_string(row_count, column_index, str(value), text_cell)

    if columns:
        sheet.autofilter(1, 0, max(1, row_count), len(columns) - 1)
    workbook.close()
    return output.getvalue()
