from __future__ import annotations

import warnings
from pathlib import Path
from threading import Lock
from typing import ClassVar

import numpy as np
from PIL import Image

from ..core.exceptions import EmbeddingError
from ..domain.interfaces import EmbeddingProvider


class DinoV2EmbeddingProvider(EmbeddingProvider):
    DIMENSIONS: ClassVar[dict[str, int]] = {"dinov2_vits14": 384, "dinov2_vitb14": 768, "dinov2_vitl14": 1024, "dinov2_vitg14": 1536}

    def __init__(
        self,
        model_name: str,
        device: str = "auto",
        normalize: bool = True,
        allow_cpu_fallback: bool = True,
        cache_dir: Path | None = None,
    ) -> None:
        self.model_name = model_name
        self.normalize = normalize
        self.allow_cpu_fallback = allow_cpu_fallback
        self.cache_dir = cache_dir
        self._requested_device = device
        self._device = None
        self._model = None
        self._transform = None
        self._load_lock = Lock()

    @property
    def dimension(self) -> int:
        if self.model_name not in self.DIMENSIONS:
            raise EmbeddingError(f"unsupported DINOv2 model: {self.model_name}")
        return self.DIMENSIONS[self.model_name]

    def _load(self) -> None:
        if self._model is not None:
            return
        with self._load_lock:
            if self._model is not None:
                return
            try:
                import torch
                from torchvision.transforms import CenterCrop, Compose, Normalize, Resize, ToTensor

                if self.cache_dir is not None:
                    cache_dir = self.cache_dir.resolve()
                    cache_dir.mkdir(parents=True, exist_ok=True)
                    torch.hub.set_dir(str(cache_dir))

                if self._requested_device == "auto":
                    device = "cuda" if torch.cuda.is_available() else "cpu"
                else:
                    device = self._requested_device
                if device == "cuda" and not torch.cuda.is_available():
                    if not self.allow_cpu_fallback:
                        raise EmbeddingError("CUDA requested but unavailable")
                    device = "cpu"
                self._device = torch.device(device)
                with warnings.catch_warnings():
                    warnings.filterwarnings("ignore", message="xFormers is not available.*", category=UserWarning)
                    model = torch.hub.load("facebookresearch/dinov2", self.model_name)
                self._model = model.to(self._device).eval()
                self._transform = Compose([Resize(256), CenterCrop(224), ToTensor(), Normalize((0.485, 0.456, 0.406), (0.229, 0.224, 0.225))])
            except EmbeddingError:
                raise
            except Exception as exc:
                raise EmbeddingError(f"unable to load DINOv2: {exc}") from exc

    def embed(self, image: Image.Image) -> np.ndarray:
        return self.embed_many([image])[0]

    def embed_many(self, images: list[Image.Image]) -> np.ndarray:
        self._load()
        import torch

        with torch.inference_mode():
            batch = torch.stack([self._transform(image.convert("RGB")) for image in images]).to(self._device)
            vector = self._model(batch)
            if self.normalize:
                vector = torch.nn.functional.normalize(vector, dim=1)
        return vector.detach().cpu().numpy().astype(np.float32)
