from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.config import get_settings
from ...db.models import ImageRecord
from ...db.session import get_session
from ...domain.schemas import RelationshipResult, StoredComparisonRequest
from ...services.image_validation_service import ImageValidationService
from ...services.pair_analysis_service import PairAnalysisService
from ...storage.local_storage import LocalImageStorage
from ..dependencies import pair_analysis_service

router = APIRouter(prefix="/compare", tags=["compare"])


@router.post("/stored", response_model=RelationshipResult)
async def compare_stored_images(
    request: StoredComparisonRequest,
    session: AsyncSession = Depends(get_session),
    service: PairAnalysisService = Depends(pair_analysis_service),
) -> RelationshipResult:
    """Analyze two existing library images without downloading them to the browser."""
    first = await session.get(ImageRecord, request.image_a_id)
    second = await session.get(ImageRecord, request.image_b_id)
    if first is None or second is None:
        raise HTTPException(status_code=404, detail="stored image not found")
    storage = LocalImageStorage(get_settings().storage.root)
    first_path = storage.resolve(first.id, first.storage_path)
    second_path = storage.resolve(second.id, second.storage_path)
    if first_path is None or second_path is None:
        raise HTTPException(status_code=404, detail="stored image file not found")
    return service.analyze_bytes(first_path.read_bytes(), second_path.read_bytes(), include_visualizations=True)


@router.post("", response_model=RelationshipResult)
async def compare_images(
    image_a: UploadFile = File(...),
    image_b: UploadFile = File(...),
    service: PairAnalysisService = Depends(pair_analysis_service),
) -> RelationshipResult:
    first, second = await image_a.read(), await image_b.read()
    validator = ImageValidationService(service.settings.app)
    validator.validate(first)
    validator.validate(second)
    return service.analyze_bytes(first, second, include_visualizations=True)
