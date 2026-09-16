from __future__ import annotations

import hashlib
import urllib.request
from pathlib import Path
from threading import Lock

import numpy as np
from PIL import Image

from ..core.exceptions import EmbeddingError
from ..domain.interfaces import EmbeddingProvider


class SSCDEmbeddingProvider(EmbeddingProvider):
    """SSCD descriptor optimized for transformed-image copy retrieval."""

    _dimension = 512

    def __init__(
        self,
        model_path: Path,
        model_url: str,
        model_sha256: str,
        device: str = "auto",
        normalize: bool = True,
        allow_cpu_fallback: bool = True,
        input_size: int = 320,
    ) -> None:
        self.model_path = model_path
        self.model_url = model_url
        self.model_sha256 = model_sha256.lower()
        self.requested_device = device
        self.normalize = normalize
        self.allow_cpu_fallback = allow_cpu_fallback
        self.input_size = input_size
        self._model = None
        self._device = None
        self._transform = None
        self._load_lock = Lock()

    @property
    def dimension(self) -> int:
        return self._dimension

    def _download_model(self) -> None:
        target = self.model_path.resolve()
        if target.is_file() and self._valid_checksum(target):
            return
        if target.is_file():
            raise EmbeddingError(f"SSCD model checksum mismatch: {target}")
        target.parent.mkdir(parents=True, exist_ok=True)
        partial = target.with_suffix(target.suffix + ".part")
        try:
            urllib.request.urlretrieve(self.model_url, partial)
            if not self._valid_checksum(partial):
                raise EmbeddingError("downloaded SSCD model checksum mismatch")
            partial.replace(target)
        except Exception as exc:
            partial.unlink(missing_ok=True)
            raise EmbeddingError(
                f"SSCD model is missing and could not be downloaded to {target}: {exc}"
            ) from exc

    def _valid_checksum(self, path: Path) -> bool:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest() == self.model_sha256

    def _load(self) -> None:
        if self._model is not None:
            return
        with self._load_lock:
            if self._model is not None:
                return
            try:
                import torch
                from torchvision.transforms import Compose, Normalize, Resize, ToTensor

                self._download_model()
                device_name = "cuda" if self.requested_device == "auto" and torch.cuda.is_available() else self.requested_device
                if device_name == "auto":
                    device_name = "cpu"
                if device_name == "cuda" and not torch.cuda.is_available():
                    if not self.allow_cpu_fallback:
                        raise EmbeddingError("CUDA requested for SSCD but unavailable")
                    device_name = "cpu"
                self._device = torch.device(device_name)
                self._model = torch.jit.load(str(self.model_path.resolve()), map_location=self._device).eval()
                self._transform = Compose(
                    [
                        Resize((self.input_size, self.input_size)),
                        ToTensor(),
                        Normalize((0.485, 0.456, 0.406), (0.229, 0.224, 0.225)),
                    ]
                )
            except EmbeddingError:
                raise
            except Exception as exc:
                raise EmbeddingError(f"unable to load SSCD: {exc}") from exc

    def embed(self, image: Image.Image) -> np.ndarray:
        return self.embed_many([image])[0]

    def embed_many(self, images: list[Image.Image]) -> np.ndarray:
        self._load()
        import torch

        with torch.inference_mode():
            batch = torch.stack([self._transform(image.convert("RGB")) for image in images]).to(self._device)
            vectors = self._model(batch)
            if self.normalize:
                vectors = torch.nn.functional.normalize(vectors, dim=1)
        return vectors.detach().cpu().numpy().astype(np.float32)
