"""Shared helpers for persisted per-image AI detection metadata."""

from __future__ import annotations

import json
from typing import Any


def serialize_ai_metadata(metadata: dict[str, object]) -> str:
    return json.dumps(metadata, ensure_ascii=False, separators=(",", ":"))


def parse_detection_boxes(value: str | None, detection_key: str) -> list[tuple[int, int, int, int, float]]:
    if not value:
        return []
    try:
        metadata: Any = json.loads(value)
    except (TypeError, ValueError):
        return []
    boxes = metadata.get(detection_key, []) if isinstance(metadata, dict) else []
    output = []
    for detection in boxes:
        if not isinstance(detection, dict):
            continue
        box = detection.get("bbox")
        confidence = detection.get("confidence")
        if not isinstance(box, list) or len(box) != 4:
            continue
        try:
            x1, y1, x2, y2 = (round(float(item)) for item in box)
            score = float(confidence)
        except (TypeError, ValueError):
            continue
        if x2 > x1 and y2 > y1:
            output.append((x1, y1, x2, y2, score))
    return output


def parse_datetime_boxes(value: str | None) -> list[tuple[int, int, int, int, float]]:
    return parse_detection_boxes(value, "datetime")


def parse_lat_long_boxes(value: str | None) -> list[tuple[int, int, int, int, float]]:
    return parse_detection_boxes(value, "lat_long")


def is_soa_metadata_scanned(value: str | None) -> bool:
    if not value:
        return False
    try:
        metadata = json.loads(value)
    except (TypeError, ValueError):
        return False
    return (
        isinstance(metadata, dict)
        and metadata.get("model") == "lat-long/v1"
        and metadata.get("metadata_version", 0) >= 2
        and isinstance(metadata.get("datetime"), list)
        and isinstance(metadata.get("lat_long"), list)
        and "error" not in metadata
    )
