from backend.app.db.models import ImageRecord
from backend.app.services.batch_analysis_service import same_submission, unique_records_by_id
from backend.app.services.image_source_service import resolve_image_source
from backend.app.services.source_filename import parse_source_reference


def test_unique_records_by_id_removes_duplicate_batch_items():
    first = ImageRecord(id="image-a")
    duplicate = ImageRecord(id="image-a")
    second = ImageRecord(id="image-b")

    result = unique_records_by_id([first, duplicate, second])

    assert [record.id for record in result] == ["image-a", "image-b"]
    assert result[0] is duplicate


def test_source_parser_supports_home_and_splitter_names():
    first = parse_source_reference("new_20260813_home_8884162504_2023020302_D_20260813013917_2.jpeg")
    second = parse_source_reference("new_20260825_splitter_8807045814_anything_1.jpeg")

    assert first and first.job_number == "8884162504"
    assert first.checkin_date == "20260813"
    assert second and second.job_number == "8807045814"


def test_source_parser_rejects_unknown_or_non_ten_digit_names():
    assert parse_source_reference("new_20260813_other_8884162504_file.jpeg") is None
    assert parse_source_reference("new_20260813_home_12345_file.jpeg") is None
    assert parse_source_reference("ordinary-image.jpeg") is None


def test_resolver_prefers_persisted_values_and_falls_back_per_missing_field():
    image = ImageRecord(
        original_filename="ma-new_20261001_home_8884162504_TECH-A_1.jpeg",
        source_job_number="persisted-id",
        source_checkin_date=None,
        source_technician_id=None,
    )

    source = resolve_image_source(image)

    assert source.customer_id == "persisted-id"
    assert source.checkin_date == "20261001"
    assert source.technician_id == "TECH-A"


def test_same_submission_skips_only_known_same_customer_and_date():
    first = ImageRecord(original_filename="new_20260813_home_8884162504_a_1.jpeg")
    second = ImageRecord(original_filename="new_20260813_splitter_8884162504_b_2.jpeg")
    different = ImageRecord(original_filename="new_20260813_home_8884162586_c_1.jpeg")
    ordinary = ImageRecord(original_filename="image.jpeg")

    assert same_submission(first, second)
    assert not same_submission(first, different)
    assert not same_submission(first, ordinary)
