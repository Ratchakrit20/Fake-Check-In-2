from __future__ import annotations

import json
import logging
import threading
from pathlib import Path

import numpy as np

from ..core.exceptions import VectorStoreError
from ..domain.interfaces import VectorStore


class FaissVectorStore(VectorStore):
    def __init__(self, dimension: int, index_path: Path, metadata_path: Path) -> None:
        try:
            logging.getLogger("faiss.loader").setLevel(logging.ERROR)
            import faiss
        except ImportError as exc:
            raise VectorStoreError("faiss-cpu is not installed") from exc
        self.faiss = faiss
        self.dimension = dimension
        self.index_path = index_path
        self.metadata_path = metadata_path
        self.lock = threading.RLock()
        self.ids: list[str] = []
        if index_path.exists() and metadata_path.exists():
            self.index = faiss.read_index(str(index_path))
            self.ids = json.loads(metadata_path.read_text(encoding="utf-8"))
            if self.index.d != dimension or self.index.ntotal != len(self.ids):
                raise VectorStoreError("FAISS index metadata is incompatible")
        else:
            self.index = faiss.IndexFlatIP(dimension)

    @staticmethod
    def _normalized(vector: np.ndarray) -> np.ndarray:
        row = np.asarray(vector, dtype=np.float32).reshape(1, -1)
        norm = np.linalg.norm(row)
        return row / norm if norm else row

    def add(self, image_id: str, vector: np.ndarray) -> None:
        self.add_many([(image_id, vector)])

    def add_many(self, items: list[tuple[str, np.ndarray]]) -> None:
        with self.lock:
            known = set(self.ids)
            pending: list[tuple[str, np.ndarray]] = []
            for image_id, vector in items:
                if image_id in known:
                    continue
                known.add(image_id)
                pending.append((image_id, vector))
            if not pending:
                return
            matrix = np.concatenate([self._normalized(vector) for _, vector in pending], axis=0)
            self.index.add(matrix)
            self.ids.extend(image_id for image_id, _ in pending)
            self.index_path.parent.mkdir(parents=True, exist_ok=True)
            self.metadata_path.parent.mkdir(parents=True, exist_ok=True)
            self.faiss.write_index(self.index, str(self.index_path))
            self.metadata_path.write_text(json.dumps(self.ids), encoding="utf-8")

    def search(self, vector: np.ndarray, top_k: int) -> list[tuple[str, float]]:
        if not self.ids:
            return []
        scores, indexes = self.index.search(self._normalized(vector), min(top_k, len(self.ids)))
        return [(self.ids[index], float(score)) for index, score in zip(indexes[0], scores[0]) if index >= 0]
