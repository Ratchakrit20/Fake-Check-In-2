import io
import zipfile

from PIL import Image

from backend.app.services.summary_export_service import DETECTION_SUMMARY_COLUMNS, SummaryColumn, create_summary_workbook


def test_default_summary_columns_follow_requested_order_without_previews():
    assert [column.key for column in DETECTION_SUMMARY_COLUMNS] == [
        "checked_at",
        "detect_category",
        "detect_sub_category",
        "image_a_technician_id",
        "image_b_technician_id",
        "image_a_customer_id",
        "image_b_customer_id",
        "image_a_filename",
        "image_a_captured_at",
        "image_a_job_type",
        "image_b_filename",
        "image_b_captured_at",
        "image_b_job_type",
    ]
    assert not any(column.is_image for column in DETECTION_SUMMARY_COLUMNS)


def test_summary_export_uses_dynamic_columns_and_writes_ids_as_text():
    content = create_summary_workbook(
        [{"customer": "0012345678", "category": "การใช้ภาพซ้ำ"}],
        columns=(
            SummaryColumn("customer", "Customer ID"),
            SummaryColumn("category", "Detect Category"),
        ),
    )

    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        strings = archive.read("xl/sharedStrings.xml").decode("utf-8")
        assert "Customer ID" in strings
        assert "0012345678" in strings
        assert "Detect Category" in strings
        assert "การใช้ภาพซ้ำ" in strings


def test_summary_export_embeds_both_comparison_images():
    image = Image.new("RGB", (12, 8), "green")
    image_data = io.BytesIO()
    image.save(image_data, format="JPEG")
    preview = image_data.getvalue()
    content = create_summary_workbook(
        [{"image_a": preview, "image_b": preview, "customer": "C001"}],
        columns=(
            SummaryColumn("image_a", "Image A", 20, is_image=True),
            SummaryColumn("customer", "Customer ID"),
            SummaryColumn("image_b", "Image B", 20, is_image=True),
        ),
    )

    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        media = [name for name in archive.namelist() if name.startswith("xl/media/")]
        worksheet = archive.read("xl/worksheets/sheet1.xml").decode("utf-8")
        drawing = archive.read("xl/drawings/drawing1.xml").decode("utf-8")
        assert len(media) == 1  # identical bytes are stored once in the workbook
        assert drawing.count("<xdr:pic>") == 2
        assert "drawing" in worksheet
