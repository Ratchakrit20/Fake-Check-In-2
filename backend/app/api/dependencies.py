from functools import lru_cache

from ..core.config import get_settings
from ..embeddings.sscd import SSCDEmbeddingProvider
from ..services.pair_analysis_service import PairAnalysisService


@lru_cache
def pair_analysis_service() -> PairAnalysisService:
    settings = get_settings()
    provider = None
    if settings.embedding.enabled:
        provider = SSCDEmbeddingProvider(
            settings.embedding.model_path,
            settings.embedding.model_url,
            settings.embedding.device,
            settings.embedding.normalize,
            settings.embedding.allow_cpu_fallback,
            settings.embedding.input_size,
        )
    return PairAnalysisService(settings, provider)
