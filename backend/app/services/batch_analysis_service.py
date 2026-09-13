from __future__ import annotations

import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image
from sqlalchemy import select

from ..core.config import get_settings
from ..core.runtime import detect_hardware
from ..db.models import AnalysisJob, AnalysisJobItem, ImageEmbedding, ImageRecord, PairwiseResult
from ..db.session import SessionFactory
from ..domain.enums import JobStatus
from ..embeddings.dinov2 import DinoV2EmbeddingProvider
from ..storage.local_storage import LocalImageStorage
from ..vector_store.faiss_store import FaissVectorStore
from .pair_analysis_service import PairAnalysisService


@lru_cache
def _components() -> tuple[DinoV2EmbeddingProvider, FaissVectorStore, PairAnalysisService]:
    settings = get_settings()
    provider = DinoV2EmbeddingProvider(
        settings.embedding.model,
        settings.embedding.device,
        settings.embedding.normalize,
        settings.embedding.allow_cpu_fallback,
        settings.embedding.cache_dir,
    )
    vector_store = FaissVectorStore(
        provider.dimension,
        settings.vector_search.index_path,
        settings.vector_search.metadata_path,
    )
    return provider, vector_store, PairAnalysisService(settings, provider)


def normalize_pair(first: str, second: str) -> tuple[str, str]:
    return (first, second) if first < second else (second, first)


async def _set_job(job_id: str, status: JobStatus, processed: int | None = None, error: str | None = None) -> None:
    async with SessionFactory() as session:
        job = await session.get(AnalysisJob, job_id)
        if job is None:
            return
        job.status = status.value
        if processed is not None:
            job.processed = processed
        job.error = error
        await session.commit()


async def process_batch_job(job_id: str, force: bool = False) -> None:
    settings = get_settings()
    profile = detect_hardware(
        settings.performance.cpu_workers,
        settings.performance.opencv_threads,
        settings.embedding.batch_size,
    )
    import cv2

    cv2.setNumThreads(profile.opencv_threads)
    provider, vector_store, pair_service = _components()
    storage = LocalImageStorage(settings.storage.root)
    try:
        await _set_job(job_id, JobStatus.EMBEDDING, 0)
        async with SessionFactory() as session:
            items = list(
                await session.scalars(
                    select(AnalysisJobItem).where(AnalysisJobItem.job_id == job_id).order_by(AnalysisJobItem.position)
                )
            )
            all_records = {record.id: record for record in await session.scalars(select(ImageRecord))}
            record_paths = {
                image_id: resolved
                for image_id, record in all_records.items()
                if (resolved := storage.resolve(image_id, record.storage_path)) is not None
            }
            vectors: dict[str, np.ndarray] = {}
            missing: list[ImageRecord] = []
            for item in items:
                record = all_records.get(item.image_id)
                if record is None or record.id not in record_paths:
                    continue
                embedding_row = await session.scalar(
                    select(ImageEmbedding).where(
                        ImageEmbedding.image_id == record.id,
                        ImageEmbedding.model_name == settings.embedding.model,
                        ImageEmbedding.model_version == settings.embedding.version,
                    )
                )
                if embedding_row is None:
                    missing.append(record)
                else:
                    vectors[record.id] = np.frombuffer(embedding_row.embedding, dtype=np.float32).copy()

            batch_size = profile.embedding_batch_size
            for offset in range(0, len(missing), batch_size):
                records_chunk = missing[offset : offset + batch_size]
                images: list[Image.Image] = []
                for record in records_chunk:
                    with Image.open(record_paths[record.id]) as opened:
                        images.append(opened.convert("RGB"))
                batch_vectors = provider.embed_many(images)
                for record, vector in zip(records_chunk, batch_vectors):
                    vectors[record.id] = vector
                    session.add(
                        ImageEmbedding(
                            image_id=record.id,
                            embedding=vector.astype(np.float32).tobytes(),
                            model_name=settings.embedding.model,
                            model_version=settings.embedding.version,
                            configuration_version=settings.configuration_version,
                        )
                    )
                await session.commit()

        vector_store.add_many([(image_id, vector) for image_id, vector in vectors.items()])
        async with SessionFactory() as session:
            existing_rows = list(await session.scalars(select(PairwiseResult)))
        existing_ids = {normalize_pair(row.image_a_id, row.image_b_id): row.id for row in existing_rows}
        seen_pairs = set() if force else set(existing_ids)
        await _set_job(job_id, JobStatus.VERIFYING, 0)

        loop = asyncio.get_running_loop()
        with ThreadPoolExecutor(max_workers=profile.pair_workers, thread_name_prefix="pair-analysis") as executor:
            for position, item in enumerate(items, start=1):
                current = all_records.get(item.image_id)
                if current is None:
                    continue
                vector = vectors.get(current.id)
                if vector is None:
                    continue
                current_path = record_paths.get(current.id)
                if current_path is None:
                    continue
                current_bytes = current_path.read_bytes()
                candidates = vector_store.search(vector, settings.vector_search.top_k)
                work: list[tuple[tuple[str, str], str, float]] = []
                for candidate_id, similarity in candidates:
                    if candidate_id == current.id or similarity < settings.performance.candidate_min_similarity:
                        continue
                    pair = normalize_pair(current.id, candidate_id)
                    if pair in seen_pairs:
                        continue
                    candidate = all_records.get(candidate_id)
                    candidate_path = record_paths.get(candidate_id)
                    if candidate is None or candidate_path is None:
                        continue
                    seen_pairs.add(pair)
                    work.append((pair, str(candidate_path), similarity))

                # Run segmentation as a batch before CPU workers start. This lets
                # Ultralytics use GPU batches and prevents duplicate model calls
                # when several candidate pairs contain the same image.
                if pair_service.body_parts is not None and work:
                    mask_paths = [str(current_path), *(path for _, path, _ in work)]
                    for offset in range(0, len(mask_paths), profile.embedding_batch_size):
                        mask_images: list[Image.Image] = []
                        for image_path in mask_paths[offset : offset + profile.embedding_batch_size]:
                            with Image.open(image_path) as opened:
                                mask_images.append(opened.convert("RGB"))
                        pair_service.body_parts.segment_many(mask_images)

                for offset in range(0, len(work), settings.performance.pair_chunk_size):
                    chunk = work[offset : offset + settings.performance.pair_chunk_size]
                    futures = [
                        loop.run_in_executor(
                            executor,
                            pair_service.analyze_bytes,
                            current_bytes,
                            Path(candidate_path).read_bytes(),
                            similarity,
                        )
                        for _, candidate_path, similarity in chunk
                    ]
                    results = await asyncio.gather(*futures)
                    async with SessionFactory() as session:
                        for (pair, _, _), result in zip(chunk, results):
                            evidence = result.evidence
                            values = {
                                "phash_distance": evidence.get("phash_distance"),
                                "dino_similarity": evidence.get("embedding_similarity"),
                                "sift_matches": int(evidence.get("sift_good_matches", 0)),
                                "ransac_inliers": int(evidence.get("ransac_inliers", 0)),
                                "ransac_inlier_ratio": float(evidence.get("ransac_inlier_ratio", 0)),
                                "flip_detected": int(bool(evidence.get("flip_detected"))),
                                "relationship_score": result.score,
                                "relationship_level": result.classification.value,
                                "details_json": json.dumps(result.model_dump(mode="json"), ensure_ascii=False),
                            }
                            existing_id = existing_ids.get(pair)
                            existing_pair = await session.get(PairwiseResult, existing_id) if existing_id else None
                            if existing_pair is None:
                                existing_pair = PairwiseResult(image_a_id=pair[0], image_b_id=pair[1], **values)
                                session.add(existing_pair)
                                await session.flush()
                                existing_ids[pair] = existing_pair.id
                            else:
                                for field, value in values.items():
                                    setattr(existing_pair, field, value)
                        await session.commit()

                async with SessionFactory() as session:
                    current_row = await session.get(ImageRecord, current.id)
                    if current_row:
                        current_row.analysis_status = "COMPLETED"
                        current_row.analyzed_at = datetime.now(UTC)
                    item_row = await session.get(AnalysisJobItem, item.id)
                    if item_row:
                        item_row.status = JobStatus.COMPLETED.value
                    await session.commit()
                await _set_job(job_id, JobStatus.VERIFYING, position)
        await _set_job(job_id, JobStatus.COMPLETED, len(items))
    except Exception as exc:  # noqa: BLE001 - job boundary must persist every failure
        await _set_job(job_id, JobStatus.FAILED, error=str(exc))


def run_batch_job(job_id: str, force: bool = False) -> None:
    asyncio.run(process_batch_job(job_id, force=force))
