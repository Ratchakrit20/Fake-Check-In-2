from fastapi import APIRouter, Depends, File, UploadFile

from ...domain.schemas import RelationshipResult
from ...services.image_validation_service import ImageValidationService
from ...services.pair_analysis_service import PairAnalysisService
from ..dependencies import pair_analysis_service

router = APIRouter(prefix="/compare", tags=["compare"])


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
