class ApplicationError(Exception):
    """Base class for expected application failures."""


class InvalidImageError(ApplicationError):
    pass


class EmbeddingError(ApplicationError):
    pass


class VectorStoreError(ApplicationError):
    pass


class FeatureMatchingError(ApplicationError):
    pass


class ConfigurationError(ApplicationError):
    pass

