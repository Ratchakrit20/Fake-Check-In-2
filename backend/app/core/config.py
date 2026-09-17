from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field, model_validator

ROOT = Path(__file__).resolve().parents[3]
load_dotenv(ROOT / ".env", override=False)


class AppConfig(BaseModel):
    name: str
    api_prefix: str = "/api/v1"
    reload: bool = False
    max_upload_files: int = Field(gt=0)
    max_file_size_mb: int = Field(gt=0)
    max_image_pixels: int = Field(gt=0)
    max_request_size_mb: int = Field(gt=0)
    allowed_mime_types: list[str]


class StorageConfig(BaseModel):
    root: Path


class DatabaseConfig(BaseModel):
    url: str


class EmbeddingConfig(BaseModel):
    enabled: bool = True
    provider: str
    model: str
    version: str
    cache_dir: Path
    model_path: Path
    model_url: str
    model_sha256: str = Field(pattern=r"^[0-9a-fA-F]{64}$")
    input_size: int = Field(ge=224, le=1024)
    device: Literal["cpu", "cuda", "mps", "auto"] = "auto"
    normalize: bool = True
    batch_size: int = Field(ge=0)
    allow_cpu_fallback: bool = True


class VectorSearchConfig(BaseModel):
    provider: str
    index_path: Path
    metadata_path: Path
    top_k: int = Field(gt=0)


class PHashConfig(BaseModel):
    enabled: bool = True
    hash_size: int = Field(ge=4, le=32)
    max_hamming_distance: int = Field(ge=0)


class SiftConfig(BaseModel):
    enabled: bool = True
    max_dimension: int = Field(ge=320, le=4096)
    contrast_threshold: float = Field(gt=0)
    edge_threshold: float = Field(gt=0)
    sigma: float = Field(gt=0)
    ratio_threshold: float = Field(gt=0, lt=1)
    min_good_matches: int = Field(gt=0)


class RansacConfig(BaseModel):
    enabled: bool = True
    reprojection_threshold: float = Field(gt=0)
    min_inlier_ratio: float = Field(ge=0, le=1)
    min_inliers: int = Field(gt=0)


class FlipConfig(BaseModel):
    horizontal: bool = True


class BodyPartsConfig(BaseModel):
    enabled: bool = True
    model_path: Path
    config_dir: Path
    device: str = "auto"
    image_size: int = Field(ge=320, le=2048)
    confidence: float = Field(gt=0, lt=1)
    cache_size: int = Field(gt=0)
    identity_classes: list[str]
    major_classes: list[str]
    reuse_classes: list[str]
    min_reuse_classes: int = Field(gt=0)
    min_reuse_inliers: int = Field(gt=0)
    min_major_inliers: int = Field(gt=0)
    identity_min_inliers: int = Field(gt=0)
    single_part_suspect_min_inliers: int = Field(gt=0)


class PersonSegmentationConfig(BaseModel):
    enabled: bool = True
    model_path: Path
    config_dir: Path
    device: str = "auto"
    image_size: int = Field(ge=320, le=2048)
    confidence: float = Field(gt=0, lt=1)
    cache_size: int = Field(gt=0)


class RelationshipWeights(BaseModel):
    phash: float = Field(ge=0)
    embedding: float = Field(ge=0)
    sift: float = Field(ge=0)
    ransac: float = Field(ge=0)

    @model_validator(mode="after")
    def valid_total(self) -> RelationshipWeights:
        if abs(sum(self.model_dump().values()) - 1.0) > 1e-6:
            raise ValueError("relationship weights must sum to 1.0")
        return self


class RelationshipConfig(BaseModel):
    exact_duplicate: float = Field(ge=0, le=1)
    very_high_threshold: float = Field(ge=0, le=1)
    high_threshold: float = Field(ge=0, le=1)
    possible_threshold: float = Field(ge=0, le=1)
    graph_edge_threshold: float = Field(ge=0, le=1)
    partial_reuse_min_inliers: int = Field(gt=0)
    partial_reuse_min_inlier_ratio: float = Field(gt=0, le=1)
    background_replaced_min_embedding_similarity: float = Field(ge=0, le=1)
    foreground_source_min_inliers: int = Field(gt=0)
    foreground_source_min_inlier_ratio: float = Field(gt=0, le=1)
    foreground_source_min_coverage: float = Field(gt=0, le=1)
    repeated_checkin_min_foreground_inliers: int = Field(gt=0)
    repeated_checkin_min_foreground_ratio: float = Field(gt=0, le=1)
    repeated_checkin_min_foreground_coverage: float = Field(gt=0, le=1)
    repeated_checkin_min_identity_inliers: int = Field(gt=0)
    repeated_checkin_min_reuse_inliers: int = Field(gt=0)
    same_image_phash_max: int = Field(ge=0)
    same_image_min_inlier_ratio: float = Field(gt=0, le=1)
    recapture_min_inliers: int = Field(gt=0)
    recapture_min_inlier_ratio: float = Field(gt=0, le=1)
    recapture_min_coverage: float = Field(gt=0, le=1)
    recapture_min_embedding_similarity: float = Field(ge=0, le=1)
    blur_variance_threshold: float = Field(gt=0)
    blurred_crop_min_inliers: int = Field(gt=0)
    blurred_crop_min_inlier_ratio: float = Field(gt=0, le=1)
    blurred_crop_min_embedding_similarity: float = Field(ge=0, le=1)
    blurred_crop_max_phash_distance: int = Field(ge=0)
    blurred_whole_min_inliers: int = Field(gt=0)
    blurred_whole_min_inlier_ratio: float = Field(gt=0, le=1)
    blurred_whole_min_coverage: float = Field(gt=0, le=1)
    blurred_whole_strong_inlier_ratio: float = Field(gt=0, le=1)
    weights: RelationshipWeights

    @model_validator(mode="after")
    def ordered(self) -> RelationshipConfig:
        if not self.very_high_threshold > self.high_threshold > self.possible_threshold:
            raise ValueError("relationship thresholds must be strictly descending")
        return self


class JobsConfig(BaseModel):
    broker_url: str
    result_backend: str
    worker_count: int = Field(gt=0)


class PerformanceConfig(BaseModel):
    auto_tune: bool = True
    cpu_workers: int = Field(ge=0)
    opencv_threads: int = Field(ge=0)
    pair_chunk_size: int = Field(gt=0)
    candidate_min_similarity: float = Field(ge=-1, le=1)


class LoggingConfig(BaseModel):
    level: str


class Settings(BaseModel):
    app: AppConfig
    storage: StorageConfig
    database: DatabaseConfig
    embedding: EmbeddingConfig
    vector_search: VectorSearchConfig
    phash: PHashConfig
    sift: SiftConfig
    ransac: RansacConfig
    flip_detection: FlipConfig
    body_parts: BodyPartsConfig
    person_segmentation: PersonSegmentationConfig
    relationship: RelationshipConfig
    jobs: JobsConfig
    performance: PerformanceConfig
    logging: LoggingConfig
    configuration_version: str


def _apply_environment(data: dict) -> dict:
    result = json.loads(json.dumps(data))
    for key, raw in os.environ.items():
        parts = key.lower().split("__")
        if len(parts) < 2:
            continue
        target = result
        for part in parts[:-1]:
            if not isinstance(target, dict) or part not in target:
                target = None
                break
            target = target[part]
        field = parts[-1]
        if not isinstance(target, dict) or field not in target:
            continue
        current = target[field]
        if isinstance(current, bool):
            target[field] = raw.lower() in {"1", "true", "yes", "on"}
        elif isinstance(current, int):
            target[field] = int(raw)
        elif isinstance(current, float):
            target[field] = float(raw)
        else:
            target[field] = raw
    return result


@lru_cache
def get_settings() -> Settings:
    path = Path(os.getenv("APP_CONFIG", ROOT / "config" / "default.yaml"))
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    settings = Settings.model_validate(_apply_environment(data))
    path_fields = (
        (settings.storage, "root"),
        (settings.embedding, "cache_dir"),
        (settings.embedding, "model_path"),
        (settings.vector_search, "index_path"),
        (settings.vector_search, "metadata_path"),
        (settings.body_parts, "model_path"),
        (settings.body_parts, "config_dir"),
        (settings.person_segmentation, "model_path"),
        (settings.person_segmentation, "config_dir"),
    )
    for section, field_name in path_fields:
        field = getattr(section, field_name)
        if not field.is_absolute():
            setattr(section, field_name, ROOT / field)
    return settings
