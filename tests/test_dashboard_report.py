import io
import zipfile

from backend.app.api.routes.exports import technician_customer_counts
from backend.app.db.models import ImageRecord, PairwiseResult
from backend.app.services.dashboard_report_service import build_dashboard_insights, create_excel_report
from backend.app.services.image_source_service import resolve_image_source


def test_technician_counts_include_other_dates_and_groups_but_only_own_customers():
    def image(identifier, technician, customer, date):
        return ImageRecord(id=identifier, original_filename="unknown.jpg", source_technician_id=technician,
                           source_job_number=customer, source_checkin_date=date)

    selected = [image("a", "T01", "C1", "20261001"), image("b", "T02", "C2", "20261002")]
    other = [image("c", "T01", "C1", "20261003"), image("d", "T01", "C3", "20261003"),
             image("e", "T03", "C4", "20261003")]
    counts = technician_customer_counts([selected], [selected, other])
    assert counts == {"T01": {"C1", "C3"}, "T02": {"C2"}}


def test_excel_report_contains_charts_and_duplicate_job_sheet():
    summary = {
        "images_in_system": 40,
        "reused_images": 8,
        "total_jobs": 12,
        "reused_jobs": 3,
        "duplicate_jobs": [
            {"job_number": "1234567890", "images_in_system": 4, "reused_images": 2, "evidence_links": 1}
        ],
    }

    content = create_excel_report(summary, total_images=100)

    assert content.startswith(b"PK")
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        names = set(archive.namelist())
        assert "xl/charts/chart1.xml" in names
        assert "xl/charts/chart2.xml" in names
        shared_strings = archive.read("xl/sharedStrings.xml").decode("utf-8")
        assert "1234567890" in shared_strings


def test_export_preview_splits_customer_ids_by_selected_and_other_dates():
    def image(identifier, customer, date):
        return ImageRecord(
            id=identifier,
            original_filename=f"{customer}_{date}.jpg",
            source_job_number=customer,
            source_checkin_date=date,
        )

    selected_a = image("a", "C001", "20261001")
    selected_b = image("b", "C002", "20261001")
    other_day = image("c", "C003", "20260930")
    pairs = [
        PairwiseResult(
            image_a_id="a",
            image_b_id=other_day.id,
            relationship_score=0.9,
            relationship_level="exact_file",
        ),
        PairwiseResult(
            image_a_id="a",
            image_b_id=selected_b.id,
            relationship_score=0.9,
            relationship_level="exact_file",
        ),
    ]
    images = [selected_a, selected_b, other_day]
    sources = {item.id: resolve_image_source(item) for item in images}

    preview = build_dashboard_insights(
        [selected_a, selected_b],
        images,
        {item.id for item in images},
        sources,
        pairs,
        minimum_score=0.5,
        date_to="20261001",
    )["export_preview"]

    assert preview["selected_date_customer_ids"] == 2
    assert preview["cross_date_customer_ids"] == 1
