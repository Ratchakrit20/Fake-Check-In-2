from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...db.models import ImageRecord, PairwiseResult
from ...db.session import get_session
from ...services.relationship_graph_service import RelationshipGraphService

router = APIRouter(prefix="/groups", tags=["groups"])


@router.get("")
async def groups(session: AsyncSession = Depends(get_session)) -> dict:
    image_records = list(await session.scalars(select(ImageRecord)))
    node_rows = [record.id for record in image_records]
    allowed = ["exact_file", "same_image", "edited_or_cropped", "background_replaced"]
    pair_rows = (
        await session.execute(
            select(PairwiseResult.image_a_id, PairwiseResult.image_b_id).where(PairwiseResult.relationship_level.in_(allowed))
        )
    ).all()
    components = RelationshipGraphService.connected_components(node_rows, list(pair_rows))
    image_map = {record.id: record for record in image_records}
    related_pairs = list(
        await session.scalars(select(PairwiseResult).where(PairwiseResult.relationship_level.in_(allowed)))
    )
    response_groups = []
    for index, component in enumerate(group for group in components if len(group) > 1):
        component_ids = set(component)
        relationships = [pair for pair in related_pairs if pair.image_a_id in component_ids and pair.image_b_id in component_ids]
        response_groups.append(
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
    return {"groups": response_groups}
