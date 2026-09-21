from backend.app.detectors.perceptual_hash_detector import PerceptualHashDetector
from backend.app.vector_store.phash_index import PerceptualHashIndex


def test_phash_index_finds_every_hash_within_hamming_radius():
    hashes = [
        ("image-a", "0000000000000000"),
        ("image-b", "0000000000000001"),
        ("image-c", "0000000000000003"),
        ("image-d", "ffffffffffffffff"),
    ]
    index = PerceptualHashIndex.from_items(hashes, PerceptualHashDetector.distance)

    assert set(index.search("0000000000000000", 1)) == {"image-a", "image-b"}


def test_phash_index_keeps_multiple_images_with_the_same_hash():
    index = PerceptualHashIndex.from_items(
        [("image-a", "0123456789abcdef"), ("image-b", "0123456789abcdef")],
        PerceptualHashDetector.distance,
    )

    assert set(index.search("0123456789abcdef", 0)) == {"image-a", "image-b"}


def test_phash_index_returns_no_match_outside_radius():
    index = PerceptualHashIndex.from_items(
        [("image-a", "0000000000000000")],
        PerceptualHashDetector.distance,
    )

    assert index.search("ffffffffffffffff", 10) == []
