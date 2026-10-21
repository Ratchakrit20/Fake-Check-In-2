from __future__ import annotations

from collections.abc import Iterable

from ..db.models import ImageRecord, PairwiseResult
from .image_source_service import resolve_image_source
from .relationship_graph_service import RelationshipGraphService
from .relationship_policy import REPORTABLE_CLASSIFICATIONS


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


def build_reportable_groups(
    images: Iterable[ImageRecord],
    pairs: Iterable[PairwiseResult],
    minimum_score: float,
    merge_by_customer: bool = True,
) -> list[list[ImageRecord]]:
    """Build the shared groups used by the export flow and dashboard preview."""
    image_list = list(images)
    image_by_id = {image.id: image for image in image_list}
    qualified_pairs = [pair for pair in pairs if pair.relationship_level in REPORTABLE_CLASSIFICATIONS and pair.relationship_score >= minimum_score and pair.image_a_id in image_by_id and pair.image_b_id in image_by_id]
    edges = RelationshipGraphService.qualified_edges(
        [(pair.image_a_id, pair.image_b_id, pair.relationship_score) for pair in qualified_pairs],
        minimum_score,
    )
    components = [
        [image_by_id[image_id] for image_id in component]
        for component in RelationshipGraphService.connected_components(list(image_by_id), edges)
        if len(component) > 1
    ]
    if not merge_by_customer:
        return components
    return merge_report_groups_by_customer(components)


def build_reportable_groups_as_of(
    images: Iterable[ImageRecord],
    pairs: Iterable[PairwiseResult],
    minimum_score: float,
    as_of_date: str | None,
) -> list[list[ImageRecord]]:
    """Build the report graph from evidence dated on or before the cutoff.

    Filtering images before building components ensures a future image cannot
    act as a bridge between earlier groups. Undated images remain eligible, as
    they cannot be identified as future evidence.
    """
    eligible_images = [
        image
        for image in images
        if as_of_date is None
        or (checkin_date := resolve_image_source(image).checkin_date) is None
        or checkin_date <= as_of_date
    ]
    return build_reportable_groups(eligible_images, pairs, minimum_score, merge_by_customer=False)


def merge_report_groups_by_customer(components: list[list[ImageRecord]]) -> list[list[ImageRecord]]:
    """Merge already selected components for presentation without adding images."""
    merged_indexes = merge_group_indexes_by_bbid(
        [
            {
                source.customer_id
                for image in component
                if (source := resolve_image_source(image)).customer_id
            }
            for component in components
        ]
    )
    return [
        [image for component_index in indexes for image in components[component_index]]
        for indexes in merged_indexes
    ]
