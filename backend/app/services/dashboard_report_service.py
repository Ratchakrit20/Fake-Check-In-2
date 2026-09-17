from __future__ import annotations

import io
from collections import Counter

import xlsxwriter
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import ImageRecord, PairwiseResult
from .source_filename import declared_source_id

REUSED_CLASSIFICATIONS = {"exact_file", "same_image", "edited_or_cropped"}


async def build_dashboard_summary(session: AsyncSession) -> dict:
    images = list(await session.scalars(select(ImageRecord)))
    reused_pairs = list(
        await session.scalars(
            select(PairwiseResult).where(
                PairwiseResult.relationship_level.in_(REUSED_CLASSIFICATIONS)
            )
        )
    )
    reused_image_ids = {
        image_id
        for pair in reused_pairs
        for image_id in (pair.image_a_id, pair.image_b_id)
    }
    source_by_image = {
        image.id: source_id
        for image in images
        if (source_id := declared_source_id(image.original_filename)) is not None
    }
    all_jobs = set(source_by_image.values())
    reused_jobs = {
        source_by_image[image_id]
        for image_id in reused_image_ids
        if image_id in source_by_image
    }
    pair_counts: Counter[str] = Counter()
    for pair in reused_pairs:
        pair_sources = {
            source_by_image[image_id]
            for image_id in (pair.image_a_id, pair.image_b_id)
            if image_id in source_by_image
        }
        pair_counts.update(pair_sources)
    image_counts = Counter(source_by_image.values())
    reused_image_counts = Counter(
        source_by_image[image_id]
        for image_id in reused_image_ids
        if image_id in source_by_image
    )
    duplicate_jobs = [
        {
            "job_number": job_number,
            "images_in_system": image_counts[job_number],
            "reused_images": reused_image_counts[job_number],
            "evidence_links": pair_counts[job_number],
        }
        for job_number in sorted(reused_jobs)
    ]
    return {
        "images_in_system": len(images),
        "reused_images": len(reused_image_ids),
        "total_jobs": len(all_jobs),
        "reused_jobs": len(reused_jobs),
        "duplicate_jobs": duplicate_jobs,
    }


def create_excel_report(summary: dict, total_images: int | None = None) -> bytes:
    output = io.BytesIO()
    workbook = xlsxwriter.Workbook(output, {"in_memory": True})
    workbook.set_properties({"title": "รายงานผลตรวจการใช้ภาพซ้ำ"})
    green, dark_green, orange = "#16805B", "#12372A", "#F59E0B"
    sheet = workbook.add_worksheet("สรุปผล")
    detail = workbook.add_worksheet("เลขงานซ้ำ")
    sheet.hide_gridlines(2)
    detail.hide_gridlines(2)
    sheet.set_column("A:A", 27)
    sheet.set_column("B:B", 16)
    sheet.set_column("C:C", 4)
    sheet.set_column("D:K", 13)
    title = workbook.add_format({"bold": True, "font_size": 16, "font_color": dark_green})
    section = workbook.add_format({"bold": True, "font_color": "#FFFFFF", "bg_color": dark_green, "align": "center"})
    label = workbook.add_format({"font_color": "#43564D"})
    count = workbook.add_format({"bold": True, "font_size": 14, "font_color": dark_green, "num_format": "#,##0"})
    input_format = workbook.add_format({"bold": True, "font_size": 14, "bg_color": "#FFF3D6", "font_color": "#9A5B00", "num_format": "#,##0", "border": 1, "border_color": orange})
    note = workbook.add_format({"italic": True, "font_color": "#76857D", "font_size": 9})
    sheet.write("A2", "รายงานผลตรวจการใช้ภาพซ้ำ", title)
    sheet.write("A4", "ภาพ", section)
    sheet.write("A5", "ภาพทั้งหมด (กรอกข้อมูลจากคลัง)", label)
    sheet.write_number("B5", max(total_images or summary["images_in_system"], summary["images_in_system"]), input_format)
    sheet.write("A6", "ภาพในระบบ", label)
    sheet.write_number("B6", summary["images_in_system"], count)
    sheet.write("A7", "ภาพที่เข้าข่ายใช้ซ้ำ", label)
    sheet.write_number("B7", summary["reused_images"], count)
    sheet.write("A9", "งาน", section)
    sheet.write("A10", "งานทั้งหมดจากเลข", label)
    sheet.write_number("B10", summary["total_jobs"], count)
    sheet.write("A11", "งานที่พบการใช้ภาพซ้ำ", label)
    sheet.write_number("B11", summary["reused_jobs"], count)
    sheet.write("A13", "ช่องสีส้มเป็นข้อมูลที่แก้ไขได้ กราฟและเปอร์เซ็นต์จะคำนวณใหม่ใน Excel", note)
    sheet.write_row("M2:N2", ["สถานะภาพ", "จำนวน"], section)
    outside_system = max(0, max(total_images or summary["images_in_system"], summary["images_in_system"]) - summary["images_in_system"])
    not_reused = max(0, summary["images_in_system"] - summary["reused_images"])
    sheet.write_formula("M3", '="ยังไม่อยู่ในระบบ ("&TEXT(N3,"#,##0")&" ภาพ)"', None, f"ยังไม่อยู่ในระบบ ({outside_system:,} ภาพ)")
    sheet.write_formula("N3", "=MAX(0,$B$5-$B$6)")
    sheet.write_formula("M4", '="ในระบบ ไม่พบใช้ซ้ำ ("&TEXT(N4,"#,##0")&" ภาพ)"', None, f"ในระบบ ไม่พบใช้ซ้ำ ({not_reused:,} ภาพ)")
    sheet.write_formula("N4", "=MAX(0,$B$6-$B$7)")
    sheet.write_formula("M5", '="เข้าข่ายใช้ซ้ำ ("&TEXT(N5,"#,##0")&" ภาพ)"', None, f"เข้าข่ายใช้ซ้ำ ({summary['reused_images']:,} ภาพ)")
    sheet.write_formula("N5", "=$B$7")
    sheet.write_row("M8:N8", ["สถานะงาน", "จำนวน"], section)
    jobs_not_reused = max(0, summary["total_jobs"] - summary["reused_jobs"])
    sheet.write_formula("M9", '="งานไม่พบใช้ซ้ำ ("&TEXT(N9,"#,##0")&" งาน)"', None, f"งานไม่พบใช้ซ้ำ ({jobs_not_reused:,} งาน)")
    sheet.write_formula("N9", "=MAX(0,$B$10-$B$11)")
    sheet.write_formula("M10", '="งานที่พบใช้ซ้ำ ("&TEXT(N10,"#,##0")&" งาน)"', None, f"งานที่พบใช้ซ้ำ ({summary['reused_jobs']:,} งาน)")
    sheet.write_formula("N10", "=$B$11")
    image_chart = workbook.add_chart({"type": "doughnut"})
    image_chart.add_series({"name": "สัดส่วนภาพ", "categories": "='สรุปผล'!$M$3:$M$5", "values": "='สรุปผล'!$N$3:$N$5", "points": [{"fill": {"color": "#DCE8DF"}}, {"fill": {"color": green}}, {"fill": {"color": orange}}], "data_labels": {"percentage": True, "leader_lines": True}})
    image_chart.set_title({"name": "สัดส่วนภาพ"})
    image_chart.set_legend({"position": "bottom"})
    image_chart.set_hole_size(58)
    image_chart.set_chartarea({"border": {"none": True}})
    sheet.insert_chart("D3", image_chart, {"x_scale": 1.12, "y_scale": 1.08})
    job_chart = workbook.add_chart({"type": "doughnut"})
    job_chart.add_series({"name": "สัดส่วนงาน", "categories": "='สรุปผล'!$M$9:$M$10", "values": "='สรุปผล'!$N$9:$N$10", "points": [{"fill": {"color": green}}, {"fill": {"color": orange}}], "data_labels": {"percentage": True, "leader_lines": True}})
    job_chart.set_title({"name": "สัดส่วนงาน"})
    job_chart.set_legend({"position": "bottom"})
    job_chart.set_hole_size(58)
    job_chart.set_chartarea({"border": {"none": True}})
    sheet.insert_chart("D19", job_chart, {"x_scale": 1.12, "y_scale": 1.08})
    detail.set_column("A:A", 18)
    detail.set_column("B:D", 18)
    detail.write_row("A1", ["เลขงาน", "ภาพในระบบ", "ภาพเข้าข่ายใช้ซ้ำ", "จำนวนหลักฐานเชื่อมโยง"], section)
    for row, job in enumerate(summary["duplicate_jobs"], start=1):
        detail.write_string(row, 0, job["job_number"])
        detail.write_number(row, 1, job["images_in_system"])
        detail.write_number(row, 2, job["reused_images"])
        detail.write_number(row, 3, job["evidence_links"])
    detail.autofilter(0, 0, max(1, len(summary["duplicate_jobs"])), 3)
    detail.freeze_panes(1, 0)
    workbook.close()
    return output.getvalue()
