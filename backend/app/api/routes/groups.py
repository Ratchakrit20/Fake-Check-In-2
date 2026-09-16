from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.config import get_settings
from ...db.models import ImageRecord, PairwiseResult
from ...db.session import get_session
from ...services.relationship_graph_service import RelationshipGraphService
from ...services.source_filename import declared_source_id

router = APIRouter(prefix="/groups", tags=["groups"])


@router.get("")
async def groups(session: AsyncSession = Depends(get_session)) -> dict:
    settings = get_settings()
    image_records = list(await session.scalars(select(ImageRecord)))
    node_rows = [record.id for record in image_records]
    allowed = [
        "exact_file",
        "same_image",
        "edited_or_cropped",
        "background_replaced",
        "repeated_checkin",
        "same_scene_new_capture",
    ]
    related_pairs = list(
        await session.scalars(
            select(PairwiseResult).where(
                PairwiseResult.relationship_level.in_(allowed),
                PairwiseResult.relationship_score >= settings.relationship.graph_edge_threshold,
            )
        )
    )
    scored_edges = [(pair.image_a_id, pair.image_b_id, pair.relationship_score) for pair in related_pairs]
    edges = RelationshipGraphService.qualified_edges(scored_edges, settings.relationship.graph_edge_threshold)
    components = RelationshipGraphService.connected_components(node_rows, edges)
    image_map = {record.id: record for record in image_records}
    relationship_groups = []
    for index, component in enumerate(group for group in components if len(group) > 1):
        component_ids = set(component)
        relationships = [pair for pair in related_pairs if pair.image_a_id in component_ids and pair.image_b_id in component_ids]
        relationship_groups.append(
            {
                "id": index + 1,
                "image_ids": component,
                "size": len(component),
                "images": [
                    {
                        "id": image_id,
                        "filename": image_map[image_id].original_filename,
                        "width": image_map[image_id].width,
                        "height": image_map[image_id].height,
                        "url": f"/api/v1/images/{image_id}/content",
                    }
                    for image_id in component
                ],
                "relationships": [
                    {
                        "image_a_id": pair.image_a_id,
                        "image_b_id": pair.image_b_id,
                        "score": pair.relationship_score,
                        "classification": pair.relationship_level,
                    }
                    for pair in relationships
                ],
            }
        )
    subgroup_indexes_by_source: dict[str, list[int]] = {}
    for subgroup_index, subgroup in enumerate(relationship_groups):
        source_ids = {
            source_id
            for image in subgroup["images"]
            if (source_id := declared_source_id(image["filename"])) is not None
        }
        subgroup["source_ids"] = sorted(source_ids)
        for source_id in source_ids:
            subgroup_indexes_by_source.setdefault(source_id, []).append(subgroup_index)

    # Components remain the actual detected relationships. This extra layer
    # only collects components carrying the same declared work/source number.
    subgroup_edges = [
        (indexes[0], subgroup_index)
        for indexes in subgroup_indexes_by_source.values()
        for subgroup_index in indexes[1:]
    ]
    outer_components = RelationshipGraphService.connected_components(
        list(range(len(relationship_groups))),
        subgroup_edges,
    )
    response_groups = []
    for outer_index, subgroup_indexes in enumerate(outer_components, start=1):
        subgroups = [relationship_groups[index] for index in subgroup_indexes]
        images_by_id = {
            image["id"]: image
            for subgroup in subgroups
            for image in subgroup["images"]
        }
        source_ids = sorted(
            {
                source_id
                for subgroup in subgroups
                for source_id in subgroup["source_ids"]
            }
        )
        response_groups.append(
            {
                "id": outer_index,
                "source_ids": source_ids,
                "size": len(images_by_id),
                "relationship_count": sum(
                    len(subgroup["relationships"]) for subgroup in subgroups
                ),
                "subgroups": subgroups,
            }
        )
    return {"groups": response_groups}
