from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field


DistanceFunction = Callable[[str, str], int]


@dataclass(slots=True)
class _Node:
    value: str
    children: dict[int, "_Node"] = field(default_factory=dict)


class PerceptualHashIndex:
    """BK-tree index for exact Hamming-radius searches over perceptual hashes."""

    def __init__(self, distance: DistanceFunction) -> None:
        self._distance = distance
        self._root: _Node | None = None
        self._image_ids: dict[str, list[str]] = {}

    @classmethod
    def from_items(
        cls,
        items: Iterable[tuple[str, str]],
        distance: DistanceFunction,
    ) -> "PerceptualHashIndex":
        index = cls(distance)
        for image_id, hash_value in items:
            index.add(hash_value, image_id)
        return index

    def add(self, hash_value: str, image_id: str) -> None:
        image_ids = self._image_ids.setdefault(hash_value, [])
        image_ids.append(image_id)
        if len(image_ids) > 1:
            return

        node = _Node(hash_value)
        if self._root is None:
            self._root = node
            return

        current = self._root
        while True:
            edge = self._distance(hash_value, current.value)
            child = current.children.get(edge)
            if child is None:
                current.children[edge] = node
                return
            current = child

    def search(self, query: str, max_distance: int) -> list[str]:
        if self._root is None:
            return []

        matches: list[str] = []
        pending = [self._root]
        while pending:
            current = pending.pop()
            distance = self._distance(query, current.value)
            if distance <= max_distance:
                matches.extend(self._image_ids[current.value])
            lower = distance - max_distance
            upper = distance + max_distance
            pending.extend(child for edge, child in current.children.items() if lower <= edge <= upper)
        return matches
