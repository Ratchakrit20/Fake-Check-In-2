from backend.app.storage.local_storage import LocalImageStorage


def test_resolve_recovers_after_absolute_path_changes(tmp_path):
    storage = LocalImageStorage(tmp_path / "images")
    image_id = "ab123456-0000-0000-0000-000000000000"
    saved = storage.save(image_id, ".jpg", b"example")

    assert storage.resolve(image_id, tmp_path / "old-machine" / "missing.jpg") == saved


def test_resolve_returns_none_for_unknown_image(tmp_path):
    storage = LocalImageStorage(tmp_path / "images")
    assert storage.resolve("missing", tmp_path / "missing.jpg") is None


def test_ensure_available_restores_file_missing_after_migration(tmp_path):
    storage = LocalImageStorage(tmp_path / "images")
    image_id = "ab123456-0000-0000-0000-000000000000"

    restored = storage.ensure_available(image_id, tmp_path / "old-machine" / "missing.jpg", ".jpg", b"uploaded-again")

    assert restored.read_bytes() == b"uploaded-again"
    assert storage.resolve(image_id, restored) == restored
