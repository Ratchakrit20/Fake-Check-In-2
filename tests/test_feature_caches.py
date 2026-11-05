import hashlib
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw

from backend.app.detectors.sift_matcher import SIFTMatcher
from backend.app.embeddings.sscd import SSCDEmbeddingProvider


def _textured_image(seed: int, size: tuple[int, int] = (320, 240)) -> Image.Image:
    rng = np.random.default_rng(seed)
    image = Image.new("RGB", size, (238, 238, 238))
    draw = ImageDraw.Draw(image)
    for _ in range(90):
        x = int(rng.integers(0, size[0]))
        y = int(rng.integers(0, size[1]))
        radius = int(rng.integers(2, 10))
        color = tuple(int(value) for value in rng.integers(0, 255, 3))
        if rng.integers(0, 2):
            draw.ellipse((x - radius, y - radius, x + radius, y + radius), outline=color, width=2)
        else:
            draw.line((x - radius, y - radius, x + radius, y + radius), fill=color, width=2)
    draw.text((12, 12), f"fixture-{seed}", fill=(0, 0, 0))
    return image


def _sift_signature(result):
    return (
        result.keypoint_count_a,
        result.keypoint_count_b,
        result.good_match_count,
        result.points_a.tobytes(),
        result.points_b.tobytes(),
    )


def test_persistent_sift_features_match_uncached_output(tmp_path):
    first, second = _textured_image(3), _textured_image(4)
    mask = np.full((240, 320), 255, dtype=np.uint8)
    mask[0:24, :] = 0

    uncached = SIFTMatcher(0.75, max_dimension=320)
    cv2.setRNGSeed(71)
    expected = uncached.match(first, second, mask, mask)

    # Keep this under the repository workspace so Windows sandbox temp mounts
    # that do not support rename still exercise the real disk-cache path.
    cache_dir = Path.cwd() / ".pytest_cache" / f"sift-features-{tmp_path.name}"
    cache_writer = SIFTMatcher(0.75, max_dimension=320, cache_dir=cache_dir)
    cv2.setRNGSeed(71)
    cache_writer.match(first, second, mask, mask)

    cache_reader = SIFTMatcher(0.75, max_dimension=320, cache_dir=cache_dir)
    assert (cache_dir / f"{cache_reader._features_cache_key(first, mask)}.npz").is_file()
    assert cache_reader._read_disk_cache(cache_reader._features_cache_key(first, mask)) is not None
    cv2.setRNGSeed(71)
    actual = cache_reader.match(first, second, mask, mask)

    assert _sift_signature(actual) == _sift_signature(expected)


def test_embedding_cache_reuses_identical_images_without_changing_vectors():
    class CountingProvider(SSCDEmbeddingProvider):
        def __init__(self):
            super().__init__(None, "", "0" * 64, device="cpu")
            self.inference_calls = 0

        def _infer_uncached(self, images):
            self.inference_calls += 1
            vectors = []
            for image in images:
                digest = hashlib.sha256(image.tobytes()).digest()
                vector = np.resize(np.frombuffer(digest, dtype=np.uint8).astype(np.float32), self.dimension)
                vectors.append(vector)
            return np.stack(vectors)

    provider = CountingProvider()
    images = [_textured_image(8), _textured_image(9)]
    first = provider.embed_many(images)
    second = provider.embed_many(images)

    assert provider.inference_calls == 1
    np.testing.assert_array_equal(first, second)
