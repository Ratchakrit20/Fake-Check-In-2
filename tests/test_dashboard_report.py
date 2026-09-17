import io
import zipfile

from backend.app.services.dashboard_report_service import create_excel_report


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
