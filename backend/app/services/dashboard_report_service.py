from __future__ import annotations

import io
from collections import Counter

import xlsxwriter
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import get_settings
from ..db.models import ImageRecord, PairwiseResult
from .image_source_service import ResolvedImageSource, resolve_image_source
from .relationship_group_service import build_reportable_groups_as_of, merge_report_groups_by_customer
from .relationship_policy import REPORTABLE_CLASSIFICATIONS


def is_in_date_range(
    checkin_date: str | None,
    date_from: str | None,
    date_to: str | None,
) -> bool:
    if checkin_date is None:
        return date_from is None and date_to is None
    return (date_from is None or checkin_date >= date_from) and (
        date_to is None or checkin_date <= date_to
    )


def build_dashboard_insights(
    selected_images: list[ImageRecord],
    all_images: list[ImageRecord],
    reused_image_ids: set[str],
    source_by_image: dict[str, ResolvedImageSource],
    pairs: list[PairwiseResult],
    minimum_score: float,
    date_to: str | None = None,
) -> dict:
    """Aggregate chart and export-preview data from the same loaded records."""
    daily: dict[str, dict] = {}
    technician_customers: dict[str, set[str]] = {}
    selected_ids = {image.id for image in selected_images}

    for image in selected_images:
        source = source_by_image[image.id]
        checkin_date = source.checkin_date
        if checkin_date:
            row = daily.setdefault(
                checkin_date,
                {
                    "date": checkin_date,
                    "total_images": 0,
                    "reused_images": 0,
                    "customer_ids": set(),
                    "reused_customer_ids": set(),
                },
            )
            row["total_images"] += 1
            if source.customer_id:
                row["customer_ids"].add(source.customer_id)
            if image.id in reused_image_ids:
                row["reused_images"] += 1
                if source.customer_id:
                    row["reused_customer_ids"].add(source.customer_id)

        if image.id in reused_image_ids and source.technician_id and source.customer_id:
            technician_customers.setdefault(source.technician_id, set()).add(source.customer_id)

    # Match the PDF's as-of graph so future evidence cannot appear or bridge
    # otherwise separate report groups in the preview.
    groups = build_reportable_groups_as_of(all_images, pairs, minimum_score, date_to)
    selected_groups = merge_report_groups_by_customer([
        group for group in groups if selected_ids.intersection({image.id for image in group})
    ])
    report_images = {
        image.id: image
        for group in selected_groups
        for image in group
    }
    cross_date_images = [
        image for image_id, image in report_images.items() if image_id not in selected_ids
    ]
    selected_report_sources = [
        source_by_image[image.id]
        for image_id, image in report_images.items()
        if image_id in selected_ids
    ]
    cross_date_sources = [source_by_image[image.id] for image in cross_date_images]
    report_sources = [*selected_report_sources, *cross_date_sources]

    return {
        "daily": [
            {
                "date": date,
                "total_images": row["total_images"],
                "reused_images": row["reused_images"],
                "total_customer_ids": len(row["customer_ids"]),
                "reused_customer_ids": len(row["reused_customer_ids"]),
            }
            for date, row in sorted(daily.items())
        ],
        "technicians": [
            {"technician_id": technician_id, "reused_customer_ids": len(customer_ids)}
            for technician_id, customer_ids in sorted(
                technician_customers.items(), key=lambda item: (-len(item[1]), item[0])
            )
        ],
        "export_preview": {
            "group_count": len(selected_groups),
            "selected_images": len(selected_ids.intersection(reused_image_ids)),
            "report_images": len(report_images),
            "cross_date_images": len(cross_date_images),
            "selected_date_customer_ids": len(
                {source.customer_id for source in selected_report_sources if source.customer_id}
            ),
            "cross_date_customer_ids": len(
                {source.customer_id for source in cross_date_sources if source.customer_id}
            ),
            "technician_ids": len({source.technician_id for source in report_sources if source.technician_id}),
            "cross_dates": sorted(
                {
                    source_by_image[image.id].checkin_date
                    for image in cross_date_images
                    if source_by_image[image.id].checkin_date
                }
            ),
        },
    }


async def build_dashboard_summary(
    session: AsyncSession,
    date_from: str | None = None,
    date_to: str | None = None,
) -> dict:
    minimum_score = get_settings().relationship.report_min_relationship_score
    images = list(await session.scalars(select(ImageRecord)))
    reused_pairs = list(
        await session.scalars(
            select(PairwiseResult).where(
                PairwiseResult.relationship_level.in_(REPORTABLE_CLASSIFICATIONS),
                PairwiseResult.relationship_score >= minimum_score,
            )
        )
    )
    reused_image_ids = {
        image_id
        for pair in reused_pairs
        for image_id in (pair.image_a_id, pair.image_b_id)
    }
    source_by_image = {image.id: resolve_image_source(image) for image in images}
    selected_images = [
        image
        for image in images
        if is_in_date_range(source_by_image[image.id].checkin_date, date_from, date_to)
    ]
    selected_source_by_image = {
        image.id: source_by_image[image.id].customer_id
        for image in selected_images
        if source_by_image[image.id].customer_id is not None
    }
    all_jobs = set(selected_source_by_image.values())
    reused_jobs = {
        selected_source_by_image[image_id]
        for image_id in reused_image_ids
        if image_id in selected_source_by_image
    }
    pair_counts: Counter[str] = Counter()
    for pair in reused_pairs:
        pair_sources = {
            selected_source_by_image[image_id]
            for image_id in (pair.image_a_id, pair.image_b_id)
            if image_id in selected_source_by_image
        }
        pair_counts.update(pair_sources)
    image_counts = Counter(selected_source_by_image.values())
    reused_image_counts = Counter(
        selected_source_by_image[image_id]
        for image_id in reused_image_ids
        if image_id in selected_source_by_image
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
        "images_in_system": len(selected_images),
        "reused_images": sum(image.id in reused_image_ids for image in selected_images),
        "total_jobs": len(all_jobs),
        "reused_jobs": len(reused_jobs),
        "duplicate_jobs": duplicate_jobs,
        "insights": build_dashboard_insights(
            selected_images,
            images,
            reused_image_ids,
            source_by_image,
            reused_pairs,
            minimum_score,
            date_to,
        ),
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
    section = workbook.add_format({"bold": True, "font_size": 12, "font_color": "#FFFFFF", "bg_color": dark_green, "align": "center"})
    label = workbook.add_format({"font_size": 12, "font_color": "#43564D"})
    count = workbook.add_format({"bold": True, "font_size": 16, "font_color": dark_green, "num_format": "#,##0"})
    input_format = workbook.add_format({"bold": True, "font_size": 16, "bg_color": "#FFF3D6", "font_color": "#9A5B00", "num_format": "#,##0", "border": 1, "border_color": orange})
    detail_text = workbook.add_format({"font_size": 12})
    detail_number = workbook.add_format({"font_size": 12, "num_format": "#,##0"})
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
    image_chart.add_series({"name": "สัดส่วนภาพ", "categories": "='สรุปผล'!$M$3:$M$5", "values": "='สรุปผล'!$N$3:$N$5", "points": [{"fill": {"color": "#DCE8DF"}}, {"fill": {"color": green}}, {"fill": {"color": orange}}], "data_labels": {"percentage": True, "leader_lines": True, "font": {"size": 14, "bold": True}}})
    image_chart.set_title({"name": "สัดส่วนภาพ", "name_font": {"size": 16, "bold": True}})
    image_chart.set_legend({"position": "bottom", "font": {"size": 12}})
    image_chart.set_hole_size(58)
    image_chart.set_chartarea({"border": {"none": True}})
    sheet.insert_chart("D3", image_chart, {"x_scale": 1.12, "y_scale": 1.08})
    job_chart = workbook.add_chart({"type": "doughnut"})
    job_chart.add_series({"name": "สัดส่วนงาน", "categories": "='สรุปผล'!$M$9:$M$10", "values": "='สรุปผล'!$N$9:$N$10", "points": [{"fill": {"color": green}}, {"fill": {"color": orange}}], "data_labels": {"percentage": True, "leader_lines": True, "font": {"size": 14, "bold": True}}})
    job_chart.set_title({"name": "สัดส่วนงาน", "name_font": {"size": 16, "bold": True}})
    job_chart.set_legend({"position": "bottom", "font": {"size": 12}})
    job_chart.set_hole_size(58)
    job_chart.set_chartarea({"border": {"none": True}})
    sheet.insert_chart("D19", job_chart, {"x_scale": 1.12, "y_scale": 1.08})
    detail.set_column("A:A", 18)
    detail.set_column("B:D", 18)
    detail.write_row("A1", ["เลขงาน", "ภาพในระบบ", "ภาพเข้าข่ายใช้ซ้ำ", "จำนวนหลักฐานเชื่อมโยง"], section)
    for row, job in enumerate(summary["duplicate_jobs"], start=1):
        detail.write_string(row, 0, job["job_number"], detail_text)
        detail.write_number(row, 1, job["images_in_system"], detail_number)
        detail.write_number(row, 2, job["reused_images"], detail_number)
        detail.write_number(row, 3, job["evidence_links"], detail_number)
    detail.autofilter(0, 0, max(1, len(summary["duplicate_jobs"])), 3)
    detail.freeze_panes(1, 0)
    workbook.close()
    return output.getvalue()
