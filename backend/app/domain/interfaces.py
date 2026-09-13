from abc import ABC, abstractmethod
from pathlib import Path

import numpy as np
from PIL import Image


class EmbeddingProvider(ABC):
    @property
    @abstractmethod
    def dimension(self) -> int: ...

    @abstractmethod
    def embed(self, image: Image.Image) -> np.ndarray: ...


class VectorStore(ABC):
    @abstractmethod
    def add(self, image_id: str, vector: np.ndarray) -> None: ...

    @abstractmethod
    def search(self, vector: np.ndarray, top_k: int) -> list[tuple[str, float]]: ...


class ImageStorage(ABC):
    @abstractmethod
    def save(self, image_id: str, suffix: str, content: bytes) -> Path: ...


class ManipulationDetector(ABC):
    @abstractmethod
    def analyze(self, first: Image.Image, second: Image.Image) -> dict: ...
