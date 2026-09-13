from PIL import Image, ImageEnhance

from backend.app.detectors.perceptual_hash_detector import PerceptualHashDetector


def test_phash_survives_small_brightness_change():
    image = Image.new("RGB", (64, 64), "navy")
    changed = ImageEnhance.Brightness(image).enhance(1.1)
    detector = PerceptualHashDetector()
    assert detector.distance(detector.calculate(image).original, detector.calculate(changed).original) <= 2


def test_phash_distance_is_json_serializable_integer():
    detector = PerceptualHashDetector()
    first = detector.calculate(Image.new("RGB", (64, 64), "white"))
    second = detector.calculate(Image.new("RGB", (64, 64), "black"))
    assert type(detector.best_distance(first, second)[0]) is int
