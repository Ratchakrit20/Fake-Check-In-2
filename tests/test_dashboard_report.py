import io
import zipfile

from backend.app.services.dashboard_report_service import create_excel_report
from backend.app.api.routes.exports import technician_customer_counts
from backend.app.db.models import ImageRecord


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
