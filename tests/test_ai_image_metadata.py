import json

from backend.app.services.ai_image_metadata import is_soa_metadata_scanned, parse_datetime_boxes


def test_datetime_boxes_are_parsed_for_pdf_crop_and_confidence():
    value = json.dumps({
        "model": "lat-long/v1",
        "metadata_version": 2,
        "lat_long": [],
        "datetime": [{"bbox": [10.2, 20, 100, 50], "confidence": 0.97}],
    })

    assert is_soa_metadata_scanned(value)
    assert parse_datetime_boxes(value) == [(10, 20, 100, 50, 0.97)]


def test_empty_datetime_detection_is_scanned_but_not_soa():
    value = json.dumps({"model": "lat-long/v1", "metadata_version": 2, "lat_long": [], "datetime": []})

    assert is_soa_metadata_scanned(value)
    assert parse_datetime_boxes(value) == []


def test_invalid_metadata_is_not_counted_as_scanned():
    assert not is_soa_metadata_scanned("not-json")
    assert parse_datetime_boxes("not-json") == []


def test_legacy_incomplete_metadata_is_rescanned():
    assert not is_soa_metadata_scanned(json.dumps({"model": "lat-long/v1", "datetime": []}))
