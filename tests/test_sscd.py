from pathlib import Path

from backend.app.embeddings.sscd import SSCDEmbeddingProvider


def test_sscd_provider_exposes_expected_descriptor_size_without_loading_model():
    provider = SSCDEmbeddingProvider(
        Path("unused.pt"),
        "https://example.invalid/unused.pt",
        "0" * 64,
    )

    assert provider.dimension == 512
