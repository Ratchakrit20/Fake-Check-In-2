from backend.app.detectors.sha256_detector import SHA256Detector


def test_sha256_is_stable_and_content_sensitive():
    assert SHA256Detector.from_bytes(b"evidence") == SHA256Detector.from_bytes(b"evidence")
    assert SHA256Detector.from_bytes(b"evidence") != SHA256Detector.from_bytes(b"other")

