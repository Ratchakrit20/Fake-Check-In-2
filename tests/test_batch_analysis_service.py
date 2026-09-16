from backend.app.db.models import ImageRecord
from backend.app.services.batch_analysis_service import declared_source_id, same_declared_source, unique_records_by_id


def test_unique_records_by_id_removes_duplicate_batch_items():
    first = ImageRecord(id="image-a")
    duplicate = ImageRecord(id="image-a")
    second = ImageRecord(id="image-b")

    result = unique_records_by_id([first, duplicate, second])

    assert [record.id for record in result] == ["image-a", "image-b"]
    assert result[0] is duplicate


def test_declared_source_id_supports_home_and_splitter_names():
    assert declared_source_id("new_20260813_home_8884162504_2023020302_D_20260813013917_2.jpeg") == "8884162504"
    assert declared_source_id("new_20260825_splitter_8807045814_anything_1.jpeg") == "8807045814"


def test_declared_source_id_rejects_unknown_or_non_ten_digit_names():
    assert declared_source_id("new_20260813_other_8884162504_file.jpeg") is None
    assert declared_source_id("new_20260813_home_12345_file.jpeg") is None
    assert declared_source_id("ordinary-image.jpeg") is None


def test_same_declared_source_skips_known_intra_source_pair_only():
    first = ImageRecord(original_filename="new_20260813_home_8884162504_a_1.jpeg")
    second = ImageRecord(original_filename="new_20260813_splitter_8884162504_b_2.jpeg")
    different = ImageRecord(original_filename="new_20260813_home_8884162586_c_1.jpeg")
    ordinary = ImageRecord(original_filename="image.jpeg")

    assert same_declared_source(first, second)
    assert not same_declared_source(first, different)
    assert not same_declared_source(first, ordinary)
