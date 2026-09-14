from backend.app.db.models import ImageRecord
from backend.app.services.batch_analysis_service import unique_records_by_id


def test_unique_records_by_id_removes_duplicate_batch_items():
    first = ImageRecord(id="image-a")
    duplicate = ImageRecord(id="image-a")
    second = ImageRecord(id="image-b")

    result = unique_records_by_id([first, duplicate, second])

    assert [record.id for record in result] == ["image-a", "image-b"]
    assert result[0] is duplicate
