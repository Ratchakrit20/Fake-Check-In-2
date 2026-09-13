from backend.app.core.runtime import detect_hardware


def test_explicit_runtime_limits_are_respected():
    profile = detect_hardware(cpu_workers=3, opencv_threads=2, embedding_batch_size=5)
    assert profile.pair_workers == 3
    assert profile.opencv_threads == 2
    assert profile.embedding_batch_size == 5


def test_auto_runtime_values_are_positive():
    profile = detect_hardware(cpu_workers=0, opencv_threads=0, embedding_batch_size=0)
    assert profile.logical_cpus >= 1
    assert profile.pair_workers >= 1
    assert profile.opencv_threads >= 1
    assert profile.embedding_batch_size >= 1
