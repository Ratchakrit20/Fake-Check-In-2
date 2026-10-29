import io
import json
import re

from PIL import Image, ImageDraw

from backend.app.api.routes import exports
from backend.app.api.routes.exports import CreateExportRequest
from backend.app.core.config import get_settings
from backend.app.db.models import ImageRecord, PairwiseResult
from backend.app.storage.local_storage import LocalImageStorage


class FakeSession:
    def __init__(self, images, pairs):
        self.images = images
        self.pairs = pairs
        self.query_count = 0
        self.added = []

    async def scalars(self, _query):
        self.query_count += 1
        return self.images if self.query_count == 1 else self.pairs

    def add(self, record):
        self.added.append(record)

    async def commit(self):
        pass


def test_export_pdf_includes_soa_datetime_context_and_crop(tmp_path, monkeypatch):
    settings = get_settings().model_copy(deep=True)
    settings.storage.root = tmp_path / "images"
    monkeypatch.setattr(exports, "get_settings", lambda: settings)
    storage = LocalImageStorage(settings.storage.root)

    images = []
    for image_id, technician, customer in (
        ("image-a", "T001", "C001"),
        ("image-b", "T002", "C002"),
    ):
        drawing = Image.new("RGB", (240, 160), "white")
        ImageDraw.Draw(drawing).rectangle((80, 40, 155, 70), outline="black", width=3)
        buffer = io.BytesIO()
        drawing.save(buffer, format="JPEG")
        path = storage.save(image_id, ".jpg", buffer.getvalue())
        images.append(ImageRecord(
            id=image_id,
            original_filename=f"{image_id}.jpg",
            source_technician_id=technician,
            source_job_number=customer,
            source_checkin_date="20261001",
            source_job_type="new",
            ai_metadata_json=json.dumps({
                "model": "lat-long/v1",
                "datetime": ([{"bbox": [80, 40, 155, 70], "confidence": 0.98}] if image_id == "image-a" else []),
            }),
            storage_path=str(path),
            file_size=path.stat().st_size,
            width=240,
            height=160,
            mime_type="image/jpeg",
            sha256=image_id.ljust(64, "0"),
            analysis_status="COMPLETED",
        ))

    pair = PairwiseResult(
        image_a_id="image-a",
        image_b_id="image-b",
        relationship_score=0.99,
        relationship_level="exact_file",
        details_json="{}",
    )
    session = FakeSession(images, [pair])

    coroutine = exports.create_export_pdf(
        CreateExportRequest(date_from="20261001", date_to="20261001"), session
    )
    try:
        coroutine.send(None)
    except StopIteration as completed:
        result = completed.value
    else:
        raise AssertionError("fake session unexpectedly yielded during PDF generation")

    pdf_path = tmp_path / "images" / "exports" / f"export-{result['report_id']}.pdf"
    content = pdf_path.read_bytes()
    assert content.startswith(b"%PDF-")
    # The output has the two original group cards, logo, and the SOA context
    # plus magnified datetime crop embedded as PDF image objects.
    assert len(re.findall(rb"/Subtype\s*/Image", content)) >= 4
    assert result["download_url"].endswith(f"{result['report_id']}")
    assert len(session.added) == 3  # report plus both original group images
