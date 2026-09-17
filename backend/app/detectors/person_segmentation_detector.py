from __future__ import annotations

import hashlib
import os
from collections import OrderedDict
from pathlib import Path
from threading import Lock

import cv2
import numpy as np
from PIL import Image

from ..core.config import PersonSegmentationConfig


class PersonSegmentationDetector:
    """Coarse person masks used only to separate foreground from background."""

    def __init__(self, config: PersonSegmentationConfig, target_max_dimension: int) -> None:
        self.config = config
        self.target_max_dimension = target_max_dimension
        self._model = None
        self._unavailable = False
        self._model_lock = Lock()
        self._inference_lock = Lock()
        self._cache: OrderedDict[str, np.ndarray] = OrderedDict()
        self._cache_lock = Lock()

    @staticmethod
    def _key(image: Image.Image) -> str:
        return hashlib.sha256(image.tobytes()).hexdigest()

    def _target_shape(self, image: Image.Image) -> tuple[int, int]:
        width, height = image.size
        scale = min(1.0, self.target_max_dimension / max(height, width))
        return round(height * scale), round(width * scale)

    def _load(self):
        if self._unavailable:
            return None
        if self._model is not None:
            return self._model
        with self._model_lock:
            if self._model is None:
                try:
                    model_path = Path(self.config.model_path).resolve()
                    # Never trigger an implicit network download from a request.
                    # Production/model provisioning must place the weight first.
                    if not model_path.is_file():
                        self._unavailable = True
                        return None
                    config_dir = Path(self.config.config_dir).resolve()
                    config_dir.mkdir(parents=True, exist_ok=True)
                    os.environ["YOLO_CONFIG_DIR"] = str(config_dir)
                    from ultralytics import YOLO

                    self._model = YOLO(str(model_path))
                except Exception:  # Model is optional; the organ/whole-image path remains available.
                    self._unavailable = True
                    return None
        return self._model

    def segment_many(self, images: list[Image.Image]) -> list[np.ndarray]:
        keys = [self._key(image) for image in images]
        output: list[np.ndarray | None] = []
        missing: list[int] = []
        with self._cache_lock:
            for index, key in enumerate(keys):
                cached = self._cache.get(key)
                output.append(cached)
                if cached is None:
                    missing.append(index)
                else:
                    self._cache.move_to_end(key)
        model = self._load() if missing else self._model
        if missing and model is not None:
            device = self.config.device
            if device == "auto":
                import torch

                device = 0 if torch.cuda.is_available() else "cpu"
            with self._inference_lock:
                sources = [np.asarray(images[index].convert("RGB")) for index in missing]
                try:
                    results = model.predict(
                        sources,
                        imgsz=self.config.image_size,
                        conf=self.config.confidence,
                        classes=[0],
                        device=device,
                        verbose=False,
                    )
                except Exception:
                    results = [None] * len(missing)
                for index, result in zip(missing, results):
                    height, width = self._target_shape(images[index])
                    mask = np.zeros((height, width), dtype=bool)
                    if result is not None and result.masks is not None:
                        for raw_mask in result.masks.data.cpu().numpy():
                            mask |= cv2.resize(raw_mask, (width, height), interpolation=cv2.INTER_NEAREST) >= 0.5
                    output[index] = mask
                    with self._cache_lock:
                        self._cache[keys[index]] = mask
                        while len(self._cache) > self.config.cache_size:
                            self._cache.popitem(last=False)
        for index in missing:
            if output[index] is None:
                height, width = self._target_shape(images[index])
                output[index] = np.zeros((height, width), dtype=bool)
        return [mask for mask in output if mask is not None]
