def normalize_pair(first: str, second: str) -> tuple[str, str]:
    return tuple(sorted((first, second)))


def test_pair_normalization_is_order_independent():
    assert normalize_pair("b", "a") == normalize_pair("a", "b") == ("a", "b")

