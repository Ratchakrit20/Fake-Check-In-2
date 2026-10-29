from __future__ import annotations

import asyncio
import io
import json
import logging
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps
from sqlalchemy import select, update

from ..core.config import get_settings
from ..core.runtime import detect_hardware
from ..db.models import AnalysisJob, AnalysisJobItem, ImageEmbedding, ImageRecord, PairwiseResult
from ..db.session import SessionFactory
from ..domain.enums import JobStatus
from ..embeddings.sscd import SSCDEmbeddingProvider
from ..storage.local_storage import LocalImageStorage
from ..vector_store.faiss_store import FaissVectorStore
from ..vector_store.phash_index import PerceptualHashIndex
from .ai_image_metadata import serialize_ai_metadata
from .image_quality_service import UNVERIFIABLE, ImageQualityAssessment, ImageQualityService
from .image_source_service import resolve_image_source
from .job_process_lock import job_process_lock
from .pair_analysis_service import PairAnalysisService

logger = logging.getLogger(__name__)


def same_submission(first: ImageRecord, second: ImageRecord) -> bool:
    """Skip images from the same Customer ID on the same check-in date.

    Technician ID is retained only as source metadata. It must not influence
    candidate selection or create additional relationships.
    """
    first_reference = resolve_image_source(first)
    second_reference = resolve_image_source(second)
    return (
        first_reference.customer_id is not None
        and second_reference.customer_id is not None
        and first_reference.checkin_date is not None
        and second_reference.checkin_date is not None
        and first_reference.customer_id == second_reference.customer_id
        and first_reference.checkin_date == second_reference.checkin_date
    )


@lru_cache
def _components() -> tuple[SSCDEmbeddingProvider, FaissVectorStore, PairAnalysisService]:
    settings = get_settings()
    provider = SSCDEmbeddingProvider(
        settings.embedding.model_path,
        settings.embedding.model_url,
        settings.embedding.model_sha256,
        settings.embedding.device,
        settings.embedding.normalize,
        settings.embedding.allow_cpu_fallback,
        settings.embedding.input_size,
    )
    vector_store = FaissVectorStore(
        provider.dimension,
        settings.vector_search.index_path,
        settings.vector_search.metadata_path,
    )
    return provider, vector_store, PairAnalysisService(settings, provider)


def normalize_pair(first: str, second: str) -> tuple[str, str]:
    return (first, second) if first < second else (second, first)


def unique_records_by_id(records: Iterable[ImageRecord]) -> list[ImageRecord]:
    """Keep one record per image when a batch contains exact duplicate files."""
    return list({record.id: record for record in records}.values())


async def _set_job(job_id: str, status: JobStatus, processed: int | None = None, error: str | None = None) -> None:
    async with SessionFactory() as session:
        job = await session.get(AnalysisJob, job_id)
        if job is None:
            return
        # The cancellation endpoint owns the terminal state. A worker which
        # finishes its current CPU task afterwards must not turn it back into
        # COMPLETED or FAILED.
        if job.status == JobStatus.CANCELLED.value and status != JobStatus.CANCELLED:
            return
        now = datetime.now(UTC).replace(tzinfo=None)
        if status == JobStatus.EMBEDDING and job.started_at is None:
            job.started_at = now
        if status not in {JobStatus.COMPLETED, JobStatus.CANCELLED, JobStatus.FAILED}:
            job.completed_at = None
            job.duration_seconds = None
        if status in {JobStatus.COMPLETED, JobStatus.CANCELLED, JobStatus.FAILED}:
            job.completed_at = now
            started_at = job.started_at or job.created_at
            job.duration_seconds = max(0.0, (now - started_at).total_seconds())
        job.status = status.value
        if processed is not None:
            job.processed = processed
        job.error = error
        await session.commit()


async def _cancel_requested(job_id: str) -> bool:
    """Read the persisted cancellation flag between safe processing units."""
    async with SessionFactory() as session:
        job = await session.get(AnalysisJob, job_id)
        return job is None or job.status == JobStatus.CANCELLED.value


async def _preflight_image_quality(
    job_id: str,
    all_records: dict[str, ImageRecord],
    record_paths: dict[str, Path],
    settings,
) -> set[str]:
    """Classify legacy records once so unusable images never enter either index."""
    service = ImageQualityService(settings.image_quality)
    pending = [
        record for record in all_records.values()
        if record.image_quality_status is None and record.id in record_paths
    ]
    updates: list[tuple[ImageRecord, ImageQualityAssessment]] = []
    for index, record in enumerate(pending, start=1):
        if index % 250 == 0 and await _cancel_requested(job_id):
            raise RuntimeError("analysis job cancelled during image-quality preflight")
        try:
            with Image.open(record_paths[record.id]) as opened:
                assessment = service.assess(opened)
        except (OSError, ValueError):
            logger.exception("image quality preflight could not decode %s", record.id)
            assessment = ImageQualityAssessment(UNVERIFIABLE, "image_decode_failed", 1.0)
        record.image_quality_status = assessment.status
        record.image_quality_reason = assessment.reason
        record.near_black_ratio = assessment.near_black_ratio
        if assessment.status == UNVERIFIABLE:
            record.analysis_status = UNVERIFIABLE
        updates.append((record, assessment))
        if len(updates) >= 250:
            async with SessionFactory() as session:
                for updated_record, result in updates:
                    await session.execute(
                        update(ImageRecord)
                        .where(ImageRecord.id == updated_record.id)
                        .values(
                            image_quality_status=result.status,
                            image_quality_reason=result.reason,
                            near_black_ratio=result.near_black_ratio,
                            analysis_status=UNVERIFIABLE if result.status == UNVERIFIABLE else updated_record.analysis_status,
                        )
                    )
                await session.commit()
            logger.info("image quality preflight: checked %d/%d legacy images", index, len(pending))
            updates.clear()
    if updates:
        async with SessionFactory() as session:
            for updated_record, result in updates:
                await session.execute(
                    update(ImageRecord)
                    .where(ImageRecord.id == updated_record.id)
                    .values(
                        image_quality_status=result.status,
                        image_quality_reason=result.reason,
                        near_black_ratio=result.near_black_ratio,
                        analysis_status=UNVERIFIABLE if result.status == UNVERIFIABLE else updated_record.analysis_status,
                    )
                )
            await session.commit()
        logger.info("image quality preflight: checked %d/%d legacy images", len(pending), len(pending))
    unverifiable_ids = {
        image_id for image_id, record in all_records.items()
        if record.image_quality_status == UNVERIFIABLE
    }
    logger.info("image quality preflight complete: %d images excluded from matching", len(unverifiable_ids))
    return unverifiable_ids


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
        if await _cancel_requested(job_id):
            return
        # Preserve the last persisted progress during recovery/resume. The
        # completed item rows below are the checkpoint used to reconcile it.
        await _set_job(job_id, JobStatus.VALIDATING)
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
        # Older library images have no quality status yet. Check them once
        # before building either candidate index; the result is persisted.
        unverifiable_ids = await _preflight_image_quality(job_id, all_records, record_paths, settings)
        skipped_items = [
            item for item in items
            if item.status != JobStatus.COMPLETED.value and item.image_id in unverifiable_ids
        ]
        if skipped_items:
            async with SessionFactory() as session:
                for item in skipped_items:
                    item_row = await session.get(AnalysisJobItem, item.id)
                    if item_row:
                        item_row.status = JobStatus.COMPLETED.value
                await session.commit()
            for item in skipped_items:
                item.status = JobStatus.COMPLETED.value
        completed_items = [item for item in items if item.status == JobStatus.COMPLETED.value]
        pending_items = [
            item for item in items
            if item.status != JobStatus.COMPLETED.value and item.image_id not in unverifiable_ids
        ]
        await _set_job(job_id, JobStatus.EMBEDDING, len(completed_items))
        records_by_sha: dict[str, list[str]] = {}
        for record in all_records.values():
            if record.image_quality_status != UNVERIFIABLE:
                records_by_sha.setdefault(record.sha256, []).append(record.id)
        phash_index = PerceptualHashIndex.from_items(
            (
                (record.id, record.phash)
                for record in all_records.values()
                if record.phash and record.image_quality_status != UNVERIFIABLE
            ),
            pair_service.phash.distance,
        )
        item_image_ids = [
            item.image_id for item in items
            if item.image_id not in unverifiable_ids and item.image_id in record_paths
        ]
        async with SessionFactory() as session:
            vectors: dict[str, np.ndarray] = {}
            missing: list[ImageRecord] = []
            embedding_rows: list[ImageEmbedding] = []
            # Keep each IN clause below SQLite's older parameter limit while
            # replacing one database round trip per image with chunked reads.
            for id_offset in range(0, len(item_image_ids), 500):
                embedding_rows.extend(
                    await session.scalars(
                        select(ImageEmbedding).where(
                            ImageEmbedding.image_id.in_(item_image_ids[id_offset : id_offset + 500]),
                            ImageEmbedding.model_name == settings.embedding.model,
                            ImageEmbedding.model_version == settings.embedding.version,
                        )
                    )
                )
            embeddings_by_image = {row.image_id: row for row in embedding_rows}
            for item in items:
                record = all_records.get(item.image_id)
                if record is None or record.id not in record_paths or record.id in unverifiable_ids:
                    continue
                embedding_row = embeddings_by_image.get(record.id)
                if embedding_row is None:
                    missing.append(record)
                else:
                    vectors[record.id] = np.frombuffer(embedding_row.embedding, dtype=np.float32).copy()

            batch_size = profile.embedding_batch_size
            missing = unique_records_by_id(missing)
            embedding_rows_since_commit = 0
            for offset in range(0, len(missing), batch_size):
                if await _cancel_requested(job_id):
                    return
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
                embedding_rows_since_commit += len(records_chunk)
                if embedding_rows_since_commit >= 64:
                    await session.commit()
                    embedding_rows_since_commit = 0
            if embedding_rows_since_commit:
                await session.commit()

        vector_store.remove_many(unverifiable_ids)
        vector_store.add_many([(image_id, vector) for image_id, vector in vectors.items()])
        async with SessionFactory() as session:
            existing_rows = list(await session.scalars(select(PairwiseResult)))
            retained_rows: list[PairwiseResult] = []
            for row in existing_rows:
                first, second = all_records.get(row.image_a_id), all_records.get(row.image_b_id)
                if first is not None and second is not None and same_submission(first, second):
                    await session.delete(row)
                else:
                    retained_rows.append(row)
            await session.commit()
            existing_rows = retained_rows
        existing_ids = {normalize_pair(row.image_a_id, row.image_b_id): row.id for row in existing_rows}
        seen_pairs = set() if force else set(existing_ids)
        await _set_job(job_id, JobStatus.VERIFYING, len(completed_items))

        loop = asyncio.get_running_loop()
        with ThreadPoolExecutor(max_workers=profile.pair_workers, thread_name_prefix="pair-analysis") as executor:
            for offset, item in enumerate(pending_items, start=1):
                if await _cancel_requested(job_id):
                    return
                current = all_records.get(item.image_id)
                if current is None:
                    continue
                vector = vectors.get(current.id)
                if vector is None:
                    continue
                current_path = record_paths.get(current.id)
                if current_path is None:
                    continue
                async with SessionFactory() as session:
                    item_row = await session.get(AnalysisJobItem, item.id)
                    if item_row:
                        item_row.status = "PROCESSING"
                        await session.commit()
                current_bytes = current_path.read_bytes()
                candidates = vector_store.search(vector, settings.vector_search.top_k)
                candidate_scores = {candidate_id: similarity for candidate_id, similarity in candidates}
                # A 90/180/270-degree copy can rank poorly in SSCD. Cheap
                # rotation-aware pHash retrieval keeps it from being lost
                # before geometric verification.
                with Image.open(io.BytesIO(current_bytes)) as opened:
                    current_image = ImageOps.exif_transpose(opened).convert("RGB")
                ai_metadata_json = serialize_ai_metadata(pair_service.ai_models.report_metadata(current_image))
                rotation_hashes = [
                    pair_service.phash.calculate_single(current_image),
                    pair_service.phash.calculate_single(current_image.transpose(Image.Transpose.ROTATE_270)),
                    pair_service.phash.calculate_single(current_image.transpose(Image.Transpose.ROTATE_180)),
                    pair_service.phash.calculate_single(current_image.transpose(Image.Transpose.ROTATE_90)),
                ]
                rotation_candidate_ids: set[str] = set()
                for hash_value in rotation_hashes:
                    rotation_candidate_ids.update(
                        phash_index.search(hash_value, settings.phash.max_hamming_distance)
                    )
                for candidate_id in rotation_candidate_ids.copy():
                    candidate = all_records.get(candidate_id)
                    candidate_vector = vectors.get(candidate_id)
                    if (
                        candidate is None
                        or candidate_id == current.id
                        or candidate_vector is None
                        or same_submission(current, candidate)
                    ):
                        rotation_candidate_ids.discard(candidate_id)
                        continue
                    candidate_scores.setdefault(candidate_id, float(np.dot(vector, candidate_vector)))
                # Exact duplicates must never be lost because of top-k or an
                # embedding threshold. They are distinct upload occurrences.
                for duplicate_id in records_by_sha.get(current.sha256, []):
                    if duplicate_id != current.id:
                        candidate_scores[duplicate_id] = 1.0
                work: list[tuple[tuple[str, str], str, float]] = []
                for candidate_id, similarity in candidate_scores.items():
                    if candidate_id == current.id or (
                        similarity < settings.performance.candidate_min_similarity
                        and candidate_id not in rotation_candidate_ids
                    ):
                        continue
                    pair = normalize_pair(current.id, candidate_id)
                    if pair in seen_pairs:
                        continue
                    candidate = all_records.get(candidate_id)
                    candidate_path = record_paths.get(candidate_id)
                    if candidate is None or candidate_path is None:
                        continue
                    if same_submission(current, candidate):
                        continue
                    seen_pairs.add(pair)
                    work.append((pair, str(candidate_path), similarity))

                for offset in range(0, len(work), settings.performance.pair_chunk_size):
                    if await _cancel_requested(job_id):
                        return
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
                        existing_pair_ids = {
                            existing_ids[pair]
                            for pair, _, _ in chunk
                            if pair in existing_ids
                        }
                        existing_pairs = list(
                            await session.scalars(
                                select(PairwiseResult).where(PairwiseResult.id.in_(existing_pair_ids))
                            )
                        ) if existing_pair_ids else []
                        existing_pairs_by_id = {row.id: row for row in existing_pairs}
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
                            existing_pair = existing_pairs_by_id.get(existing_id) if existing_id else None
                            if existing_pair is None:
                                existing_pair = PairwiseResult(image_a_id=pair[0], image_b_id=pair[1], **values)
                                session.add(existing_pair)
                            else:
                                for field, value in values.items():
                                    setattr(existing_pair, field, value)
                        await session.commit()

                async with SessionFactory() as session:
                    current_row = await session.get(ImageRecord, current.id)
                    if current_row:
                        current_row.analysis_status = "COMPLETED"
                        current_row.analyzed_at = datetime.now(UTC)
                        current_row.ai_metadata_json = ai_metadata_json
                    item_row = await session.get(AnalysisJobItem, item.id)
                    if item_row:
                        item_row.status = JobStatus.COMPLETED.value
                    await session.commit()
                await _set_job(job_id, JobStatus.VERIFYING, len(completed_items) + offset)
        await _set_job(job_id, JobStatus.COMPLETED, len(items))
    except Exception as exc:  # noqa: BLE001 - job boundary must persist every failure
        if await _cancel_requested(job_id):
            return
        if "cannot schedule new futures after shutdown" in str(exc):
            await _set_job(job_id, JobStatus.INTERRUPTED, error="worker interrupted; resume from checkpoint")
            return
        await _set_job(job_id, JobStatus.FAILED, error=str(exc))


def run_batch_job(job_id: str, force: bool = False) -> bool:
    with job_process_lock(job_id) as acquired:
        if not acquired:
            logger.info("job %s is already running in another process", job_id)
            return False
        asyncio.run(process_batch_job(job_id, force=force))
        return True
