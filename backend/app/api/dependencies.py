from functools import lru_cache

from ..core.config import get_settings
from ..embeddings.dinov2 import DinoV2EmbeddingProvider
from ..services.pair_analysis_service import PairAnalysisService


@lru_cache
def pair_analysis_service() -> PairAnalysisService:
    settings = get_settings()
    provider = None
    if settings.embedding.enabled:
        provider = DinoV2EmbeddingProvider(
            settings.embedding.model,
            settings.embedding.device,
            settings.embedding.normalize,
            settings.embedding.allow_cpu_fallback,
            settings.embedding.cache_dir,
        )
    return PairAnalysisService(settings, provider)
