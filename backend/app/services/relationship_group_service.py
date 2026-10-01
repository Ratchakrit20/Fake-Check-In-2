from __future__ import annotations

from .relationship_graph_service import RelationshipGraphService


def merge_group_indexes_by_bbid(group_bbids: list[set[str]]) -> list[list[int]]:
    """Merge presentation/report groups that share at least one BBID.

    This changes only how detected components are presented. It never creates
    or persists a new image-to-image relationship.
    """
    indexes_by_bbid: dict[str, list[int]] = {}
    for index, bbids in enumerate(group_bbids):
        for bbid in bbids:
            indexes_by_bbid.setdefault(bbid, []).append(index)

    edges = [
        (indexes[0], index)
        for indexes in indexes_by_bbid.values()
        for index in indexes[1:]
    ]
    return RelationshipGraphService.connected_components(list(range(len(group_bbids))), edges)
